"""Report Composer — Layer 4 of Forecast & Reporting.

Assembles structured ClientIntelligenceReport from collected data.
Phase 1: observed_json only.
Phase 2: compose_with_forecast adds forecasted_json (S-curve scenarios,
         gap-to-leader, model metadata).
Phase 3: compose_full_report populates all 5 JSONB layers (observed,
         planned, forecasted, risks, business_impact).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.intelligence_report import ClientIntelligenceReport
from app.models.observed_snapshot import ObservedSnapshot
from app.services.forecast.accuracy_tracker import record_predictions
from app.services.forecast.business_impact import (
    PLAN_PRICES,
    BusinessImpactCalculator,
)
from app.services.forecast.intent_snapshot import collect_intent
from app.services.forecast.observed_reality import ObservedRealityCollector
from app.services.forecast.platform_risk import PlatformRiskAssessment
from app.services.forecast.visibility_forecaster import (
    DEFAULT_CEILING,
    DEFAULT_MIDPOINT,
    DEFAULT_STEEPNESS,
    ENGINE_MULTIPLIERS,
    NOISE_AMPLITUDE,
    VisibilityForecast,
    VisibilityForecaster,
    get_scenario_triple,
)

logger = logging.getLogger(__name__)


class ReportComposer:
    """Assembles ClientIntelligenceReport from collected observation data.

    Phase 1 populates observed_json only. Other layers (planned_json,
    forecasted_json, risks_json, business_impact_json) are empty placeholders
    until Tasks 5-11 add them.
    """

    def compose_observed_report(
        self, db: Session, client_id: uuid.UUID
    ) -> ClientIntelligenceReport:
        """Compose a report with Layer 1 (observed) data only.

        1. Collect observed metrics via ObservedRealityCollector
        2. Build observed_json section
        3. Compute data_freshness_json
        4. Create ClientIntelligenceReport with status='draft'
        5. Save to DB and return

        Args:
            db: SQLAlchemy session.
            client_id: UUID of the client.

        Returns:
            Persisted ClientIntelligenceReport with status='draft'.
        """
        # Collect observed data
        collector = ObservedRealityCollector()
        snapshot = collector.collect(db, client_id)

        # Build observed_json from snapshot
        observed_json = self._build_observed_section(snapshot)

        # Compute data freshness
        data_freshness = self._compute_data_freshness(snapshot)

        # Determine report period (current ISO week)
        report_period = self._current_iso_week()

        # Get next version number
        version = self._next_version(db, client_id, report_period)

        # Create report
        report = ClientIntelligenceReport(
            client_id=client_id,
            report_period=report_period,
            report_version=version,
            observed_json=observed_json,
            planned_json={},
            forecasted_json={},
            risks_json={},
            business_impact_json={},
            model_version="scurve_v1",
            data_freshness_json=data_freshness,
            status="draft",
        )

        db.add(report)
        db.flush()

        logger.info(
            "Composed observed report for client %s, period %s v%d",
            client_id,
            report_period,
            version,
        )
        return report

    def compose_with_forecast(
        self, db: Session, client_id: uuid.UUID
    ) -> ClientIntelligenceReport:
        """Compose a report with Layer 1 (observed) + Layer 3 (forecast) data.

        Extends compose_observed_report by also computing visibility forecast
        and populating forecasted_json with ScenarioTriple at 4w/12w/24w,
        per-engine projections, gap-to-leader analysis, and model metadata.

        Args:
            db: SQLAlchemy session.
            client_id: UUID of the client.

        Returns:
            Persisted ClientIntelligenceReport with status='draft'.
        """
        # a) Collect observed metrics
        collector = ObservedRealityCollector()
        snapshot = collector.collect(db, client_id)

        # b) Build observed_json from snapshot
        observed_json = self._build_observed_section(snapshot)

        # c) Compute platform risk
        risk = PlatformRiskAssessment.compute(snapshot, None)

        # d) Generate forecast
        forecaster = VisibilityForecaster()
        seed_key = f"{client_id}_{self._current_iso_week()}"
        forecast = forecaster.forecast(snapshot, None, risk, seed_key=seed_key)

        # e) Build forecasted_json
        forecasted_json = self._build_forecasted_section(
            forecast, observed_json, risk
        )

        # f) Build risks_json
        risks_json = self._assemble_risks(risk, snapshot)

        # g) Compute data freshness
        data_freshness = self._compute_data_freshness(snapshot)

        # h) Determine report period (current ISO week)
        report_period = self._current_iso_week()

        # i) Get next version number
        version = self._next_version(db, client_id, report_period)

        # j) Create report with forecasted_json + risks_json populated
        report = ClientIntelligenceReport(
            client_id=client_id,
            report_period=report_period,
            report_version=version,
            observed_json=observed_json,
            planned_json={},
            forecasted_json=forecasted_json,
            risks_json=risks_json,
            business_impact_json={},
            model_version="scurve_v1",
            data_freshness_json=data_freshness,
            status="draft",
        )

        db.add(report)
        db.flush()

        logger.info(
            "Composed forecast report for client %s, period %s v%d",
            client_id,
            report_period,
            version,
        )
        return report

    def compose_full_report(
        self, db: Session, client_id: uuid.UUID
    ) -> ClientIntelligenceReport:
        """Compose a complete report with all 5 layers populated.

        1. Collect observed metrics (Layer 1)
        2. Collect execution intent (Layer 2)
        3. Compute platform risk
        4. Generate forecast (Layer 3)
        5. Assemble risks (Layer 4 — risks section)
        6. Build planned_json from intent snapshot
        7. Build business_impact_json (Layer 5)
        8. Record accuracy predictions
        9. Create report with ALL 5 layers populated
        10. Supersede old drafts

        Args:
            db: SQLAlchemy session.
            client_id: UUID of the client.

        Returns:
            Persisted ClientIntelligenceReport with all layers and status='draft'.
        """
        # 1. Collect observed metrics
        collector = ObservedRealityCollector()
        snapshot = collector.collect(db, client_id)

        # 2. Collect execution intent
        intent = collect_intent(db, client_id)

        # 3. Build observed_json
        observed_json = self._build_observed_section(snapshot)

        # 4. Compute platform risk
        risk = PlatformRiskAssessment.compute(snapshot, intent)

        # 5. Generate forecast
        forecaster = VisibilityForecaster()
        report_period = self._current_iso_week()
        seed_key = f"{client_id}_{report_period}"
        forecast = forecaster.forecast(snapshot, intent, risk, seed_key=seed_key)

        # 6. Build forecasted_json
        forecasted_json = self._build_forecasted_section(
            forecast, observed_json, risk
        )

        # 7. Build risks_json
        risks_json = self._assemble_risks(risk, snapshot)

        # 8. Build planned_json from intent snapshot
        planned_json = self._build_planned_section(intent)

        # 9. Build business_impact_json
        business_impact_json = self._build_business_impact_section(
            db, client_id, observed_json, forecasted_json
        )

        # 10. Compute data freshness
        data_freshness = self._compute_data_freshness(snapshot)

        # 11. Get next version number
        version = self._next_version(db, client_id, report_period)

        # 12. Supersede old drafts for same client+period
        self._supersede_old_drafts(db, client_id, report_period)

        # 13. Create report with all 5 layers
        report = ClientIntelligenceReport(
            client_id=client_id,
            report_period=report_period,
            report_version=version,
            observed_json=observed_json,
            planned_json=planned_json,
            forecasted_json=forecasted_json,
            risks_json=risks_json,
            business_impact_json=business_impact_json,
            model_version="scurve_v1",
            data_freshness_json=data_freshness,
            status="draft",
        )

        db.add(report)
        db.flush()

        # 14. Record accuracy predictions
        record_predictions(
            db=db,
            report_id=report.id,
            client_id=client_id,
            forecasted_json=forecasted_json,
        )

        logger.info(
            "Composed full 5-layer report for client %s, period %s v%d",
            client_id,
            report_period,
            version,
        )
        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_planned_section(self, intent) -> dict:
        """Build the planned_json section from IntentSnapshot.

        Returns a dict matching the PlannedSection schema:
        - planned_comments_this_week: count of comment_slot intents
        - avatars_active: count of avatars in phase_roadmap without blockers
        - subreddits_targeted: from coverage_plan
        - phase_distribution: from phase_roadmap
        - next_geo_batch: first geo_batch target_date formatted
        - next_pipeline_run: static or computed
        - pending_drafts: count of planned/approved comment_slot in weekly_plan
        - plan_version: snapshot_version
        - plan_valid_until: captured_at + 7 days
        """
        # Count planned comments (daily_plan + weekly_plan of type comment_slot)
        comment_count = 0
        for item in intent.daily_plan:
            if item.get("intent_type") == "comment_slot":
                comment_count += 1
        for item in intent.weekly_plan:
            if item.get("intent_type") == "comment_slot":
                comment_count += 1

        # Active avatars (no blockers)
        avatars_active = 0
        phase_distribution: dict[str, int] = {}
        for avatar_entry in intent.phase_roadmap:
            blockers = avatar_entry.get("blockers", [])
            if not blockers:
                avatars_active += 1
            phase_label = f"Phase {avatar_entry.get('current_phase', 0)}"
            phase_distribution[phase_label] = (
                phase_distribution.get(phase_label, 0) + 1
            )

        # Subreddits targeted
        subreddits_targeted = [
            entry.get("subreddit_name", "")
            for entry in intent.coverage_plan
            if entry.get("subreddit_name")
        ]

        # Next GEO batch from weekly_plan
        next_geo_batch = "Not scheduled"
        for item in intent.weekly_plan:
            if item.get("intent_type") == "geo_batch":
                target_str = item.get("target_date", "")
                try:
                    target_dt = datetime.fromisoformat(target_str)
                    next_geo_batch = target_dt.strftime("%a %b %-d, %H:%M")
                except (ValueError, TypeError):
                    pass
                break

        # Next pipeline run (static for now: "Tomorrow 08:00")
        next_pipeline_run = "Tomorrow 08:00"

        # Pending drafts: count of weekly_plan intents of type comment_slot
        # with status planned or approved
        pending_drafts = 0
        for item in intent.weekly_plan:
            if item.get("intent_type") == "comment_slot" and item.get(
                "status"
            ) in ("planned", "approved"):
                pending_drafts += 1

        # Plan validity
        captured_at_str = intent.captured_at
        try:
            captured_dt = datetime.fromisoformat(captured_at_str)
            plan_valid_until = (captured_dt + timedelta(days=7)).isoformat()
        except (ValueError, TypeError):
            plan_valid_until = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat()

        return {
            "label": "📋 Current Execution Plan",
            "planned_comments_this_week": comment_count,
            "avatars_active": avatars_active,
            "subreddits_targeted": subreddits_targeted,
            "phase_distribution": phase_distribution,
            "next_geo_batch": next_geo_batch,
            "next_pipeline_run": next_pipeline_run,
            "pending_drafts": pending_drafts,
            "plan_version": intent.snapshot_version,
            "plan_valid_until": plan_valid_until,
        }

    def _build_business_impact_section(
        self,
        db: Session,
        client_id: uuid.UUID,
        observed_json: dict,
        forecasted_json: dict,
    ) -> dict:
        """Build the business_impact_json section.

        Delegates to BusinessImpactCalculator for all computations.

        Args:
            db: SQLAlchemy session.
            client_id: UUID of the client.
            observed_json: Observed section with brand_visibility_rate + competitor_rates.
            forecasted_json: Forecasted section with visibility projections.

        Returns:
            Dict matching the business_impact_json schema.
        """
        # Get client plan_type for pricing
        plan_type = (
            db.query(Client.plan_type)
            .filter(Client.id == client_id)
            .scalar()
        )
        plan_type = plan_type or "starter"

        calculator = BusinessImpactCalculator()
        impact = calculator.compute(observed_json, forecasted_json, plan_type)
        return impact.to_dict()

    def _supersede_old_drafts(
        self, db: Session, client_id: uuid.UUID, report_period: str
    ) -> int:
        """Mark previous draft reports as 'superseded' for same client+period.

        Returns the number of reports superseded.
        """
        superseded_count = (
            db.query(ClientIntelligenceReport)
            .filter(
                ClientIntelligenceReport.client_id == client_id,
                ClientIntelligenceReport.report_period == report_period,
                ClientIntelligenceReport.status == "draft",
            )
            .update({"status": "superseded"})
        )

        if superseded_count > 0:
            logger.info(
                "Superseded %d old draft report(s) for client %s, period %s",
                superseded_count,
                client_id,
                report_period,
            )

        return superseded_count

    def _assemble_risks(
        self, risk: PlatformRiskAssessment, snapshot: ObservedSnapshot
    ) -> dict:
        """Build the risks_json section of the report.

        Derives:
          - platform_risk_level from discount_factor thresholds
          - platform_risk_factors from individual risk fields
          - forecast_sensitivity (static assumptions list)
          - data_gaps from snapshot.data_gaps
          - stale_data_warnings from metrics where is_stale == True

        Args:
            risk: Computed PlatformRiskAssessment with all risk factors.
            snapshot: ObservedSnapshot with metrics_json and data_gaps.

        Returns:
            Dict matching the risks_json schema for ClientIntelligenceReport.
        """
        # --- Platform risk level from discount_factor ---
        if risk.discount_factor < 0.15:
            platform_risk_level = "low"
        elif risk.discount_factor < 0.35:
            platform_risk_level = "medium"
        else:
            platform_risk_level = "high"

        # --- Platform risk factors ---
        platform_risk_factors = self._build_platform_risk_factors(risk)

        # --- Forecast sensitivity (what happens if assumptions are wrong) ---
        forecast_sensitivity = [
            {
                "assumption": "Reddit content → LLM citation lag is 6-8 weeks",
                "if_wrong": "Visibility growth delayed by 4+ weeks",
                "how_we_detect": "GEO batch at week 8 shows no improvement",
            },
            {
                "assumption": "Continued posting volume at current rate",
                "if_wrong": "Projection delayed proportionally to volume reduction",
                "how_we_detect": "Weekly draft count drops >50% vs last week",
            },
            {
                "assumption": "No major Reddit platform policy changes",
                "if_wrong": "Re-baseline needed, current forecast invalidated",
                "how_we_detect": "Survival rate drops >20pp in single week",
            },
            {
                "assumption": "Per-engine growth rates remain stable",
                "if_wrong": "Per-engine projections become unreliable",
                "how_we_detect": "Engine-specific brand rate deviates >10pp from projection",
            },
        ]

        # --- Data gaps from snapshot ---
        data_gaps = list(snapshot.data_gaps) if snapshot.data_gaps else []

        # --- Stale data warnings from metrics ---
        stale_data_warnings = self._extract_stale_warnings(snapshot)

        return {
            "label": "⚠️ Risks & Sensitivities",
            "platform_risk_level": platform_risk_level,
            "platform_risk_factors": platform_risk_factors,
            "forecast_sensitivity": forecast_sensitivity,
            "data_gaps": data_gaps,
            "stale_data_warnings": stale_data_warnings,
        }

    def _build_platform_risk_factors(
        self, risk: PlatformRiskAssessment
    ) -> list[dict]:
        """Build the platform_risk_factors list from PlatformRiskAssessment fields.

        Each factor includes: factor name, level, impact_on_forecast, mitigation.
        Level thresholds: <0.1 = low, 0.1-0.3 = medium, >0.3 = high.
        """
        factors: list[dict] = []

        # 1. Avatar shadowban risk
        sb_level = self._classify_risk_level(risk.shadowban_probability)
        sb_impact = self._compute_factor_impact(
            "shadowban", risk.shadowban_probability
        )
        factors.append(
            {
                "factor": "avatar_shadowban_risk",
                "level": sb_level,
                "impact_on_forecast": sb_impact,
                "mitigation": "health checks 2×/day, auto-recovery via Phase 0",
            }
        )

        # 2. Content removal trend
        removal_level = self._classify_removal_trend_level(
            risk.removal_rate_trend
        )
        removal_impact = self._compute_removal_impact(risk.removal_rate_trend)
        factors.append(
            {
                "factor": "content_removal_trend",
                "level": removal_level,
                "impact_on_forecast": removal_impact,
                "mitigation": "fitness gate blocks dangerous subs",
            }
        )

        # 3. Subreddit moderation risk
        sub_risk_value = risk.subreddit_risk_avg / 100.0
        sub_level = self._classify_risk_level(sub_risk_value)
        sub_impact = self._compute_factor_impact(
            "subreddit_moderation", sub_risk_value
        )
        factors.append(
            {
                "factor": "subreddit_moderation_risk",
                "level": sub_level,
                "impact_on_forecast": sub_impact,
                "mitigation": "risk-aware zone routing, weekly profile refresh",
            }
        )

        # 4. Account maturity risk (1 - account_age_factor = risk)
        age_risk_value = 1.0 - risk.account_age_factor
        age_level = self._classify_risk_level(age_risk_value)
        age_impact = self._compute_factor_impact(
            "account_maturity", age_risk_value
        )
        factors.append(
            {
                "factor": "account_maturity_risk",
                "level": age_level,
                "impact_on_forecast": age_impact,
                "mitigation": "phase system gates content by account age and karma",
            }
        )

        return factors

    def _classify_risk_level(self, value: float) -> str:
        """Classify a 0-1 risk value into low/medium/high.

        <0.1 = low, 0.1-0.3 = medium, >0.3 = high.
        """
        if value < 0.1:
            return "low"
        elif value <= 0.3:
            return "medium"
        else:
            return "high"

    def _classify_removal_trend_level(self, trend: str) -> str:
        """Map removal_rate_trend string to a risk level."""
        mapping = {
            "improving": "low",
            "stable": "stable",
            "degrading": "high",
        }
        return mapping.get(trend, "stable")

    def _compute_factor_impact(self, factor_type: str, value: float) -> str:
        """Compute human-readable impact statement for a risk factor."""
        pct = round(value * 100)
        if value < 0.1:
            return "no impact on current forecast"
        elif value <= 0.3:
            return f"reduces ceiling by {pct}%"
        else:
            return f"significantly reduces ceiling by {pct}%"

    def _compute_removal_impact(self, trend: str) -> str:
        """Compute impact statement for removal rate trend."""
        if trend == "improving":
            return "no impact on current forecast"
        elif trend == "stable":
            return "no impact on current forecast"
        else:
            return "reduces ceiling by 15-30%, widens confidence interval"

    def _extract_stale_warnings(self, snapshot: ObservedSnapshot) -> list[str]:
        """Extract stale data warnings from snapshot.metrics_json.

        Finds all metrics where is_stale == True and builds warning strings.
        """
        warnings: list[str] = []
        metrics = snapshot.metrics_json if snapshot.metrics_json else []

        if not isinstance(metrics, list):
            return warnings

        for metric in metrics:
            if not isinstance(metric, dict):
                continue
            if metric.get("is_stale", False):
                metric_id = metric.get("metric_id", "unknown")
                measured_at = metric.get("measured_at", "unknown")
                threshold = metric.get("staleness_threshold_hours", "?")
                warnings.append(
                    f"{metric_id} is stale (last measured: {measured_at}, "
                    f"threshold: {threshold}h)"
                )

        return warnings

    def _build_forecasted_section(
        self,
        forecast: VisibilityForecast,
        observed_json: dict,
        risk: PlatformRiskAssessment,
    ) -> dict:
        """Build the forecasted_json section from forecast results.

        Returns a dict with:
          - label, visibility_4w/12w/24w (ScenarioTriple dicts)
          - per_engine_12w (per-engine ScenarioTriple at week 12)
          - leader_name, leader_rate, gap_current_pp, gap_projected_12w_pp, weeks_to_parity
          - model_name, model_parameters, assumptions
        """
        scenarios = forecast.scenarios

        # ScenarioTriple at 4w, 12w, 24w horizons (0-indexed: week 3, 11, 23)
        visibility_4w = self._scenario_triple_to_dict(
            get_scenario_triple(scenarios, 3)
        )
        visibility_12w = self._scenario_triple_to_dict(
            get_scenario_triple(scenarios, 11)
        )
        visibility_24w = self._scenario_triple_to_dict(
            get_scenario_triple(scenarios, 23)
        )

        # Per-engine at 12w (week index 11)
        per_engine_12w = {}
        for engine_name, engine_weekly in forecast.per_engine.items():
            if len(engine_weekly) > 11:
                per_engine_12w[engine_name] = {
                    "c": round(engine_weekly[11] * 0.7, 2),  # conservative estimate
                    "e": round(engine_weekly[11], 2),
                    "o": round(engine_weekly[11] * 1.2, 2),  # optimistic estimate
                }
            else:
                per_engine_12w[engine_name] = {"c": 0.0, "e": 0.0, "o": 0.0}

        # Gap-to-leader calculation
        gap_result = self._compute_gap_to_leader(
            observed_json, forecast
        )

        # Model metadata
        model_parameters = {
            "ceiling": DEFAULT_CEILING,
            "midpoint": DEFAULT_MIDPOINT,
            "steepness": DEFAULT_STEEPNESS,
            "engine_multipliers": ENGINE_MULTIPLIERS,
            "noise_amplitude": NOISE_AMPLITUDE,
            "risk_discount": risk.discount_factor,
        }

        return {
            "label": "📈 Forecasted Outcomes",
            "visibility_4w": visibility_4w,
            "visibility_12w": visibility_12w,
            "visibility_24w": visibility_24w,
            "per_engine_12w": per_engine_12w,
            "leader_name": gap_result["leader_name"],
            "leader_rate": gap_result["leader_rate"],
            "gap_current_pp": gap_result["gap_current_pp"],
            "gap_projected_12w_pp": gap_result["gap_projected_12w_pp"],
            "weeks_to_parity": gap_result["weeks_to_parity"],
            "model_name": "logistic_scurve_v1",
            "model_parameters": model_parameters,
            "assumptions": forecast.assumptions,
        }

    def _scenario_triple_to_dict(self, triple) -> dict:
        """Convert a ScenarioTriple dataclass to a JSON-serializable dict."""
        return {
            "conservative": round(triple.conservative, 2),
            "expected": round(triple.expected, 2),
            "optimistic": round(triple.optimistic, 2),
            "unit": triple.unit,
            "confidence_level": triple.confidence_level,
        }

    def _compute_gap_to_leader(
        self, observed_json: dict, forecast: VisibilityForecast
    ) -> dict:
        """Compute gap-to-leader metrics from competitor rates.

        Competitor rates are stored as ratios (0-1) in observed_json.
        Forecast values are in percentage (0-100).
        Converts competitor rates to % for comparison.

        Returns a dict with: leader_name, leader_rate, gap_current_pp,
                             gap_projected_12w_pp, weeks_to_parity.
        """
        competitor_rates = observed_json.get("competitor_rates", {})

        if not competitor_rates:
            return {
                "leader_name": None,
                "leader_rate": None,
                "gap_current_pp": 0.0,
                "gap_projected_12w_pp": 0.0,
                "weeks_to_parity": None,
            }

        # Find the competitor with the highest rate
        leader_name = max(competitor_rates, key=competitor_rates.get)
        leader_rate_ratio = competitor_rates[leader_name]
        # Convert ratio (0-1) to percentage (0-100)
        leader_rate_pct = leader_rate_ratio * 100.0

        # Current gap: leader_rate - baseline_rate (both in %)
        baseline_rate = forecast.baseline_rate
        gap_current_pp = round(leader_rate_pct - baseline_rate, 1)

        # Projected gap at 12w: leader_rate - expected scenario at week 11
        expected_scenario = forecast.scenarios.get("expected", [])
        if len(expected_scenario) > 11:
            projected_12w = expected_scenario[11]
        else:
            projected_12w = baseline_rate

        gap_projected_12w_pp = round(leader_rate_pct - projected_12w, 1)

        # Weeks to parity: iterate expected scenario to find when value >= leader_rate_pct
        weeks_to_parity = None
        for week_idx, value in enumerate(expected_scenario):
            if value >= leader_rate_pct:
                weeks_to_parity = week_idx + 1  # 1-indexed weeks
                break

        return {
            "leader_name": leader_name,
            "leader_rate": round(leader_rate_ratio, 4),
            "gap_current_pp": gap_current_pp,
            "gap_projected_12w_pp": gap_projected_12w_pp,
            "weeks_to_parity": weeks_to_parity,
        }

    def _build_observed_section(self, snapshot: ObservedSnapshot) -> dict:
        """Transform the raw snapshot metrics into structured observed section.

        Returns a dict with keys:
          - brand_visibility_rate: overall GEO rate
          - per_engine_rates: {perplexity, chatgpt, claude} → float
          - competitor_rates: {name → float}
          - category_rates: {category → float}
          - brand_mentions_count: int
          - total_queries_measured: int
          - engines_active: list of active engine names
          - comments_posted: int (from execution metrics)
          - avg_karma_per_comment: float
          - survival_rate: float
          - reply_depth_avg: float
          - brand_excerpts: list of excerpt dicts
          - sample_sizes: dict of metric → sample_size
          - staleness: dict of source → is_stale flag
        """
        metrics = snapshot.metrics_json or []

        # Helper to find a metric by ID
        def _find(metric_id: str) -> dict | None:
            for m in metrics:
                if m.get("metric_id") == metric_id:
                    return m
            return None

        # Helper to find all metrics matching a prefix
        def _find_prefix(prefix: str) -> list[dict]:
            return [m for m in metrics if m.get("metric_id", "").startswith(prefix)]

        # Brand visibility rate (overall GEO)
        overall_metric = _find("geo.brand_rate.overall")
        brand_visibility_rate = overall_metric["value"] if overall_metric else 0.0
        total_queries = overall_metric.get("sample_size", 0) if overall_metric else 0

        # Per-engine rates
        per_engine_rates: dict[str, float] = {}
        engines_active: list[str] = []
        for engine_metric in _find_prefix("geo.brand_rate."):
            mid = engine_metric["metric_id"]
            # Skip overall
            if mid == "geo.brand_rate.overall":
                continue
            engine_name = mid.replace("geo.brand_rate.", "")
            per_engine_rates[engine_name] = engine_metric["value"]
            engines_active.append(engine_name)

        # Competitor rates
        competitor_rates: dict[str, float] = {}
        for comp_metric in _find_prefix("geo.competitor_rate."):
            comp_name = comp_metric["metric_id"].replace("geo.competitor_rate.", "")
            competitor_rates[comp_name] = comp_metric["value"]

        # Category rates
        category_rates: dict[str, float] = {}
        for cat_metric in _find_prefix("geo.category_rate."):
            cat_name = cat_metric["metric_id"].replace("geo.category_rate.", "")
            category_rates[cat_name] = cat_metric["value"]

        # Brand mentions count (derived from overall rate × sample)
        brand_mentions_count = 0
        if overall_metric:
            brand_mentions_count = round(
                overall_metric["value"] * overall_metric.get("sample_size", 0)
            )

        # Reddit / execution metrics
        posted_metric = _find("execution.drafts_posted_7d")
        comments_posted = int(posted_metric["value"]) if posted_metric else 0

        karma_metric = _find("execution.avg_karma_per_comment")
        avg_karma_per_comment = karma_metric["value"] if karma_metric else 0.0

        survival_metric = _find("reddit.survival_rate_7d")
        survival_rate = survival_metric["value"] if survival_metric else 0.0

        reply_metric = _find("reddit.reply_depth_avg")
        reply_depth_avg = reply_metric["value"] if reply_metric else 0.0

        # Brand excerpts from source_availability
        source_avail = snapshot.source_availability or {}
        brand_excerpts = source_avail.get("brand_excerpts", [])

        # Sample sizes for transparency
        sample_sizes: dict[str, int] = {}
        for m in metrics:
            sample_sizes[m["metric_id"]] = m.get("sample_size", 0)

        # Staleness indicators
        staleness: dict[str, bool] = {}
        for source_name, source_info in source_avail.items():
            if source_name == "brand_excerpts":
                continue
            if isinstance(source_info, dict):
                stale_count = source_info.get("stale_count", 0)
                staleness[source_name] = stale_count > 0

        return {
            "brand_visibility_rate": brand_visibility_rate,
            "per_engine_rates": per_engine_rates,
            "competitor_rates": competitor_rates,
            "category_rates": category_rates,
            "brand_mentions_count": brand_mentions_count,
            "total_queries_measured": total_queries,
            "engines_active": engines_active,
            "comments_posted": comments_posted,
            "avg_karma_per_comment": avg_karma_per_comment,
            "survival_rate": survival_rate,
            "reply_depth_avg": reply_depth_avg,
            "brand_excerpts": brand_excerpts,
            "sample_sizes": sample_sizes,
            "staleness": staleness,
        }

    def _compute_data_freshness(self, snapshot: ObservedSnapshot) -> dict:
        """Compute data freshness from source timestamps.

        Returns a dict like: {"geo": "2d ago", "karma": "4h ago", "execution": "1h ago"}
        """
        source_avail = snapshot.source_availability or {}
        now = datetime.now(timezone.utc)
        freshness: dict[str, str] = {}

        # Map source tables to human-friendly names
        source_name_map = {
            "geo_query_results": "geo",
            "karma_snapshots": "karma",
            "comment_drafts": "execution",
        }

        for table_name, friendly_name in source_name_map.items():
            source_info = source_avail.get(table_name)
            if not source_info or not isinstance(source_info, dict):
                freshness[friendly_name] = "no data"
                continue

            latest = source_info.get("latest_measurement")
            if not latest:
                freshness[friendly_name] = "no data"
                continue

            freshness[friendly_name] = self._format_time_ago(latest, now)

        return freshness

    def _format_time_ago(self, timestamp_str: str, now: datetime) -> str:
        """Format an ISO timestamp as a human-readable 'X ago' string."""
        try:
            if isinstance(timestamp_str, datetime):
                ts = timestamp_str
            else:
                ts = datetime.fromisoformat(timestamp_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return "unknown"

        delta = now - ts
        total_seconds = delta.total_seconds()

        if total_seconds < 0:
            return "just now"

        minutes = total_seconds / 60
        hours = total_seconds / 3600
        days = total_seconds / 86400

        if minutes < 60:
            return f"{int(minutes)}m ago"
        elif hours < 24:
            return f"{int(hours)}h ago"
        elif days < 7:
            return f"{int(days)}d ago"
        else:
            weeks = int(days / 7)
            return f"{weeks}w ago"

    def _current_iso_week(self) -> str:
        """Return current ISO week in '2026-W27' format."""
        now = datetime.now(timezone.utc)
        return now.strftime("%G-W%V")

    def _next_version(
        self, db: Session, client_id: uuid.UUID, report_period: str
    ) -> int:
        """Query max report_version for this client+period, return +1."""
        max_version = (
            db.query(func.max(ClientIntelligenceReport.report_version))
            .filter(
                ClientIntelligenceReport.client_id == client_id,
                ClientIntelligenceReport.report_period == report_period,
            )
            .scalar()
        )
        return (max_version or 0) + 1

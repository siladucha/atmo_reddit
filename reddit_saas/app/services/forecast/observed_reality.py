"""Observed Reality Collector — Layer 1 of Forecast & Reporting.

Collects all ground-truth metrics for a client from validated data sources:
- GeoQueryResult (brand mention rates per engine)
- KarmaSnapshot (engagement quality)
- CommentDraft (execution throughput)
- GeoPrompt (category-level breakdown)

All queries are client-scoped (P7 isolation). No LLM calls.
Output: ObservedSnapshot (immutable, stored in DB).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.comment_draft import CommentDraft
from app.models.geo_execution import GeoExecutionBatch, GeoQueryResult
from app.models.geo_prompt import GeoPrompt
from app.models.karma_snapshot import KarmaSnapshot
from app.models.observed_snapshot import ObservedSnapshot

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Staleness thresholds in hours
GEO_STALENESS_HOURS = 168  # 7 days
REDDIT_STALENESS_HOURS = 48
EXECUTION_STALENESS_HOURS = 24

# Provider mapping for metric IDs
PROVIDER_MAP = {
    "perplexity": "perplexity",
    "openai": "chatgpt",
    "anthropic": "claude",
}

# Confidence thresholds
CONFIDENCE_HIGH = 20
CONFIDENCE_MEDIUM = 5


def _confidence(sample_size: int) -> str:
    """Determine confidence level based on sample size."""
    if sample_size >= CONFIDENCE_HIGH:
        return "high"
    elif sample_size >= CONFIDENCE_MEDIUM:
        return "medium"
    return "low"


def _is_stale(measured_at: datetime, threshold_hours: int) -> bool:
    """Check if a measurement is stale."""
    now = datetime.now(timezone.utc)
    if measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    return (now - measured_at).total_seconds() > threshold_hours * 3600


def _make_metric(
    metric_id: str,
    value: float,
    measured_at: datetime,
    time_window: str,
    validation: str,
    staleness_threshold_hours: int,
    source_table: str,
    sample_size: int,
) -> dict[str, Any]:
    """Build a single ObservedMetric dict."""
    if measured_at and measured_at.tzinfo is None:
        measured_at = measured_at.replace(tzinfo=timezone.utc)
    return {
        "metric_id": metric_id,
        "value": round(value, 4),
        "measured_at": measured_at.isoformat() if measured_at else None,
        "time_window": time_window,
        "validation": validation,
        "staleness_threshold_hours": staleness_threshold_hours,
        "is_stale": _is_stale(measured_at, staleness_threshold_hours) if measured_at else True,
        "source_table": source_table,
        "sample_size": sample_size,
        "confidence": _confidence(sample_size),
    }


# ---------------------------------------------------------------------------
# Main Collector
# ---------------------------------------------------------------------------


class ObservedRealityCollector:
    """Collects all ground-truth metrics for a client.

    Returns an immutable ObservedSnapshot containing validated measurements
    from GEO batches, KarmaSnapshots, CommentDrafts, and related sources.
    """

    def collect(self, db: Session, client_id: uuid.UUID) -> ObservedSnapshot:
        """Collect all observed metrics and persist as ObservedSnapshot.

        Args:
            db: SQLAlchemy session.
            client_id: UUID of the client to collect metrics for.

        Returns:
            Persisted ObservedSnapshot instance.
        """
        now = datetime.now(timezone.utc)

        metrics: list[dict[str, Any]] = []
        metrics.extend(self._collect_geo_metrics(db, client_id))
        metrics.extend(self._collect_reddit_metrics(db, client_id))
        metrics.extend(self._collect_execution_metrics(db, client_id))
        metrics.extend(self._collect_competitor_metrics(db, client_id))
        metrics.extend(self._collect_category_metrics(db, client_id))

        data_gaps = self._identify_gaps(db, client_id)
        brand_excerpts = self._extract_brand_excerpts(db, client_id)

        # Build source availability map
        source_availability = self._build_source_availability(metrics)

        snapshot = ObservedSnapshot(
            client_id=client_id,
            collected_at=now,
            metrics_json=metrics,
            data_gaps=data_gaps,
            source_availability=source_availability,
        )

        # Store brand excerpts in metrics_json as a separate metadata entry
        # (excerpts are informational, not numeric metrics)
        if brand_excerpts:
            snapshot.source_availability["brand_excerpts"] = brand_excerpts

        db.add(snapshot)
        db.flush()

        logger.info(
            "Collected %d metrics for client %s (gaps: %d)",
            len(metrics),
            client_id,
            len(data_gaps),
        )
        return snapshot

    # ------------------------------------------------------------------
    # GEO Metrics (brand mention rates per engine)
    # ------------------------------------------------------------------

    def _collect_geo_metrics(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Query GeoQueryResult for the latest completed batch, compute per-engine rates."""
        metrics: list[dict[str, Any]] = []

        # Find the latest completed batch for this client
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )

        if not latest_batch:
            return metrics

        batch_id = latest_batch.id
        batch_time = latest_batch.completed_at or latest_batch.started_at

        # Get all successful results from this batch
        results = (
            db.query(GeoQueryResult)
            .filter(
                GeoQueryResult.execution_batch_id == batch_id,
                GeoQueryResult.client_id == client_id,
                GeoQueryResult.status == "success",
            )
            .all()
        )

        if not results:
            return metrics

        # Overall brand rate
        total = len(results)
        brand_count = sum(1 for r in results if r.brand_mentioned)
        brand_rate = brand_count / total if total > 0 else 0.0

        metrics.append(
            _make_metric(
                metric_id="geo.brand_rate.overall",
                value=brand_rate,
                measured_at=batch_time,
                time_window="batch",
                validation="api_measured",
                staleness_threshold_hours=GEO_STALENESS_HOURS,
                source_table="geo_query_results",
                sample_size=total,
            )
        )

        # Per-engine brand rates
        engine_groups: dict[str, list[GeoQueryResult]] = {}
        for r in results:
            provider = r.provider.lower() if r.provider else "unknown"
            engine_groups.setdefault(provider, []).append(r)

        for provider_key, provider_results in engine_groups.items():
            metric_name = PROVIDER_MAP.get(provider_key, provider_key)
            engine_total = len(provider_results)
            engine_brand = sum(1 for r in provider_results if r.brand_mentioned)
            engine_rate = engine_brand / engine_total if engine_total > 0 else 0.0

            metrics.append(
                _make_metric(
                    metric_id=f"geo.brand_rate.{metric_name}",
                    value=engine_rate,
                    measured_at=batch_time,
                    time_window="batch",
                    validation="api_measured",
                    staleness_threshold_hours=GEO_STALENESS_HOURS,
                    source_table="geo_query_results",
                    sample_size=engine_total,
                )
            )

        return metrics

    # ------------------------------------------------------------------
    # Reddit Metrics (karma, survival, reply depth)
    # ------------------------------------------------------------------

    def _collect_reddit_metrics(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Collect karma avg, survival rate, removal rate, reply depth from KarmaSnapshot."""
        metrics: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # Get comment_draft_ids for this client (posted in last 7 days)
        posted_draft_ids = (
            db.query(CommentDraft.id)
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= seven_days_ago,
            )
            .subquery()
        )

        # Karma avg from 7d window snapshots
        karma_snapshots = (
            db.query(KarmaSnapshot)
            .filter(
                KarmaSnapshot.comment_draft_id.in_(
                    db.query(posted_draft_ids.c.id)
                ),
                KarmaSnapshot.check_window == "7d",
            )
            .all()
        )

        if karma_snapshots:
            karma_values = [s.karma_value for s in karma_snapshots]
            karma_avg = sum(karma_values) / len(karma_values)
            latest_checked = max(s.checked_at for s in karma_snapshots)

            metrics.append(
                _make_metric(
                    metric_id="reddit.karma_avg_7d",
                    value=karma_avg,
                    measured_at=latest_checked,
                    time_window="7d",
                    validation="platform_confirmed",
                    staleness_threshold_hours=REDDIT_STALENESS_HOURS,
                    source_table="karma_snapshots",
                    sample_size=len(karma_snapshots),
                )
            )

            # Reply depth avg
            reply_counts = [s.reply_count for s in karma_snapshots]
            reply_avg = sum(reply_counts) / len(reply_counts)
            metrics.append(
                _make_metric(
                    metric_id="reddit.reply_depth_avg",
                    value=reply_avg,
                    measured_at=latest_checked,
                    time_window="7d",
                    validation="platform_confirmed",
                    staleness_threshold_hours=REDDIT_STALENESS_HOURS,
                    source_table="karma_snapshots",
                    sample_size=len(karma_snapshots),
                )
            )

        # Survival rate (posted, not deleted in 7d window)
        posted_7d_count = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        deleted_7d_count = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= seven_days_ago,
                CommentDraft.is_deleted == True,  # noqa: E712
            )
            .scalar()
        ) or 0

        if posted_7d_count > 0:
            survival_rate = (posted_7d_count - deleted_7d_count) / posted_7d_count
            removal_rate = deleted_7d_count / posted_7d_count

            # Use the latest posted_at as measured_at
            latest_posted = (
                db.query(func.max(CommentDraft.posted_at))
                .filter(
                    CommentDraft.client_id == client_id,
                    CommentDraft.status == "posted",
                    CommentDraft.posted_at >= seven_days_ago,
                )
                .scalar()
            )

            metrics.append(
                _make_metric(
                    metric_id="reddit.survival_rate_7d",
                    value=survival_rate,
                    measured_at=latest_posted or now,
                    time_window="7d",
                    validation="system_counted",
                    staleness_threshold_hours=REDDIT_STALENESS_HOURS,
                    source_table="comment_drafts",
                    sample_size=posted_7d_count,
                )
            )

            metrics.append(
                _make_metric(
                    metric_id="reddit.removal_rate_7d",
                    value=removal_rate,
                    measured_at=latest_posted or now,
                    time_window="7d",
                    validation="platform_confirmed",
                    staleness_threshold_hours=REDDIT_STALENESS_HOURS,
                    source_table="comment_drafts",
                    sample_size=posted_7d_count,
                )
            )

        return metrics

    # ------------------------------------------------------------------
    # Execution Metrics (drafts generated, posted, success rate)
    # ------------------------------------------------------------------

    def _collect_execution_metrics(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Collect drafts generated/posted/deleted counts from CommentDraft."""
        metrics: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Drafts generated in last 7 days
        drafts_generated = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.created_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        metrics.append(
            _make_metric(
                metric_id="execution.drafts_generated_7d",
                value=float(drafts_generated),
                measured_at=now,
                time_window="7d",
                validation="system_counted",
                staleness_threshold_hours=EXECUTION_STALENESS_HOURS,
                source_table="comment_drafts",
                sample_size=drafts_generated,
            )
        )

        # Drafts posted in last 7 days
        drafts_posted = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        metrics.append(
            _make_metric(
                metric_id="execution.drafts_posted_7d",
                value=float(drafts_posted),
                measured_at=now,
                time_window="7d",
                validation="system_counted",
                staleness_threshold_hours=EXECUTION_STALENESS_HOURS,
                source_table="comment_drafts",
                sample_size=drafts_posted,
            )
        )

        # Posting success rate: posted / (posted + rejected) in 7d
        # "failed" in this context means rejected drafts that never got posted
        rejected_7d = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "rejected",
                CommentDraft.created_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        denominator = drafts_posted + rejected_7d
        if denominator > 0:
            success_rate = drafts_posted / denominator
            metrics.append(
                _make_metric(
                    metric_id="execution.posting_success_rate",
                    value=success_rate,
                    measured_at=now,
                    time_window="7d",
                    validation="system_counted",
                    staleness_threshold_hours=EXECUTION_STALENESS_HOURS,
                    source_table="comment_drafts",
                    sample_size=denominator,
                )
            )

        # Average karma per comment (30d window, from 48h snapshots)
        # Get posted drafts in last 30 days
        posted_30d_ids = (
            db.query(CommentDraft.id)
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= thirty_days_ago,
            )
            .subquery()
        )

        karma_48h_snapshots = (
            db.query(KarmaSnapshot.karma_value)
            .filter(
                KarmaSnapshot.comment_draft_id.in_(
                    db.query(posted_30d_ids.c.id)
                ),
                KarmaSnapshot.check_window == "48h",
            )
            .all()
        )

        if karma_48h_snapshots:
            karma_values = [s[0] for s in karma_48h_snapshots]
            avg_karma = sum(karma_values) / len(karma_values)
            metrics.append(
                _make_metric(
                    metric_id="execution.avg_karma_per_comment",
                    value=avg_karma,
                    measured_at=now,
                    time_window="30d",
                    validation="platform_confirmed",
                    staleness_threshold_hours=GEO_STALENESS_HOURS,
                    source_table="karma_snapshots",
                    sample_size=len(karma_values),
                )
            )

        return metrics

    # ------------------------------------------------------------------
    # Competitor Metrics
    # ------------------------------------------------------------------

    def _collect_competitor_metrics(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Collect competitor mention rates from GeoQueryResult.competitors_mentioned."""
        metrics: list[dict[str, Any]] = []

        # Find the latest completed batch
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )

        if not latest_batch:
            return metrics

        batch_time = latest_batch.completed_at or latest_batch.started_at

        # Get all successful results from this batch
        results = (
            db.query(GeoQueryResult)
            .filter(
                GeoQueryResult.execution_batch_id == latest_batch.id,
                GeoQueryResult.client_id == client_id,
                GeoQueryResult.status == "success",
            )
            .all()
        )

        if not results:
            return metrics

        total = len(results)

        # Count competitor mentions across all results
        competitor_counts: dict[str, int] = {}
        for r in results:
            if r.competitors_mentioned and isinstance(r.competitors_mentioned, list):
                for comp in r.competitors_mentioned:
                    name = comp.strip().lower() if isinstance(comp, str) else str(comp).strip().lower()
                    if name:
                        competitor_counts[name] = competitor_counts.get(name, 0) + 1

        # Create metric per competitor
        for comp_name, count in sorted(
            competitor_counts.items(), key=lambda x: x[1], reverse=True
        ):
            rate = count / total
            # Sanitize competitor name for metric_id (replace spaces with underscores)
            safe_name = comp_name.replace(" ", "_").replace(".", "")
            metrics.append(
                _make_metric(
                    metric_id=f"geo.competitor_rate.{safe_name}",
                    value=rate,
                    measured_at=batch_time,
                    time_window="batch",
                    validation="api_measured",
                    staleness_threshold_hours=GEO_STALENESS_HOURS,
                    source_table="geo_query_results",
                    sample_size=total,
                )
            )

        return metrics

    # ------------------------------------------------------------------
    # Category Metrics
    # ------------------------------------------------------------------

    def _collect_category_metrics(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Collect per-category brand mention rates via GeoPrompt.category JOIN."""
        metrics: list[dict[str, Any]] = []

        # Find the latest completed batch
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )

        if not latest_batch:
            return metrics

        batch_time = latest_batch.completed_at or latest_batch.started_at

        # Join GeoQueryResult with GeoPrompt to get category
        results_with_category = (
            db.query(
                GeoQueryResult.brand_mentioned,
                GeoPrompt.category,
            )
            .join(GeoPrompt, GeoQueryResult.prompt_id == GeoPrompt.id)
            .filter(
                GeoQueryResult.execution_batch_id == latest_batch.id,
                GeoQueryResult.client_id == client_id,
                GeoQueryResult.status == "success",
                GeoPrompt.category.isnot(None),
            )
            .all()
        )

        if not results_with_category:
            return metrics

        # Group by category
        category_groups: dict[str, dict[str, int]] = {}
        for brand_mentioned, category in results_with_category:
            cat = category.strip().lower()
            if cat not in category_groups:
                category_groups[cat] = {"total": 0, "brand": 0}
            category_groups[cat]["total"] += 1
            if brand_mentioned:
                category_groups[cat]["brand"] += 1

        for cat_name, counts in sorted(category_groups.items()):
            if counts["total"] > 0:
                rate = counts["brand"] / counts["total"]
                metrics.append(
                    _make_metric(
                        metric_id=f"geo.category_rate.{cat_name}",
                        value=rate,
                        measured_at=batch_time,
                        time_window="batch",
                        validation="api_measured",
                        staleness_threshold_hours=GEO_STALENESS_HOURS,
                        source_table="geo_query_results",
                        sample_size=counts["total"],
                    )
                )

        return metrics

    # ------------------------------------------------------------------
    # Gaps Identification
    # ------------------------------------------------------------------

    def _identify_gaps(
        self, db: Session, client_id: uuid.UUID
    ) -> list[str]:
        """Identify missing or stale data sources."""
        gaps: list[str] = []
        now = datetime.now(timezone.utc)

        # Check GEO data
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )

        if not latest_batch:
            gaps.append("No GEO batch data available (geo_execution_batches)")
        else:
            batch_time = latest_batch.completed_at or latest_batch.started_at
            if batch_time.tzinfo is None:
                batch_time = batch_time.replace(tzinfo=timezone.utc)
            hours_since = (now - batch_time).total_seconds() / 3600
            if hours_since > GEO_STALENESS_HOURS:
                gaps.append(
                    f"GEO data is stale ({hours_since:.0f}h old, threshold: {GEO_STALENESS_HOURS}h)"
                )

        # Check Reddit/karma data
        seven_days_ago = now - timedelta(days=7)
        posted_count = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        if posted_count == 0:
            gaps.append("No posted comments in last 7 days (comment_drafts)")
        else:
            # Check if karma snapshots exist for posted comments
            posted_ids = (
                db.query(CommentDraft.id)
                .filter(
                    CommentDraft.client_id == client_id,
                    CommentDraft.status == "posted",
                    CommentDraft.posted_at >= seven_days_ago,
                )
                .subquery()
            )
            snapshot_count = (
                db.query(func.count(KarmaSnapshot.id))
                .filter(
                    KarmaSnapshot.comment_draft_id.in_(
                        db.query(posted_ids.c.id)
                    )
                )
                .scalar()
            ) or 0

            if snapshot_count == 0:
                gaps.append("No karma snapshots for recent posted comments (karma_snapshots)")

        # Check execution activity
        drafts_7d = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == client_id,
                CommentDraft.created_at >= seven_days_ago,
            )
            .scalar()
        ) or 0

        if drafts_7d == 0:
            gaps.append("No drafts generated in last 7 days (comment_drafts)")

        # Check if GEO prompts exist (needed for category/competitor metrics)
        prompt_count = (
            db.query(func.count(GeoPrompt.id))
            .filter(
                GeoPrompt.client_id == client_id,
                GeoPrompt.is_active == True,  # noqa: E712
            )
            .scalar()
        ) or 0

        if prompt_count == 0:
            gaps.append("No active GEO prompts configured (geo_prompts)")

        return gaps

    # ------------------------------------------------------------------
    # Brand Excerpts
    # ------------------------------------------------------------------

    def _extract_brand_excerpts(
        self, db: Session, client_id: uuid.UUID
    ) -> list[dict[str, str]]:
        """Find actual AI response text where brand_mentioned=true.

        Returns up to 10 excerpts (max 300 chars each) from the most recent batch.
        """
        excerpts: list[dict[str, str]] = []

        # Find the latest completed batch
        latest_batch = (
            db.query(GeoExecutionBatch)
            .filter(
                GeoExecutionBatch.client_id == client_id,
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .order_by(GeoExecutionBatch.started_at.desc())
            .first()
        )

        if not latest_batch:
            return excerpts

        # Get results where brand is mentioned
        brand_results = (
            db.query(GeoQueryResult)
            .filter(
                GeoQueryResult.execution_batch_id == latest_batch.id,
                GeoQueryResult.client_id == client_id,
                GeoQueryResult.brand_mentioned == True,  # noqa: E712
                GeoQueryResult.status == "success",
                GeoQueryResult.response_text.isnot(None),
            )
            .order_by(GeoQueryResult.executed_at.desc())
            .limit(10)
            .all()
        )

        for result in brand_results:
            text = result.response_text or ""
            # Truncate to 300 chars
            excerpt = text[:300].strip()
            if len(text) > 300:
                excerpt += "..."

            excerpts.append(
                {
                    "provider": result.provider,
                    "excerpt": excerpt,
                    "executed_at": result.executed_at.isoformat() if result.executed_at else None,
                    "prompt_id": str(result.prompt_id),
                }
            )

        return excerpts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_source_availability(
        self, metrics: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build a source availability map from collected metrics."""
        sources: dict[str, Any] = {}

        # Group by source_table
        for metric in metrics:
            table = metric.get("source_table", "unknown")
            if table not in sources:
                sources[table] = {
                    "available": True,
                    "metric_count": 0,
                    "stale_count": 0,
                    "latest_measurement": None,
                }
            sources[table]["metric_count"] += 1
            if metric.get("is_stale"):
                sources[table]["stale_count"] += 1

            measured = metric.get("measured_at")
            if measured:
                current_latest = sources[table]["latest_measurement"]
                if current_latest is None or measured > current_latest:
                    sources[table]["latest_measurement"] = measured

        return sources

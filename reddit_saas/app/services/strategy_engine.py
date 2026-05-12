"""Strategy Engine — generates and manages avatar strategy documents.

Uses Claude Haiku 3.5 by default for cost efficiency (~$0.005/strategy).
Full JSON schema in prompt ensures structured, high-quality output.
Includes subreddit affinity, forecast, weekly cadence, and client questions.
"""

import logging
import time
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.config import get_config
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.strategy_document import StrategyDocument
from app.services.ai import call_llm_json, log_ai_usage
from app.services.transparency import record_activity_event

logger = logging.getLogger(__name__)

# Default to Haiku for strategy — good quality, 10x cheaper than Sonnet
STRATEGY_MODEL_SETTING = "llm_strategy_model"

STRATEGY_PROMPT = """You are a Reddit strategy expert. Generate a structured engagement strategy for the given avatar.

## Input data

**Avatar Profile:**
- Username: u/{username}
- Voice: {voice_profile}
- Constraints: {constraints}
- Hill I Die On: {hill_i_die_on}
- Helpful Mode Topics: {helpful_topics}
- Hobby subreddits: {hobby_subs}
- Business subreddits: {business_subs}
- Current warming phase: {phase} ({phase_label})
- Account age (days): {account_age_days}
- Current karma: {karma}

**Subreddit historical affinity (score where available, higher = better):**
{subreddit_affinity_json}

**Client brand context (if client exists):**
{client_context}

**Current performance (30 days):**
- Comments posted: {comments_30d}
- Average karma per comment: {avg_karma}
- Brand ratio: {brand_ratio}%

**Phase rules:**
- Phase 1: ONLY hobby subreddits, max 3/day, NO brand mentions. First 7 days: max 2/day.
- Phase 2: Hobby + professional, max 7/day, no explicit brand name/link.
- Phase 3: All subs, full budget, brand OK if ratio < 30%.

**Quality requirements:**
- Exclude any subreddit with historical affinity score < 0 from priorities.
- For Phase 1, set professional_percent = 0 for week 1.
- Include weekly_cadence with 4 weeks of progression.
- Include forecast based on current karma and cadence.
- If client exists: include 3-5 questions_for_client.
- If no client: include 3 suggestions for karma building.
- Goals must have numeric targets, not vague descriptions.
- Subreddit priorities must ONLY use subreddits from the affinity list above.

## Output format (JSON only, no extra text, no code fences):

{{"goals": [{{"metric": "string", "target": "number or specific value", "days": 30, "description": "string"}}], "subreddit_priorities": [{{"subreddit": "name_without_r_prefix", "frequency_per_week": 3, "type": "professional|hobby", "hill_usage_percent": 30, "priority": 1-10, "reason": "string"}}], "tone_calibration": {{"formality": "casual|moderate|formal", "humor": "none|subtle|frequent", "expertise": "beginner|intermediate|experienced", "avoid": ["string"]}}, "hook": {{"primary": "exact hill text", "target_usage_percent": 30, "angles": ["string"]}}, "weekly_cadence": [{{"week": 1, "comments_per_day": 2, "professional_percent": 0, "hobby_percent": 100}}, {{"week": 2, "comments_per_day": 3, "professional_percent": 30, "hobby_percent": 70}}, {{"week": 3, "comments_per_day": 4, "professional_percent": 50, "hobby_percent": 50}}, {{"week": 4, "comments_per_day": 5, "professional_percent": 60, "hobby_percent": 40}}], "forecast": {{"karma_day_7": 10, "karma_day_14": 25, "karma_day_30": 80, "phase_transition_expected_day": 24}}, "questions_for_client_or_user": ["string"], "summary": "2-3 sentence strategy summary"}}"""


class StrategyEngine:
    """Generates and manages avatar strategy documents."""

    def get_current_strategy(self, db: Session, avatar_id: uuid.UUID) -> StrategyDocument | None:
        """Get the current (latest active) strategy document for an avatar."""
        return (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id == avatar_id,
                StrategyDocument.is_current.is_(True),
            )
            .first()
        )

    def get_approved_strategy(self, db: Session, avatar_id: uuid.UUID) -> StrategyDocument | None:
        """Get the approved + current strategy for pipeline use.

        Returns None if no strategy is both approved and current.
        Pipeline should only use strategies that have been explicitly approved.
        """
        return (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id == avatar_id,
                StrategyDocument.is_current.is_(True),
                StrategyDocument.is_approved.is_(True),
            )
            .first()
        )

    def get_strategy_history(
        self, db: Session, avatar_id: uuid.UUID, limit: int = 10
    ) -> list[StrategyDocument]:
        """Get all strategy document versions for an avatar, newest first."""
        return (
            db.query(StrategyDocument)
            .filter(StrategyDocument.avatar_id == avatar_id)
            .order_by(StrategyDocument.version.desc())
            .limit(limit)
            .all()
        )

    def _get_subreddit_affinity(self, db: Session, avatar: Avatar) -> dict:
        """Get per-subreddit karma as {name: score} dict for prompt injection."""
        from app.services import karma_tracker
        rows = karma_tracker.get_breakdown(db, avatar)

        affinity = {}
        for row in rows:
            total = (row.comment_karma or 0) + (row.post_karma or 0)
            affinity[f"r/{row.subreddit_name}"] = round(total / max(row.comment_count or 1, 1), 1)

        # Add configured subs with no karma yet
        hobby_subs = avatar.hobby_subreddits or []
        business_subs = avatar.business_subreddits or []

        for sub in hobby_subs:
            name = sub if isinstance(sub, str) else (sub.get("subreddit") or sub.get("name") or "")
            name = name.strip().replace("r/", "")
            if name and f"r/{name}" not in affinity:
                affinity[f"r/{name}"] = 0.0

        for sub in business_subs:
            name = sub if isinstance(sub, str) else (sub.get("subreddit") or sub.get("name") or "")
            name = name.strip().replace("r/", "")
            if name and f"r/{name}" not in affinity:
                affinity[f"r/{name}"] = 0.0

        return affinity

    def _compute_forecast(self, db: Session, avatar: Avatar, comments_30d: int, avg_karma: float) -> dict:
        """Deterministic forecast — no LLM cost."""
        now = datetime.now(timezone.utc)
        if avatar.reddit_account_created:
            age_days = (now - avatar.reddit_account_created).days
        else:
            age_days = (now - avatar.created_at).days

        daily_rate = comments_30d / 30 if comments_30d > 0 else 2.0
        karma_per = avg_karma if avg_karma > 0 else 2.0

        phase = avatar.warming_phase
        if phase == 1:
            days_to_next = max(0, 60 - age_days)
        elif phase == 2:
            days_to_next = max(0, 150 - age_days)
        else:
            days_to_next = None

        return {
            "karma_day_7": round(daily_rate * karma_per * 7),
            "karma_day_14": round(daily_rate * karma_per * 14),
            "karma_day_30": round(daily_rate * karma_per * 30),
            "phase_transition_expected_day": days_to_next,
            "daily_comment_rate": round(daily_rate, 1),
            "avg_karma_per_comment": round(karma_per, 1),
            "account_age_days": age_days,
            "current_phase": phase,
        }

    def generate_strategy(
        self, db: Session, avatar: Avatar, client: Client | None = None
    ) -> StrategyDocument:
        """Generate strategy using structured prompt with full JSON schema.

        Uses Haiku/Flash by default (llm_scoring_model setting).
        Injects real subreddit affinity data.
        Validates output structure.
        """
        start_time = time.time()

        from sqlalchemy import func as sa_func
        from app.models.comment_draft import CommentDraft
        import json

        now = datetime.now(timezone.utc)
        month_ago = now - timedelta(days=30)

        # --- Gather data ---
        comments_30d = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= month_ago,
            )
            .scalar()
        ) or 0

        avg_karma = (
            db.query(sa_func.avg(CommentDraft.reddit_score))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status == "posted",
                CommentDraft.reddit_score.isnot(None),
                CommentDraft.created_at >= month_ago,
            )
            .scalar()
        )
        avg_karma = round(float(avg_karma), 1) if avg_karma else 0.0

        from app.services.phase import PhasePolicy
        brand_ratio = PhasePolicy().get_brand_ratio(db, avatar, window_days=30)

        # Account age
        if avatar.reddit_account_created:
            account_age_days = (now - avatar.reddit_account_created).days
        else:
            account_age_days = (now - avatar.created_at).days

        # Subreddit affinity
        affinity = self._get_subreddit_affinity(db, avatar)
        affinity_str = json.dumps(affinity, indent=2) if affinity else '"No historical data available"'

        # Subreddit lists
        hobby_subs = avatar.hobby_subreddits or []
        business_subs = avatar.business_subreddits or []
        hobby_str = json.dumps(hobby_subs[:10]) if hobby_subs else "[]"
        business_str = json.dumps(business_subs[:10]) if business_subs else "null"

        # Client context
        if client:
            client_context = (
                f"Brand: {client.brand_name}\n"
                f"Voice: {(client.brand_voice or client.company_worldview or '')[:300]}\n"
                f"Problem: {(client.company_problem or '')[:200]}\n"
                f"Competitors: {(client.competitive_landscape or '')[:200]}"
            )
        else:
            client_context = "No client assigned. Karma-building mode. Focus on hobby engagement only."

        # Phase label
        phase_labels = {1: "Credibility Building", 2: "Content Seeding", 3: "Brand Integration"}

        # --- Build prompt ---
        prompt = STRATEGY_PROMPT.format(
            username=avatar.reddit_username,
            voice_profile=(avatar.voice_profile_md or "")[:400],
            constraints=avatar.constraints or "(none)",
            hill_i_die_on=avatar.hill_i_die_on or "(not set)",
            helpful_topics=avatar.helpful_mode_topics or "(not set)",
            hobby_subs=hobby_str,
            business_subs=business_str,
            phase=avatar.warming_phase,
            phase_label=phase_labels.get(avatar.warming_phase, "Unknown"),
            account_age_days=account_age_days,
            karma=avatar.karma_comment or avatar.reddit_karma_comment or 0,
            subreddit_affinity_json=affinity_str,
            client_context=client_context,
            comments_30d=comments_30d,
            avg_karma=avg_karma,
            brand_ratio=round(brand_ratio * 100, 1),
        )

        messages = [{"role": "user", "content": prompt}]

        # --- Call LLM with retry ---
        max_retries = 2
        last_error = None
        result = None
        for attempt in range(max_retries + 1):
            try:
                result = call_llm_json(
                    messages=messages,
                    model=get_config(STRATEGY_MODEL_SETTING),
                    temperature=0.3,
                    max_tokens=2000,
                )
                break
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                if attempt < max_retries and any(
                    kw in error_str for kw in ("overloaded", "timeout", "rate_limit", "529", "503")
                ):
                    wait = 3 * (attempt + 1)
                    logger.warning("Strategy LLM attempt %d failed (transient), retry in %ds", attempt + 1, wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"Strategy generation failed: {e}") from e
        else:
            raise RuntimeError(f"Strategy generation failed after {max_retries + 1} attempts: {last_error}") from last_error

        duration_ms = int((time.time() - start_time) * 1000)

        # Log AI usage
        try:
            log_ai_usage(
                db, str(client.id) if client else None, "strategy_generation", result,
                avatar_id=str(avatar.id),
            )
        except Exception:
            logger.warning("Failed to log AI usage for strategy generation")

        data = result["data"]

        # --- Sanitize subreddit names in LLM output (strip r/ prefix) ---
        if "subreddit_priorities" in data and isinstance(data["subreddit_priorities"], list):
            for item in data["subreddit_priorities"]:
                if isinstance(item, dict) and "subreddit" in item:
                    name = item["subreddit"]
                    # Strip any r/ prefix(es)
                    while isinstance(name, str) and name.lower().startswith("r/"):
                        name = name[2:]
                    item["subreddit"] = name.strip()

        # --- Validate & enforce Phase 1 safety ---
        if avatar.warming_phase == 1:
            cadence = data.get("weekly_cadence", [])
            if cadence and isinstance(cadence, list) and len(cadence) > 0:
                if isinstance(cadence[0], dict):
                    cadence[0]["professional_percent"] = 0
                    cadence[0]["hobby_percent"] = 100
                    cadence[0]["comments_per_day"] = min(cadence[0].get("comments_per_day", 2), 3)

        # --- Compute deterministic forecast ---
        forecast = self._compute_forecast(db, avatar, comments_30d, avg_karma)
        # Merge LLM forecast hints if provided
        llm_forecast = data.get("forecast", {})
        if isinstance(llm_forecast, dict):
            forecast.update({k: v for k, v in llm_forecast.items() if v is not None})

        # --- Render markdown from structured data ---
        document_md = self._render_strategy_md(data, avatar, client, forecast)

        # --- Save ---
        prev = self.get_current_strategy(db, avatar.id)
        next_version = 1
        if prev:
            prev.is_current = False
            next_version = prev.version + 1
            db.flush()

        strategy_doc = StrategyDocument(
            avatar_id=avatar.id,
            goals=data.get("goals", []),
            subreddit_priorities=data.get("subreddit_priorities", []),
            tone_guidelines=data.get("tone_calibration", data.get("tone", {})),
            cadence_rules=data.get("weekly_cadence", data.get("cadence", {})),
            hook_inventory=data.get("hook", data.get("hook_plan", {})),
            forecast=forecast,
            document_md=document_md,
            version=next_version,
            is_current=True,
            model_used=get_config(STRATEGY_MODEL_SETTING),
            input_tokens=result.get("input_tokens"),
            output_tokens=result.get("output_tokens"),
            cost_usd=result.get("cost"),
            generation_duration_ms=duration_ms,
        )

        db.add(strategy_doc)
        db.commit()
        db.refresh(strategy_doc)

        # Activity event
        client_uuid = None
        if client:
            client_uuid = uuid.UUID(str(client.id)) if isinstance(client.id, str) else client.id
        record_activity_event(
            db,
            "strategy_generated",
            f"Strategy v{next_version} for u/{avatar.reddit_username} ({duration_ms}ms, ${result.get('cost') or 0:.4f})",
            client_id=client_uuid,
            metadata={
                "avatar_id": str(avatar.id),
                "version": next_version,
                "cost_usd": result.get("cost"),
                "duration_ms": duration_ms,
                "model": get_config(STRATEGY_MODEL_SETTING),
                "input_tokens": result.get("input_tokens"),
                "output_tokens": result.get("output_tokens"),
            },
        )

        logger.info(
            "Strategy v%d for %s: %dms, $%.4f, %d/%d tokens",
            next_version, avatar.reddit_username, duration_ms,
            result.get("cost") or 0,
            result.get("input_tokens") or 0,
            result.get("output_tokens") or 0,
        )

        return strategy_doc

    def _render_strategy_md(self, data: dict, avatar: Avatar, client: Client | None, forecast: dict) -> str:
        """Render structured JSON into readable markdown for display."""
        lines = []
        lines.append(f"# Strategy: u/{avatar.reddit_username}")
        lines.append(f"Phase {avatar.warming_phase} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        lines.append("")

        # Summary
        if data.get("summary"):
            lines.append(data["summary"])
            lines.append("")

        # Goals
        goals = data.get("goals", [])
        if goals:
            lines.append("## Goals (30 days)")
            for g in goals:
                if isinstance(g, dict):
                    lines.append(f"- **{g.get('metric', '?')}**: {g.get('target', '?')} — {g.get('description', '')}")
                else:
                    lines.append(f"- {g}")
            lines.append("")

        # Subreddit priorities
        subs = data.get("subreddit_priorities", [])
        if subs:
            lines.append("## Subreddit Priorities")
            lines.append("| Subreddit | Freq | Type | Hill% | Priority | Reason |")
            lines.append("|-----------|------|------|-------|----------|--------|")
            for s in subs:
                if isinstance(s, dict):
                    name = (s.get("subreddit") or s.get("sub") or "?").removeprefix("r/")
                    lines.append(
                        f"| r/{name} | {s.get('frequency_per_week', s.get('freq', '?'))}/wk "
                        f"| {s.get('type', '?')} | {s.get('hill_usage_percent', 30)}% "
                        f"| {s.get('priority', '?')} | {s.get('reason', s.get('why', ''))} |"
                    )
            lines.append("")

        # Tone
        tone = data.get("tone_calibration", data.get("tone", {}))
        if tone and isinstance(tone, dict):
            lines.append(f"## Tone: {tone.get('formality', '?')} / humor: {tone.get('humor', '?')} / expertise: {tone.get('expertise', '?')}")
            if tone.get("avoid"):
                lines.append(f"Avoid: {', '.join(tone['avoid'])}")
            lines.append("")

        # Hook
        hook = data.get("hook", data.get("hook_plan", {}))
        if hook and isinstance(hook, dict):
            lines.append(f"## Hook: \"{hook.get('primary', avatar.hill_i_die_on or '?')}\"")
            lines.append(f"Target: {hook.get('target_usage_percent', 30)}% of comments")
            if hook.get("angles"):
                lines.append(f"Angles: {', '.join(hook['angles'])}")
            lines.append("")

        # Weekly cadence
        cadence = data.get("weekly_cadence", [])
        if cadence and isinstance(cadence, list):
            lines.append("## Weekly Cadence")
            lines.append("| Week | Comments/day | Professional | Hobby |")
            lines.append("|------|-------------|-------------|-------|")
            for w in cadence:
                if isinstance(w, dict):
                    lines.append(f"| {w.get('week', '?')} | {w.get('comments_per_day', '?')} | {w.get('professional_percent', 0)}% | {w.get('hobby_percent', 100)}% |")
            lines.append("")

        # Forecast
        lines.append("## Forecast")
        lines.append(f"- Karma: +{forecast.get('karma_day_7', '?')} (7d) / +{forecast.get('karma_day_14', '?')} (14d) / +{forecast.get('karma_day_30', '?')} (30d)")
        lines.append(f"- Rate: {forecast.get('daily_comment_rate', '?')} comments/day, avg {forecast.get('avg_karma_per_comment', '?')} karma/comment")
        if forecast.get("phase_transition_expected_day") is not None:
            lines.append(f"- Phase transition in ~{forecast['phase_transition_expected_day']} days")
        lines.append("")

        # Questions
        questions = data.get("questions_for_client_or_user", [])
        if questions:
            label = "Questions for Client" if client else "Suggestions"
            lines.append(f"## {label}")
            for q in questions:
                lines.append(f"- {q}")
            lines.append("")

        return "\n".join(lines)

    def generate_fallback_strategy(
        self, db: Session, avatar: Avatar, client: Client | None = None
    ) -> StrategyDocument:
        """Generate a rule-based strategy without LLM. Used as fallback when API fails.

        Creates a deterministic strategy based on:
        - Avatar's configured subreddits (hobby/business)
        - Phase rules (daily limits, sub restrictions)
        - Subreddit affinity data (exclude negative karma subs)
        - Default cadence progression

        No LLM cost. Instant. Always succeeds.
        """
        from sqlalchemy import func as sa_func
        from app.models.comment_draft import CommentDraft
        import json

        now = datetime.now(timezone.utc)
        month_ago = now - timedelta(days=30)

        # Gather basic stats
        comments_30d = (
            db.query(sa_func.count(CommentDraft.id))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status.in_(["approved", "posted"]),
                CommentDraft.created_at >= month_ago,
            )
            .scalar()
        ) or 0

        avg_karma = (
            db.query(sa_func.avg(CommentDraft.reddit_score))
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.status == "posted",
                CommentDraft.reddit_score.isnot(None),
                CommentDraft.created_at >= month_ago,
            )
            .scalar()
        )
        avg_karma = round(float(avg_karma), 1) if avg_karma else 2.0

        # Subreddit affinity — exclude negative
        affinity = self._get_subreddit_affinity(db, avatar)
        good_subs = [a for a in affinity if not a.get("banned", False)]

        # Phase-based budget
        phase = avatar.warming_phase
        if phase == 1:
            budget = 3
            pro_ratio = 0.0
        elif phase == 2:
            budget = 7
            pro_ratio = 0.4
        else:
            budget = 10
            pro_ratio = 0.6

        # Build subreddit priorities from affinity
        sub_priorities = []
        for i, sub in enumerate(good_subs[:8]):
            sub_type = sub.get("type", "hobby")
            # Phase 1: only hobby
            if phase == 1 and sub_type == "professional":
                continue
            freq = 4 if i < 2 else (3 if i < 4 else 2)
            sub_priorities.append({
                "subreddit": sub["subreddit"],
                "frequency_per_week": freq,
                "type": sub_type,
                "hill_usage_percent": 30 if sub_type == "professional" else 15,
                "priority": 10 - i,
                "reason": f"karma={sub['karma']}, {sub['comments']} comments" if sub["karma"] > 0 else "configured, no history yet",
            })

        # Goals
        goals = [
            {"metric": "comment_karma", "target": str(max(50, comments_30d * 2)), "days": 30, "description": "Grow karma through consistent engagement"},
            {"metric": "comments_per_week", "target": str(budget * 5), "days": 30, "description": "Maintain posting cadence"},
            {"metric": "subreddit_diversity", "target": str(min(len(good_subs), 5)), "days": 30, "description": "Engage across multiple communities"},
        ]
        if phase < 3:
            goals.append({"metric": "phase_progression", "target": f"Phase {phase + 1}", "days": 30, "description": "Meet promotion criteria"})

        # Tone (defaults)
        tone = {
            "formality": "casual",
            "humor": "subtle",
            "expertise": "experienced" if avatar.karma_comment > 100 else "peer",
            "avoid": ["guru-speak", "sales pitch", "absolute statements"],
        }

        # Hook
        hook = {
            "primary": avatar.hill_i_die_on or "(not set)",
            "target_usage_percent": 30,
            "angles": ["consistency over perfection", "practical experience", "data-backed"],
        }

        # Weekly cadence
        if phase == 1:
            cadence = [
                {"week": 1, "comments_per_day": 2, "professional_percent": 0, "hobby_percent": 100},
                {"week": 2, "comments_per_day": 3, "professional_percent": 0, "hobby_percent": 100},
                {"week": 3, "comments_per_day": 3, "professional_percent": 0, "hobby_percent": 100},
                {"week": 4, "comments_per_day": 3, "professional_percent": 0, "hobby_percent": 100},
            ]
        elif phase == 2:
            cadence = [
                {"week": 1, "comments_per_day": 4, "professional_percent": 30, "hobby_percent": 70},
                {"week": 2, "comments_per_day": 5, "professional_percent": 40, "hobby_percent": 60},
                {"week": 3, "comments_per_day": 6, "professional_percent": 50, "hobby_percent": 50},
                {"week": 4, "comments_per_day": 7, "professional_percent": 50, "hobby_percent": 50},
            ]
        else:
            cadence = [
                {"week": 1, "comments_per_day": 6, "professional_percent": 60, "hobby_percent": 40},
                {"week": 2, "comments_per_day": 7, "professional_percent": 60, "hobby_percent": 40},
                {"week": 3, "comments_per_day": 8, "professional_percent": 65, "hobby_percent": 35},
                {"week": 4, "comments_per_day": 8, "professional_percent": 70, "hobby_percent": 30},
            ]

        # Forecast (deterministic)
        forecast = self._compute_forecast(db, avatar, comments_30d, avg_karma)

        # Questions/suggestions
        if client:
            questions = [
                "What specific topics should this avatar emphasize?",
                "Are there competitor products to never mention?",
                "Any case studies or data points to reference indirectly?",
            ]
        else:
            questions = [
                "Focus on building karma in hobby communities first",
                "Engage with specific details from posts, not generic replies",
                "Vary comment length and style to appear natural",
            ]

        # Render markdown
        data = {
            "goals": goals,
            "subreddit_priorities": sub_priorities,
            "tone_calibration": tone,
            "hook": hook,
            "weekly_cadence": cadence,
            "forecast": forecast,
            "questions_for_client_or_user": questions,
            "summary": f"Rule-based strategy for Phase {phase} avatar. Focus on {'hobby karma building' if phase == 1 else 'balanced engagement'}. Budget: {budget}/day.",
        }
        document_md = self._render_strategy_md(data, avatar, client, forecast)

        # Save
        prev = self.get_current_strategy(db, avatar.id)
        next_version = 1
        if prev:
            prev.is_current = False
            next_version = prev.version + 1
            db.flush()

        strategy_doc = StrategyDocument(
            avatar_id=avatar.id,
            goals=goals,
            subreddit_priorities=sub_priorities,
            tone_guidelines=tone,
            cadence_rules=cadence,
            hook_inventory=hook,
            forecast=forecast,
            document_md=document_md,
            version=next_version,
            is_current=True,
            model_used="fallback (rule-based)",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            generation_duration_ms=0,
        )

        db.add(strategy_doc)
        db.commit()
        db.refresh(strategy_doc)

        # Activity event
        client_uuid = None
        if client:
            client_uuid = uuid.UUID(str(client.id)) if isinstance(client.id, str) else client.id
        record_activity_event(
            db,
            "strategy_generated",
            f"Strategy v{next_version} (fallback) for u/{avatar.reddit_username}",
            client_id=client_uuid,
            metadata={
                "avatar_id": str(avatar.id),
                "version": next_version,
                "mode": "fallback",
                "cost_usd": 0.0,
            },
        )

        logger.info("Fallback strategy v%d for %s", next_version, avatar.reddit_username)
        return strategy_doc

"""Cost Governor — budget enforcement for agent operations.

Hard cap: $1/day (configurable via system setting).
Target: $0.30-0.50/day normal operations.
Budget split: 40% review, 40% monitoring, 20% reserve.

When exhausted: LLM calls blocked, system falls back to SQL + templates.
Never blocks operators from completing their review.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog

logger = logging.getLogger(__name__)

# Agent operations are tagged with this prefix in AIUsageLog.operation
AGENT_OP_PREFIX = "agent_"


@dataclass
class CostBudget:
    """Daily budget state for agent operations."""

    daily_limit_usd: Decimal
    spent_today_usd: Decimal
    session_spent_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return max(Decimal("0"), self.daily_limit_usd - self.spent_today_usd)

    @property
    def is_warning(self) -> bool:
        """Budget >= 80% consumed."""
        return self.spent_today_usd >= self.daily_limit_usd * Decimal("0.80")

    @property
    def is_exhausted(self) -> bool:
        """Budget >= 100% consumed. LLM calls blocked."""
        return self.spent_today_usd >= self.daily_limit_usd

    @property
    def utilization_pct(self) -> float:
        """Current budget utilization as percentage."""
        if self.daily_limit_usd == 0:
            return 100.0
        return float(self.spent_today_usd / self.daily_limit_usd * 100)

    def can_spend(self, estimated_cost: float) -> bool:
        """Check if an estimated cost fits within remaining budget."""
        return self.remaining_usd >= Decimal(str(estimated_cost))

    def record_spend(
        self,
        db: Session,
        cost: Decimal,
        operation: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        session_id: uuid.UUID | None = None,
    ) -> None:
        """Record an agent LLM call in AIUsageLog and update accumulators."""
        log_entry = AIUsageLog(
            operation=f"{AGENT_OP_PREFIX}{operation}",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            triggered_by="agent",
            # client_id/avatar_id/thread_id left null — agent-level op
        )
        db.add(log_entry)

        self.spent_today_usd += cost
        self.session_spent_usd += cost

        logger.info(
            f"Agent spend: ${cost:.4f} ({operation}/{model}). "
            f"Today: ${self.spent_today_usd:.4f}/{self.daily_limit_usd}. "
            f"Remaining: ${self.remaining_usd:.4f}"
        )

    def to_dict(self) -> dict:
        """Serialize for template rendering."""
        return {
            "daily_limit_usd": float(self.daily_limit_usd),
            "spent_today_usd": float(self.spent_today_usd),
            "session_spent_usd": float(self.session_spent_usd),
            "remaining_usd": float(self.remaining_usd),
            "is_warning": self.is_warning,
            "is_exhausted": self.is_exhausted,
            "utilization_pct": round(self.utilization_pct, 1),
        }


def get_today_budget(db: Session, session_id: uuid.UUID | None = None) -> CostBudget:
    """Load daily budget from settings + sum today's agent_ops spend.

    Args:
        db: Database session
        session_id: If provided, also computes session-level spend
    """
    from app.services.settings import get_setting

    # Get configured limit
    limit_str = get_setting(db, "agent_daily_budget_usd") or "1.00"
    try:
        daily_limit = Decimal(limit_str)
    except Exception:
        daily_limit = Decimal("1.00")

    # Today's boundary (Asia/Jerusalem midnight, but use UTC for simplicity)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Sum today's agent spend
    spent_today = (
        db.query(sa_func.sum(AIUsageLog.cost_usd))
        .filter(
            AIUsageLog.created_at >= today_start,
            AIUsageLog.operation.startswith(AGENT_OP_PREFIX),
        )
        .scalar()
    ) or Decimal("0")

    # Session spend (if tracking a specific session)
    session_spent = Decimal("0")
    # Note: session-level tracking is handled by the session's cost_used_usd field

    return CostBudget(
        daily_limit_usd=daily_limit,
        spent_today_usd=Decimal(str(spent_today)),
        session_spent_usd=session_spent,
    )


def get_weekly_cost_summary(db: Session) -> dict:
    """Weekly agent cost summary for reporting."""
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Daily totals for the week
    daily_totals = []
    for i in range(7):
        day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        total = (
            db.query(sa_func.sum(AIUsageLog.cost_usd))
            .filter(
                AIUsageLog.created_at >= day_start,
                AIUsageLog.created_at < day_end,
                AIUsageLog.operation.startswith(AGENT_OP_PREFIX),
            )
            .scalar()
        ) or Decimal("0")
        daily_totals.append(float(total))

    # Model distribution
    model_rows = (
        db.query(
            AIUsageLog.model,
            sa_func.count(AIUsageLog.id).label("calls"),
            sa_func.sum(AIUsageLog.cost_usd).label("cost"),
        )
        .filter(
            AIUsageLog.created_at >= week_ago,
            AIUsageLog.operation.startswith(AGENT_OP_PREFIX),
        )
        .group_by(AIUsageLog.model)
        .all()
    )

    total_calls = sum(r.calls for r in model_rows)
    model_distribution = {
        r.model: {
            "calls": r.calls,
            "cost": float(r.cost or 0),
            "pct": round(r.calls / total_calls * 100, 1) if total_calls > 0 else 0,
        }
        for r in model_rows
    }

    avg_daily = sum(daily_totals) / 7 if daily_totals else 0
    peak_day = max(daily_totals) if daily_totals else 0

    from app.services.settings import get_setting
    limit = float(get_setting(db, "agent_daily_budget_usd") or "1.00")
    utilization = (avg_daily / limit * 100) if limit > 0 else 0

    return {
        "avg_daily_usd": round(avg_daily, 4),
        "peak_day_usd": round(peak_day, 4),
        "budget_utilization_pct": round(utilization, 1),
        "total_week_usd": round(sum(daily_totals), 4),
        "daily_totals": daily_totals,
        "model_distribution": model_distribution,
    }

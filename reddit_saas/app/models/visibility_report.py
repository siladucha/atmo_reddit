"""Visibility Report model — structured assessment of Reddit's potential value for a client.

The final output of a Discovery Session. Contains a comprehensive analysis packaged as
a deliverable document covering demand assessment, community mapping, entry points,
competitive landscape, and visibility outcomes.

Content is stored as JSONB with a defined structure:
- executive_summary: high-level overview
- demand_assessment: market demand analysis
- communities: list of relevant subreddits with metrics
- discussion_activity: volume and engagement patterns
- entry_points: recommended engagement opportunities
- competitive_landscape: competitor presence analysis
- visibility_outcomes: predicted outcomes with probability
- risks_and_limitations: caveats and constraints
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VisibilityReport(Base):
    __tablename__ = "visibility_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Report content — structured JSONB
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # content structure:
    # {
    #   "executive_summary": "...",
    #   "demand_assessment": "...",
    #   "communities": [{"name": "r/...", "subscribers": N, "daily_posts": N, "relevance": N, "approach": "..."}],
    #   "discussion_activity": "...",
    #   "entry_points": [...],
    #   "competitive_landscape": "...",
    #   "visibility_outcomes": [{"type": "clients", "probability": "high", "reasoning": "..."}],
    #   "risks_and_limitations": "..."
    # }

    # Timestamps
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Operator annotations (max 5000 chars)
    operator_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Versioning and cost tracking
    report_version: Mapped[int] = mapped_column(Integer, default=1)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    # Relationships
    session = relationship("DiscoverySession", back_populates="reports")

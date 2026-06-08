"""Discovery Hypothesis model — testable hypothesis within a discovery session.

Each hypothesis represents a specific, testable statement about a client's Reddit
ecosystem potential. Hypotheses are formed by AI from extracted entities, then
validated against Reddit signals (subreddit activity, engagement metrics).

Category values:
- clients: potential client acquisition opportunities
- partners: partnership/collaboration signals
- feedback: product feedback and sentiment
- recognition: brand recognition and mentions
- hiring: talent acquisition signals
- market_research: market intelligence opportunities

Status workflow:
- proposed: initial AI-generated hypothesis (default)
- confirmed: operator validated, Reddit signals support it
- rejected: operator rejected (rejection_reason recorded)
- abandoned: session abandoned before decision
- research_failed: Reddit API failed to return signals

Classification:
- fact: objectively verifiable via Reddit data
- choice: subjective operator decision about strategy
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DiscoveryHypothesis(Base):
    __tablename__ = "discovery_hypotheses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Iteration context
    iteration_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Hypothesis content
    statement: Mapped[str] = mapped_column(Text, nullable=False)  # max 1000 chars
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # clients | partners | feedback | recognition | hiring | market_research

    # Confidence scoring (rule-based)
    confidence_score: Mapped[int] = mapped_column(Integer, default=50)
    confidence_delta: Mapped[int] = mapped_column(Integer, default=0)  # change from initial 50

    # Status and classification
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | confirmed | rejected | abandoned | research_failed
    classification: Mapped[str | None] = mapped_column(String(10), nullable=True)  # fact | choice

    # Provenance — how this hypothesis was formed
    provenance: Mapped[dict] = mapped_column(JSONB, default=dict)
    # provenance structure:
    # {
    #   "triggering_entities": [{"id": "...", "name": "...", "category": "..."}],
    #   "reasoning": "...",
    #   "llm_prompt_hash": "...",
    #   "search_terms": ["term1", "term2"],
    #   "confidence_reasoning": "..."
    # }

    # Reddit research signals
    reddit_signals: Mapped[dict] = mapped_column(JSONB, default=dict)
    # reddit_signals structure:
    # {
    #   "subreddits": [
    #     {"name": "r/...", "subscribers": 50000, "posts_30d": 120, "avg_engagement": 15, "relevance_score": 78}
    #   ],
    #   "total_posts_found": 45,
    #   "avg_engagement_overall": 12,
    #   "no_signal": null | {"cause": "search_too_narrow"|"topic_absent", "explanation": "...", "suggestions": [...]}
    # }

    # Rejection
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    session = relationship("DiscoverySession", back_populates="hypotheses")

    __table_args__ = (
        UniqueConstraint("session_id", "iteration_number", "statement", name="uq_hypothesis_session_iter_stmt"),
        Index("ix_hypothesis_session_status", "session_id", "status"),
        Index("ix_hypothesis_session_iteration", "session_id", "iteration_number"),
    )

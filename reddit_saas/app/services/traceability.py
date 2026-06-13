"""Traceability Service — reconstructs the full reasoning chain for any entity.

Given a CommentDraft ID, traces backward and forward through the entire cycle:
Discovery Hypothesis → Client → Avatar → Strategy → EPG Slot → CommentDraft → 
PostingEvent → KarmaSnapshot(s) → Feedback adjustments

This satisfies the observability requirement: "A human operator must be able to 
reconstruct the full reasoning chain at any time."

All data is read-only — this service never modifies anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class TraceNode:
    """A single node in the reasoning chain."""
    layer: str  # "discovery" | "strategy" | "epg" | "execution" | "outcome" | "feedback"
    entity_type: str  # "hypothesis" | "strategy_doc" | "epg_slot" | "draft" | "posting_event" | "karma_snapshot"
    entity_id: str
    timestamp: datetime | None = None
    summary: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class FullTrace:
    """Complete reasoning chain from Discovery to Outcomes."""
    comment_draft_id: str
    generated_at: datetime | None = None
    nodes: list[TraceNode] = field(default_factory=list)
    
    # Summary fields
    discovery_session_id: str | None = None
    hypothesis_statement: str | None = None
    strategy_version: int | None = None
    epg_slot_id: str | None = None
    posting_event_id: str | None = None
    karma_snapshots_count: int = 0
    latest_karma: int | None = None
    is_deleted: bool = False
    feedback_applied: bool = False


def trace_comment(db: Session, draft_id: UUID) -> FullTrace:
    """Trace the full lifecycle of a comment draft.
    
    Reconstructs: Discovery → Strategy → EPG → Draft → Posting → Outcomes → Feedback
    """
    from app.models.comment_draft import CommentDraft
    from app.models.epg_slot import EPGSlot
    from app.models.posting_event import PostingEvent
    from app.models.karma_snapshot import KarmaSnapshot
    from app.models.strategy_document import StrategyDocument
    from app.models.avatar import Avatar
    from app.models.discovery_session import DiscoverySession
    from app.models.discovery_hypothesis import DiscoveryHypothesis
    from app.models.activity_event import ActivityEvent

    trace = FullTrace(comment_draft_id=str(draft_id))
    trace.generated_at = datetime.utcnow()

    # --- Load the draft ---
    draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
    if not draft:
        return trace

    trace.nodes.append(TraceNode(
        layer="execution",
        entity_type="comment_draft",
        entity_id=str(draft.id),
        timestamp=draft.created_at,
        summary=f"Draft created: {draft.type} / approach={draft.comment_approach}",
        data={
            "status": draft.status,
            "type": draft.type,
            "approach": draft.comment_approach,
            "strategic_angle": draft.strategic_angle,
            "subreddit": draft.thread.subreddit if draft.thread else None,
            "thread_title": draft.thread.post_title if draft.thread else None,
            "reddit_score": draft.reddit_score,
            "is_deleted": draft.is_deleted,
            "learning_metadata": draft.learning_metadata,
        },
    ))

    # --- EPG Slot (if exists) ---
    epg_slot = (
        db.query(EPGSlot)
        .filter(EPGSlot.draft_id == draft_id)
        .first()
    )
    if epg_slot:
        trace.epg_slot_id = str(epg_slot.id)
        trace.nodes.append(TraceNode(
            layer="epg",
            entity_type="epg_slot",
            entity_id=str(epg_slot.id),
            timestamp=epg_slot.created_at,
            summary=f"EPG slot: {epg_slot.slot_type} in r/{epg_slot.subreddit} (status={epg_slot.status})",
            data={
                "slot_type": epg_slot.slot_type,
                "plan_date": str(epg_slot.plan_date),
                "scheduled_at": epg_slot.scheduled_at.isoformat() if epg_slot.scheduled_at else None,
                "status": epg_slot.status,
                "subreddit": epg_slot.subreddit,
                "thread_title": epg_slot.thread_title,
                "selection_reasoning": epg_slot.selection_reasoning,
            },
        ))

    # --- Strategy (current for this avatar) ---
    avatar = draft.avatar
    if avatar:
        strategy = (
            db.query(StrategyDocument)
            .filter(
                StrategyDocument.avatar_id == avatar.id,
                StrategyDocument.is_current == True,
            )
            .first()
        )
        if strategy:
            trace.strategy_version = strategy.version
            trace.nodes.append(TraceNode(
                layer="strategy",
                entity_type="strategy_document",
                entity_id=str(strategy.id),
                timestamp=strategy.generated_at,
                summary=f"Strategy v{strategy.version} ({strategy.model_used})",
                data={
                    "version": strategy.version,
                    "is_approved": strategy.is_approved,
                    "model_used": strategy.model_used,
                    "goals": strategy.goals,
                    "subreddit_priorities": strategy.subreddit_priorities[:5] if strategy.subreddit_priorities else [],
                },
            ))

    # --- Discovery (if client linked) ---
    client_id = draft.client_id
    if client_id:
        # Find discovery session for this client
        disc_session = (
            db.query(DiscoverySession)
            .filter(DiscoverySession.client_id == client_id)
            .order_by(DiscoverySession.created_at.desc())
            .first()
        )
        if disc_session:
            trace.discovery_session_id = str(disc_session.id)

            # Find confirmed hypotheses that mention this draft's subreddit
            subreddit = draft.thread.subreddit if draft.thread else None
            confirmed_hyps = [
                h for h in disc_session.hypotheses
                if h.status == "confirmed"
            ]

            # Find the most relevant hypothesis
            relevant_hyp = None
            if subreddit and confirmed_hyps:
                for hyp in confirmed_hyps:
                    signals = hyp.reddit_signals or {}
                    signal_subs = [
                        s.get("name", "").replace("r/", "").lower()
                        for s in signals.get("subreddits", [])
                    ]
                    if subreddit.lower() in signal_subs:
                        relevant_hyp = hyp
                        break

            if not relevant_hyp and confirmed_hyps:
                relevant_hyp = confirmed_hyps[0]  # Fallback to first confirmed

            if relevant_hyp:
                trace.hypothesis_statement = relevant_hyp.statement
                trace.nodes.append(TraceNode(
                    layer="discovery",
                    entity_type="hypothesis",
                    entity_id=str(relevant_hyp.id),
                    timestamp=relevant_hyp.created_at,
                    summary=f"Hypothesis: {relevant_hyp.statement[:100]}... (confidence={relevant_hyp.confidence_score})",
                    data={
                        "statement": relevant_hyp.statement,
                        "confidence_score": relevant_hyp.confidence_score,
                        "category": relevant_hyp.category,
                        "reddit_signals": relevant_hyp.reddit_signals,
                        "provenance": relevant_hyp.provenance,
                    },
                ))

    # --- Posting Event ---
    posting_event = (
        db.query(PostingEvent)
        .filter(PostingEvent.draft_id == draft_id)
        .order_by(PostingEvent.posted_at.desc())
        .first()
    )
    if posting_event:
        trace.posting_event_id = str(posting_event.id)
        trace.nodes.append(TraceNode(
            layer="execution",
            entity_type="posting_event",
            entity_id=str(posting_event.id),
            timestamp=posting_event.posted_at,
            summary=f"Posted: outcome={posting_event.outcome} (duration={posting_event.duration_ms}ms)",
            data={
                "outcome": posting_event.outcome,
                "reddit_comment_id": posting_event.reddit_comment_id,
                "reddit_comment_url": posting_event.reddit_comment_url,
                "duration_ms": posting_event.duration_ms,
                "attempt_number": posting_event.attempt_number,
                "ip_used": posting_event.ip_used,
                "error_message": posting_event.error_message,
            },
        ))

    # --- Karma Snapshots ---
    snapshots = (
        db.query(KarmaSnapshot)
        .filter(KarmaSnapshot.comment_draft_id == draft_id)
        .order_by(KarmaSnapshot.checked_at.asc())
        .all()
    )
    trace.karma_snapshots_count = len(snapshots)
    if snapshots:
        trace.latest_karma = snapshots[-1].karma_value
        trace.is_deleted = snapshots[-1].is_deleted

        for snap in snapshots:
            trace.nodes.append(TraceNode(
                layer="outcome",
                entity_type="karma_snapshot",
                entity_id=str(snap.id),
                timestamp=snap.checked_at,
                summary=f"Snapshot [{snap.check_window}]: karma={snap.karma_value}, replies={snap.reply_count}, deleted={snap.is_deleted}",
                data={
                    "check_window": snap.check_window,
                    "karma_value": snap.karma_value,
                    "reply_count": snap.reply_count,
                    "is_deleted": snap.is_deleted,
                    "karma_delta": snap.karma_delta,
                    "subreddit": snap.subreddit,
                },
            ))

    # --- Feedback events (if any adjustments were triggered by this data) ---
    feedback_events = (
        db.query(ActivityEvent)
        .filter(
            ActivityEvent.event_type == "feedback_loop_executed",
            ActivityEvent.event_metadata["avatar_id"].astext == str(draft.avatar_id),
        )
        .order_by(ActivityEvent.created_at.desc())
        .limit(1)
        .all()
    )
    if feedback_events:
        trace.feedback_applied = True
        fe = feedback_events[0]
        trace.nodes.append(TraceNode(
            layer="feedback",
            entity_type="feedback_event",
            entity_id=str(fe.id),
            timestamp=fe.created_at,
            summary=f"Feedback loop: {fe.message}",
            data=fe.event_metadata or {},
        ))

    # Sort nodes by timestamp (reconstruct chronological order)
    trace.nodes.sort(key=lambda n: n.timestamp or datetime.min)

    return trace


def trace_comment_json(db: Session, draft_id: UUID) -> dict:
    """Return trace as serializable dict for API/UI consumption."""
    trace = trace_comment(db, draft_id)

    return {
        "comment_draft_id": trace.comment_draft_id,
        "generated_at": trace.generated_at.isoformat() if trace.generated_at else None,
        "summary": {
            "discovery_session_id": trace.discovery_session_id,
            "hypothesis": trace.hypothesis_statement,
            "strategy_version": trace.strategy_version,
            "epg_slot_id": trace.epg_slot_id,
            "posting_event_id": trace.posting_event_id,
            "karma_snapshots": trace.karma_snapshots_count,
            "latest_karma": trace.latest_karma,
            "is_deleted": trace.is_deleted,
            "feedback_applied": trace.feedback_applied,
        },
        "chain": [
            {
                "layer": node.layer,
                "entity_type": node.entity_type,
                "entity_id": node.entity_id,
                "timestamp": node.timestamp.isoformat() if node.timestamp else None,
                "summary": node.summary,
                "data": node.data,
            }
            for node in trace.nodes
        ],
    }

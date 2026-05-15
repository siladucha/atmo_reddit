"""Learning Service — captures human edits and feeds corrections into generation pipeline.

This module implements the Self-Learning Loop: deterministic diff computation,
edit record capture, few-shot example selection, correction pattern extraction,
and prompt injection formatting.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.comment_draft import CommentDraft
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.models.thread import RedditThread

logger = logging.getLogger(__name__)


def compute_edit_summary(ai_draft: str, edited_draft: str) -> str | None:
    """Compute a human-readable summary of changes between two texts.

    Uses a deterministic word-level diff algorithm (no LLM calls).
    Returns None if texts are identical.
    Returns semicolon-separated change descriptions, max 500 chars.

    Args:
        ai_draft: The original AI-generated text.
        edited_draft: The human-edited version of the text.

    Returns:
        A semicolon-separated string describing changes (max 500 chars),
        or None if the texts are identical.
    """
    if ai_draft == edited_draft:
        return None

    ai_words = ai_draft.split()
    edited_words = edited_draft.split()

    changes: list[str] = []

    # Word count change
    if len(ai_words) != len(edited_words):
        direction = "shortened" if len(edited_words) < len(ai_words) else "lengthened"
        changes.append(f"{direction} {len(ai_words)}\u2192{len(edited_words)} words")

    # Removed words (in ai but not in edited) — sorted for determinism
    removed = set(ai_words) - set(edited_words)
    if removed:
        sample = sorted(removed)[:3]
        changes.append(f"removed '{'; '.join(sample)}'")

    # Added words (in edited but not in ai) — sorted for determinism
    added = set(edited_words) - set(ai_words)
    if added:
        sample = sorted(added)[:3]
        changes.append(f"added '{'; '.join(sample)}'")

    # Structural changes (sentence count based on terminal punctuation)
    ai_sentences = ai_draft.count(".") + ai_draft.count("!") + ai_draft.count("?")
    edited_sentences = edited_draft.count(".") + edited_draft.count("!") + edited_draft.count("?")
    if ai_sentences != edited_sentences:
        changes.append(f"restructured {ai_sentences}\u2192{edited_sentences} sentences")

    summary = "; ".join(changes)

    # If texts differ but no specific changes detected (e.g., whitespace-only diff),
    # produce a fallback so we never return empty string for non-identical texts
    if not summary:
        summary = "content modified"

    return summary[:500]


class LearningService:
    """Core service for the self-learning loop.

    Captures human edits, computes correction patterns, selects few-shot examples,
    and formats learning context for prompt injection.

    All public methods are wrapped in try/except — learning is non-critical
    and must NEVER fail the review or generation workflow.
    """

    def capture_edit_record(
        self, db: Session, draft: CommentDraft, thread: RedditThread, status: str
    ) -> EditRecord | None:
        """Called on every review action. Computes diff, stores record, triggers
        pattern recomputation if needed.

        Args:
            db: SQLAlchemy session.
            draft: The CommentDraft being reviewed.
            thread: The RedditThread associated with the draft.
            status: One of "approved", "approved_unchanged", "rejected".

        Returns:
            The created EditRecord on success, or None on failure.
        """
        try:
            # Determine edited_draft and edit_summary based on status
            if status == "approved":
                # Approved with edits — edited_draft differs from ai_draft
                edited_draft = draft.edited_draft
                # Use original_ai_draft for diff if available (before AI Editor cleanup)
                before_text_for_diff = draft.original_ai_draft or draft.ai_draft
                edit_summary = compute_edit_summary(before_text_for_diff, edited_draft)
            elif status == "approved_unchanged":
                # Approved without changes — edited_draft equals ai_draft (or is None)
                edited_draft = draft.edited_draft if draft.edited_draft else draft.ai_draft
                edit_summary = None
            elif status == "rejected":
                # Rejected — no edited version
                edited_draft = None
                edit_summary = None
            else:
                logger.warning("capture_edit_record called with unknown status: %s", status)
                return None

            # Truncate post_body to 500 characters
            post_body = thread.post_body[:500] if thread.post_body else None

            # Use original_ai_draft (before AI Editor) if available, for better few-shot quality
            before_text = draft.original_ai_draft or draft.ai_draft

            record = EditRecord(
                comment_draft_id=draft.id,
                avatar_id=draft.avatar_id,
                client_id=draft.client_id,
                ai_draft=before_text,
                edited_draft=edited_draft,
                edit_summary=edit_summary,
                subreddit=thread.subreddit,
                engagement_mode=draft.engagement_mode,
                post_title=thread.post_title,
                post_body=post_body,
                final_status=status,
            )

            db.add(record)
            db.flush()

            # Check if we should trigger pattern recomputation
            # Count total non-archived records for this avatar-client pair
            non_archived_count = (
                db.query(func.count(EditRecord.id))
                .filter(
                    EditRecord.avatar_id == draft.avatar_id,
                    EditRecord.client_id == draft.client_id,
                    EditRecord.is_archived == False,  # noqa: E712
                )
                .scalar()
            )

            if non_archived_count and non_archived_count % 5 == 0:
                self.recompute_correction_patterns(
                    db, draft.avatar_id, draft.client_id
                )

            # Enforce retention limits after capture
            self.enforce_retention_limits(db, draft.avatar_id, draft.client_id)

            return record

        except Exception:
            logger.exception(
                "Failed to capture edit record for draft %s — learning skipped",
                draft.id,
            )
            return None

    def recompute_correction_patterns(
        self, db: Session, avatar_id: UUID, client_id: UUID
    ) -> None:
        """Recompute correction patterns from accumulated edit records.

        Analyzes edit_summaries for recurring themes across all non-archived
        approved records. Categorizes into 6 pattern types and upserts into
        the correction_patterns table.

        Only computes when 5+ qualifying edit records exist.
        A pattern must appear in 2+ summaries to be considered recurring.

        Args:
            db: SQLAlchemy session.
            avatar_id: The avatar's UUID.
            client_id: The client's UUID.
        """
        try:
            # Query all non-archived, approved records with edit_summary
            records = (
                db.query(EditRecord)
                .filter(
                    EditRecord.avatar_id == avatar_id,
                    EditRecord.client_id == client_id,
                    EditRecord.is_archived == False,  # noqa: E712
                    EditRecord.final_status == "approved",
                    EditRecord.edit_summary.isnot(None),
                )
                .all()
            )

            # Only compute when 5+ qualifying records exist
            if len(records) < 5:
                return

            # Parse edit summaries and detect pattern types
            pattern_counts: Counter = Counter()
            pattern_details: dict[str, list[str]] = {
                "length_adjustment": [],
                "tone_shift": [],
                "vocabulary_change": [],
                "structure_change": [],
                "content_removal": [],
                "content_addition": [],
            }

            for record in records:
                if not record.edit_summary:
                    continue

                # Split semicolon-separated summary into parts
                parts = [p.strip().lower() for p in record.edit_summary.split(";")]

                for part in parts:
                    if not part:
                        continue

                    # Categorize each part
                    if "shortened" in part or "lengthened" in part:
                        pattern_counts["length_adjustment"] += 1
                        pattern_details["length_adjustment"].append(part)

                    if any(
                        word in part
                        for word in [
                            "tone",
                            "casual",
                            "formal",
                            "friendly",
                            "professional",
                            "conversational",
                            "aggressive",
                            "softer",
                            "warmer",
                        ]
                    ):
                        pattern_counts["tone_shift"] += 1
                        pattern_details["tone_shift"].append(part)

                    if ("removed" in part or "added" in part) and (
                        "'" in part or '"' in part or "word" in part
                    ):
                        pattern_counts["vocabulary_change"] += 1
                        pattern_details["vocabulary_change"].append(part)

                    if "restructured" in part or "restructur" in part:
                        pattern_counts["structure_change"] += 1
                        pattern_details["structure_change"].append(part)

                    if "removed" in part and "'" not in part and '"' not in part:
                        pattern_counts["content_removal"] += 1
                        pattern_details["content_removal"].append(part)

                    if "added" in part and "'" not in part and '"' not in part:
                        pattern_counts["content_addition"] += 1
                        pattern_details["content_addition"].append(part)

            now = datetime.now(timezone.utc)

            # Only create patterns that appear in 2+ summaries (recurring)
            for pattern_type, count in pattern_counts.items():
                if count < 2:
                    continue

                # Generate a concise imperative rule based on the pattern type
                rule_text = self._generate_rule_text(
                    pattern_type, pattern_details[pattern_type]
                )

                # Ensure rule_text is ≤ 100 characters
                rule_text = rule_text[:100]

                # Upsert: update if exists, create if new
                existing = (
                    db.query(CorrectionPattern)
                    .filter(
                        CorrectionPattern.avatar_id == avatar_id,
                        CorrectionPattern.client_id == client_id,
                        CorrectionPattern.pattern_type == pattern_type,
                    )
                    .first()
                )

                if existing:
                    existing.frequency = count
                    existing.last_seen_at = now
                    existing.rule_text = rule_text
                else:
                    pattern = CorrectionPattern(
                        avatar_id=avatar_id,
                        client_id=client_id,
                        pattern_type=pattern_type,
                        rule_text=rule_text,
                        frequency=count,
                        last_seen_at=now,
                    )
                    db.add(pattern)

            db.flush()

        except Exception:
            logger.exception(
                "Failed to recompute correction patterns for avatar %s, client %s",
                avatar_id,
                client_id,
            )

    def _generate_rule_text(
        self, pattern_type: str, details: list[str]
    ) -> str:
        """Generate a concise imperative rule (max 100 chars) from pattern details.

        Args:
            pattern_type: One of the 6 pattern types.
            details: List of edit summary fragments matching this pattern.

        Returns:
            An imperative rule string, max 100 characters.
        """
        if pattern_type == "length_adjustment":
            # Determine if mostly shortened or lengthened
            shortened_count = sum(1 for d in details if "shortened" in d)
            lengthened_count = sum(1 for d in details if "lengthened" in d)

            if shortened_count >= lengthened_count:
                # Try to extract a typical target word count
                word_counts = []
                for d in details:
                    match = re.search(r"\u2192(\d+)\s*words", d)
                    if match:
                        word_counts.append(int(match.group(1)))
                if word_counts:
                    avg_target = sum(word_counts) // len(word_counts)
                    return f"Keep responses concise, aim for under {avg_target} words"
                return "Keep responses concise and shorter"
            else:
                return "Expand responses with more detail and context"

        elif pattern_type == "tone_shift":
            # Determine dominant tone direction
            casual_words = ["casual", "conversational", "friendly", "warmer", "softer"]
            formal_words = ["formal", "professional"]
            casual_count = sum(
                1 for d in details if any(w in d for w in casual_words)
            )
            formal_count = sum(
                1 for d in details if any(w in d for w in formal_words)
            )
            if casual_count >= formal_count:
                return "Use a casual, conversational tone"
            else:
                return "Maintain a professional, formal tone"

        elif pattern_type == "vocabulary_change":
            # Extract commonly removed/added words
            removed_words: list[str] = []
            added_words: list[str] = []
            for d in details:
                if "removed" in d:
                    # Extract quoted words
                    matches = re.findall(r"'([^']+)'", d)
                    removed_words.extend(matches)
                if "added" in d:
                    matches = re.findall(r"'([^']+)'", d)
                    added_words.extend(matches)

            if removed_words:
                top_removed = Counter(removed_words).most_common(2)
                words = ", ".join(w for w, _ in top_removed)
                return f"Avoid using: {words}"
            elif added_words:
                top_added = Counter(added_words).most_common(2)
                words = ", ".join(w for w, _ in top_added)
                return f"Prefer using: {words}"
            return "Adjust vocabulary to match reviewer preferences"

        elif pattern_type == "structure_change":
            return "Restructure responses for better flow and readability"

        elif pattern_type == "content_removal":
            return "Remove unnecessary filler and redundant content"

        elif pattern_type == "content_addition":
            return "Add more substantive content and supporting details"

        return "Follow reviewer correction patterns"

    def select_few_shot_examples(
        self,
        db: Session,
        avatar_id: UUID,
        client_id: UUID,
        subreddit: str,
        engagement_mode: str,
    ) -> list[EditRecord]:
        """Select up to 3 relevant examples (max 1 negative) from the 50 most recent
        non-archived records for the given avatar-client pair.

        Scoring priority:
        - Same subreddit: +2 points
        - Same engagement_mode: +1 point
        - Recency as tiebreaker (more recent = higher priority)

        Selection logic:
        - Up to 2 positives (status="approved") + up to 1 negative (status="rejected")
        - If no negatives exist, fills the 3rd slot from positives
        - Returns empty list if no records exist (zero degradation)

        Args:
            db: SQLAlchemy session.
            avatar_id: The avatar's UUID.
            client_id: The client's UUID.
            subreddit: The target subreddit for relevance scoring.
            engagement_mode: The target engagement mode for relevance scoring.

        Returns:
            List of up to 3 EditRecord objects selected by relevance.
        """
        try:
            # Query the 50 most recent non-archived records for this avatar-client
            candidates = (
                db.query(EditRecord)
                .filter(
                    EditRecord.avatar_id == avatar_id,
                    EditRecord.client_id == client_id,
                    EditRecord.is_archived == False,  # noqa: E712
                )
                .order_by(EditRecord.created_at.desc())
                .limit(50)
                .all()
            )

            if not candidates:
                return []

            # Post-load assertion: verify all candidates belong to the expected client_id
            verified_candidates = []
            for record in candidates:
                if record.client_id != client_id:
                    logger.error(
                        "SECURITY: Few-shot candidate EditRecord %s has client_id=%s, "
                        "expected client_id=%s — excluding from results",
                        record.id,
                        record.client_id,
                        client_id,
                    )
                else:
                    verified_candidates.append(record)
            candidates = verified_candidates

            if not candidates:
                return []

            # Score each candidate by relevance
            def relevance_score(record: EditRecord) -> tuple[int, int, datetime]:
                sub_match = 2 if record.subreddit == subreddit else 0
                mode_match = 1 if record.engagement_mode == engagement_mode else 0
                return (sub_match, mode_match, record.created_at)

            # Separate positive and negative examples
            positives = [r for r in candidates if r.final_status == "approved"]
            negatives = [r for r in candidates if r.final_status == "rejected"]

            # Sort by relevance (highest first)
            positives.sort(key=relevance_score, reverse=True)
            negatives.sort(key=relevance_score, reverse=True)

            # Select: up to 2 positives + up to 1 negative, total max 3
            results = positives[:2]
            if negatives:
                results.append(negatives[0])
            elif len(positives) > 2:
                results.append(positives[2])

            return results[:3]

        except Exception:
            logger.exception(
                "Failed to select few-shot examples for avatar %s, client %s",
                avatar_id,
                client_id,
            )
            return []

    def get_correction_patterns(
        self, db: Session, avatar_id: UUID, client_id: UUID
    ) -> list[CorrectionPattern]:
        """Returns top 3 patterns by frequency for the given avatar-client pair.

        Returns an empty list if fewer than 5 qualifying edit records exist.
        Used by the generation pipeline to inject correction rules into prompts.

        Args:
            db: SQLAlchemy session.
            avatar_id: The avatar's UUID.
            client_id: The client's UUID.

        Returns:
            List of up to 3 CorrectionPattern objects, sorted by frequency descending.
        """
        try:
            # Check if 5+ qualifying records exist
            qualifying_count = (
                db.query(func.count(EditRecord.id))
                .filter(
                    EditRecord.avatar_id == avatar_id,
                    EditRecord.client_id == client_id,
                    EditRecord.is_archived == False,  # noqa: E712
                    EditRecord.final_status == "approved",
                    EditRecord.edit_summary.isnot(None),
                )
                .scalar()
            )

            if not qualifying_count or qualifying_count < 5:
                return []

            # Return top 3 patterns by frequency
            patterns = (
                db.query(CorrectionPattern)
                .filter(
                    CorrectionPattern.avatar_id == avatar_id,
                    CorrectionPattern.client_id == client_id,
                )
                .order_by(CorrectionPattern.frequency.desc())
                .limit(3)
                .all()
            )

            # Post-load assertion: verify all patterns belong to the expected client_id
            verified_patterns = []
            for pattern in patterns:
                if pattern.client_id != client_id:
                    logger.error(
                        "SECURITY: CorrectionPattern %s has client_id=%s, "
                        "expected client_id=%s — excluding from results",
                        pattern.id,
                        pattern.client_id,
                        client_id,
                    )
                else:
                    verified_patterns.append(pattern)

            return verified_patterns

        except Exception:
            logger.exception(
                "Failed to get correction patterns for avatar %s, client %s",
                avatar_id,
                client_id,
            )
            return []

    def format_learning_context(
        self, examples: list[EditRecord], patterns: list[CorrectionPattern]
    ) -> str:
        """Formats examples and patterns into prompt-ready text.

        Produces a formatted string for injection into the system prompt,
        placed after voice profile and before thread content.

        The output contains:
        - A "Correction Rules" section with imperative rules from patterns
        - An "Examples of Past Corrections" section with before/after pairs
        - Negative examples (rejected drafts) are labeled with rejection indicator

        Args:
            examples: List of EditRecord objects (few-shot examples).
            patterns: List of CorrectionPattern objects (distilled rules).

        Returns:
            Formatted string ready for prompt injection, or empty string
            if both examples and patterns are empty.
        """
        if not examples and not patterns:
            return ""

        sections: list[str] = []
        sections.append("## Learned Corrections from Past Reviews")

        # Correction Rules section
        if patterns:
            sections.append("### Correction Rules")
            for pattern in patterns:
                sections.append(f"- {pattern.rule_text}")

        # Examples of Past Corrections section
        if examples:
            sections.append("")
            sections.append("### Examples of Past Corrections")

            for i, example in enumerate(examples, start=1):
                if example.final_status == "rejected":
                    # Negative example — rejection indicator
                    sections.append(
                        f'**Example {i} (rejected draft \u2014 avoid this style):**'
                    )
                    sections.append(f'BEFORE: "{example.ai_draft}"')
                    sections.append("(This was rejected by the reviewer)")
                else:
                    # Positive example — approved edit with before/after
                    sections.append(f"**Example {i} (approved edit):**")
                    sections.append(f'BEFORE: "{example.ai_draft}"')
                    after_text = example.edited_draft if example.edited_draft else example.ai_draft
                    sections.append(f'AFTER: "{after_text}"')

                # Add blank line between examples (but not after the last one)
                if i < len(examples):
                    sections.append("")

        return "\n".join(sections)

    def enforce_retention_limits(
        self, db: Session, avatar_id: UUID, client_id: UUID
    ) -> int:
        """Archives records beyond 200, deletes archived records older than 180 days.

        Retention policy:
        - Keep at most 200 non-archived records per avatar-client pair.
        - Records beyond 200 are marked is_archived=True (oldest first).
        - Archived records older than 180 days are permanently deleted.
        - Only non-archived records (up to 200) are used for pattern computation.
        - Only 50 most recent non-archived are used for example selection.

        Args:
            db: SQLAlchemy session.
            avatar_id: The avatar's UUID.
            client_id: The client's UUID.

        Returns:
            Count of actions taken (archives + deletes). Returns 0 on failure.
        """
        try:
            actions_taken = 0

            # Step 1: Archive records beyond 200 per avatar-client pair
            # Count non-archived records
            non_archived_count = (
                db.query(func.count(EditRecord.id))
                .filter(
                    EditRecord.avatar_id == avatar_id,
                    EditRecord.client_id == client_id,
                    EditRecord.is_archived == False,  # noqa: E712
                )
                .scalar()
            ) or 0

            if non_archived_count > 200:
                # Find the 200th most recent record's created_at as the cutoff
                # Records older than this cutoff should be archived
                cutoff_record = (
                    db.query(EditRecord.created_at)
                    .filter(
                        EditRecord.avatar_id == avatar_id,
                        EditRecord.client_id == client_id,
                        EditRecord.is_archived == False,  # noqa: E712
                    )
                    .order_by(EditRecord.created_at.desc())
                    .offset(199)
                    .limit(1)
                    .scalar()
                )

                if cutoff_record:
                    # Archive all non-archived records older than the cutoff
                    archived_count = (
                        db.query(EditRecord)
                        .filter(
                            EditRecord.avatar_id == avatar_id,
                            EditRecord.client_id == client_id,
                            EditRecord.is_archived == False,  # noqa: E712
                            EditRecord.created_at < cutoff_record,
                        )
                        .update(
                            {EditRecord.is_archived: True},
                            synchronize_session="fetch",
                        )
                    )
                    actions_taken += archived_count

            # Step 2: Delete archived records older than 180 days permanently
            retention_cutoff = datetime.now(timezone.utc) - timedelta(days=180)

            deleted_count = (
                db.query(EditRecord)
                .filter(
                    EditRecord.avatar_id == avatar_id,
                    EditRecord.client_id == client_id,
                    EditRecord.is_archived == True,  # noqa: E712
                    EditRecord.created_at < retention_cutoff,
                )
                .delete(synchronize_session="fetch")
            )
            actions_taken += deleted_count

            db.flush()

            if actions_taken > 0:
                logger.info(
                    "Retention limits enforced for avatar %s, client %s: "
                    "%d actions taken",
                    avatar_id,
                    client_id,
                    actions_taken,
                )

            return actions_taken

        except Exception:
            logger.exception(
                "Failed to enforce retention limits for avatar %s, client %s",
                avatar_id,
                client_id,
            )
            return 0

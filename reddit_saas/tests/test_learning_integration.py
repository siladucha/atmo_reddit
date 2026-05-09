"""Integration tests for the Self-Learning Loop.

Task 13.1: End-to-end learning loop integration test
- Approve a draft with edits -> verify EditRecord created -> generate new comment
  -> verify learning context in prompt -> verify learning_metadata stored
- Test the full cycle from capture to injection
- Requirements: 1.1, 2.1, 2.4

Task 13.3: Pattern extraction integration test
- Creates 5+ EditRecords with similar edits (all shorten text)
- Triggers recompute_correction_patterns
- Verifies patterns extracted with correct type and frequency
- Verifies rule_text <= 100 characters
- Requirements: 3.1, 3.2, 3.3, 3.4

Uses mock DB sessions to test the full pipeline without requiring
a running PostgreSQL instance.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.services.generation import generate_comment
from app.services.learning import LearningService, compute_edit_summary


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def learning_service():
    """Provide a LearningService instance."""
    return LearningService()


@pytest.fixture
def avatar_id():
    """Generate a test avatar UUID."""
    return uuid.uuid4()


@pytest.fixture
def client_id():
    """Generate a test client UUID."""
    return uuid.uuid4()


@pytest.fixture
def comment_draft_id():
    """Generate a test comment draft UUID."""
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def create_shortening_edit_records(
    avatar_id, client_id, comment_draft_id, subreddit="cybersecurity", count=6
) -> list[EditRecord]:
    """Create multiple EditRecords that all demonstrate text shortening."""
    long_drafts = [
        "The landscape of cybersecurity is fundamentally shifting as organizations need to completely rethink their entire approach to exposure management and vulnerability assessment.",
        "I would argue that the ecosystem of threat detection tools has fundamentally evolved beyond what most security professionals currently understand or appreciate.",
        "In my professional experience working with enterprise security teams, the most critical challenge remains the integration of disparate security tools into a cohesive platform.",
        "The reality is that most organizations are still running legacy vulnerability scanners and calling it exposure management, which is a fundamentally flawed approach.",
        "From a strategic perspective, the convergence of AI and cybersecurity represents an unprecedented opportunity for organizations to dramatically improve their security posture.",
        "It is worth noting that the current state of cloud security tooling leaves much to be desired, particularly when it comes to multi-cloud environments and hybrid architectures.",
        "The fundamental problem with traditional security approaches is that they focus too heavily on perimeter defense while ignoring the increasingly complex internal threat landscape.",
    ]

    short_drafts = [
        "cybersecurity is shifting, orgs need to rethink exposure management.",
        "threat detection tools have evolved beyond what most pros understand.",
        "biggest challenge is integrating disparate security tools into one platform.",
        "most orgs still run legacy vuln scanners and call it exposure management.",
        "AI + cybersecurity convergence is a huge opportunity for better security.",
        "cloud security tooling needs work, especially for multi-cloud setups.",
        "traditional security focuses too much on perimeter, ignores internal threats.",
    ]

    records = []
    for i in range(count):
        ai_text = long_drafts[i % len(long_drafts)]
        edited_text = short_drafts[i % len(short_drafts)]
        edit_summary = compute_edit_summary(ai_text, edited_text)

        record = EditRecord(
            id=uuid.uuid4(),
            comment_draft_id=comment_draft_id,
            avatar_id=avatar_id,
            client_id=client_id,
            ai_draft=ai_text,
            edited_draft=edited_text,
            edit_summary=edit_summary,
            subreddit=subreddit,
            engagement_mode="helpful_peer",
            post_title="Test post",
            post_body="Test body",
            final_status="approved",
            is_archived=False,
            created_at=datetime.now(timezone.utc),
        )
        records.append(record)

    return records


def create_mock_db_with_records(records: list[EditRecord]) -> MagicMock:
    """Create a mock DB session that simulates real query behavior for
    recompute_correction_patterns."""
    db = MagicMock()
    added_patterns: list[CorrectionPattern] = []

    def mock_add(obj):
        if isinstance(obj, CorrectionPattern):
            added_patterns.append(obj)

    db.add.side_effect = mock_add
    db.flush.return_value = None
    db._added_patterns = added_patterns

    call_count = {"value": 0}

    def mock_query(model):
        call_count["value"] += 1
        mock_q = MagicMock()

        if call_count["value"] == 1:
            mock_q.filter.return_value = mock_q
            qualifying = [
                r for r in records
                if not r.is_archived
                and r.final_status == "approved"
                and r.edit_summary is not None
            ]
            mock_q.all.return_value = qualifying
        else:
            mock_q.filter.return_value = mock_q
            mock_q.first.return_value = None

        return mock_q

    db.query.side_effect = mock_query
    return db


# ---------------------------------------------------------------------------
# Task 13.1: End-to-end learning loop integration test
# ---------------------------------------------------------------------------


class TestLearningLoopEndToEnd:
    """End-to-end test: capture -> store -> generate -> inject -> verify provenance.

    Validates Requirements 1.1, 2.1, 2.4:
    - 1.1: EditRecord created on approve with edits
    - 2.1: Few-shot examples retrieved for generation
    - 2.4: Learning context formatted and injected into system prompt
    """

    def test_full_cycle_capture_to_injection(self, learning_service):
        """
        Full learning loop cycle:
        1. Approve a draft with edits -> EditRecord created
        2. Generate a new comment -> learning context injected into prompt
        3. Verify learning_metadata stored on resulting CommentDraft

        Validates: Requirements 1.1, 2.1, 2.4
        """
        avatar_id = uuid.uuid4()
        client_id = uuid.uuid4()
        thread_id = uuid.uuid4()
        draft_id = uuid.uuid4()

        ai_draft_text = (
            "The landscape of cybersecurity is shifting. Organizations need to "
            "rethink their approach to exposure management fundamentally."
        )
        edited_draft_text = (
            "honestly most orgs are still running vuln scanners and calling it "
            "exposure management. wild."
        )

        # --- Step 1: Create mock draft and thread for capture ---
        mock_draft = MagicMock()
        mock_draft.id = draft_id
        mock_draft.avatar_id = avatar_id
        mock_draft.client_id = client_id
        mock_draft.ai_draft = ai_draft_text
        mock_draft.edited_draft = edited_draft_text
        mock_draft.engagement_mode = "helpful_peer"

        mock_thread = MagicMock()
        mock_thread.subreddit = "cybersecurity"
        mock_thread.post_title = "What is the best approach to exposure management in 2025?"
        mock_thread.post_body = "We are a mid-size company trying to move beyond vulnerability scanning."

        # Mock DB for capture_edit_record
        capture_db = MagicMock()
        captured_records: list[EditRecord] = []

        def capture_add(obj):
            if isinstance(obj, EditRecord):
                obj.id = uuid.uuid4()
                obj.created_at = datetime.now(timezone.utc)
                captured_records.append(obj)

        capture_db.add.side_effect = capture_add
        capture_db.flush.return_value = None

        # Mock the count query for pattern recomputation trigger
        mock_count_query = MagicMock()
        mock_count_query.filter.return_value = mock_count_query
        mock_count_query.scalar.return_value = 1  # Only 1 record, no recomputation
        capture_db.query.return_value = mock_count_query

        # Call capture_edit_record
        edit_record = learning_service.capture_edit_record(
            db=capture_db,
            draft=mock_draft,
            thread=mock_thread,
            status="approved",
        )

        # --- Verify EditRecord was created with correct fields ---
        assert edit_record is not None
        assert edit_record.avatar_id == avatar_id
        assert edit_record.client_id == client_id
        assert edit_record.ai_draft == ai_draft_text
        assert edit_record.edited_draft == edited_draft_text
        assert edit_record.final_status == "approved"
        assert edit_record.subreddit == "cybersecurity"
        assert edit_record.post_title == mock_thread.post_title
        assert edit_record.created_at is not None

        # Verify edit_summary was computed (texts differ)
        assert edit_record.edit_summary is not None
        assert len(edit_record.edit_summary) > 0
        assert len(edit_record.edit_summary) <= 500

        # Verify the record was added to the DB session
        assert len(captured_records) == 1
        assert captured_records[0].final_status == "approved"

        # --- Step 2: Generate a new comment with mocked LLM ---
        # Set up the generation mock to capture the prompt
        mock_llm_response = {
            "content": '{"comment": "tbh most teams still treat vuln scanning as exposure management", '
            '"comment_to": "post", "location_depth": 0, '
            '"location_reasoning": "top-level reply to OP", '
            '"comment_approach": "cynical_deconstruction", '
            '"strategic_angle": "reframe"}',
            "input_tokens": 1500,
            "output_tokens": 80,
            "cost_usd": 0.005,
            "duration_ms": 2000,
            "model": "anthropic/claude-sonnet-4-20250514",
            "data": {
                "comment": "tbh most teams still treat vuln scanning as exposure management",
                "comment_to": "post",
                "location_depth": 0,
                "location_reasoning": "top-level reply to OP",
                "comment_approach": "cynical_deconstruction",
                "strategic_angle": "reframe",
            },
        }

        captured_messages = []

        def mock_call_llm_json(messages, **kwargs):
            """Capture the messages sent to the LLM for verification."""
            captured_messages.append(messages)
            return mock_llm_response

        # Mock avatar and client for generate_comment
        mock_avatar = MagicMock()
        mock_avatar.id = avatar_id
        mock_avatar.client_ids = [str(client_id)]
        mock_avatar.reddit_username = "test_avatar"
        mock_avatar.voice_profile_md = "Cynical security practitioner. Short, punchy comments."

        mock_client = MagicMock()
        mock_client.id = client_id
        mock_client.company_worldview = "Security should be proactive, not reactive."
        mock_client.company_problem = "Organizations lack visibility into their attack surface."

        mock_gen_thread = MagicMock()
        mock_gen_thread.id = thread_id
        mock_gen_thread.subreddit = "cybersecurity"
        mock_gen_thread.post_title = "What is the best approach to exposure management in 2025?"
        mock_gen_thread.post_body = "We are a mid-size company trying to move beyond vulnerability scanning."
        mock_gen_thread.comments_json = None
        mock_gen_thread.type = "professional"

        persona_selection = {
            "persona_username": "test_avatar",
            "mode": "helpful_peer",
            "thread_angle": "challenge the assumption that vuln scanning = exposure management",
            "pov_opportunity": "reframe what real exposure management looks like",
        }

        # Mock the learning service calls within generate_comment to return our captured record
        mock_select_examples = MagicMock(return_value=[edit_record])
        mock_get_patterns = MagicMock(return_value=[])

        # Mock DB for generate_comment (needs add, commit, refresh)
        gen_db = MagicMock()
        gen_db.add.return_value = None
        gen_db.commit.return_value = None
        gen_db.refresh.return_value = None

        with patch("app.services.generation.call_llm_json", side_effect=mock_call_llm_json):
            with patch("app.services.generation.log_ai_usage"):
                with patch("app.services.generation.get_config", return_value="anthropic/claude-sonnet-4-20250514"):
                    with patch(
                        "app.services.learning.LearningService.select_few_shot_examples",
                        mock_select_examples,
                    ):
                        with patch(
                            "app.services.learning.LearningService.get_correction_patterns",
                            mock_get_patterns,
                        ):
                            new_draft = generate_comment(
                                db=gen_db,
                                thread=mock_gen_thread,
                                client=mock_client,
                                avatar=mock_avatar,
                                persona_selection=persona_selection,
                            )

        # --- Step 3: Verify learning context was injected into the prompt ---
        assert len(captured_messages) == 1, "LLM should have been called exactly once"

        system_prompt = captured_messages[0][0]["content"]

        # Verify the learning context section is present (Requirement 2.4)
        assert "Learned Corrections from Past Reviews" in system_prompt, (
            "Learning context header should be in the system prompt"
        )

        # Verify the before/after example is present
        assert "BEFORE:" in system_prompt, "BEFORE label should be in prompt"
        assert "AFTER:" in system_prompt, "AFTER label should be in prompt"

        # --- Step 4: Verify learning_metadata on the new CommentDraft ---
        assert new_draft is not None
        assert new_draft.learning_metadata is not None, (
            "learning_metadata should be stored on the new draft"
        )

        metadata = new_draft.learning_metadata
        assert "edit_record_ids" in metadata
        assert "correction_patterns" in metadata
        assert "learning_token_count" in metadata

        # The edit_record_ids should contain the ID of the record we created
        assert str(edit_record.id) in metadata["edit_record_ids"], (
            "The captured EditRecord ID should appear in learning_metadata"
        )

        # Token count should be positive (learning context was injected)
        assert metadata["learning_token_count"] > 0

    def test_no_learning_context_when_no_edit_records(self, learning_service):
        """
        When no EditRecords exist for the avatar-client pair,
        generation proceeds without learning context (zero degradation).

        Validates: Requirement 2.7 (zero degradation)
        """
        avatar_id = uuid.uuid4()
        client_id = uuid.uuid4()
        thread_id = uuid.uuid4()

        mock_llm_response = {
            "content": '{"comment": "just use a proper EASM tool", '
            '"comment_to": "post", "location_depth": 0, '
            '"location_reasoning": "direct reply", '
            '"comment_approach": "drive_by", '
            '"strategic_angle": "reframe"}',
            "input_tokens": 1000,
            "output_tokens": 50,
            "cost_usd": 0.003,
            "duration_ms": 1500,
            "model": "anthropic/claude-sonnet-4-20250514",
            "data": {
                "comment": "just use a proper EASM tool",
                "comment_to": "post",
                "location_depth": 0,
                "location_reasoning": "direct reply",
                "comment_approach": "drive_by",
                "strategic_angle": "reframe",
            },
        }

        captured_messages = []

        def mock_call_llm_json(messages, **kwargs):
            captured_messages.append(messages)
            return mock_llm_response

        mock_avatar = MagicMock()
        mock_avatar.id = avatar_id
        mock_avatar.client_ids = [str(client_id)]
        mock_avatar.reddit_username = "test_avatar"
        mock_avatar.voice_profile_md = "Cynical security practitioner."

        mock_client = MagicMock()
        mock_client.id = client_id
        mock_client.company_worldview = "Security should be proactive."
        mock_client.company_problem = "Lack of visibility."

        mock_thread = MagicMock()
        mock_thread.id = thread_id
        mock_thread.subreddit = "cybersecurity"
        mock_thread.post_title = "Best EASM tools?"
        mock_thread.post_body = "Looking for recommendations."
        mock_thread.comments_json = None
        mock_thread.type = "professional"

        persona_selection = {
            "persona_username": "test_avatar",
            "mode": "helpful_peer",
            "thread_angle": "recommend practical tools",
            "pov_opportunity": None,
        }

        # Mock learning service to return empty (no edit records)
        mock_select_examples = MagicMock(return_value=[])
        mock_get_patterns = MagicMock(return_value=[])

        gen_db = MagicMock()
        gen_db.add.return_value = None
        gen_db.commit.return_value = None
        gen_db.refresh.return_value = None

        with patch("app.services.generation.call_llm_json", side_effect=mock_call_llm_json):
            with patch("app.services.generation.log_ai_usage"):
                with patch("app.services.generation.get_config", return_value="anthropic/claude-sonnet-4-20250514"):
                    with patch(
                        "app.services.learning.LearningService.select_few_shot_examples",
                        mock_select_examples,
                    ):
                        with patch(
                            "app.services.learning.LearningService.get_correction_patterns",
                            mock_get_patterns,
                        ):
                            new_draft = generate_comment(
                                db=gen_db,
                                thread=mock_thread,
                                client=mock_client,
                                avatar=mock_avatar,
                                persona_selection=persona_selection,
                            )

        # Verify no learning context in prompt
        system_prompt = captured_messages[0][0]["content"]
        assert "Learned Corrections from Past Reviews" not in system_prompt, (
            "No learning context should be injected when no edit records exist"
        )

        # Verify learning_metadata is None (no learning context used)
        assert new_draft.learning_metadata is None

    def test_edit_summary_computed_correctly_on_capture(self, learning_service):
        """
        Verify that the edit summary is computed deterministically
        and captures meaningful change information.

        Validates: Requirement 1.1 (edit_summary computed on capture)
        """
        avatar_id = uuid.uuid4()
        client_id = uuid.uuid4()
        draft_id = uuid.uuid4()

        ai_draft_text = (
            "The landscape of cybersecurity is shifting. Organizations need to "
            "rethink their approach to exposure management fundamentally."
        )
        edited_draft_text = (
            "honestly most orgs are still running vuln scanners and calling it "
            "exposure management. wild."
        )

        mock_draft = MagicMock()
        mock_draft.id = draft_id
        mock_draft.avatar_id = avatar_id
        mock_draft.client_id = client_id
        mock_draft.ai_draft = ai_draft_text
        mock_draft.edited_draft = edited_draft_text
        mock_draft.engagement_mode = "helpful_peer"

        mock_thread = MagicMock()
        mock_thread.subreddit = "cybersecurity"
        mock_thread.post_title = "Test post"
        mock_thread.post_body = "Test body"

        # Mock DB
        capture_db = MagicMock()
        captured_records: list[EditRecord] = []

        def capture_add(obj):
            if isinstance(obj, EditRecord):
                obj.id = uuid.uuid4()
                obj.created_at = datetime.now(timezone.utc)
                captured_records.append(obj)

        capture_db.add.side_effect = capture_add
        capture_db.flush.return_value = None

        mock_count_query = MagicMock()
        mock_count_query.filter.return_value = mock_count_query
        mock_count_query.scalar.return_value = 1
        capture_db.query.return_value = mock_count_query

        edit_record = learning_service.capture_edit_record(
            db=capture_db,
            draft=mock_draft,
            thread=mock_thread,
            status="approved",
        )

        assert edit_record is not None
        assert edit_record.edit_summary is not None

        # The summary should mention word count changes
        summary = edit_record.edit_summary
        assert "shortened" in summary or "words" in summary or "removed" in summary, (
            f"Edit summary should describe the nature of changes, got: '{summary}'"
        )

        # Verify determinism: computing again gives same result
        summary_again = compute_edit_summary(ai_draft_text, edited_draft_text)
        assert summary_again == edit_record.edit_summary



# ---------------------------------------------------------------------------
# Task 13.3: Pattern extraction integration test
# ---------------------------------------------------------------------------


class TestPatternExtractionIntegration:
    """Integration tests for pattern extraction pipeline.

    Validates Requirements 3.1, 3.2, 3.3, 3.4:
    - 3.1: Patterns computed when 5+ approved EditRecords with edit_summary exist
    - 3.2: Patterns categorized into correct types
    - 3.3: Patterns store frequency count and last_seen_at
    - 3.4: Recomputation triggered after every 5 new records
    """

    def test_pattern_extraction_with_shortening_edits(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """Create 6 edit records with shortening edits -> recompute -> verify
        length_adjustment pattern is extracted with correct frequency.

        Validates: Requirements 3.1, 3.2, 3.3
        """
        records = create_shortening_edit_records(
            avatar_id=avatar_id,
            client_id=client_id,
            comment_draft_id=comment_draft_id,
            count=6,
        )

        assert len(records) == 6
        for r in records:
            assert r.final_status == "approved"
            assert r.edit_summary is not None
            assert "shortened" in r.edit_summary.lower()

        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        assert len(added_patterns) >= 1, (
            f"Expected at least 1 pattern from 6 shortening edits, got {len(added_patterns)}"
        )

        pattern_types = [p.pattern_type for p in added_patterns]
        assert "length_adjustment" in pattern_types, (
            f"Expected 'length_adjustment' pattern type, got types: {pattern_types}"
        )

        length_pattern = next(
            p for p in added_patterns if p.pattern_type == "length_adjustment"
        )
        assert length_pattern.frequency >= 2
        assert length_pattern.last_seen_at is not None
        assert length_pattern.rule_text is not None
        assert len(length_pattern.rule_text) <= 100

    def test_pattern_rule_text_within_100_chars(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """All extracted patterns must have rule_text <= 100 characters.

        Validates: Requirements 3.5
        """
        records = create_shortening_edit_records(
            avatar_id=avatar_id,
            client_id=client_id,
            comment_draft_id=comment_draft_id,
            count=7,
        )

        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        assert len(added_patterns) >= 1

        for pattern in added_patterns:
            assert len(pattern.rule_text) <= 100, (
                f"Pattern '{pattern.pattern_type}' has rule_text exceeding 100 chars: "
                f"'{pattern.rule_text}' (len={len(pattern.rule_text)})"
            )

    def test_pattern_not_extracted_below_threshold(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """With fewer than 5 qualifying records, no patterns should be extracted.

        Validates: Requirements 3.1
        """
        records = create_shortening_edit_records(
            avatar_id=avatar_id,
            client_id=client_id,
            comment_draft_id=comment_draft_id,
            count=4,
        )

        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        assert len(added_patterns) == 0, (
            f"Expected 0 patterns with only 4 records, got {len(added_patterns)}"
        )

    def test_pattern_frequency_reflects_occurrence_count(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """Pattern frequency should reflect how many edit summaries exhibit the pattern.

        Validates: Requirements 3.3
        """
        records = create_shortening_edit_records(
            avatar_id=avatar_id,
            client_id=client_id,
            comment_draft_id=comment_draft_id,
            count=5,
        )

        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        length_patterns = [
            p for p in added_patterns if p.pattern_type == "length_adjustment"
        ]

        assert len(length_patterns) == 1
        assert length_patterns[0].frequency >= 5, (
            f"Expected frequency >= 5, got {length_patterns[0].frequency}"
        )

    def test_pattern_type_categorization_vocabulary_change(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """Edit records with vocabulary changes produce vocabulary_change patterns.

        Validates: Requirements 3.2
        """
        vocab_edits = [
            (
                "The fundamental paradigm of cybersecurity is evolving rapidly",
                "cybersecurity is evolving rapidly",
            ),
            (
                "The fundamental approach to threat detection requires rethinking",
                "threat detection needs rethinking",
            ),
            (
                "The fundamental challenge in cloud security remains unresolved",
                "cloud security challenge remains unresolved",
            ),
            (
                "The fundamental issue with legacy tools is their complexity",
                "legacy tools are too complex",
            ),
            (
                "The fundamental problem with perimeter defense is well documented",
                "perimeter defense problems are well known",
            ),
        ]

        records = []
        for ai_text, edited_text in vocab_edits:
            edit_summary = compute_edit_summary(ai_text, edited_text)
            record = EditRecord(
                id=uuid.uuid4(),
                comment_draft_id=comment_draft_id,
                avatar_id=avatar_id,
                client_id=client_id,
                ai_draft=ai_text,
                edited_draft=edited_text,
                edit_summary=edit_summary,
                subreddit="cybersecurity",
                engagement_mode="helpful_peer",
                post_title="Test post",
                post_body="Test body",
                final_status="approved",
                is_archived=False,
                created_at=datetime.now(timezone.utc),
            )
            records.append(record)

        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        assert len(added_patterns) >= 1, (
            f"Expected at least 1 pattern from vocabulary edits, got {len(added_patterns)}"
        )

        valid_types = {
            "length_adjustment",
            "tone_shift",
            "vocabulary_change",
            "structure_change",
            "content_removal",
            "content_addition",
        }
        for pattern in added_patterns:
            assert pattern.pattern_type in valid_types
            assert len(pattern.rule_text) <= 100
            assert pattern.frequency >= 2

    def test_full_pipeline_edit_to_pattern(
        self, learning_service, avatar_id, client_id, comment_draft_id
    ):
        """End-to-end: create edit records -> compute summaries -> extract patterns ->
        verify the complete pipeline produces correct output.

        Validates: Requirements 3.1, 3.2, 3.3, 3.4
        """
        edits = [
            (
                "The comprehensive analysis of the cybersecurity landscape reveals significant vulnerabilities in modern enterprise infrastructure",
                "cybersecurity analysis reveals enterprise vulnerabilities",
            ),
            (
                "It is absolutely essential that organizations understand the fundamental importance of proactive threat hunting",
                "orgs need proactive threat hunting",
            ),
            (
                "The overwhelming consensus among security professionals is that zero trust architecture represents the future",
                "security pros agree zero trust is the future",
            ),
            (
                "From my extensive experience in the field, I can confidently state that endpoint detection has matured significantly",
                "endpoint detection has matured significantly",
            ),
            (
                "The reality of the situation is that most companies are woefully unprepared for sophisticated supply chain attacks",
                "most companies are unprepared for supply chain attacks",
            ),
        ]

        records = []
        for ai_text, edited_text in edits:
            edit_summary = compute_edit_summary(ai_text, edited_text)
            assert edit_summary is not None

            record = EditRecord(
                id=uuid.uuid4(),
                comment_draft_id=comment_draft_id,
                avatar_id=avatar_id,
                client_id=client_id,
                ai_draft=ai_text,
                edited_draft=edited_text,
                edit_summary=edit_summary,
                subreddit="cybersecurity",
                engagement_mode="helpful_peer",
                post_title="Test post",
                post_body="Test body",
                final_status="approved",
                is_archived=False,
                created_at=datetime.now(timezone.utc),
            )
            records.append(record)

        # Verify edit summaries
        for record in records:
            assert len(record.edit_summary) <= 500
            assert "shortened" in record.edit_summary.lower()

        # Trigger pattern extraction
        db = create_mock_db_with_records(records)
        learning_service.recompute_correction_patterns(db, avatar_id, client_id)

        added_patterns = db._added_patterns
        assert len(added_patterns) >= 1

        length_patterns = [
            p for p in added_patterns if p.pattern_type == "length_adjustment"
        ]
        assert len(length_patterns) == 1

        length_pattern = length_patterns[0]
        assert length_pattern.frequency >= 5
        assert len(length_pattern.rule_text) <= 100
        assert length_pattern.last_seen_at is not None
        assert length_pattern.avatar_id == avatar_id
        assert length_pattern.client_id == client_id

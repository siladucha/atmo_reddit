# Implementation Plan: Self-Learning Loop

## Overview

Implement a self-learning loop that captures human edits to AI-generated comment drafts and feeds corrections back into the generation pipeline as few-shot examples and distilled correction patterns. The system stores structured edit records, computes recurring patterns, selects relevant examples for prompt injection, and provides admin visibility via an avatar learning panel and generation debug view.

## Tasks

- [x] 1. Database models and migrations
  - [x] 1.1 Create EditRecord SQLAlchemy model
    - Create `app/models/edit_record.py` with the EditRecord model
    - Fields: id, comment_draft_id, avatar_id, client_id, ai_draft, edited_draft, edit_summary, subreddit, engagement_mode, post_title, post_body (max 500 chars), final_status (CHECK constraint), is_archived, created_at
    - Add indexes: ix_edit_records_avatar_client, ix_edit_records_avatar_client_created, ix_edit_records_subreddit, ix_edit_records_not_archived (partial)
    - Register model in `app/models/__init__.py`
    - _Requirements: 1.1, 1.2, 1.3, 1.5, 1.6_

  - [x] 1.2 Create CorrectionPattern SQLAlchemy model
    - Create `app/models/correction_pattern.py` with the CorrectionPattern model
    - Fields: id, avatar_id, client_id, pattern_type (CHECK constraint for 6 types), rule_text (max 100 chars), frequency, last_seen_at, created_at, updated_at
    - Add indexes: unique ix_correction_patterns_avatar_client_rule, ix_correction_patterns_frequency
    - Register model in `app/models/__init__.py`
    - _Requirements: 3.2, 3.3, 3.5_

  - [x] 1.3 Add learning_metadata JSONB column to CommentDraft
    - Add `learning_metadata` column (JSONB, nullable) to `app/models/comment_draft.py`
    - Structure: `{"edit_record_ids": [...], "correction_patterns": [...], "learning_token_count": int}`
    - _Requirements: 5.1_

  - [x] 1.4 Create Alembic migration for all schema changes
    - Generate migration with `alembic revision --autogenerate`
    - Include: edit_records table, correction_patterns table, learning_metadata column on comment_drafts
    - Verify migration runs forward and backward cleanly
    - _Requirements: 1.1, 3.2, 5.1_

- [x] 2. Edit summary algorithm
  - [x] 2.1 Implement compute_edit_summary function
    - Create the deterministic diff algorithm in `app/services/learning.py`
    - Word-level diff: word count change, removed words (sample up to 3), added words (sample up to 3), structural changes (sentence count)
    - Return semicolon-separated string, max 500 characters
    - Return None if texts are identical
    - Compute synchronously (not deferred)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [x] 2.2 Write property test for edit summary determinism
    - **Property 2: Round trip consistency — calling compute_edit_summary multiple times with same inputs produces same output**
    - **Validates: Requirements 7.1**
    - Test file: `tests/test_edit_summary_props.py`

  - [x] 2.3 Write property test for edit summary format invariants
    - **Property 3: For any two distinct strings, result is non-empty semicolon-separated string with length ≤ 500**
    - **Validates: Requirements 7.2, 7.3**
    - Test file: `tests/test_edit_summary_props.py`

  - [x] 2.4 Write property test for edit summary null on identity
    - **Property 4: For any string s, compute_edit_summary(s, s) returns None**
    - **Validates: Requirements 7.4**
    - Test file: `tests/test_edit_summary_props.py`

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Learning service — capture and patterns
  - [x] 4.1 Implement capture_edit_record method
    - Create `app/services/learning.py` with LearningService class
    - Handle three statuses: approved (with edits), approved_unchanged, rejected
    - Call compute_edit_summary for approved-with-edits records
    - Store thread context (post_title, post_body truncated to 500 chars, subreddit)
    - Trigger pattern recomputation when edit count % 5 == 0
    - Enforce retention limits after capture
    - Wrap in try/except — never fail the review workflow
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 4.2 Write property test for edit capture record structure
    - **Property 1: For any CommentDraft and review action, capture_edit_record produces correct record structure (status matches action, ai_draft non-null, edited_draft null iff rejected, edit_summary null iff rejected or unchanged, post_body ≤ 500)**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6**
    - Test file: `tests/test_learning_capture_props.py`

  - [x] 4.3 Implement recompute_correction_patterns method
    - Analyze edit_summaries for recurring themes across all non-archived records
    - Categorize into 6 types: length_adjustment, tone_shift, vocabulary_change, structure_change, content_removal, content_addition
    - Store frequency count and last_seen_at
    - Express each pattern as imperative rule ≤ 100 characters
    - Only compute when 5+ qualifying edit records exist
    - Recompute after every 5 new records
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 4.4 Write property test for pattern computation threshold and limit
    - **Property 7: get_correction_patterns returns empty list when fewer than 5 qualifying records exist, and at most 3 patterns when 5+ exist**
    - **Validates: Requirements 2.5, 3.1**
    - Test file: `tests/test_pattern_computation_props.py`

  - [x] 4.5 Write property test for pattern rule length constraint
    - **Property 8: For any CorrectionPattern, rule_text length ≤ 100 characters**
    - **Validates: Requirements 3.5**
    - Test file: `tests/test_pattern_constraints_props.py`

- [x] 5. Few-shot example selection
  - [x] 5.1 Implement select_few_shot_examples method
    - Query 50 most recent non-archived records for avatar-client pair
    - Score by relevance: same subreddit (2 pts) > same engagement_mode (1 pt) > recency
    - Return up to 3 examples total, max 1 negative (rejected)
    - Selection logic: up to 2 positives + up to 1 negative, fill remaining from positives
    - Return empty list if no records exist (zero degradation)
    - _Requirements: 2.1, 2.2, 2.3, 6.3_

  - [x] 5.2 Write property test for example selection bounds and priority
    - **Property 5: select_few_shot_examples returns at most 3 examples, max 1 rejected, same-subreddit examples appear before different-subreddit**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Test file: `tests/test_example_selection_props.py`

  - [x] 5.3 Write property test for example selection window
    - **Property 10: With more than 50 non-archived records, only records from the 50 most recent are returned**
    - **Validates: Requirements 6.3**
    - Test file: `tests/test_example_selection_props.py`

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Generation pipeline integration
  - [x] 7.1 Implement format_learning_context method
    - Format few-shot examples as before/after pairs labeled "Learned corrections from past reviews"
    - Include correction patterns as concise imperative rules
    - Format negative examples with rejection indicator
    - Place after voice profile, before thread content in prompt structure
    - _Requirements: 2.4, 2.6_

  - [x] 7.2 Write property test for prompt formatting
    - **Property 6: For any non-empty list of examples, format_learning_context output contains "Learned corrections from past reviews" and BEFORE/AFTER text for each example**
    - **Validates: Requirements 2.4**
    - Test file: `tests/test_prompt_format_props.py`

  - [x] 7.3 Integrate learning context into generate_comment
    - Modify `app/services/generation.py` `generate_comment` function
    - Call `select_few_shot_examples` and `get_correction_patterns` before LLM call
    - Inject formatted learning context into system prompt between voice profile and thread content
    - Store provenance metadata (edit_record_ids, correction_patterns text, token count) on resulting CommentDraft
    - Skip injection gracefully if no records exist (zero degradation)
    - Wrap learning calls in try/except — generation must never fail due to learning
    - _Requirements: 2.1, 2.5, 2.6, 2.7, 5.1_

  - [x] 7.4 Write property test for generation provenance storage
    - **Property 11: When learning context is used, CommentDraft.learning_metadata contains IDs of used EditRecords and text of applied CorrectionPatterns**
    - **Validates: Requirements 5.1**
    - Test file: `tests/test_provenance_props.py`

- [x] 8. Review route hook
  - [x] 8.1 Integrate capture_edit_record into review route
    - Modify `app/routes/review.py` `update_comment` endpoint
    - After status transition to "approved" or "rejected", call `LearningService.capture_edit_record`
    - Determine correct status: "approved" (edited_draft != ai_draft), "approved_unchanged" (edited_draft == ai_draft or None), "rejected"
    - Pass thread context (post_title, post_body, subreddit) from the related RedditThread
    - Wrap in try/except — review action must never fail due to learning capture
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 8.2 Write unit tests for review route learning hook
    - Test that capture_edit_record is called on approve with edits
    - Test that capture_edit_record is called on approve unchanged
    - Test that capture_edit_record is called on reject
    - Test that review succeeds even if capture_edit_record raises an exception
    - _Requirements: 1.1, 1.2, 1.3_

- [x] 9. Data retention and cleanup
  - [x] 9.1 Implement enforce_retention_limits method
    - Archive records beyond 200 per avatar-client pair (mark is_archived=True)
    - Delete archived records older than 180 days permanently
    - Use only non-archived records (up to 200) for pattern computation
    - Use only 50 most recent non-archived for example selection
    - Return count of actions taken (archives + deletes)
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

  - [x] 9.2 Write property test for retention limit enforcement
    - **Property 9: After enforce_retention_limits, non-archived count ≤ 200, and any archived record older than 180 days is deleted**
    - **Validates: Requirements 6.1, 6.2, 6.5**
    - Test file: `tests/test_retention_props.py`

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Admin UI — Avatar learning panel
  - [x] 11.1 Create avatar learning panel API endpoint
    - Add `GET /admin/avatars/{id}/learning-panel` to `app/routes/admin.py`
    - Return: total edit records (broken down by status), most recent edit date + summary, top 5 correction patterns with frequencies, up to 3 preview few-shot examples (truncated to 100 chars)
    - Return empty-state message when zero edit records exist
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 11.2 Create avatar learning panel HTMX template
    - Create `app/templates/partials/avatar_learning_panel.html`
    - Dark theme (extends admin_base.html patterns)
    - Display stats, recent edit, correction patterns, preview examples
    - Empty state: "No learning data available yet"
    - Load asynchronously via HTMX on avatar detail page
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

- [x] 12. Debug view — Generation provenance
  - [x] 12.1 Create debug view API endpoint
    - Add `GET /admin/comments/{id}/debug-view` to `app/routes/admin.py`
    - Return: list of few-shot examples used (with edit_record IDs), correction patterns applied, total token count from learning context
    - Return "No learning context applied" message when learning_metadata is null/empty
    - _Requirements: 5.1, 5.2, 5.3_

  - [x] 12.2 Create debug view HTMX template
    - Create `app/templates/partials/comment_debug_view.html`
    - Expandable section (hidden by default) in comment review UI
    - Show few-shot examples with links to original edit records
    - Show correction patterns applied
    - Show token count added by learning context
    - _Requirements: 5.2, 5.3, 5.4_

- [x] 13. Integration tests
  - [x] 13.1 Write end-to-end learning loop integration test
    - Approve a draft with edits → verify EditRecord created → generate new comment → verify learning context in prompt
    - Test the full cycle from capture to injection
    - _Requirements: 1.1, 2.1, 2.4_

  - [x] 13.2 Write retention cleanup integration test
    - Create 210 records for one avatar-client pair → run enforce_retention_limits → verify 200 remain active, 10 archived
    - Create archived records older than 180 days → verify permanent deletion
    - _Requirements: 6.1, 6.2, 6.5_

  - [x] 13.3 Write pattern extraction integration test
    - Create 5+ edit records with similar edits (e.g., all shorten text) → trigger recomputation → verify patterns extracted with correct type and frequency
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The learning service is non-critical: all operations are wrapped in try/except to ensure zero degradation of existing review and generation workflows
- Python with Hypothesis is used for all property-based tests (already configured in project)
- All templates follow the existing dark theme (admin_base.html) and HTMX partial patterns

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["1.4"] },
    { "id": 2, "tasks": ["2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "2.4", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3"] },
    { "id": 5, "tasks": ["4.4", "4.5", "5.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "8.1", "9.1"] },
    { "id": 8, "tasks": ["7.4", "8.2", "9.2"] },
    { "id": 9, "tasks": ["11.1", "12.1"] },
    { "id": 10, "tasks": ["11.2", "12.2"] },
    { "id": 11, "tasks": ["13.1", "13.2", "13.3"] }
  ]
}
```

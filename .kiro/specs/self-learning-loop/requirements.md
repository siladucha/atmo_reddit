# Requirements Document

## Introduction

Self-Learning Loop from Human Edits — a system that captures human modifications to AI-generated comment drafts and uses those edits to improve future generations for the same avatar and client. The system stores structured edit records, computes recurring correction patterns, and injects relevant few-shot examples into the generation pipeline. An admin UI block on the avatar page provides visibility into learned edits and their influence on generation.

## Glossaryа

- **Edit_Record**: A structured record capturing the original AI draft, the human-edited version, the diff summary, and contextual metadata (avatar, client, subreddit, thread context, final status)
- **Learning_Service**: The service responsible for storing edit records, computing correction patterns, and selecting relevant examples for injection into generation prompts
- **Generation_Pipeline**: The existing comment generation flow (persona selection → comment writing → editing) that produces CommentDraft records
- **Few_Shot_Example**: A past edit record selected for inclusion in a generation prompt to guide the LLM toward the avatar's learned voice
- **Negative_Example**: An edit record from a rejected draft, used to show the LLM what to avoid
- **Correction_Pattern**: A recurring type of edit (e.g., "always removes em-dashes", "shortens sentences", "adds specific jargon") extracted from multiple edit records for the same avatar
- **Voice_Memory**: The accumulated set of correction patterns and few-shot examples that represent an avatar's learned voice preferences
- **Edit_Summary**: A concise textual description of what changed between the AI draft and the human-edited version (computed via diff analysis)
- **Avatar_Learning_Panel**: The UI block on the avatar admin page showing learning statistics, recent edits, and top correction patterns
- **Debug_View**: A view or metadata section in the generation output that shows which few-shot examples and correction patterns were used for a specific generation

## Requirements

### Requirement 1: Capture Edit Records on Review Actions

**User Story:** As an operator, I want every human edit to an AI-generated draft to be automatically captured with full context, so that the system can learn from my corrections over time.

#### Acceptance Criteria

1. WHEN an operator approves a CommentDraft that has an edited_draft different from the ai_draft, THE Learning_Service SHALL create an Edit_Record containing the original ai_draft, the edited_draft, a computed Edit_Summary, the avatar_id, the client_id, the subreddit name, the thread context (post title and body), and the final status "approved"
2. WHEN an operator rejects a CommentDraft, THE Learning_Service SHALL create an Edit_Record containing the ai_draft, a null edited_draft, a null Edit_Summary, the avatar_id, the client_id, the subreddit name, the thread context, and the final status "rejected"
3. WHEN an operator approves a CommentDraft where edited_draft equals ai_draft (no changes made), THE Learning_Service SHALL create an Edit_Record with the final status "approved_unchanged" and a null Edit_Summary
4. THE Learning_Service SHALL compute the Edit_Summary by comparing ai_draft and edited_draft using a diff algorithm that produces a human-readable description of changes (e.g., "shortened from 85 to 42 words", "removed em-dash", "changed tone from formal to casual")
5. THE Edit_Record SHALL store the created_at timestamp of when the edit was captured
6. THE Edit_Record SHALL store the thread context as structured data including post_title, post_body (truncated to 500 characters), and subreddit name

### Requirement 2: Inject Learned Edits into Generation Pipeline

**User Story:** As a system operator, I want future comment generations for an avatar to reflect past human corrections, so that the AI produces drafts closer to what the human reviewer expects.

#### Acceptance Criteria

1. WHEN the Generation_Pipeline generates a comment for an avatar, THE Learning_Service SHALL retrieve up to 3 relevant Few_Shot_Examples for that avatar and client combination
2. THE Learning_Service SHALL prioritize Few_Shot_Examples by relevance: same subreddit first, then same engagement_mode, then most recent
3. THE Learning_Service SHALL include at most 1 Negative_Example (from rejected drafts) in the retrieved examples when a rejected draft exists for the same avatar and subreddit
4. THE Generation_Pipeline SHALL format Few_Shot_Examples as before/after pairs in the system prompt, clearly labeled as "Learned corrections from past reviews"
5. WHILE an avatar has 5 or more Edit_Records, THE Learning_Service SHALL compute and include up to 3 top Correction_Patterns as concise rules in the system prompt (e.g., "Always keep comments under 50 words", "Never use parenthetical asides")
6. THE Generation_Pipeline SHALL place learned examples and correction patterns after the voice profile section and before the thread content in the prompt structure
7. IF no Edit_Records exist for an avatar-client combination, THEN THE Generation_Pipeline SHALL proceed without learned examples (no degradation of existing behavior)

### Requirement 3: Compute and Store Correction Patterns

**User Story:** As a system operator, I want the system to identify recurring correction patterns from accumulated edits, so that the AI can internalize systematic preferences without needing individual examples for every case.

#### Acceptance Criteria

1. WHEN an avatar accumulates 5 or more Edit_Records with status "approved" (where edited_draft differs from ai_draft), THE Learning_Service SHALL compute Correction_Patterns by analyzing the Edit_Summaries for recurring themes
2. THE Learning_Service SHALL categorize Correction_Patterns into types: length_adjustment, tone_shift, vocabulary_change, structure_change, content_removal, content_addition
3. THE Learning_Service SHALL store each Correction_Pattern with a frequency count (how many edits exhibited this pattern) and a last_seen_at timestamp
4. THE Learning_Service SHALL recompute Correction_Patterns after every 5 new Edit_Records for the avatar
5. THE Learning_Service SHALL express each Correction_Pattern as a concise imperative rule suitable for LLM prompt injection (max 100 characters per rule)

### Requirement 4: Avatar Learning Panel in Admin UI

**User Story:** As an admin, I want to see a "Learning / Voice Adaptation" block on the avatar page, so that I can understand how the system has learned from past edits and verify the learning is working correctly.

#### Acceptance Criteria

1. THE Avatar_Learning_Panel SHALL display the total number of Edit_Records for the avatar (broken down by status: approved with edits, approved unchanged, rejected)
2. THE Avatar_Learning_Panel SHALL display the date and Edit_Summary of the most recent Edit_Record
3. THE Avatar_Learning_Panel SHALL display the top 5 Correction_Patterns with their frequency counts, sorted by frequency descending
4. THE Avatar_Learning_Panel SHALL display up to 3 recent Few_Shot_Examples that would be used in the next generation, showing the before/after text truncated to 100 characters each
5. WHEN the avatar has zero Edit_Records, THE Avatar_Learning_Panel SHALL display a message indicating no learning data is available yet
6. THE Avatar_Learning_Panel SHALL render as an HTMX partial loaded asynchronously on the avatar detail page, following the existing dark theme (admin_base.html)

### Requirement 5: Debug View for Generation Provenance

**User Story:** As a system operator, I want to see which learned examples and correction patterns were used when generating a specific comment, so that I can verify the learning loop is functioning and debug unexpected outputs.

#### Acceptance Criteria

1. WHEN the Generation_Pipeline uses Few_Shot_Examples or Correction_Patterns in a generation, THE Generation_Pipeline SHALL store the IDs of used Edit_Records and the text of applied Correction_Patterns as metadata on the resulting CommentDraft
2. THE Debug_View SHALL be accessible from the review queue for each CommentDraft, showing: the list of Few_Shot_Examples used (with links to original Edit_Records), the Correction_Patterns applied, and the total token count added by learning context
3. IF no learning context was used for a generation, THEN THE Debug_View SHALL indicate "No learning context applied (insufficient edit history)"
4. THE Debug_View SHALL render as an expandable section in the comment review UI, hidden by default to avoid cluttering the review workflow

### Requirement 6: Edit Record Data Retention and Limits

**User Story:** As a system architect, I want edit records to be bounded in storage and have clear retention policies, so that the system remains performant as edit history grows.

#### Acceptance Criteria

1. THE Learning_Service SHALL retain a maximum of 200 Edit_Records per avatar-client combination
2. WHEN the Edit_Record count exceeds 200 for an avatar-client combination, THE Learning_Service SHALL archive the oldest records by marking them as archived (excluded from example selection but retained for pattern computation)
3. THE Learning_Service SHALL use only the most recent 50 non-archived Edit_Records when selecting Few_Shot_Examples
4. THE Learning_Service SHALL use all non-archived Edit_Records (up to 200) when computing Correction_Patterns
5. IF an Edit_Record is older than 180 days and archived, THEN THE Learning_Service SHALL delete the record permanently

### Requirement 7: Edit Summary Computation

**User Story:** As a system operator, I want each edit to have a clear, concise summary of what changed, so that I can quickly understand the nature of corrections without reading full diffs.

#### Acceptance Criteria

1. THE Learning_Service SHALL compute Edit_Summary using a deterministic diff algorithm (not LLM-based) that identifies: word count change, added words, removed words, and structural changes
2. THE Edit_Summary SHALL be formatted as a semicolon-separated list of changes (e.g., "shortened 85→42 words; removed 'landscape'; added 'tbh'; restructured to single sentence")
3. THE Edit_Summary SHALL have a maximum length of 500 characters
4. WHEN the edited_draft is identical to ai_draft, THE Learning_Service SHALL set Edit_Summary to null
5. THE Learning_Service SHALL compute Edit_Summary synchronously at the time of edit capture (not deferred to a background task)


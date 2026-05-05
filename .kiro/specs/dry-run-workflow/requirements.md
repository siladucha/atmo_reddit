# Requirements Document

## Introduction

This feature introduces a **Dry-Run Workflow** that lets the team operate the entire Reddit Marketing SaaS pipeline (scrape → score → persona-select → generate → edit) without requiring a live LLM API key. At every stage that would normally invoke an LLM, the system instead renders the fully-assembled prompt to the screen with a "copy" affordance and a text area where the operator pastes back the response from an external LLM (ChatGPT, Claude.ai web, etc.). The pasted response is parsed and saved exactly as if it had been returned by a programmatic LLM call.

This serves three goals: (1) **practical understanding** — the team sees with their own eyes what is sent to the LLM at each stage, removing the "black box" feeling; (2) **client demos and pilots** without burning AI budget; (3) **prompt quality control** — operators can spot prompt issues before going live.

The feature also covers two adjacent gaps the team identified: the onboarding wizard must equally support **creating new clients from scratch** and **editing existing clients** (e.g. NeuroYoga), and the system must offer a **one-time importer** that ingests historical persona, keyword, and subreddit data from the legacy no-code project (Ori's CSV and JSON exports stored at the repository root) so we don't re-enter 469 personas and 136 keywords by hand.

## Glossary

- **Dry_Run_Mode**: A system-wide toggle that, when enabled, replaces every programmatic LLM call with a UI step where the operator copies the prompt to an external LLM and pastes the response back. Stored in `system_settings` as `dry_run_enabled`.
- **LLM_Stage**: One of the four pipeline operations that invoke an LLM: `scoring`, `persona_select`, `generation`, `editing`.
- **Prompt_Preview_Page**: An admin page that shows the fully-rendered system prompt and user prompt for a chosen LLM stage and a chosen entity (thread or draft), with copy-to-clipboard buttons and a text area for the pasted response.
- **Manual_Response**: The text the operator pastes back after running the prompt through an external LLM. For JSON-output stages it must be valid JSON; for text-output stages it can be free-form text.
- **Ori_Data_Importer**: A one-time admin tool that ingests data from the four legacy artefacts at the repository root: `Reddit Personas-Grid view.csv`, `keywords-Grid view.csv`, `Run subreddits - Cyber copy.json`, and (optionally) `Scrape-Grid view.csv`.
- **Wizard_Edit_Mode**: The behaviour where the existing 7-step onboarding wizard is opened against an already-created client (e.g. via `/admin/clients/{id}/onboard/step/1`) and pre-fills every field from the database.
- **Client_View**: The user-facing dashboard a client sees (`/`, `/review`, `/threads/{id}`, `/avatars-page`) — distinct from the admin operator's view.
- **System_View**: The admin's full operational view (`/admin/*`).

## Requirements

### Requirement 1: Dry-Run Mode System Toggle

**User Story:** As an admin, I want to toggle Dry-Run Mode on and off without redeploying the application, so that I can switch between live LLM operation and dry-run training mode at will.

#### Acceptance Criteria

1. THE system SHALL persist a `dry_run_enabled` boolean flag in the `system_settings` table with a default value of `false`.
2. WHEN the admin opens `/admin/health` or a dedicated `/admin/settings/dry-run` page, THE system SHALL display the current state of `dry_run_enabled` and a toggle control.
3. WHEN the admin toggles `dry_run_enabled`, THE system SHALL persist the change and create an Activity_Event with `event_type="system"` and a message describing the new state.
4. WHEN `dry_run_enabled` is `false`, THE pipeline SHALL invoke LLM APIs as it does today (no behaviour change to the live flow).
5. WHEN `dry_run_enabled` is `true`, THE pipeline SHALL skip all programmatic LLM calls and instead create pending Manual_Response records that the operator must complete via the UI.

### Requirement 2: Wizard Edit Mode for Existing Clients

**User Story:** As an admin, I want to re-open the 7-step onboarding wizard against an existing client and have every step pre-filled from the database, so that I can fix or refine an existing client's configuration the same way I would create a new one.

#### Acceptance Criteria

1. WHEN the admin opens `/admin/clients/{client_id}/onboard/step/1` for an existing client, THE wizard SHALL pre-fill all profile fields (`client_name`, `brand_name`, `company_profile`, `company_worldview`, `company_problem`, `competitive_landscape`, `brand_voice`, `icp_profiles`) from the database.
2. WHEN the admin opens any subsequent step (2-6) for an existing client, THE wizard SHALL display the current state of subreddits, keywords, avatar assignments, and personas without losing previously saved data.
3. WHEN the admin submits a wizard step that already has data, THE system SHALL update the existing records rather than creating duplicates.
4. THE existing client detail page (`/admin/clients/{id}`) SHALL include a button "Open Onboarding Wizard" that links to step 1 of the wizard for that client.
5. WHEN the admin opens the wizard for a new client (`client_id == "new"`), THE wizard SHALL behave as today — Step 1 creates a new Client record on submit.

### Requirement 3: Prompt Preview for Scoring Stage

**User Story:** As an admin operating in Dry-Run Mode, I want to see the exact scoring prompt that would be sent to the LLM for any unscored thread, so that I can run it through an external LLM and paste the result back.

#### Acceptance Criteria

1. WHEN `dry_run_enabled` is `true` AND the operator opens `/admin/dry-run/score/{thread_id}`, THE system SHALL render a page showing: (a) the rendered system prompt with all template substitutions applied (brand_name, company_profile, keywords, etc.), (b) the rendered user prompt containing the thread title, body, and comments_json, (c) a "Copy System Prompt" button, (d) a "Copy User Prompt" button, (e) a "Copy Both as Conversation" button (combined message format), (f) a textarea labelled "Paste LLM JSON response here", (g) a "Submit Response" button.
2. WHEN the operator submits a response for scoring, THE system SHALL parse the JSON and apply the same field assignments as the live `score_thread` function (tag, alert, relevance, quality, strategic, composite, intent, scoring_reasoning).
3. IF the pasted response is not valid JSON, THEN THE system SHALL display the parse error and keep the textarea filled so the operator can fix it.
4. WHEN the response is successfully saved, THE system SHALL log an Activity_Event with `event_type="score"` and metadata indicating `mode="dry_run"`, and redirect to the same page for the next unscored thread of the same client (or back to the threads list if none remain).
5. THE Prompt_Preview_Page SHALL include the model name that would be used (`litellm_scoring_model` from settings) so the operator knows which external LLM to mimic.

### Requirement 4: Prompt Preview for Persona Selection Stage

**User Story:** As an admin in Dry-Run Mode, I want to see the persona selection prompt for an engage-tagged thread before deciding which avatar speaks, so that I can run the selection through an external LLM and store the result.

#### Acceptance Criteria

1. WHEN `dry_run_enabled` is `true` AND the operator opens `/admin/dry-run/persona-select/{thread_id}`, THE system SHALL render the persona selection prompt with the JSON list of available avatars (those with `client_id` in the avatar's `client_ids`), the thread content, and the brand context.
2. THE Prompt_Preview_Page SHALL render the same input/output controls as in Requirement 3 (copy buttons, textarea, submit).
3. WHEN the operator submits a JSON response containing `persona_username`, `mode`, `audience`, `thread_angle`, `pov_opportunity`, `selection_reasoning`, THE system SHALL store this selection as the input to the next stage (generation), keyed by `thread_id`, in a new `dry_run_state` table or as JSONB on the thread.
4. IF the pasted `persona_username` does not match any avatar assigned to the client, THEN THE system SHALL display an error and keep the response in the textarea.

### Requirement 5: Prompt Preview for Comment Generation Stage

**User Story:** As an admin in Dry-Run Mode, I want to see the comment-writing prompt with the full voice profile and previous-comments context, paste in the generated comment, and have it saved as a CommentDraft.

#### Acceptance Criteria

1. WHEN `dry_run_enabled` is `true` AND the operator opens `/admin/dry-run/generate/{thread_id}` after persona selection has been stored, THE system SHALL render the generation prompt with all template substitutions (voice_profile, company_worldview, mode, thread_angle, pov_opportunity, previous_comments) applied.
2. WHEN the operator submits a JSON response containing `comment`, `comment_to`, `location_depth`, `location_reasoning`, `comment_approach`, `strategic_angle`, THE system SHALL create a CommentDraft record with `status="pending"`, `engagement_mode` from persona_select, and link it to the thread, client, and selected avatar.
3. THE system SHALL log an Activity_Event with `event_type="generate"` and metadata indicating `mode="dry_run"`.
4. AFTER successful generation, THE system SHALL redirect to `/admin/dry-run/edit/{draft_id}` so the operator can run the editor stage on the same draft.

### Requirement 6: Prompt Preview for Editor Stage

**User Story:** As an admin in Dry-Run Mode, I want to see the editor prompt for a freshly generated comment draft and paste the cleaned-up version back.

#### Acceptance Criteria

1. WHEN `dry_run_enabled` is `true` AND the operator opens `/admin/dry-run/edit/{draft_id}`, THE system SHALL render the editor prompt with the current `ai_draft`, the original post title, and the post body (truncated to 1000 chars).
2. WHEN the operator submits a free-form text response, THE system SHALL update `comment_drafts.ai_draft` with the pasted text.
3. THE system SHALL log an Activity_Event with `event_type="generate"` and metadata indicating `mode="dry_run", stage="edit"`.
4. AFTER successful save, THE system SHALL redirect to `/review` showing the newly edited draft in the pending queue.

### Requirement 7: Dry-Run Workflow Hub Page

**User Story:** As an admin in Dry-Run Mode, I want a single hub page that shows all unfinished dry-run steps for a client, so that I can resume any stage without remembering URLs.

#### Acceptance Criteria

1. WHEN the operator opens `/admin/dry-run/{client_id}`, THE system SHALL display four sections: (a) Threads awaiting scoring (count + list with "Score" buttons), (b) Engage threads awaiting persona selection (count + list with "Select Persona" buttons), (c) Threads with persona selected awaiting generation (count + list with "Generate" buttons), (d) Drafts awaiting editor pass (count + list with "Edit" buttons).
2. EACH list SHALL display the thread title, subreddit, and timestamp; for drafts also the avatar username.
3. THE hub page SHALL be accessible from the main admin nav under a "Dry Run" item visible only when `dry_run_enabled=true`.
4. IF `dry_run_enabled` is `false`, THEN navigating to `/admin/dry-run/*` URLs SHALL return a 404 or redirect to `/admin/`.

### Requirement 8: System View vs Client View Visibility

**User Story:** As a client (non-superuser), I want to see the same drafts and threads I see today, regardless of whether they were generated by a live LLM call or a dry-run paste, so that the dry-run mode is invisible to me.

#### Acceptance Criteria

1. WHEN a client opens `/review`, THE system SHALL show CommentDraft records identical to today's behaviour, with no indication of whether each draft was generated via live LLM or dry-run paste.
2. WHEN a client opens `/threads/{client_id}`, THE system SHALL show RedditThread records with their tags identical to today's behaviour.
3. THE Client_View SHALL never expose the `/admin/dry-run/*` URLs, the `dry_run_enabled` flag, or any "mode=dry_run" metadata.
4. THE admin transparency dashboard at `/admin/clients/{id}/transparency` SHALL count dry-run-generated drafts and live-generated drafts identically in pipeline stats.

### Requirement 9: Ori Data Importer — Personas

**User Story:** As an admin setting up a new tenant, I want a one-time tool that imports the 469 persona records from `Reddit Personas-Grid view.csv` into the `avatars` table, so that I don't re-enter voice profiles by hand.

#### Acceptance Criteria

1. THE system SHALL provide a CLI script at `scripts/import_ori_data.py` and an admin endpoint `POST /admin/import/ori-personas` that reads `Reddit Personas-Grid view.csv` from the repository root.
2. FOR each row in the CSV, THE importer SHALL create or update an Avatar record using `reddit_username` as the natural key, mapping CSV columns: `reddit_username`, `email_address`, `voice_profile_md`, `tone_principles`, `speech_patterns`, `hill_i_die_on`, `helpful_mode_topics`, `constraints`, `vocabulary_lean`, `business_sub-reddits` (parsed as `client_subreddits` for an optional target client), `hobby_sub-reddits` (parsed into `hobby_subreddits` array).
3. THE importer SHALL skip rows where `active != "Active"` and log the skip count.
4. THE importer SHALL NOT import `email_password` or `reddit_password` from the CSV (security — credentials are not stored in plain text).
5. THE importer SHALL log an Activity_Event with `event_type="system"` summarising rows imported, rows updated, and rows skipped.
6. THE admin endpoint SHALL require `require_superuser` and return a JSON summary `{imported, updated, skipped, errors}`.

### Requirement 10: Ori Data Importer — Keywords

**User Story:** As an admin onboarding the XM Cyber client, I want to import the 136 keywords from `keywords-Grid view.csv` into the client's `keywords` JSONB field, so that scoring uses the legacy curated keyword list.

#### Acceptance Criteria

1. THE importer SHALL accept a target `client_id` and read `keywords-Grid view.csv` from the repository root.
2. FOR each row, THE importer SHALL group keywords by `probability_level` column into the existing `{"high": [...], "medium": [...], "low": [...]}` JSONB structure on the target Client.
3. THE importer SHALL preserve the keyword's category by appending it to a new optional Client field `keyword_categories` (JSONB) for future use, but SHALL NOT block import if this field does not exist yet.
4. THE importer SHALL deduplicate (case-insensitive) against existing keywords on the target client.
5. THE importer SHALL log an Activity_Event with `event_type="system"` summarising the import.
6. THE importer SHALL be invocable via CLI (`python -m scripts.import_ori_data --keywords --client-id=<id>`) and via the admin endpoint `POST /admin/import/ori-keywords?client_id=<id>`.

### Requirement 11: Ori Data Importer — Subreddits

**User Story:** As an admin onboarding the XM Cyber client, I want to import the 33-subreddit list from `Run subreddits - Cyber copy.json` so that the client's `client_subreddits` table matches the legacy configuration.

#### Acceptance Criteria

1. THE importer SHALL parse `Run subreddits - Cyber copy.json` and extract the `assignments` block at `nodes[1].parameters.assignments.assignments[0].value` (the embedded JSON list of `{subreddit, limit}` objects).
2. FOR each entry, THE importer SHALL create or reactivate a ClientSubreddit record with `type="professional"`, `subreddit_name=<name>`, `is_active=true`.
3. THE importer SHALL store the per-subreddit `limit` value in a new optional ClientSubreddit field `scrape_limit` (integer, nullable, default null) for future per-sub scraping policy. IF this field does not exist yet, THE importer SHALL create the rows without the limit and emit a warning.
4. THE importer SHALL deduplicate against existing rows on `(client_id, subreddit_name)`.
5. THE importer SHALL be invocable via CLI and via `POST /admin/import/ori-subreddits?client_id=<id>`.

### Requirement 12: Activity Event Coverage for Dry-Run Operations

**User Story:** As an admin reviewing the activity feed, I want every dry-run stage submission to produce an Activity_Event identical in shape to its live counterpart but tagged with `mode=dry_run`, so that the activity feed remains a complete operational record.

#### Acceptance Criteria

1. WHEN any dry-run stage submission succeeds (scoring, persona-select, generation, editing), THE system SHALL create an Activity_Event with the same `event_type` it would emit in live mode and add `metadata.mode = "dry_run"` and `metadata.operator_user_id = <current admin user id>`.
2. WHEN a dry-run submission fails (invalid JSON, mismatched username, validation error), THE system SHALL create an Activity_Event with `event_type="system"`, severity in metadata, and the error message.
3. THE Activity Feed display SHALL render dry-run events with a small "DRY" badge next to the existing event_type badge.
4. THE Activity Feed filter SHALL allow filtering by `mode=dry_run` to isolate the dry-run history.

### Requirement 13: Reversibility — No Live-Mode Side-Effects

**User Story:** As an admin, I want the dry-run workflow to be fully reversible — turning the toggle off must restore today's live behaviour with zero residual artefacts blocking the pipeline.

#### Acceptance Criteria

1. WHEN `dry_run_enabled` is toggled from `true` to `false`, THE pipeline SHALL resume invoking LLMs programmatically without requiring any cleanup of pending dry-run state.
2. ANY pending dry-run state records (e.g. unfilled persona-select for a thread) SHALL remain in the database but be ignored by the live pipeline (the live pipeline operates on its own input — unscored threads, engage threads without drafts).
3. THE Wizard_Edit_Mode and Ori_Data_Importer SHALL function identically regardless of the value of `dry_run_enabled`.

### Requirement 14: AI Cost Logging Compatibility

**User Story:** As an admin reviewing AI costs, I want dry-run operations to NOT inflate the AI cost dashboard, since no API was actually called.

#### Acceptance Criteria

1. WHEN a dry-run stage is submitted, THE system SHALL NOT create an AIUsageLog record (zero tokens, zero cost — there was no API call).
2. THE `/admin/ai-costs` page SHALL continue to show only real API spending and SHALL NOT be affected by dry-run activity.
3. THE Activity_Event for the dry-run submission SHALL include `metadata.cost_usd = 0` to make this explicit in the activity feed.

### Requirement 15: Documentation and Operator Guide

**User Story:** As an admin onboarding a new operator, I want a short written guide describing how to use Dry-Run Mode end-to-end, so that the operator can run a full pipeline in dry-run within their first hour.

#### Acceptance Criteria

1. THE feature SHALL include a Markdown guide at `docs/dry_run_operator_guide.md` covering: enabling the toggle, walking through the four stages for one thread, common JSON parse errors and how to fix them, expected fields for each stage's response, and how to verify the result in the regular admin views.
2. THE guide SHALL include screenshots or annotated code blocks showing the expected response JSON shape for scoring, persona selection, and generation.
3. THE guide SHALL note that dry-run drafts behave identically to live drafts in `/review` and require human approval the same way.

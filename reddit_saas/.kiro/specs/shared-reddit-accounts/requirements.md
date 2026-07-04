# Requirements Document

## Introduction

This feature enables a single Reddit account to serve multiple clients simultaneously. Instead of duplicating Reddit accounts per client, the system extracts shared account-level properties (credentials, health, karma, CQS, proxy, posting state) into a dedicated `reddit_accounts` table. Each client relationship is maintained through a separate Avatar record referencing the shared account via FK. This maximizes ROI on pre-warmed accounts while preserving P7 client isolation, per-avatar voice profiles, and independent phase progression.

## Glossary

- **Reddit_Account**: A physical Reddit account represented in the `reddit_accounts` table, holding credentials, karma, health status, CQS level, proxy configuration, and posting state shared across all avatars referencing it.
- **Avatar**: A client-specific persona record referencing a Reddit_Account via FK. Owns voice profile, strategy, subreddits, correction patterns, and phase progression. Exactly one client_id per Avatar.
- **Budget_Share**: The portion of a Reddit_Account's daily physical cap allocated to a specific Avatar. The sum of all budget shares for avatars on the same Reddit_Account must not exceed the account's daily_cap.
- **Daily_Cap**: The physical maximum number of posts a Reddit_Account can make per day without exceeding safe platform limits.
- **Scheduling_Mutex**: A timing constraint ensuring a minimum interval (45 min) between ANY posts from the same Reddit_Account, regardless of which Avatar the post belongs to.
- **Niche_Compatibility**: A constraint requiring that all avatars sharing a Reddit_Account operate within compatible industries or niches to maintain persona coherence on the Reddit username.
- **EPG_Scheduler**: The system component that builds daily publishing programs per avatar, now respecting shared account constraints.
- **Executor**: A person or browser extension session that physically posts content on Reddit for a given Reddit_Account.
- **System**: The RAMP platform as a whole.

## Requirements

### Requirement 1: Reddit Account Data Model

**User Story:** As a platform operator, I want account-level properties (credentials, health, karma, CQS, proxy, posting state) stored in a dedicated table, so that multiple avatars can reference the same physical Reddit account without data duplication.

#### Acceptance Criteria

1. THE System SHALL store the following fields in the `reddit_accounts` table: `reddit_username` (unique, not null), `proxy_url_encrypted`, `user_agent_string`, `refresh_token_encrypted`, `reddit_password_encrypted`, `karma_post`, `karma_comment`, `is_shadowbanned`, `cqs_level`, `cqs_checked_at`, `cqs_notes`, `last_posted_at`, `last_posted_ip`, `consecutive_post_failures`, `reddit_account_created`, `reddit_status`, `reddit_karma_comment`, `reddit_karma_post`, `reddit_icon_url`, `reddit_status_checked_at`, `last_health_check`, `health_status`, `health_status_changed_at`, `health_check_details`, and `consecutive_check_failures`.
2. THE System SHALL enforce a unique constraint on `reddit_accounts.reddit_username`.
3. WHEN a new Avatar is created referencing a Reddit_Account, THE System SHALL store the `reddit_account_id` FK on the Avatar record, where the referenced `reddit_account_id` must exist in the `reddit_accounts` table (FK enforced by the database).
4. THE System SHALL allow multiple Avatar records to reference the same `reddit_account_id`.
5. THE System SHALL remove `reddit_username`, `proxy_url_encrypted`, `user_agent_string`, `refresh_token_encrypted`, `reddit_password_encrypted`, `karma_post`, `karma_comment`, `is_shadowbanned`, `cqs_level`, `cqs_checked_at`, `cqs_notes`, `last_posted_at`, `last_posted_ip`, `consecutive_post_failures`, `reddit_account_created`, `reddit_status`, `reddit_karma_comment`, `reddit_karma_post`, `reddit_icon_url`, `reddit_status_checked_at`, `last_health_check`, `health_status`, `health_status_changed_at`, `health_check_details`, and `consecutive_check_failures` from the Avatar model after migration to the `reddit_accounts` table.
6. IF a Reddit_Account deletion is attempted while any Avatar record (regardless of active status) still references that `reddit_account_id`, THEN THE System SHALL reject the deletion (FK ON DELETE RESTRICT).
7. WHEN the migration runs, THE System SHALL create one `reddit_accounts` row per distinct `reddit_username` in the existing `avatars` table, copying all account-level field values from the avatar row into the new `reddit_accounts` row, and set the `reddit_account_id` FK on each corresponding avatar without deleting or modifying existing avatar data until the FK is confirmed populated.

### Requirement 2: Budget Sharing

**User Story:** As a platform operator, I want to assign a portion of a Reddit account's daily posting capacity to each avatar sharing it, so that total posting volume respects the account's physical safety limits.

#### Acceptance Criteria

1. THE Reddit_Account SHALL have a `daily_cap` integer field (minimum value 1) representing the maximum total posts per day across all avatars sharing the account.
2. THE Avatar SHALL have a `budget_share` integer field (minimum value 0) representing the maximum posts per day allocated to that avatar from the shared account's daily_cap, where a value of 0 means the avatar receives no posting slots from this account.
3. WHEN a new avatar is assigned to a Reddit_Account or an existing avatar's budget_share value is modified, THE System SHALL validate that the sum of all budget_share values for avatars on that account does not exceed the account's daily_cap.
4. WHEN the EPG_Scheduler builds a daily plan for an avatar, THE System SHALL limit planned slots to min(phase_budget, budget_share), where phase_budget is the value computed by the AttentionBudget class based on avatar phase and CQS level.
5. IF the sum of budget_share values would exceed daily_cap after an assignment or budget_share change, THEN THE System SHALL reject the change, preserve the previous values, and return an error indicating the budget overflow with the current sum and the daily_cap.
6. IF a Reddit_Account's daily_cap is reduced to a value below the current sum of budget_share values of its assigned avatars, THEN THE System SHALL reject the reduction and return an error indicating that existing budget_share allocations must be reduced first.

### Requirement 3: Scheduling Mutex

**User Story:** As a platform operator, I want a minimum time gap between any posts from the same Reddit account regardless of which avatar they belong to, so that posting patterns appear natural and reduce detection risk.

#### Acceptance Criteria

1. THE System SHALL enforce a minimum interval of 45 minutes between any two posts from the same Reddit_Account, regardless of which Avatar the posts belong to.
2. WHEN the EPG_Scheduler builds daily plans for avatars sharing a Reddit_Account, THE System SHALL interleave slots from different avatars on a merged timeline, spacing each consecutive slot by at least 45 minutes from the previous slot on that account.
3. IF a scheduled slot for Avatar A conflicts with a slot for Avatar B on the same Reddit_Account within 45 minutes, THEN THE System SHALL shift the later slot forward by the minimum amount of time needed to satisfy the 45-minute interval, and recursively shift any subsequent slots on the same account that are then in conflict.
4. WHEN the Executor dispatches a post for a Reddit_Account, THE System SHALL acquire a distributed lock keyed by the Reddit_Account identifier with a TTL of 300 seconds, and SHALL verify that at least 45 minutes have elapsed since the account's `last_posted_at` timestamp before proceeding.
5. IF the 45-minute interval has not elapsed since the Reddit_Account's last post at the time of dispatch, THEN THE System SHALL defer the current post until the interval is satisfied, provided the deferred time still falls within active hours (08:00-23:00 account local time) and the avatar's daily cap is not exceeded.
6. IF a deferred post would fall outside active hours or would exceed the avatar's daily cap, THEN THE System SHALL skip the post and mark the EPG slot as `skipped` with reason `mutex_overflow`.
7. IF the distributed lock for a Reddit_Account cannot be acquired within 60 seconds, THEN THE System SHALL skip the post, mark the EPG slot as `skipped` with reason `lock_timeout`, and emit an activity event indicating the lock contention.

### Requirement 4: Health and Shadowban Sharing

**User Story:** As a platform operator, I want health checks and shadowban detection to run per Reddit account (not per avatar), so that all avatars sharing an account are immediately affected when the account's health degrades.

#### Acceptance Criteria

1. THE System SHALL run health checks (shadowban detection, suspension detection) once per Reddit_Account per scheduled health-check cycle, rather than once per Avatar, deduplicating API calls when multiple avatars reference the same Reddit_Account.
2. WHEN a Reddit_Account is detected as shadowbanned, THE System SHALL demote ALL avatars referencing that Reddit_Account to Phase 0 within the same task execution that detected the shadowban.
3. WHEN a Reddit_Account is detected as suspended (HTTP 404 or 403 from Reddit API), THE System SHALL freeze ALL avatars referencing that Reddit_Account within the same task execution that detected the suspension.
4. WHEN a Reddit_Account recovers from shadowban (health check detects profile visibility restored), THE System SHALL clear the shadowban flag on the Reddit_Account and allow all referencing avatars to graduate from Phase 0 through standard phase graduation criteria (account age ≥ 7 days, karma ≥ 10, ≥ 3 posted comments, 0 deleted).
5. THE System SHALL store health check results (last_health_check, health_status, health_status_changed_at, health_check_details, consecutive_check_failures) on the Reddit_Account record, keyed by the unique reddit_username.
6. IF a Reddit_Account accumulates 3 or more consecutive_check_failures (network errors, timeouts, or inconclusive results), THEN THE System SHALL retain the Reddit_Account's previous health_status unchanged and emit an activity event indicating repeated check failures.

### Requirement 5: Niche Compatibility Constraint

**User Story:** As a platform operator, I want to enforce that avatars sharing the same Reddit account have compatible industries or niches, so that the Reddit username maintains a coherent public persona.

#### Acceptance Criteria

1. WHEN an operator assigns an avatar to a Reddit_Account that already has one or more avatars assigned, THE System SHALL validate that the new avatar's industry value is compatible with the industry values of all existing avatars on that account by consulting the compatibility matrix.
2. IF the new avatar's industry is not present in any compatible pair with at least one existing avatar's industry on the target Reddit_Account, THEN THE System SHALL reject the assignment, preserve the current account-avatar assignments unchanged, and return an error indicating the new avatar's industry and each conflicting existing avatar's industry.
3. IF the new avatar's industry field is null at the time of assignment, THEN THE System SHALL reject the assignment and return an error indicating that an industry value is required before account assignment.
4. THE System SHALL provide a configurable compatibility matrix stored as JSONB (on the Reddit_Account record or as a system-level setting) defining which industry pairs are compatible, where each entry specifies exactly two industry values that may coexist on the same account.
5. WHERE no compatibility matrix is configured for the target Reddit_Account and no system-level compatibility matrix exists, THE System SHALL require all avatars on a shared Reddit_Account to have identical industry values.
6. WHEN the compatibility matrix is updated, THE System SHALL validate that all existing avatar-account assignments remain compatible under the new matrix and return a list of violations without modifying existing assignments.

### Requirement 6: Executor Routing

**User Story:** As a platform operator, I want one executor (browser session) to serve all avatars on the same Reddit account, so that extension tasks from different clients are posted through a single authenticated session.

#### Acceptance Criteria

1. THE System SHALL route all execution tasks for avatars sharing the same Reddit_Account to the same Executor (browser session), using `reddit_username` as the grouping key.
2. THE System SHALL create execution tasks per Avatar (preserving the avatar's client-specific generated content and target thread) but dispatch them through the single executor session authenticated as that `reddit_username`.
3. WHEN the browser extension polls for tasks, THE System SHALL return all pending tasks for every avatar whose Reddit_Account matches the executor's authenticated Reddit username, regardless of which client owns each avatar.
4. THE System SHALL store executor configuration (executor_email, executor_email_verified, delivery_channel) on the Reddit_Account rather than on individual Avatar records, so that all avatars sharing an account inherit the same executor settings.
5. IF multiple avatars sharing a Reddit_Account have tasks scheduled within the same 3-minute minimum posting interval, THEN THE System SHALL serialize execution by queuing tasks sequentially and respecting the per-account minimum interval between posts.

### Requirement 7: Shared Karma

**User Story:** As a platform operator, I want karma values to be tracked at the Reddit account level so that all avatars sharing an account see the same karma data, while performance metrics remain per-avatar.

#### Acceptance Criteria

1. THE Reddit_Account SHALL own karma values (karma_post, karma_comment, reddit_karma_post, reddit_karma_comment).
2. WHEN the karma tracking task fetches karma data from Reddit via PRAW, THE System SHALL execute one PRAW call per Reddit_Account (not per Avatar), and update karma fields on the Reddit_Account record.
3. THE System SHALL make Reddit_Account karma values accessible from any Avatar referencing the account via a SQLAlchemy relationship (e.g., `avatar.reddit_account.karma_comment`).
4. THE System SHALL maintain per-avatar performance metrics (which comment got how much karma, removal rate, engagement velocity) on the existing per-avatar models (KarmaSnapshot linked to CommentDraft, PerformanceMetric linked to Avatar).
5. WHEN multiple avatars share a Reddit_Account, THE System SHALL attribute each KarmaSnapshot to the specific Avatar whose CommentDraft generated the posted comment, not to all avatars on the account.

### Requirement 8: Phase Independence

**User Story:** As a platform operator, I want each avatar to progress through warming phases independently even when sharing a Reddit account, so that one client's phase 3 avatar does not constrain another client's phase 2 avatar on the same account.

#### Acceptance Criteria

1. THE System SHALL maintain `warming_phase` on the Avatar record (not on Reddit_Account).
2. WHEN the phase evaluator runs for an avatar, THE System SHALL assess phase promotion criteria using account-level karma (from Reddit_Account) combined with avatar-level metrics (survival rate over 7-day window, posted comment count).
3. WHILE an Avatar is in Phase 1, THE System SHALL generate only hobby content for that avatar, regardless of other avatars on the same Reddit_Account being in Phase 3.
4. IF the Reddit_Account's CQS level drops to "lowest", THEN THE System SHALL set the daily comment budget to zero for ALL avatars linked to that account, while continuing to run phase evaluation for those avatars at the scheduled 06:00 cycle.
5. IF the Reddit_Account's karma is below the promotion threshold required for an avatar's target phase (100 for Phase 1→2, 500 for Phase 2→3), THEN THE System SHALL block promotion for that avatar regardless of individual performance metrics.
6. IF an Avatar has no associated Reddit_Account record, THEN THE System SHALL skip phase promotion evaluation for that avatar and emit an activity event indicating the missing account association.

### Requirement 9: Backward Compatibility

**User Story:** As a platform operator, I want existing single-client avatars to continue working without modification, so that the multi-client feature is opt-in and does not disrupt current operations.

#### Acceptance Criteria

1. THE System SHALL support 1:1 Reddit_Account-to-Avatar mapping as the default configuration.
2. WHEN the Alembic migration runs, THE System SHALL create one `reddit_accounts` row per distinct `reddit_username` in the existing `avatars` table, copying all account-level fields from the avatar into the new row, and setting `reddit_account_id` FK on the avatar record — all within a single transaction.
3. WHILE a Reddit_Account has exactly one Avatar referencing it, THE System SHALL behave identically to the current system: no shared scheduling constraints, no budget_share validation (budget_share defaults to daily_cap), and no niche compatibility checks.
4. THE System SHALL NOT require any manual configuration changes for existing single-avatar setups after migration (pipeline continues operating immediately).
5. WHEN an Avatar's `reddit_account_id` is NULL (edge case during migration), THE System SHALL fall back to reading account-level fields directly from the Avatar's deprecated columns until the FK is populated.
6. THE migration SHALL be reversible: a downgrade migration SHALL restore account-level columns on Avatar and drop the `reddit_accounts` table without data loss.

### Requirement 10: Admin UI for Account Management

**User Story:** As a platform operator, I want an admin interface to assign multiple avatars to a Reddit account, view shared account health, and manage budget allocation, so that I can operationally manage multi-client accounts.

#### Acceptance Criteria

1. THE System SHALL provide an admin page at `/admin/reddit-accounts` showing all Reddit_Account records in a table with columns: reddit_username, assigned avatars (list of display_names with client badge), health_status (color-coded), total karma, daily_cap, and remaining budget for the current day.
2. WHEN an operator assigns a new avatar to a Reddit_Account via the admin UI, THE System SHALL enforce budget_share validation (sum ≤ daily_cap) and niche compatibility checks before saving.
3. IF budget_share validation fails or niche compatibility check fails, THEN THE System SHALL reject the assignment and display an inline error message indicating which validation failed and the specific values causing the failure.
4. THE System SHALL display a merged timeline view showing interleaved EPG slots from all avatars assigned to a shared Reddit_Account, ordered by scheduled_at ascending, with each slot showing: avatar display_name, subreddit, scheduled time, slot status, and a color per-client.
5. WHEN a Reddit_Account's health_status changes, THE System SHALL display the cascading impact on all referencing avatars (current phase, frozen status, pipeline impact).
6. THE System SHALL provide inline-editable controls (HTMX partial swap) to adjust daily_cap, budget_share per avatar, and niche compatibility settings for each Reddit_Account.

# Requirements Document

## Introduction

Рефакторинг модели данных сабреддитов: переход от привязки сабреддита к одному клиенту (`ClientSubreddit.client_id`) к общему реестру сабреддитов с таблицей связи many-to-many. Это позволит нескольким клиентам мониторить один и тот же сабреддит без дублирования скрейпинга — данные скрейпятся один раз и расшариваются между всеми подписанными клиентами.

## Glossary

- **Subreddit**: Центральная сущность реестра — запись о Reddit-сообществе с метаданными скрейпинга (имя, last_scraped_at, is_active). Не привязана к конкретному клиенту.
- **Client_Subreddit_Assignment**: Таблица связи (many-to-many) между Client и Subreddit. Содержит тип мониторинга (professional/hobby) и статус активности для конкретного клиента.
- **Scraper**: Компонент системы (Celery tasks), выполняющий скрейпинг Reddit-постов из сабреддитов.
- **Scoring_Pipeline**: Компонент системы, выполняющий оценку (scoring) тредов по ключевым словам конкретного клиента.
- **RedditThread**: Запись о Reddit-посте. После рефакторинга привязывается к Subreddit (не к клиенту), а оценка (scoring) остаётся per-client.

## Requirements

### Requirement 1: Core Subreddit Registry Table

**User Story:** As an admin, I want subreddits to exist as independent entities in the system, so that multiple clients can share the same subreddit without data duplication.

#### Acceptance Criteria

1. THE System SHALL store each subreddit as a unique record in the `subreddits` table with fields: id (UUID PK), subreddit_name (unique, case-insensitive), is_active (boolean), created_at (timestamp), last_scraped_at (nullable timestamp).
2. THE System SHALL enforce a unique constraint on `lower(subreddit_name)` in the `subreddits` table to prevent duplicate entries for the same Reddit community.
3. WHEN a subreddit record is created, THE System SHALL normalize the subreddit_name to its canonical form (lowercase comparison, original casing preserved).

### Requirement 2: Many-to-Many Assignment Table

**User Story:** As an admin, I want to assign the same subreddit to multiple clients, so that each client can monitor communities relevant to their business without blocking other clients.

#### Acceptance Criteria

1. THE System SHALL maintain a `client_subreddit_assignments` table with fields: id (UUID PK), client_id (FK to clients), subreddit_id (FK to subreddits), type (professional/hobby), is_active (boolean), created_at (timestamp).
2. THE System SHALL enforce a unique constraint on (client_id, subreddit_id) to prevent duplicate assignments of the same subreddit to the same client.
3. WHEN an admin assigns a subreddit to a client, THE System SHALL create the Subreddit record if it does not already exist, then create the Client_Subreddit_Assignment record.
4. WHEN an admin removes a subreddit from a client, THE System SHALL set is_active to false on the Client_Subreddit_Assignment record without affecting other clients' assignments or the Subreddit record itself.

### Requirement 3: Shared Scraping (Scrape Once, Share Data)

**User Story:** As a system operator, I want each subreddit to be scraped only once regardless of how many clients monitor it, so that Reddit API rate limits are used efficiently.

#### Acceptance Criteria

1. THE Scraper SHALL select subreddits for scraping from the `subreddits` table based on last_scraped_at, independent of which clients are assigned to them.
2. THE Scraper SHALL update last_scraped_at on the Subreddit record after a successful scrape.
3. WHEN a subreddit is scraped, THE Scraper SHALL store RedditThread records without a client_id foreign key — threads belong to the subreddit, not to a specific client.
4. THE Scraper SHALL only scrape subreddits that have at least one active Client_Subreddit_Assignment.

### Requirement 4: Per-Client Scoring Separation

**User Story:** As a client, I want my thread scoring to use my own keywords and relevance criteria, so that shared subreddit data is evaluated in the context of my business.

#### Acceptance Criteria

1. THE Scoring_Pipeline SHALL create per-client scoring records that reference both the RedditThread and the client_id.
2. WHEN a new thread is scraped from a shared subreddit, THE Scoring_Pipeline SHALL score it separately for each client that has an active assignment to that subreddit.
3. THE System SHALL allow different clients to have different scores (relevance, quality, strategic, composite, tag) for the same RedditThread.

### Requirement 5: RedditThread Model Refactoring

**User Story:** As a developer, I want RedditThread to reference the subreddit registry instead of a client, so that thread data is not duplicated across clients monitoring the same subreddit.

#### Acceptance Criteria

1. THE System SHALL replace the `client_id` FK on RedditThread with a `subreddit_id` FK referencing the `subreddits` table.
2. THE System SHALL retain the `subreddit` text field on RedditThread for denormalized display purposes.
3. THE System SHALL remove per-client scoring fields (tag, relevance, quality, strategic, composite, intent, scoring_reasoning) from RedditThread and move them to a separate `thread_scores` table with (thread_id, client_id) composite reference.
4. THE System SHALL maintain the unique constraint on `reddit_native_id` to prevent duplicate thread records.

### Requirement 6: Migration of Existing Data

**User Story:** As a system operator, I want existing data to be migrated to the new schema without data loss, so that the transition is seamless.

#### Acceptance Criteria

1. WHEN the migration runs, THE System SHALL create a Subreddit record for each distinct `subreddit_name` found in the existing `client_subreddits` table.
2. WHEN the migration runs, THE System SHALL create Client_Subreddit_Assignment records preserving the existing client-to-subreddit relationships, types, and active statuses.
3. WHEN the migration runs, THE System SHALL populate `subreddit_id` on existing RedditThread records by matching the `subreddit` text field to the new Subreddit registry.
4. WHEN the migration runs, THE System SHALL migrate existing scoring fields from RedditThread into the new `thread_scores` table, associating them with the original client_id.
5. IF the migration encounters a RedditThread with no matching Subreddit record, THEN THE System SHALL create the missing Subreddit record before linking.

### Requirement 7: Admin API Compatibility

**User Story:** As an admin, I want the subreddit management UI to continue working after the refactoring, so that I can add/remove subreddits for clients without disruption.

#### Acceptance Criteria

1. WHEN an admin adds a subreddit to a client, THE System SHALL allow the operation even if the subreddit is already assigned to another client.
2. WHEN an admin lists subreddits for a client, THE System SHALL return only the subreddits assigned to that client with their assignment-level is_active status.
3. THE System SHALL remove the old global uniqueness check that prevented the same subreddit from being active for more than one client.
4. WHEN an admin deactivates a subreddit for a client, THE System SHALL only deactivate that client's assignment without affecting the Subreddit record or other clients' assignments.

### Requirement 8: Scrape Queue Compatibility

**User Story:** As a system operator, I want the queue_ticker to work with the new shared model, so that scraping continues to function correctly.

#### Acceptance Criteria

1. THE Scraper SHALL query the `subreddits` table (not client_subreddit_assignments) to determine which subreddit to scrape next, ordered by last_scraped_at.
2. THE Scraper SHALL only consider subreddits that have at least one active assignment (JOIN to client_subreddit_assignments WHERE is_active = true AND client.is_active = true).
3. THE Scraper SHALL no longer pass client_id to the scrape worker — scraping is subreddit-centric, not client-centric.
4. WHEN a scrape completes, THE System SHALL record ScrapeLog entries without requiring a single client_id (or with a nullable client_id since the subreddit is shared).

### Requirement 9: Deduplication of Scraped Threads

**User Story:** As a system operator, I want thread deduplication to work globally rather than per-client, so that the same Reddit post is never stored twice.

#### Acceptance Criteria

1. THE Scraper SHALL deduplicate posts by `reddit_native_id` globally across the entire `reddit_threads` table, not per-client.
2. WHEN a post already exists in the system, THE Scraper SHALL skip it regardless of which clients are assigned to that subreddit.

# Requirements Document

## Introduction

The admin threads page (`/admin/threads`) displays scraped Reddit threads with metadata like title, subreddit, score, and author. Currently, the `author` field is a plain username string with no additional context. The operator has no way to assess who they're engaging with — whether the author is a high-karma authority in the subreddit, a brand-new throwaway account, or a suspended user.

Author Intelligence adds a cached profile layer for thread authors, fetched via PRAW from the Reddit API. This gives the operator visibility into author karma, account age, active subreddits, and account status — enabling better decisions about which threads to prioritize for engagement.

## Glossary

- **Author_Cache**: The `reddit_authors` database table that stores cached Reddit profile data for thread authors.
- **Author_Intel_Service**: The service module (`app/services/author_intel.py`) responsible for fetching, caching, and retrieving author profile data.
- **Threads_Page**: The admin threads page at `/admin/threads` displaying scraped Reddit threads.
- **PRAW_Client**: The Reddit API client (PRAW library) used to fetch author profile data.
- **Author_Profile**: The set of cached data for a Reddit author: karma, account age, top subreddits, and account status.
- **Staleness_Threshold**: The maximum age of cached author data before it is considered stale and eligible for re-fetch (7 days).
- **Rate_Limiter**: The mechanism that enforces a minimum delay between Reddit API calls to stay within rate limits.
- **Author_Popover**: A UI component that displays detailed author information when the operator clicks an author name in the threads table.

## Requirements

### Requirement 1: Author Data Cache Model

**User Story:** As an operator, I want author profile data to be stored in the database, so that the threads page loads quickly without hitting the Reddit API on every page view.

#### Acceptance Criteria

1. THE Author_Cache SHALL store the following fields for each author: `username` (unique string), `karma_comment` (integer), `karma_post` (integer), `account_created_at` (datetime or null), `top_subreddits` (JSONB list of objects with subreddit name and karma), `is_suspended` (boolean), `is_deleted` (boolean), `fetched_at` (datetime), and `created_at` (datetime).
2. THE Author_Cache SHALL enforce a unique constraint on the `username` field.
3. THE Author_Cache SHALL index the `fetched_at` column to support efficient staleness queries.
4. WHEN an author profile is fetched successfully, THE Author_Intel_Service SHALL upsert the Author_Cache record with the new data and set `fetched_at` to the current UTC timestamp.
5. WHEN an author profile already exists in the Author_Cache with `fetched_at` less than 7 days old, THE Author_Intel_Service SHALL return the cached data without making a Reddit API call.

### Requirement 2: Fetch Author Profile from Reddit API

**User Story:** As an operator, I want the system to fetch real author data from Reddit, so that I can see accurate karma, account age, and activity information.

#### Acceptance Criteria

1. WHEN a profile fetch is requested for a username, THE Author_Intel_Service SHALL use the PRAW_Client to retrieve the Reddit user's comment karma, post karma, account creation date, and suspension status.
2. THE Author_Intel_Service SHALL determine the author's top subreddits by analyzing up to 100 recent comments and aggregating karma by subreddit, storing the top 10 subreddits with their respective karma values.
3. IF the Reddit account does not exist or returns a 404 response, THEN THE Author_Intel_Service SHALL mark the Author_Cache record with `is_deleted` set to true and all numeric fields set to zero.
4. IF the Reddit account is suspended, THEN THE Author_Intel_Service SHALL mark the Author_Cache record with `is_suspended` set to true and store whatever karma data is available.
5. IF the PRAW_Client raises a network error or rate limit exception, THEN THE Author_Intel_Service SHALL log the error and SHALL NOT update the previously cached data.
6. THE Author_Intel_Service SHALL skip fetching for usernames matching `[deleted]`, `AutoModerator`, or any username starting with `[`.

### Requirement 3: Rate-Limited Batch Enrichment

**User Story:** As an operator, I want author data to be fetched in batches with rate limiting, so that the system stays within Reddit API limits and doesn't get throttled.

#### Acceptance Criteria

1. THE Author_Intel_Service SHALL enforce a minimum delay of 2 seconds between consecutive Reddit API calls when fetching author profiles.
2. WHEN a batch enrichment is triggered, THE Author_Intel_Service SHALL process authors sequentially with the 2-second delay, yielding a maximum throughput of 30 authors per minute.
3. WHEN a batch enrichment is triggered, THE Author_Intel_Service SHALL skip authors whose cached data is less than 7 days old.
4. WHEN a batch enrichment is triggered, THE Author_Intel_Service SHALL skip authors marked as `is_deleted` set to true.
5. IF a single author fetch fails during batch enrichment, THEN THE Author_Intel_Service SHALL log the error and continue processing the remaining authors.

### Requirement 4: On-Demand Author Fetch from UI

**User Story:** As an operator, I want to trigger an author profile fetch on demand, so that I can get fresh data for a specific author when I need it.

#### Acceptance Criteria

1. THE Admin API SHALL expose a `POST /admin/authors/{username}/refresh` endpoint that triggers a fresh fetch of the author's Reddit profile regardless of cache age.
2. WHEN the refresh endpoint is called, THE Author_Intel_Service SHALL fetch the author profile from Reddit and update the Author_Cache.
3. WHEN the refresh endpoint completes successfully, THE Admin API SHALL return the updated Author_Profile data as an HTML partial suitable for HTMX swap.
4. IF the username contains invalid characters or exceeds 20 characters, THEN THE Admin API SHALL return HTTP 400 with a descriptive error message.
5. THE refresh endpoint SHALL require superuser authentication.

### Requirement 5: Author Info Display in Threads Table

**User Story:** As an operator, I want to see key author information inline in the threads table, so that I can quickly assess author quality without leaving the page.

#### Acceptance Criteria

1. WHEN the Threads_Page renders a thread row, THE Threads_Page SHALL display the author's total karma (comment + post) as a compact badge next to the username if cached data exists.
2. WHEN cached author data does not exist for a thread's author, THE Threads_Page SHALL display only the username with no karma badge.
3. WHEN the author is marked as `is_suspended` in the Author_Cache, THE Threads_Page SHALL display a red "suspended" indicator next to the username.
4. WHEN the author is marked as `is_deleted` in the Author_Cache, THE Threads_Page SHALL display a gray "deleted" indicator next to the username.
5. THE Threads_Page SHALL format karma values using compact notation: values above 1000 displayed as "1.2k", values above 1000000 displayed as "1.2M".

### Requirement 6: Author Detail Popover

**User Story:** As an operator, I want to click an author name and see detailed profile information in a popover, so that I can make informed engagement decisions without navigating away.

#### Acceptance Criteria

1. WHEN the operator clicks an author name in the threads table, THE Threads_Page SHALL display an Author_Popover loaded via HTMX from the server.
2. THE Author_Popover SHALL display: username, comment karma, post karma, account age (formatted as years/months), top 5 subreddits with karma per subreddit, account status (active/suspended/deleted), last fetched timestamp, and a link to the Reddit profile.
3. THE Author_Popover SHALL include a "Refresh" button that triggers an on-demand fetch and updates the popover content in place.
4. WHEN cached data does not exist for the clicked author, THE Author_Popover SHALL display a "Fetch Profile" button that triggers the initial fetch and displays results upon completion.
5. WHILE a fetch is in progress, THE Author_Popover SHALL display a loading indicator.
6. THE Admin API SHALL expose a `GET /admin/authors/{username}/popover` endpoint that returns the Author_Popover as an HTML partial.

### Requirement 7: Background Enrichment After Scraping

**User Story:** As an operator, I want author profiles to be automatically enriched after new threads are scraped, so that author data is available by the time I review threads.

#### Acceptance Criteria

1. WHEN a scraping task completes and new threads are saved, THE system SHALL queue a background task to enrich the authors of the newly scraped threads.
2. THE background enrichment task SHALL collect all unique author usernames from the new threads, exclude those already cached within the Staleness_Threshold, and fetch the remaining profiles using the rate-limited batch process.
3. THE background enrichment task SHALL run with lower priority than scraping and scoring tasks to avoid competing for Reddit API rate limit budget.
4. WHEN the background enrichment task encounters a Reddit API rate limit response (HTTP 429), THE task SHALL pause for 60 seconds before resuming.
5. THE background enrichment task SHALL log the number of authors enriched and the number skipped (already cached or deleted) upon completion.

### Requirement 8: Staleness Indicator and Cache Management

**User Story:** As an operator, I want to know when author data is stale, so that I can decide whether to refresh it before making engagement decisions.

#### Acceptance Criteria

1. WHEN the Author_Popover displays cached data with `fetched_at` older than 7 days, THE Author_Popover SHALL display a "stale" warning indicator next to the last-fetched timestamp.
2. WHEN the Threads_Page displays an author karma badge with `fetched_at` older than 7 days, THE Threads_Page SHALL render the badge in a muted color to indicate staleness.
3. THE Author_Intel_Service SHALL provide a method to query all authors with stale data (fetched_at older than 7 days) for use by the background enrichment scheduler.

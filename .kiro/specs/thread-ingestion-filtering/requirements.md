# Requirements Document

## Introduction

Thread ingestion filtering ensures the scraping pipeline only accepts Reddit posts with meaningful plain-text content suitable for AI analysis. Posts that are primarily media (images, videos, galleries), external links, or lack substantive text body are skipped early in the pipeline, saving AI scoring costs and preventing low-quality threads from entering the review queue.

## Glossary

- **Scraping_Service**: The Reddit scraping module (`app/services/reddit.py`) that fetches posts from subreddits via PRAW and returns standardized post dicts.
- **Post_Filter**: The new filtering component that evaluates each scraped Reddit submission against text-quality rules before it enters the pipeline.
- **selftext**: The Reddit API field containing the text body of a self-post (user-authored text content). Empty string for link/media posts.
- **is_self**: A boolean Reddit API field. True when the post is a text-based self-post, False when the post links to an external URL.
- **post_hint**: A Reddit API field indicating the content type of a post (e.g., "image", "hosted:video", "rich:video", "link").
- **is_gallery**: A boolean Reddit API field. True when the post contains multiple images in a gallery format.
- **Skip_Reason**: A structured enum value indicating why a post was filtered out (e.g., empty_selftext, too_short, non_self_post, media_post, mostly_urls, deleted_or_removed).
- **MIN_SELF_TEXT_LENGTH**: The minimum character count (120) required for a post's selftext to be considered meaningful.
- **Filter_Result**: A structured object returned by the Post_Filter containing the pass/skip decision and, when skipped, the Skip_Reason.

## Requirements

### Requirement 1: Self-Post Gate

**User Story:** As a pipeline operator, I want the system to only process self-posts (text posts), so that link-only submissions never enter the AI scoring pipeline.

#### Acceptance Criteria

1. WHEN a scraped submission has `is_self` equal to False, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "non_self_post" without evaluating subsequent filter rules
2. WHEN a scraped submission has `is_self` equal to True, THE Post_Filter SHALL continue evaluating subsequent filter rules
3. IF the `is_self` field is null or absent on a scraped submission, THEN THE Post_Filter SHALL treat the submission as non-self and return a Filter_Result with status "skip" and Skip_Reason "non_self_post"

### Requirement 2: Deleted or Removed Post Detection

**User Story:** As a pipeline operator, I want deleted or removed posts to be skipped immediately, so that no AI resources are spent on content that no longer exists.

#### Acceptance Criteria

1. WHEN a submission's selftext equals "[deleted]", THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "deleted_or_removed"
2. WHEN a submission's selftext equals "[removed]", THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "deleted_or_removed"

### Requirement 3: Empty Selftext Detection

**User Story:** As a pipeline operator, I want posts with empty text bodies to be skipped, so that only posts with actual content reach the AI.

#### Acceptance Criteria

1. WHEN a submission's selftext is an empty string after stripping leading and trailing whitespace characters (spaces, tabs, newlines), THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "empty_selftext"
2. WHEN a submission's selftext is None or null, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "empty_selftext"

### Requirement 4: Minimum Text Length Enforcement

**User Story:** As a pipeline operator, I want posts with very short text bodies to be skipped, so that only posts with enough content for meaningful analysis are processed.

#### Acceptance Criteria

1. WHEN a submission's selftext length (after stripping leading and trailing whitespace, measured on the resulting string including internal whitespace) is less than MIN_SELF_TEXT_LENGTH (120 characters), THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "too_short"
2. WHEN a submission's selftext length (after whitespace trimming) is greater than or equal to MIN_SELF_TEXT_LENGTH, THE Post_Filter SHALL continue evaluating subsequent filter rules

### Requirement 5: Media Post Detection

**User Story:** As a pipeline operator, I want image, video, and gallery posts to be skipped, so that media-only content does not waste AI scoring resources.

#### Acceptance Criteria

1. WHEN a submission's post_hint is "image", THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
2. WHEN a submission's post_hint is "hosted:video", THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
3. WHEN a submission's post_hint is "rich:video", THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
4. WHEN a submission's post_hint is "link" and the submission's selftext field is empty or None, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
5. WHEN a submission's is_gallery field equals True, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
6. WHEN a submission's media field is not None and the submission's selftext field is empty or None, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
7. WHEN a submission's secure_media field is not None and the submission's selftext field is empty or None, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "media_post"
8. THE Post_Filter SHALL evaluate media detection conditions in criteria order (1 through 7) and return the Filter_Result on the first matching condition without evaluating remaining conditions

### Requirement 6: URL-Dominated Text Detection

**User Story:** As a pipeline operator, I want posts where the text body is mostly URLs to be skipped, so that posts lacking meaningful discussion text are excluded.

#### Acceptance Criteria

1. WHEN more than 50% of the non-whitespace characters in a submission's selftext are part of matched URL strings, THE Post_Filter SHALL return a Filter_Result with status "skip" and Skip_Reason "mostly_urls"
2. THE Post_Filter SHALL identify URLs by matching strings that begin with "http://" or "https://" and extend until the next whitespace character or end of text
3. WHEN calculating the URL character ratio, THE Post_Filter SHALL count all characters within each matched URL (including protocol, domain, path, query parameters, and fragment) as URL characters and divide by the total non-whitespace character count of the selftext

### Requirement 7: Accepted Post Processing

**User Story:** As a pipeline operator, I want posts that pass all filter rules to have their extracted text stored and forwarded as source content, so that downstream AI services receive clean text input.

#### Acceptance Criteria

1. WHEN a submission passes all filter rules, THE Post_Filter SHALL return a Filter_Result with status "pass" and no Skip_Reason value
2. WHEN a submission passes all filter rules, THE Scraping_Service SHALL include the submission's selftext verbatim (without truncation or sanitization) as the post_body field in the output dict
3. IF the submission's selftext is None after passing all filter rules, THEN THE Scraping_Service SHALL store an empty string as the post_body field in the output dict

### Requirement 8: Skip Reason Logging

**User Story:** As a pipeline operator, I want each skipped post to be logged with a clear reason, so that I can debug filtering behavior and audit what was excluded.

#### Acceptance Criteria

1. WHEN THE Post_Filter returns a Filter_Result with status "skip", THE Scraping_Service SHALL log a structured INFO-level message containing the submission ID, subreddit name, post title, and Skip_Reason as key=value pairs
2. THE Scraping_Service SHALL log skipped posts using the existing structured logging format via `get_logger`

### Requirement 9: Filter Evaluation Order

**User Story:** As a pipeline operator, I want filters to be evaluated in a defined order from cheapest to most expensive, so that the system short-circuits early on obvious non-text posts.

#### Acceptance Criteria

1. THE Post_Filter SHALL evaluate rules in the following fixed order: (1) is_self check, (2) deleted_or_removed check, (3) empty_selftext check, (4) minimum_length check, (5) media_post check, (6) mostly_urls check
2. WHEN a rule produces a "skip" result, THE Post_Filter SHALL return the Filter_Result with the Skip_Reason from that rule immediately without evaluating subsequent rules
3. WHEN a submission would fail multiple rules, THE Post_Filter SHALL return the Skip_Reason corresponding to the earliest-ordered failing rule

### Requirement 10: Filter Integration Point

**User Story:** As a pipeline operator, I want the filter to be applied inside the scrape_subreddit function before posts are returned to callers, so that all scraping tasks (professional, hobby, repurpose, shared) benefit from the filter.

#### Acceptance Criteria

1. THE Scraping_Service SHALL apply the Post_Filter to each submission inside the scrape_subreddit function after the existing stickied/age/locked/score filters and before adding the post to the results list
2. THE Scraping_Service SHALL emit a single structured INFO-level log line per scrape invocation that includes the count of posts filtered for each Skip_Reason that occurred at least once
3. IF the Post_Filter raises an unexpected exception for a submission, THEN THE Scraping_Service SHALL log the error at WARNING level with the submission ID, skip that submission, and continue processing remaining submissions without interrupting the scrape

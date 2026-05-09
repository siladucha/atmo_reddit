# Requirements Document

## Introduction

A comprehensive daily timeline for each avatar on the avatar detail page (`/admin/avatars/{id}`). The timeline shows every day from the avatar's creation to today, with daily activity counts (comments posted, hobby comments posted, posts created), karma earned per day, and key lifecycle events (phase transitions, system age). This replaces the limited "Karma — Last 30 Days" section with a full historical view on a dedicated "Timeline" tab.

## Glossary

- **Timeline_Service**: The backend service that aggregates daily activity and karma data for an avatar across its entire lifetime in the system.
- **Timeline_Tab**: A new tab on the avatar detail page that displays the daily timeline UI.
- **Day_Entry**: A single row in the timeline representing one calendar day, containing activity counts and karma totals.
- **Phase_Event**: An ActivityEvent record of type `phase_promotion`, `auto_downgrade`, or `phase_override` associated with a specific avatar.
- **Professional_Comment**: A CommentDraft with `status = "posted"`.
- **Hobby_Comment**: A HobbySubreddit record with `status = "posted"` linked to the avatar via `avatar_username`.
- **Post_Action**: A PostDraft with `status = "posted"` linked to the avatar via `avatar_id`.
- **Avatar_Age**: The number of days between the avatar's `created_at` date and today.

## Requirements

### Requirement 1: Timeline Data Aggregation

**User Story:** As an admin, I want to see daily activity and karma data for an avatar's entire lifetime, so that I can understand the avatar's full history at a glance.

#### Acceptance Criteria

1. WHEN the Timeline_Tab is loaded, THE Timeline_Service SHALL return a Day_Entry for every calendar day (UTC) from the avatar's `created_at` date to today (inclusive).
2. THE Timeline_Service SHALL include in each Day_Entry the count of Professional_Comments (CommentDraft records with status="posted") whose `posted_at` falls within that UTC day.
3. THE Timeline_Service SHALL include in each Day_Entry the count of Hobby_Comments (HobbySubreddit records with status="posted", matched by `avatar_username`) whose `created_at` falls within that UTC day.
4. THE Timeline_Service SHALL include in each Day_Entry the count of Post_Actions (PostDraft records with status="posted") whose `posted_at` falls within that UTC day.
5. THE Timeline_Service SHALL include in each Day_Entry the total karma earned from Professional_Comments posted on that day, calculated as the sum of `reddit_score` values, treating NULL `reddit_score` as 0.
6. THE Timeline_Service SHALL include in each Day_Entry the total karma earned from Post_Actions posted on that day, calculated as the sum of `reddit_score` values, treating NULL `reddit_score` as 0.
7. IF a Day_Entry has no activity and no karma, THEN THE Timeline_Service SHALL still include that day in the timeline with zero values for all counts and karma fields.
8. IF the avatar's `created_at` date is more than 3650 days (10 years) before today, THEN THE Timeline_Service SHALL return Day_Entries only for the most recent 3650 days.
9. WHEN the Timeline_Tab is loaded, THE Timeline_Service SHALL return the response within 3 seconds for timelines up to 3650 Day_Entries.

### Requirement 2: Phase Transition Events

**User Story:** As an admin, I want to see when and why the avatar's warming phase changed, so that I can understand the avatar's lifecycle progression.

#### Acceptance Criteria

1. THE Timeline_Service SHALL retrieve all Phase_Events associated with the avatar by filtering ActivityEvent records where `event_type` is in (`phase_promotion`, `auto_downgrade`, `phase_override`) and `event_metadata->>'avatar_id'` matches the avatar's ID, ordered by `created_at` ascending.
2. THE Timeline_Service SHALL include in each Phase_Event the event type (promotion, downgrade, or override), the previous phase (integer 1-3), the new phase (integer 1-3), and the `created_at` timestamp of the ActivityEvent record.
3. WHEN a Day_Entry corresponds to a day on which one or more Phase_Events occurred, THE Timeline_Tab SHALL display a distinct icon per event type (promotion, downgrade, override) adjacent to the Day_Entry row, showing one icon per Phase_Event if multiple transitions occurred on the same day.
4. IF the Phase_Event `event_metadata` contains a non-empty `trigger_reason` or `reason` field, THEN THE Timeline_Tab SHALL display that value as the phase transition reason alongside the visual marker.
5. IF the Phase_Event `event_metadata` does not contain a `trigger_reason` or `reason` field, or the field is empty, THEN THE Timeline_Tab SHALL display no reason text for that Phase_Event.

### Requirement 3: Avatar Age and Summary Statistics

**User Story:** As an admin, I want to see how long the avatar has been in the system and summary statistics, so that I can quickly assess the avatar's maturity.

#### Acceptance Criteria

1. THE Timeline_Tab SHALL display the Avatar_Age as the whole number of days between the avatar's `created_at` timestamp and the current date, positioned at the top of the timeline.
2. THE Timeline_Tab SHALL display the avatar's current warming_phase (1, 2, or 3) and the phase_changed_at date in YYYY-MM-DD format.
3. THE Timeline_Tab SHALL display total lifetime counts of items with status "posted": total Professional_Comments (CommentDraft), total Hobby_Comments (HobbySubreddit matched by avatar_username), and total Post_Actions (PostDraft).
4. THE Timeline_Tab SHALL display total lifetime karma as the sum of reddit_score from all posted CommentDraft records plus all posted PostDraft records belonging to the avatar, treating NULL reddit_score values as 0.
5. IF the avatar has zero posted items, THEN THE Timeline_Tab SHALL display 0 for each count and 0 for total karma.

### Requirement 4: Timeline UI Presentation

**User Story:** As an admin, I want the timeline to be visually clear and easy to scan, so that I can quickly identify active and inactive periods.

#### Acceptance Criteria

1. THE Timeline_Tab SHALL appear as a new tab labeled "Timeline" on the avatar detail page, positioned immediately after the "Performance" tab in the tab bar.
2. THE Timeline_Tab SHALL display Day_Entries in reverse chronological order (most recent day first).
3. WHEN a Day_Entry has activity (any count greater than zero), THE Timeline_Tab SHALL render that row with a lighter background (distinguishable from the default inactive-day row background) so that active days are identifiable without reading individual values.
4. THE Timeline_Tab SHALL display each Day_Entry as a single horizontal row containing: the date in YYYY-MM-DD format, professional comment count, hobby comment count, post count, and karma total — each in a fixed-width column.
5. WHILE the timeline contains more than 60 Day_Entries, THE Timeline_Tab SHALL paginate the entries displaying 60 Day_Entries per page with next/previous navigation controls visible above or below the list.
6. IF the timeline contains zero Day_Entries (avatar created today with no prior days), THEN THE Timeline_Tab SHALL display a message indicating no timeline data is available yet.

### Requirement 5: Timeline Data Loading

**User Story:** As an admin, I want the timeline to load efficiently without blocking the rest of the avatar detail page, so that I can navigate other tabs without delay.

#### Acceptance Criteria

1. WHEN the admin activates the Timeline tab on the avatar detail page, THE Timeline_Tab SHALL issue an HTMX request to load timeline content using the `hx-trigger="intersect once"` pattern consistent with the existing Analytics and Presence tabs.
2. WHILE the Timeline_Tab HTMX request is in flight, THE Timeline_Tab SHALL display a loading indicator and THE remaining page tabs and controls SHALL remain interactive.
3. IF the Timeline_Service query takes longer than 5 seconds, THEN THE Timeline_Tab SHALL display a timeout message indicating the data could not be loaded and SHALL present a retry button that re-issues the request.
4. IF the Timeline_Service returns a server error or the HTMX request fails due to a network error, THEN THE Timeline_Tab SHALL display an error message indicating the failure and SHALL present a retry button.
5. IF the avatar has no timeline data, THEN THE Timeline_Tab SHALL display an empty-state message indicating no activity has been recorded yet.
6. THE Timeline_Service SHALL return the aggregation query result within 2 seconds for avatars with up to 365 days of history and up to 10,000 activity records, querying on indexed columns (`avatar_id`, `status`, `posted_at`).

### Requirement 6: Hobby Comment Correlation

**User Story:** As an admin, I want hobby comments attributed to the correct day, so that the timeline accurately reflects daily activity.

#### Acceptance Criteria

1. THE Timeline_Service SHALL use the `created_at` field of HobbySubreddit records with `status = "posted"` to determine the UTC day a hobby comment was posted.
2. THE Timeline_Service SHALL filter HobbySubreddit records by matching `avatar_username` to the avatar's `reddit_username`.
3. IF a HobbySubreddit record has no `created_at` value, THEN THE Timeline_Service SHALL exclude it from the timeline count.

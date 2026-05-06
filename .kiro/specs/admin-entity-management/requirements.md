# Requirements Document

## Introduction

This feature extends the admin panel with two entity management capabilities:
1. Adding subreddits directly from the global `/admin/subreddits` page (with or without a client assignment).
2. Assigning free (unassigned) avatars to a client from the `/admin/avatars?client_id={id}` page.

Both features follow the existing HTMX modal pattern already used in the admin panel and integrate with the shared registry model (Subreddit + ClientSubredditAssignment) and the avatar multi-client assignment model (Avatar.client_ids array).

## Glossary

- **Admin_Panel**: The dark-themed administrative interface accessible at `/admin/*` routes, restricted to superusers.
- **Subreddit_Registry**: The shared `subreddits` table containing one record per unique subreddit name.
- **Subreddit_Assignment**: A `client_subreddit_assignments` record linking a client to a subreddit with type and active status.
- **Avatar**: A Reddit account entity in the `avatars` table with a `client_ids` array field supporting multi-client assignment.
- **Free_Avatar**: An avatar whose `client_ids` array is empty or null (not assigned to any client).
- **Subreddits_Page**: The global subreddits management page at `/admin/subreddits` showing all assignments across all clients.
- **Avatars_Page**: The admin avatars page at `/admin/avatars` with filter bar including client_id dropdown.
- **Add_Subreddit_Modal**: An HTMX-driven modal dialog for adding a new subreddit from the Subreddits_Page.
- **Assign_Avatar_Modal**: The existing HTMX-driven modal dialog for assigning available avatars to a client on the Avatars_Page.
- **Audit_Service**: The service responsible for recording admin actions in the audit log.

## Requirements

### Requirement 1: Add Subreddit Button on Global Subreddits Page

**User Story:** As an admin, I want to add new subreddits directly from the global subreddits page, so that I can manage subreddit assignments without navigating to individual client pages.

#### Acceptance Criteria

1. THE Subreddits_Page SHALL display an "Add Subreddit" button in the page header area.
2. WHEN the admin clicks the "Add Subreddit" button, THE Admin_Panel SHALL display the Add_Subreddit_Modal with a form containing: a subreddit name input, a type selector (professional/hobby), and an optional client dropdown.
3. THE Add_Subreddit_Modal SHALL populate the client dropdown with all active clients from the database, plus an empty option representing "no client" (growth/hobby subreddit).
4. WHEN the admin submits the form with a client selected, THE Admin_Panel SHALL create a Subreddit_Registry record (if not already existing) and a Subreddit_Assignment linking the subreddit to the selected client.
5. WHEN the admin submits the form without a client selected, THE Admin_Panel SHALL create a Subreddit_Registry record only (no Subreddit_Assignment), making the subreddit available for future assignment.
6. WHEN the admin submits the form with a valid subreddit name and a selected client, THE Admin_Panel SHALL trigger an immediate scrape of the subreddit for the assigned client.
7. IF the subreddit name is invalid (fewer than 3 characters, contains invalid characters), THEN THE Admin_Panel SHALL display a validation error message inside the modal without closing it.
8. IF the subreddit is already assigned to the selected client, THEN THE Admin_Panel SHALL display an error message indicating the duplicate assignment.
9. WHEN a subreddit is successfully added, THE Admin_Panel SHALL close the modal and refresh the subreddits table to show the new entry.
10. WHEN a subreddit is successfully added, THE Audit_Service SHALL log the action with the admin user ID, subreddit name, type, and client ID (if applicable).

### Requirement 2: Subreddit Name Validation

**User Story:** As an admin, I want subreddit names to be validated before submission, so that I avoid creating invalid registry entries.

#### Acceptance Criteria

1. THE Admin_Panel SHALL strip the `r/` prefix from the subreddit name input if the admin includes it.
2. THE Admin_Panel SHALL trim leading and trailing whitespace from the subreddit name input.
3. THE Admin_Panel SHALL validate that the subreddit name is at least 3 characters long after normalization.
4. THE Admin_Panel SHALL validate that the subreddit name contains only alphanumeric characters and underscores.
5. IF the subreddit name fails validation, THEN THE Admin_Panel SHALL display the specific validation error without submitting the form.

### Requirement 3: Assign Free Avatars to Client from Avatars Page

**User Story:** As an admin, I want to assign unassigned avatars to a client directly from the avatars page when filtering by that client, so that I can quickly expand a client's avatar pool.

#### Acceptance Criteria

1. WHILE the Avatars_Page is filtered by a specific client_id, THE Avatars_Page SHALL display the "Assign Existing Avatar" button (existing behavior, confirmed present).
2. WHEN the admin clicks the "Assign Existing Avatar" button, THE Admin_Panel SHALL load and display a modal listing all active avatars not currently assigned to the filtered client.
3. THE Assign_Avatar_Modal SHALL display each available avatar with its reddit_username, current karma (comment + post), and warming phase.
4. WHEN the admin selects an avatar and confirms assignment, THE Admin_Panel SHALL append the client_id to the selected avatar's `client_ids` array.
5. IF the avatar's `client_ids` array is null, THEN THE Admin_Panel SHALL initialize it as a new array containing the client_id.
6. WHEN an avatar is successfully assigned, THE Admin_Panel SHALL close the modal and refresh the avatars list to reflect the new assignment.
7. WHEN an avatar is successfully assigned, THE Audit_Service SHALL log the action with the admin user ID, avatar ID, avatar username, and target client ID.
8. THE Assign_Avatar_Modal SHALL support assigning multiple avatars in sequence without requiring the admin to reopen the modal for each one.

### Requirement 4: Avatar Assignment Idempotency

**User Story:** As an admin, I want the system to prevent duplicate avatar assignments, so that the client_ids array remains consistent.

#### Acceptance Criteria

1. IF the avatar is already assigned to the target client, THEN THE Admin_Panel SHALL skip the assignment and display an informational message.
2. THE Admin_Panel SHALL perform a duplicate check before modifying the avatar's `client_ids` array.
3. FOR ALL avatar assignment operations, THE Admin_Panel SHALL ensure the resulting `client_ids` array contains no duplicate entries.

### Requirement 5: Modal UI Consistency

**User Story:** As an admin, I want the new modals to match the existing admin panel design patterns, so that the interface remains consistent and familiar.

#### Acceptance Criteria

1. THE Add_Subreddit_Modal SHALL use the dark theme styling consistent with the existing Admin_Panel modals (bg-slate-800, border-slate-700, rounded-xl).
2. THE Add_Subreddit_Modal SHALL be dismissible by clicking the close button or clicking outside the modal overlay.
3. THE Add_Subreddit_Modal SHALL use HTMX for form submission and partial content updates without full page reload.
4. WHILE a form submission is in progress, THE Add_Subreddit_Modal SHALL display a loading indicator on the submit button.
5. THE Assign_Avatar_Modal SHALL display a search/filter input to help the admin find specific avatars when the list is long.

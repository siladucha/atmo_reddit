# Requirements Document

## Introduction

Cascade Soft Delete provides the admin with a unified mechanism to deactivate system entities (Client, Avatar, Subreddit) and automatically propagate the deactivation to dependent records. No data is physically removed from the database — all deletions are logical (soft delete via `is_active`/`active` flags or status transitions). The feature includes a confirmation UI showing cascade impact, audit logging, a filter to view inactive entities, and the ability to restore (undo) soft-deleted entities.

## Glossary

- **Admin**: The superuser operating the admin panel with full system access
- **Cascade_Delete_Service**: The backend service responsible for executing soft-delete operations and propagating deactivation to dependent entities
- **Admin_Panel**: The HTMX-based dark-themed admin interface at `/admin/*` routes
- **Soft_Delete**: Setting an entity's active flag to False (or transitioning status to "cancelled") without removing the database record
- **Restore**: Reversing a soft-delete by reactivating an entity and its eligible dependents
- **Impact_Summary**: A preview showing the count and types of dependent entities that will be affected by a cascade soft-delete
- **Client**: A business customer entity with `is_active` flag, linked to subreddit assignments, avatars, comment drafts, thread scores, and logs
- **Avatar**: A pre-warmed Reddit account entity with `active` flag and a `client_ids` array linking it to multiple clients
- **Subreddit**: A shared registry entity with `is_active` flag, linked to client assignments and threads
- **ClientSubredditAssignment**: A many-to-many link between Client and Subreddit with `is_active` flag
- **CommentDraft**: A generated comment with a `status` field (pending/approved/rejected/posted)
- **Audit_Logger**: The existing `audit.log_action()` service that records admin operations

## Requirements

### Requirement 1: Client Cascade Soft Delete

**User Story:** As an Admin, I want to soft-delete a client and have all dependent entities automatically deactivated, so that the client's data is preserved but no longer active in the system.

#### Acceptance Criteria

1. WHEN the Admin confirms a client soft-delete, THE Cascade_Delete_Service SHALL set the client's `is_active` field to False
2. WHEN a client is soft-deleted, THE Cascade_Delete_Service SHALL set `is_active` to False on all ClientSubredditAssignment records belonging to that client
3. WHEN a client is soft-deleted, THE Cascade_Delete_Service SHALL remove the client's ID from the `client_ids` array of all Avatar records that reference it
4. WHEN a client is soft-deleted, THE Cascade_Delete_Service SHALL set the `status` field to "cancelled" on all CommentDraft records belonging to that client where status is "pending" or "approved"
5. WHEN a client is soft-deleted, THE Cascade_Delete_Service SHALL preserve all ThreadScore, ActivityEvent, ScrapeLog, and AIUsageLog records without modification
6. WHEN a client is soft-deleted, THE Audit_Logger SHALL record a "cascade_delete" action with entity_type "client", the client ID, and a details object listing all affected entity counts

### Requirement 2: Avatar Cascade Soft Delete

**User Story:** As an Admin, I want to soft-delete an avatar and have its pending work cancelled, so that the avatar is deactivated while preserving all historical data.

#### Acceptance Criteria

1. WHEN the Admin confirms an avatar soft-delete, THE Cascade_Delete_Service SHALL set the avatar's `active` field to False
2. WHEN an avatar is soft-deleted, THE Cascade_Delete_Service SHALL set the `status` field to "cancelled" on all CommentDraft records belonging to that avatar where status is "pending" or "approved"
3. WHEN an avatar is soft-deleted, THE Cascade_Delete_Service SHALL preserve all ActivityEvent records and historical CommentDraft records (status "posted" or "rejected") without modification
4. WHEN an avatar is soft-deleted, THE Cascade_Delete_Service SHALL NOT remove the avatar's ID from any client's references
5. WHEN an avatar is soft-deleted, THE Audit_Logger SHALL record a "cascade_delete" action with entity_type "avatar", the avatar ID, and a details object listing all affected entity counts

### Requirement 3: Subreddit Cascade Soft Delete

**User Story:** As an Admin, I want to soft-delete a subreddit from the shared registry and have all client assignments deactivated, so that no new activity targets that subreddit while historical data is preserved.

#### Acceptance Criteria

1. WHEN the Admin confirms a subreddit soft-delete, THE Cascade_Delete_Service SHALL set the subreddit's `is_active` field to False
2. WHEN a subreddit is soft-deleted, THE Cascade_Delete_Service SHALL set `is_active` to False on all ClientSubredditAssignment records referencing that subreddit
3. WHEN a subreddit is soft-deleted, THE Cascade_Delete_Service SHALL preserve all RedditThread records linked to that subreddit without modification
4. WHEN a subreddit is soft-deleted, THE Audit_Logger SHALL record a "cascade_delete" action with entity_type "subreddit", the subreddit ID, and a details object listing all affected entity counts

### Requirement 4: Cascade Impact Preview

**User Story:** As an Admin, I want to see a summary of what will be affected before confirming a soft-delete, so that I can make an informed decision.

#### Acceptance Criteria

1. WHEN the Admin initiates a soft-delete action, THE Admin_Panel SHALL display a confirmation dialog showing the entity name and type
2. WHEN the confirmation dialog is displayed, THE Cascade_Delete_Service SHALL compute and return the count of each dependent entity type that will be affected
3. WHEN a client soft-delete is previewed, THE Impact_Summary SHALL display the count of subreddit assignments to deactivate, avatars to unlink, and comment drafts to cancel
4. WHEN an avatar soft-delete is previewed, THE Impact_Summary SHALL display the count of comment drafts to cancel
5. WHEN a subreddit soft-delete is previewed, THE Impact_Summary SHALL display the count of client assignments to deactivate
6. THE Admin_Panel SHALL require explicit confirmation (a confirm button click) before executing the cascade soft-delete

### Requirement 5: Delete Button on Entity Detail Pages

**User Story:** As an Admin, I want a clearly visible delete button on entity detail pages, so that I can initiate the soft-delete workflow from the entity I am viewing.

#### Acceptance Criteria

1. THE Admin_Panel SHALL display a "Delete" button on the Client detail page
2. THE Admin_Panel SHALL display a "Delete" button on the Avatar detail page
3. THE Admin_Panel SHALL display a "Delete" button on the Subreddit detail page
4. WHEN the Admin clicks the "Delete" button, THE Admin_Panel SHALL trigger the cascade impact preview (Requirement 4) before executing any changes
5. THE Admin_Panel SHALL style the "Delete" button with a destructive-action visual indicator (red color) consistent with the dark theme

### Requirement 6: View Inactive Entities

**User Story:** As an Admin, I want to filter entity lists to show deleted/inactive entities, so that I can review what has been deactivated and potentially restore items.

#### Acceptance Criteria

1. THE Admin_Panel SHALL provide a toggle filter on the Client list page to show inactive clients
2. THE Admin_Panel SHALL provide a toggle filter on the Avatar list page to show inactive avatars
3. THE Admin_Panel SHALL provide a toggle filter on the Subreddit list page to show inactive subreddits
4. WHEN the inactive filter is enabled, THE Admin_Panel SHALL display inactive entities with a visual indicator distinguishing them from active entities
5. THE Admin_Panel SHALL default to showing only active entities when the filter is not engaged

### Requirement 7: Restore (Undo Soft Delete)

**User Story:** As an Admin, I want to restore a previously soft-deleted entity, so that I can reactivate it if the deletion was a mistake or circumstances changed.

#### Acceptance Criteria

1. WHEN the Admin triggers a restore on a soft-deleted client, THE Cascade_Delete_Service SHALL set the client's `is_active` field to True
2. WHEN a client is restored, THE Cascade_Delete_Service SHALL set `is_active` to True on all ClientSubredditAssignment records that were deactivated as part of the original cascade delete
3. WHEN a client is restored, THE Cascade_Delete_Service SHALL NOT automatically re-add the client ID to avatar `client_ids` arrays (manual re-linking required)
4. WHEN a client is restored, THE Cascade_Delete_Service SHALL NOT automatically change cancelled CommentDraft records back to pending (drafts remain cancelled)
5. WHEN the Admin triggers a restore on a soft-deleted avatar, THE Cascade_Delete_Service SHALL set the avatar's `active` field to True
6. WHEN an avatar is restored, THE Cascade_Delete_Service SHALL NOT automatically change cancelled CommentDraft records back to pending
7. WHEN the Admin triggers a restore on a soft-deleted subreddit, THE Cascade_Delete_Service SHALL set the subreddit's `is_active` field to True
8. WHEN a subreddit is restored, THE Cascade_Delete_Service SHALL set `is_active` to True on all ClientSubredditAssignment records that were deactivated as part of the original cascade delete
9. WHEN any entity is restored, THE Audit_Logger SHALL record a "restore" action with the entity type, entity ID, and details of what was reactivated
10. THE Admin_Panel SHALL display a "Restore" button on inactive entity detail pages

### Requirement 8: Cascade Operation Atomicity

**User Story:** As an Admin, I want cascade operations to either fully succeed or fully roll back, so that the system never ends up in a partially-deactivated state.

#### Acceptance Criteria

1. THE Cascade_Delete_Service SHALL execute all steps of a cascade soft-delete within a single database transaction
2. IF any step of the cascade soft-delete fails, THEN THE Cascade_Delete_Service SHALL roll back all changes made during that operation
3. THE Cascade_Delete_Service SHALL execute all steps of a restore operation within a single database transaction
4. IF any step of the restore operation fails, THEN THE Cascade_Delete_Service SHALL roll back all changes made during that operation
5. IF a cascade operation fails, THEN THE Admin_Panel SHALL display an error message indicating the operation was not completed

### Requirement 9: Authorization

**User Story:** As the system owner, I want cascade delete and restore operations restricted to superusers, so that only authorized administrators can deactivate or reactivate entities.

#### Acceptance Criteria

1. THE Admin_Panel SHALL require the `require_superuser` dependency on all cascade delete API endpoints
2. THE Admin_Panel SHALL require the `require_superuser` dependency on all restore API endpoints
3. IF a non-superuser attempts a cascade delete or restore operation, THEN THE Admin_Panel SHALL return an HTTP 403 response

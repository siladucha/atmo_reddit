"""User role enum — defines access levels in the system."""

from enum import Enum


class UserRole(str, Enum):
    """System roles with increasing access levels.

    owner          — Full system access (Max). Infrastructure, kill switches, all settings.
    partner        — Business admin (Tzvi). All clients, onboarding, reports, user management.
                     Cannot modify system settings or kill switches.
    avatar_manager — Avatar lifecycle manager (Peredo). Full access to ALL avatars
                     (assigned and unassigned). Can freeze/unfreeze, override phase,
                     trigger health checks, build EPG, view/approve hobby drafts.
                     Cannot see client business data, system settings, or billing.
                     Access to admin panel (avatars + review queue).
    qa             — Cross-client reviewer (Jenny). Can review/approve/reject all clients.
                     Read-only access to client data. Can warm own avatars.
    client_admin   — B2B company administrator. Scoped to own client. Can manage team
                     (create/edit/deactivate client_manager and client_viewer users),
                     manage avatars, approve drafts, configure client-level settings.
    client_manager — B2B client contact. Scoped to own client. Can approve/reject,
                     add subreddits/keywords. Cannot manage avatars or system config.
    client_viewer  — B2B read-only observer. Scoped to own client. Dashboard + reports only.
    b2c_user       — Self-service user (future). One avatar, simplified UI.
                     Goal: "my brand is present on Reddit".
    """

    owner = "owner"
    partner = "partner"
    avatar_manager = "avatar_manager"
    qa = "qa"
    client_admin = "client_admin"
    client_manager = "client_manager"
    client_viewer = "client_viewer"
    b2c_user = "b2c_user"

    @property
    def is_internal(self) -> bool:
        """Returns True for internal team roles (owner, partner, avatar_manager, qa)."""
        return self in (UserRole.owner, UserRole.partner, UserRole.avatar_manager, UserRole.qa)

    @property
    def is_admin_level(self) -> bool:
        """Returns True for roles that can access the admin panel."""
        return self in (UserRole.owner, UserRole.partner, UserRole.avatar_manager)

    @property
    def can_review(self) -> bool:
        """Returns True for roles that can approve/reject comment drafts."""
        return self in (
            UserRole.owner,
            UserRole.partner,
            UserRole.avatar_manager,
            UserRole.qa,
            UserRole.client_admin,
            UserRole.client_manager,
        )

    @property
    def can_manage_clients(self) -> bool:
        """Returns True for roles that can create/edit clients."""
        return self in (UserRole.owner, UserRole.partner)

    @property
    def can_manage_avatars(self) -> bool:
        """Returns True for roles that can assign/freeze/configure avatars.

        For client_admin this is scoped to their own company's avatars.
        For avatar_manager this is scoped to unassigned avatars only.
        """
        return self in (UserRole.owner, UserRole.partner, UserRole.avatar_manager, UserRole.client_admin)

    @property
    def can_manage_system(self) -> bool:
        """Returns True for roles that can change kill switches and system settings."""
        return self == UserRole.owner

    @property
    def can_manage_users(self) -> bool:
        """Returns True for roles that can create/deactivate users."""
        return self in (UserRole.owner, UserRole.partner)

    @property
    def can_trigger_pipeline(self) -> bool:
        """Returns True for roles that can manually trigger pipeline runs."""
        return self in (UserRole.owner, UserRole.partner)

    @property
    def can_view_all_clients(self) -> bool:
        """Returns True for roles that can see all clients (not scoped to one)."""
        return self in (UserRole.owner, UserRole.partner, UserRole.qa)

    @property
    def can_manage_unassigned_avatars(self) -> bool:
        """Returns True for roles limited to unassigned (no-client) avatars only.

        NOTE: As of May 2026, avatar_manager has full access to ALL avatars
        (assigned and unassigned) for lifecycle management (warming, health, EPG).
        This property is kept for backward compat but always returns False now.
        """
        return False

    @property
    def can_warm_avatars(self) -> bool:
        """Returns True for roles that can own/warm personal avatars (farm)."""
        return self in (UserRole.owner, UserRole.partner, UserRole.avatar_manager, UserRole.qa)

    @property
    def can_manage_team(self) -> bool:
        """Returns True for roles that can manage team members within own company.

        client_admin can create/edit/deactivate client_manager and client_viewer
        users within their own company only.
        """
        return self == UserRole.client_admin

    @property
    def is_client_scoped(self) -> bool:
        """Returns True for roles scoped to a single client (own company).

        These roles use User.client_id for single-company scoping and cannot
        access data belonging to other clients.
        """
        return self in (
            UserRole.client_admin,
            UserRole.client_manager,
            UserRole.client_viewer,
            UserRole.b2c_user,
        )

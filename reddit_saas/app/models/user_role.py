"""User role enum — defines access levels in the system."""

from enum import Enum


class UserRole(str, Enum):
    """System roles with increasing access levels.

    owner          — Full system access (Max). Infrastructure, kill switches, all settings.
    partner        — Business admin (Tzvi). All clients, onboarding, reports, user management.
                     Cannot modify system settings or kill switches.
    qa             — Cross-client reviewer (Jenny). Can review/approve/reject all clients.
                     Read-only access to client data. Can warm own avatars.
    client_manager — B2B client contact. Scoped to own client. Can approve/reject,
                     add subreddits/keywords. Cannot manage avatars or system config.
    client_viewer  — B2B read-only observer. Scoped to own client. Dashboard + reports only.
    b2c_user       — Self-service user (future). One avatar, simplified UI.
                     Goal: "my brand is present on Reddit".
    """

    owner = "owner"
    partner = "partner"
    qa = "qa"
    client_manager = "client_manager"
    client_viewer = "client_viewer"
    b2c_user = "b2c_user"

    @property
    def is_internal(self) -> bool:
        """Returns True for internal team roles (owner, partner, qa)."""
        return self in (UserRole.owner, UserRole.partner, UserRole.qa)

    @property
    def is_admin_level(self) -> bool:
        """Returns True for roles that can access the admin panel."""
        return self in (UserRole.owner, UserRole.partner)

    @property
    def can_review(self) -> bool:
        """Returns True for roles that can approve/reject comment drafts."""
        return self in (
            UserRole.owner,
            UserRole.partner,
            UserRole.qa,
            UserRole.client_manager,
        )

    @property
    def can_manage_clients(self) -> bool:
        """Returns True for roles that can create/edit clients."""
        return self in (UserRole.owner, UserRole.partner)

    @property
    def can_manage_avatars(self) -> bool:
        """Returns True for roles that can assign/freeze/configure avatars."""
        return self in (UserRole.owner, UserRole.partner)

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
    def can_warm_avatars(self) -> bool:
        """Returns True for roles that can own/warm personal avatars (farm)."""
        return self in (UserRole.owner, UserRole.partner, UserRole.qa)

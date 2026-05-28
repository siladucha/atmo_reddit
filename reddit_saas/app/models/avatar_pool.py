"""Avatar pool classification — determines avatar's operational category."""

import enum


class AvatarPool(str, enum.Enum):
    """Pool determines the avatar's operational category, independent of warming phase.

    - b2b: Working avatars assigned to B2B clients (current default)
    - b2c: Avatars for self-service B2C users (future)
    - mentor: Pre-warmed high-karma accounts, excluded from all automated pipelines
    - warm: On warming/aging, not yet assigned to any client
    """

    b2b = "b2b"
    b2c = "b2c"
    mentor = "mentor"
    warm = "warm"

    @property
    def is_pipeline_eligible(self) -> bool:
        """Whether avatars in this pool can participate in automated pipelines."""
        return self in (AvatarPool.b2b, AvatarPool.b2c)

    @property
    def display_label(self) -> str:
        labels = {
            "b2b": "B2B Client",
            "b2c": "B2C Self-Service",
            "mentor": "Mentor (Pre-warmed)",
            "warm": "Warming",
        }
        return labels[self.value]

    @property
    def badge_color(self) -> str:
        """Tailwind color class for admin UI badges."""
        colors = {
            "b2b": "indigo",
            "b2c": "emerald",
            "mentor": "purple",
            "warm": "amber",
        }
        return colors[self.value]

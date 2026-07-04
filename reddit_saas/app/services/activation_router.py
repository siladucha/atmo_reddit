"""Risk-Aware Avatar Activation — ActivationRouter service.

Generates personalized activation routes that move avatars toward client target
subreddits through progressively riskier zones (safe → bridge → target).

Uses SubredditRiskProfile data for zone classification and
AvatarSubredditCompatibility for bridge discovery.

No LLM calls — purely DB-driven decisions. Route planning < 2s per avatar.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.services.transparency import record_activity_event

if TYPE_CHECKING:
    from app.models.avatar import Avatar
    from app.models.client import Client

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Zone Classification Thresholds
# ---------------------------------------------------------------------------

ZONE_THRESHOLDS = {
    "safe": (0, 25),       # risk_score 0-25
    "bridge": (26, 50),    # risk_score 26-50
    "target": (51, 80),    # risk_score 51-80
    "dangerous": (81, 100),  # risk_score 81-100 (blocked for Phase 0-1)
}

UNIVERSAL_SAFE_LIST = [
    "AskReddit", "CasualConversation", "TodayILearned",
    "NoStupidQuestions", "OutOfTheLoop", "ExplainLikeImFive",
    "AskMen", "AskWomen", "LifeProTips",
]

# Budget per (zone, phase) — max comments per day from this zone
ZONE_BUDGETS: dict[tuple[str, int], int] = {
    ("safe", 0): 1,
    ("safe", 1): 1,
    ("bridge", 0): 0,
    ("bridge", 1): 3,
    ("target", 0): 0,
    ("target", 1): 0,
}

# Max subs per zone in route
MAX_SUBS_PER_ZONE = 5
MAX_BRIDGE_SUBS = 8


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_hobby_names(raw: list | dict | None) -> list[str]:
    """Extract subreddit names from hobby_subreddits JSONB (list or dict format)."""
    if not raw:
        return []
    names: list[str] = []
    if isinstance(raw, dict):
        for sub_list in raw.values():
            if isinstance(sub_list, list):
                for s in sub_list:
                    if isinstance(s, str):
                        names.append(s.strip().removeprefix("r/"))
                    elif isinstance(s, dict):
                        n = s.get("subreddit") or s.get("name") or ""
                        if n:
                            names.append(n.strip().removeprefix("r/"))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                n = item.get("subreddit") or item.get("name") or ""
                if n:
                    names.append(n.strip().removeprefix("r/"))
            elif isinstance(item, str):
                names.append(item.strip().removeprefix("r/"))
    return [n for n in names if n]


class ActivationRouter:
    """Core routing service for Risk-Aware Avatar Activation."""

    def plan_route(
        self, db: Session, avatar: "Avatar", client: "Client | None"
    ) -> dict | None:
        """Generate activation route for avatar.

        Called on: avatar creation, demotion to Phase 0, client sub changes.
        Returns route dict (stored in avatar.activation_route), or None if routing disabled.
        """
        from app.services.settings import get_setting

        enabled = get_setting(db, "activation_routing_enabled")
        if enabled not in ("true", "True", "1"):
            return None

        target_subs = self._get_client_target_subs(db, client)
        bridge_subs = self._find_bridge_subs(db, avatar, target_subs)
        safe_subs = self._select_safe_subs(db, avatar)

        route = {
            "version": 1,
            "planned_at": _utcnow().isoformat(),
            "current_zone": "safe",
            "zone_entered_at": _utcnow().isoformat(),
            "safe_subs": safe_subs[:MAX_SUBS_PER_ZONE],
            "bridge_subs": bridge_subs[:MAX_BRIDGE_SUBS],
            "target_subs": target_subs[:MAX_SUBS_PER_ZONE],
            "graduation_history": [],
        }

        avatar.activation_route = route
        avatar.activation_zone = "safe"
        avatar.zone_entered_at = _utcnow()

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(avatar, "activation_route")
        db.commit()

        # Emit activity event
        client_id = None
        if client:
            client_id = client.id
        elif avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                pass

        record_activity_event(
            db,
            event_type="route_planned",
            message=f"Activation route planned for {avatar.reddit_username}: "
                    f"{len(safe_subs)} safe, {len(bridge_subs)} bridge, {len(target_subs)} target subs",
            client_id=client_id,
            metadata={
                "avatar": avatar.reddit_username,
                "safe_subs": safe_subs[:MAX_SUBS_PER_ZONE],
                "bridge_subs": bridge_subs[:MAX_BRIDGE_SUBS],
                "target_subs": target_subs[:MAX_SUBS_PER_ZONE],
            },
        )

        logger.info(
            "ACTIVATION_ROUTE | avatar=%s | zone=safe | safe=%d bridge=%d target=%d",
            avatar.reddit_username, len(safe_subs), len(bridge_subs), len(target_subs),
        )
        return route

    def get_current_zone_subs(self, avatar: "Avatar") -> list[str]:
        """Return subreddits for avatar's current zone.

        Falls back to hobby_subreddits if no route exists (backward compat).
        """
        route = avatar.activation_route
        if not route:
            return _extract_hobby_names(avatar.hobby_subreddits)

        zone = route.get("current_zone", "safe")
        return route.get(f"{zone}_subs", [])

    def get_zone_budget(self, avatar: "Avatar") -> int:
        """Get max daily comments for avatar's current zone + phase."""
        route = avatar.activation_route
        if not route:
            return 3  # legacy fallback

        zone = route.get("current_zone", "safe")
        phase = avatar.warming_phase
        return ZONE_BUDGETS.get((zone, phase), 0)

    def refresh_route(
        self, db: Session, avatar: "Avatar", client: "Client | None"
    ) -> dict | None:
        """Regenerate route (e.g. when client subs change or risk profiles update).

        Preserves current_zone and graduation_history.
        """
        from app.services.settings import get_setting

        enabled = get_setting(db, "activation_routing_enabled")
        if enabled not in ("true", "True", "1"):
            return None

        old_route = avatar.activation_route or {}
        current_zone = old_route.get("current_zone", "safe")
        history = old_route.get("graduation_history", [])

        target_subs = self._get_client_target_subs(db, client)
        bridge_subs = self._find_bridge_subs(db, avatar, target_subs)
        safe_subs = self._select_safe_subs(db, avatar)

        route = {
            "version": 1,
            "planned_at": _utcnow().isoformat(),
            "current_zone": current_zone,
            "zone_entered_at": old_route.get("zone_entered_at", _utcnow().isoformat()),
            "safe_subs": safe_subs[:MAX_SUBS_PER_ZONE],
            "bridge_subs": bridge_subs[:MAX_BRIDGE_SUBS],
            "target_subs": target_subs[:MAX_SUBS_PER_ZONE],
            "graduation_history": history,
        }

        avatar.activation_route = route
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(avatar, "activation_route")
        db.commit()

        record_activity_event(
            db,
            event_type="route_updated",
            message=f"Activation route refreshed for {avatar.reddit_username}",
            metadata={
                "avatar": avatar.reddit_username,
                "current_zone": current_zone,
                "bridge_subs": bridge_subs[:MAX_BRIDGE_SUBS],
                "target_subs": target_subs[:MAX_SUBS_PER_ZONE],
            },
        )
        return route

    def graduate(self, db: Session, avatar: "Avatar", new_zone: str) -> None:
        """Execute zone graduation (safe→bridge or bridge→target)."""
        route = avatar.activation_route
        if not route:
            return

        old_zone = route["current_zone"]
        route["current_zone"] = new_zone
        route["zone_entered_at"] = _utcnow().isoformat()
        route.setdefault("graduation_history", []).append({
            "from": old_zone,
            "to": new_zone,
            "at": _utcnow().isoformat(),
            "reason": "criteria_met",
        })

        avatar.activation_route = route
        avatar.activation_zone = new_zone
        avatar.zone_entered_at = _utcnow()

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(avatar, "activation_route")
        db.commit()

        client_id = None
        if avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                pass

        record_activity_event(
            db,
            event_type="zone_graduation",
            message=f"{avatar.reddit_username} graduated: {old_zone} → {new_zone}",
            client_id=client_id,
            metadata={
                "avatar": avatar.reddit_username,
                "from_zone": old_zone,
                "to_zone": new_zone,
            },
        )

        logger.info(
            "ZONE_GRADUATION | avatar=%s | %s → %s",
            avatar.reddit_username, old_zone, new_zone,
        )

    def demote_zone(self, db: Session, avatar: "Avatar", reason: str) -> None:
        """Demote to previous zone (bridge→safe or target→bridge)."""
        route = avatar.activation_route
        if not route:
            return

        current = route["current_zone"]
        if current == "bridge":
            new_zone = "safe"
        elif current == "target":
            new_zone = "bridge"
        else:
            return  # already in safe, can't demote further

        route["current_zone"] = new_zone
        route["zone_entered_at"] = _utcnow().isoformat()
        route.setdefault("graduation_history", []).append({
            "from": current,
            "to": new_zone,
            "at": _utcnow().isoformat(),
            "reason": f"demotion: {reason}",
        })

        avatar.activation_route = route
        avatar.activation_zone = new_zone
        avatar.zone_entered_at = _utcnow()

        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(avatar, "activation_route")
        db.commit()

        client_id = None
        if avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                pass

        record_activity_event(
            db,
            event_type="zone_demotion",
            message=f"{avatar.reddit_username} demoted: {current} → {new_zone} ({reason})",
            client_id=client_id,
            metadata={
                "avatar": avatar.reddit_username,
                "from_zone": current,
                "to_zone": new_zone,
                "reason": reason,
            },
        )

        logger.info(
            "ZONE_DEMOTION | avatar=%s | %s → %s | reason=%s",
            avatar.reddit_username, current, new_zone, reason,
        )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _get_client_target_subs(self, db: Session, client: "Client | None") -> list[str]:
        """Get client's assigned subreddits (target zone candidates)."""
        if not client:
            return []

        from app.models.subreddit import ClientSubredditAssignment, Subreddit

        rows = (
            db.query(Subreddit.subreddit_name)
            .join(
                ClientSubredditAssignment,
                ClientSubredditAssignment.subreddit_id == Subreddit.id,
            )
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .all()
        )
        return [row[0] for row in rows if row[0]]

    def _select_safe_subs(self, db: Session, avatar: "Avatar") -> list[str]:
        """Select safe zone subreddits.

        Uses SubredditRiskProfile (risk_score 0-25) + universal safe list.
        Prefers subs with existing compatibility scores.
        """
        from app.models.subreddit import Subreddit
        from app.models.subreddit_risk_profile import SubredditRiskProfile

        # Query subs with low risk score
        low_risk_subs = (
            db.query(Subreddit.subreddit_name)
            .join(SubredditRiskProfile, SubredditRiskProfile.subreddit_id == Subreddit.id)
            .filter(
                SubredditRiskProfile.risk_score <= 25,
                SubredditRiskProfile.risk_score.isnot(None),
            )
            .order_by(SubredditRiskProfile.risk_score.asc())
            .limit(10)
            .all()
        )
        low_risk_names = [row[0] for row in low_risk_subs if row[0]]

        # Combine with universal safe list, deduplicate
        combined = []
        seen = set()
        for name in low_risk_names + UNIVERSAL_SAFE_LIST:
            lower = name.lower()
            if lower not in seen:
                seen.add(lower)
                combined.append(name)

        # Also include avatar's hobby subs that have low risk
        hobby_names = _extract_hobby_names(avatar.hobby_subreddits)
        for name in hobby_names:
            lower = name.lower()
            if lower not in seen:
                seen.add(lower)
                combined.append(name)

        return combined[:MAX_SUBS_PER_ZONE]

    def _find_bridge_subs(
        self, db: Session, avatar: "Avatar", target_subs: list[str]
    ) -> list[str]:
        """Find bridge subreddits (risk 26-50, thematic proximity to targets).

        Strategy: find subs with moderate risk that the avatar has compatibility with.
        """
        from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility
        from app.models.subreddit import Subreddit
        from app.models.subreddit_risk_profile import SubredditRiskProfile

        if not target_subs:
            # No targets — use hobby subs as bridge
            return _extract_hobby_names(avatar.hobby_subreddits)[:MAX_BRIDGE_SUBS]

        target_lower = {s.lower() for s in target_subs}

        # Find subs with risk_score 26-50
        candidates = (
            db.query(Subreddit.subreddit_name, SubredditRiskProfile.risk_score)
            .join(SubredditRiskProfile, SubredditRiskProfile.subreddit_id == Subreddit.id)
            .filter(
                SubredditRiskProfile.risk_score.between(26, 50),
                SubredditRiskProfile.risk_score.isnot(None),
                sa_func.lower(Subreddit.subreddit_name).notin_(target_lower),
            )
            .order_by(SubredditRiskProfile.risk_score.asc())
            .limit(20)
            .all()
        )

        # Filter by compatibility (AvatarSubredditCompatibility uses subreddit_name, not FK)
        compat_records = (
            db.query(AvatarSubredditCompatibility.subreddit_name, AvatarSubredditCompatibility.score)
            .filter(
                AvatarSubredditCompatibility.avatar_id == avatar.id,
                AvatarSubredditCompatibility.score >= 50,
            )
            .all()
        )
        compat_subs = {r.subreddit_name.lower(): r.score for r in compat_records}

        # Prefer candidates that have compatibility data, then any moderate-risk subs
        bridges = []
        for row in candidates:
            name = row[0]
            if name and name.lower() in compat_subs:
                bridges.append(name)
        # Fill remaining with other moderate-risk subs (no compat data = still OK)
        for row in candidates:
            name = row[0]
            if name and name not in bridges:
                bridges.append(name)
            if len(bridges) >= MAX_BRIDGE_SUBS:
                break

        # If insufficient bridges, supplement with hobby subs
        if len(bridges) < 3:
            hobby_names = _extract_hobby_names(avatar.hobby_subreddits)
            seen = {b.lower() for b in bridges}
            for h in hobby_names:
                if h.lower() not in seen and h.lower() not in target_lower:
                    bridges.append(h)
                    seen.add(h.lower())
                if len(bridges) >= MAX_BRIDGE_SUBS:
                    break

        return bridges[:MAX_BRIDGE_SUBS]

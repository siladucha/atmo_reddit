"""Backfill activation routes for all existing Phase 0-1 avatars.

Usage:
    cd reddit_saas
    PYTHONPATH=. python _backfill_activation_routes.py

Idempotent: skips avatars that already have an activation_route.
Requires activation_routing_enabled=true in system_settings.
"""

import sys
import uuid

from app.database import SessionLocal
from app.models.avatar import Avatar
from app.models.client import Client
from app.services.activation_router import ActivationRouter
from app.services.settings import get_setting, set_setting


def main():
    db = SessionLocal()
    try:
        # Check (and optionally enable) the feature flag
        enabled = get_setting(db, "activation_routing_enabled")
        if enabled not in ("true", "True", "1"):
            print("activation_routing_enabled is not 'true'. Enabling temporarily for backfill...")
            set_setting(db, "activation_routing_enabled", "true")

        # Get all active Phase 0-1 avatars without activation_route
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.warming_phase <= 1,
                Avatar.pool.in_(["b2b", "b2c", "warm"]),
                Avatar.activation_route.is_(None),
            )
            .all()
        )

        print(f"Found {len(avatars)} Phase 0-1 avatars without activation_route")

        router = ActivationRouter()
        planned = 0
        errors = 0

        for avatar in avatars:
            try:
                client = None
                if avatar.client_ids:
                    try:
                        client = (
                            db.query(Client)
                            .filter(Client.id == uuid.UUID(avatar.client_ids[0]))
                            .first()
                        )
                    except (ValueError, TypeError, IndexError):
                        pass

                route = router.plan_route(db, avatar, client)
                if route:
                    planned += 1
                    zone_subs = route.get("safe_subs", [])
                    print(f"  ✓ {avatar.reddit_username}: safe={zone_subs}")
                else:
                    print(f"  - {avatar.reddit_username}: routing disabled or failed")

            except Exception as e:
                errors += 1
                print(f"  ✗ {avatar.reddit_username}: {e}")
                continue

        print(f"\nDone: {planned} routes planned, {errors} errors")

    finally:
        db.close()


if __name__ == "__main__":
    main()

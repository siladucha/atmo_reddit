# Design — Risk-Aware Avatar Activation

## Overview

The Risk-Aware Activation system adds a **zone layer** between avatar phases and subreddit selection. Instead of hardcoded safe lists, avatars receive a personalized route from safe → bridge → target subreddits based on risk profiles and thematic proximity.

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    EPG Portfolio Manager                  │
│                    (build_portfolio)                      │
└───────────────────────────┬─────────────────────────────┘
                            │ reads activation_route
                            │ for Phase 0-1 avatars
┌───────────────────────────▼─────────────────────────────┐
│              ActivationRouter (NEW)                       │
│                                                          │
│  plan_route(avatar, client) → ActivationRoute            │
│  get_current_zone(avatar) → Zone                         │
│  get_zone_subs(avatar) → list[str]                       │
│  refresh_route(avatar) → ActivationRoute                 │
└───────────────────────────┬─────────────────────────────┘
                            │ uses
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
SubredditRiskProfile   Compatibility      BridgeDiscovery
(risk_score 0-100)     (score 0-100)      (thematic matching)
```

---

## Data Model

### Avatar Model Addition

```python
# In app/models/avatar.py — new field
activation_route = mapped_column(JSONB, nullable=True, default=None)
# Structure:
# {
#   "version": 1,
#   "planned_at": "2026-06-28T10:00:00Z",
#   "current_zone": "safe" | "bridge" | "target",
#   "zone_entered_at": "2026-06-28T10:00:00Z",
#   "safe_subs": ["AskReddit", "CasualConversation", "TodayILearned"],
#   "bridge_subs": ["homelab", "linuxadmin", "selfhosted"],
#   "target_subs": ["sysadmin", "networking", "devops"],
#   "graduation_history": [
#     {"from": "safe", "to": "bridge", "at": "2026-07-05T06:00:00Z", "reason": "criteria_met"}
#   ]
# }
```

### Zone Classification Constants

```python
# In app/services/activation_router.py

ZONE_THRESHOLDS = {
    "safe": (0, 25),       # risk_score 0-25
    "bridge": (26, 50),    # risk_score 26-50
    "target": (51, 80),    # risk_score 51-80
    "dangerous": (81, 100) # risk_score 81-100 (blocked)
}

UNIVERSAL_SAFE_LIST = [
    "AskReddit", "CasualConversation", "TodayILearned",
    "NoStupidQuestions", "OutOfTheLoop", "ExplainLikeImFive",
    "AskMen", "AskWomen", "LifeProTips"
]

ZONE_BUDGETS = {
    # (zone, phase): max_comments_per_day
    ("safe", 0): 2,
    ("safe", 1): 1,
    ("bridge", 0): 1,
    ("bridge", 1): 3,
    ("target", 0): 0,
    ("target", 1): 0,
}

GRADUATION_CRITERIA = {
    "safe_to_bridge": {
        "min_karma": 10,
        "min_survival_rate": 0.90,
        "min_age_days": 7,
        "min_posted": 3,
        "max_deleted": 0,
        "cqs_not": "lowest",
    },
    "bridge_to_target": {
        "min_bridge_subs_with_karma": 2,
        "min_karma_per_bridge_sub": 15,
        "min_survival_rate": 0.85,
        "min_total_karma": 50,
        "min_compatibility_score": 60,
    }
}
```

---

## Service: ActivationRouter

**File:** `app/services/activation_router.py`

### Core Methods

```python
class ActivationRouter:
    
    def plan_route(self, db: Session, avatar: Avatar, client: Client) -> dict:
        """
        Generate activation route for avatar.
        Called on: avatar creation, demotion to Phase 0, client sub changes.
        Returns: route dict (stored in avatar.activation_route)
        """
        target_subs = self._get_client_target_subs(db, client)
        bridge_subs = self._find_bridge_subs(db, avatar, target_subs)
        safe_subs = self._select_safe_subs(db, avatar)
        
        route = {
            "version": 1,
            "planned_at": utcnow().isoformat(),
            "current_zone": "safe",
            "zone_entered_at": utcnow().isoformat(),
            "safe_subs": safe_subs[:5],
            "bridge_subs": bridge_subs[:8],
            "target_subs": [s for s in target_subs if self._is_eligible(db, avatar, s)],
            "graduation_history": []
        }
        
        avatar.activation_route = route
        db.commit()
        return route
    
    def get_current_zone_subs(self, avatar: Avatar) -> list[str]:
        """Return subreddits for avatar's current zone."""
        route = avatar.activation_route
        if not route:
            return avatar.hobby_subreddits or []  # legacy fallback
        
        zone = route.get("current_zone", "safe")
        return route.get(f"{zone}_subs", [])
    
    def evaluate_graduation(self, db: Session, avatar: Avatar) -> str | None:
        """
        Check if avatar qualifies for zone graduation.
        Returns: new zone name if graduating, None otherwise.
        Called daily at 06:00.
        """
        route = avatar.activation_route
        if not route:
            return None
        
        current = route["current_zone"]
        
        if current == "safe":
            if self._meets_safe_to_bridge(db, avatar):
                return "bridge"
        elif current == "bridge":
            if self._meets_bridge_to_target(db, avatar):
                return "target"
        
        return None
    
    def graduate(self, db: Session, avatar: Avatar, new_zone: str):
        """Execute zone graduation."""
        route = avatar.activation_route
        old_zone = route["current_zone"]
        
        route["current_zone"] = new_zone
        route["zone_entered_at"] = utcnow().isoformat()
        route["graduation_history"].append({
            "from": old_zone,
            "to": new_zone,
            "at": utcnow().isoformat(),
            "reason": "criteria_met"
        })
        
        avatar.activation_route = route
        flag_modified(avatar, "activation_route")
        db.commit()
        
        # Emit activity event
        emit_activity_event(db, avatar, "zone_graduation", {
            "from_zone": old_zone, "to_zone": new_zone
        })
    
    def demote_zone(self, db: Session, avatar: Avatar, reason: str):
        """Demote to previous zone (bridge→safe)."""
        route = avatar.activation_route
        current = route["current_zone"]
        
        if current == "bridge":
            route["current_zone"] = "safe"
        elif current == "target":
            route["current_zone"] = "bridge"
        
        route["zone_entered_at"] = utcnow().isoformat()
        route["graduation_history"].append({
            "from": current,
            "to": route["current_zone"],
            "at": utcnow().isoformat(),
            "reason": f"demotion: {reason}"
        })
        
        avatar.activation_route = route
        flag_modified(avatar, "activation_route")
        db.commit()
```

### Bridge Discovery Logic

```python
def _find_bridge_subs(self, db: Session, avatar: Avatar, target_subs: list[str]) -> list[str]:
    """
    Find subreddits thematically close to targets but lower risk.
    Strategy: for each target, find 2-3 subs in same category with risk 26-50.
    """
    bridges = []
    
    for target in target_subs:
        # Get risk profile to find category/theme
        profile = db.query(SubredditRiskProfile).join(Subreddit).filter(
            Subreddit.name == target
        ).first()
        
        if not profile:
            continue
        
        # Find subs with:
        # - same category/topic keywords in extracted_rules
        # - risk_score 26-50
        # - compatibility >= 50 for this avatar
        candidates = db.query(SubredditRiskProfile).join(Subreddit).filter(
            SubredditRiskProfile.risk_score.between(26, 50),
            Subreddit.name != target,
            Subreddit.name.notin_(bridges)
        ).order_by(SubredditRiskProfile.risk_score.asc()).limit(10).all()
        
        # Filter by compatibility
        for c in candidates:
            compat = db.query(AvatarSubredditCompatibility).filter_by(
                avatar_id=avatar.id,
                subreddit_id=c.subreddit_id
            ).first()
            if compat and compat.score >= 50:
                bridges.append(c.subreddit.name)
                if len(bridges) >= 8:
                    break
    
    # Fallback: use avatar's hobby_subreddits if insufficient bridges
    if len(bridges) < 3:
        hobby_names = _extract_hobby_names(avatar.hobby_subreddits or [])
        bridges.extend([h for h in hobby_names if h not in bridges][:5])
    
    return bridges[:8]
```

---

## Integration Points

### 1. EPG Portfolio Manager (`portfolio_manager.py`)

In `scan_opportunities()` for Phase 0-1 avatars:

```python
# Current: uses hobby_subreddits directly
# New: uses activation_route zone subs

def _get_phase01_subreddits(avatar: Avatar) -> list[str]:
    """Get subreddits for Phase 0-1 based on activation route."""
    if avatar.activation_route:
        router = ActivationRouter()
        return router.get_current_zone_subs(avatar)
    else:
        # Legacy fallback
        return _extract_hobby_names(avatar.hobby_subreddits or [])
```

### 2. Phase Evaluator (`phase.py`)

In `evaluate_all_avatar_phases()`:

```python
# After existing phase evaluation, run zone graduation
from app.services.activation_router import ActivationRouter

router = ActivationRouter()
for avatar in phase_01_avatars:
    new_zone = router.evaluate_graduation(db, avatar)
    if new_zone:
        router.graduate(db, avatar, new_zone)
        
        # If graduating bridge→target, trigger Phase 2 re-evaluation
        if new_zone == "target":
            # Avatar is now eligible for professional pipeline
            pass  # existing Phase evaluation handles promotion
```

### 3. Timing Engine (`timing_engine.py`)

Add dangerous hours check:

```python
def is_safe_posting_time(subreddit_name: str, current_hour: int, db: Session) -> bool:
    """Check if current hour is NOT in dangerous_hours for this sub."""
    profile = get_risk_profile(db, subreddit_name)
    if not profile or not profile.dangerous_hours:
        return True  # no data = assume safe
    return current_hour not in profile.dangerous_hours
```

### 4. Avatar Creation / Demotion

Trigger route planning:

```python
# On avatar creation (avatar_onboard.py, admin.py):
router = ActivationRouter()
router.plan_route(db, avatar, client)

# On demotion to Phase 0 (phase.py):
if new_phase == 0:
    router = ActivationRouter()
    router.plan_route(db, avatar, client)  # fresh route
```

---

## Dangerous Hours Implementation

```python
# In timing_engine.py or opportunity_engine.py

def filter_by_dangerous_hours(opportunities: list, db: Session) -> list:
    """Remove opportunities in subreddits during their dangerous hours."""
    now = datetime.now(tz=timezone.utc)
    filtered = []
    
    for opp in opportunities:
        profile = get_cached_risk_profile(db, opp.subreddit)
        if profile and profile.dangerous_hours:
            # Convert to sub's effective timezone (or use UTC)
            hour = now.hour
            if hour in profile.dangerous_hours:
                continue  # skip — dangerous hour
        filtered.append(opp)
    
    return filtered
```

---

## Migration Path

1. Add `activation_route` JSONB column to avatars (Alembic migration)
2. Deploy `activation_router.py` service
3. Run route planning for all Phase 0-1 avatars (one-time backfill)
4. Integrate with EPG Portfolio Manager (feature flag: `activation_routing_enabled`)
5. Add zone graduation to daily phase evaluation
6. Add dangerous hours to timing engine

Feature flag allows gradual rollout — existing behavior unchanged until enabled.

---

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Bridge subs have no fresh threads | Zero-day for Phase 1 | Fallback to safe zone + hobby subs |
| Risk profile stale (>14d) | Wrong zone classification | Treat as bridge (conservative) |
| Insufficient bridge candidates | Avatar stuck in safe zone | Use hobby_subreddits as bridge fallback |
| Zone graduation too aggressive | Premature entry to risky subs | Min sample size (5 posted) |
| Bridge sub moderation changes | Sudden removal spike | Auto-demotion if survival <70% in zone |
| Thematic proximity is wrong | Avatar in irrelevant bridge sub | Compatibility score ≥ 50 as guard |

---

## File Plan

| File | Action | Description |
|------|--------|-------------|
| `app/services/activation_router.py` | NEW | Core routing service |
| `app/services/zone_evaluator.py` | NEW | Daily graduation check |
| `app/models/avatar.py` | MODIFY | Add `activation_route` JSONB field |
| `alembic/versions/raa01_*.py` | NEW | Migration for new column |
| `app/services/portfolio_manager.py` | MODIFY | Read route for Phase 0-1 subs |
| `app/tasks/epg.py` | MODIFY | Call zone evaluation in EPG flow |
| `app/services/phase.py` | MODIFY | Add zone graduation after phase eval |
| `app/services/timing_engine.py` | MODIFY | Add dangerous hours check |
| `app/templates/partials/avatar_zone.html` | NEW | Admin UI zone display |

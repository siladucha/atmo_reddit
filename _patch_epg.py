"""Patch script to replace enforce_subreddit_cap function in allocation_engine.py"""
import re

filepath = "reddit_saas/app/services/allocation_engine.py"

with open(filepath, "r") as f:
    content = f.read()

# Find and replace the enforce_subreddit_cap function
old_function = '''def enforce_subreddit_cap(
    selected: list[SelectedAction],
    max_share: float = SUBREDDIT_MAX_SHARE,
) -> tuple[list[SelectedAction], list[tuple]]:
    """Enforce no single subreddit receives > max_share of actions.

    When a subreddit exceeds the cap, drops the lowest risk-adjusted-return
    actions from that subreddit until the constraint is satisfied.

    Does NOT enforce the cap when there are fewer than 3 selected actions
    (at 2 actions, a single subreddit at 50% could still be the best choice)
    or when the avatar has only one subreddit represented.

    Args:
        selected: List of SelectedAction objects.
        max_share: Maximum fraction of actions for any single subreddit.

    Returns:
        Tuple of (filtered_selected, rejected_with_reasons).
    """
    if len(selected) < 3:
        return selected, []

    # Count subreddits
    subreddit_counts: dict[str, int] = {}
    for action in selected:
        sub = action.opportunity.subreddit
        subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1

    # If only one subreddit, can't diversify further
    if len(subreddit_counts) <= 1:
        return selected, []

    rejected: list[tuple] = []
    result = list(selected)

    # Iteratively enforce the cap
    changed = True
    while changed:
        changed = False
        total = len(result)
        if total < 3:
            break

        max_allowed = math.floor(total * max_share)
        # At minimum, allow 1 action per subreddit
        max_allowed = max(max_allowed, 1)

        # Find subreddits over the cap
        sub_counts: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts[sub] = sub_counts.get(sub, 0) + 1

        for sub, count in sub_counts.items():
            if count > max_allowed:
                # Find actions in this subreddit, sort by risk-adjusted return ascending
                sub_actions = [a for a in result if a.opportunity.subreddit == sub]
                sub_actions.sort(
                    key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
                )

                # Drop the lowest until within cap
                excess = count - max_allowed
                for i in range(excess):
                    action_to_drop = sub_actions[i]
                    result.remove(action_to_drop)
                    rejected.append(
                        (action_to_drop.opportunity, f"subreddit_cap_exceeded: {sub} > {int(max_share * 100)}%")
                    )
                    changed = True
                break  # Recount after modification

    return result, rejected'''

new_function = '''def enforce_subreddit_cap(
    selected: list[SelectedAction],
    max_share: float = SUBREDDIT_MAX_SHARE,
    absolute_cap: int = SUBREDDIT_ABSOLUTE_CAP,
) -> tuple[list[SelectedAction], list[tuple]]:
    """Enforce subreddit diversification with both relative and absolute caps.

    Two constraints applied in order:
    1. Absolute cap: no subreddit gets more than `absolute_cap` slots (default 2).
    2. Relative cap: no subreddit gets more than `max_share` fraction of total actions.

    When a subreddit exceeds either cap, drops the lowest risk-adjusted-return
    actions from that subreddit until the constraint is satisfied.

    The relative cap is NOT enforced when there are fewer than 3 selected actions
    or when the avatar has only one subreddit represented.

    Args:
        selected: List of SelectedAction objects.
        max_share: Maximum fraction of actions for any single subreddit.
        absolute_cap: Maximum absolute number of slots per subreddit (default 2).

    Returns:
        Tuple of (filtered_selected, rejected_with_reasons).
    """
    rejected: list[tuple] = []
    result = list(selected)

    # --- Phase 1: Enforce absolute per-subreddit cap ---
    changed = True
    while changed:
        changed = False
        sub_counts: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts[sub] = sub_counts.get(sub, 0) + 1

        for sub, count in sub_counts.items():
            if count > absolute_cap:
                # Find actions in this subreddit, sort by risk-adjusted return ascending
                sub_actions = [a for a in result if a.opportunity.subreddit == sub]
                sub_actions.sort(
                    key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
                )
                # Drop the lowest until within absolute cap
                excess = count - absolute_cap
                for i in range(excess):
                    action_to_drop = sub_actions[i]
                    result.remove(action_to_drop)
                    rejected.append(
                        (action_to_drop.opportunity, f"subreddit_absolute_cap: {sub} > {absolute_cap}/day")
                    )
                    changed = True
                break  # Recount after modification

    # --- Phase 2: Enforce relative share cap ---
    if len(result) < 3:
        return result, rejected

    # Count subreddits
    subreddit_counts: dict[str, int] = {}
    for action in result:
        sub = action.opportunity.subreddit
        subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1

    # If only one subreddit, can't diversify further
    if len(subreddit_counts) <= 1:
        return result, rejected

    changed = True
    while changed:
        changed = False
        total = len(result)
        if total < 3:
            break

        max_allowed = math.floor(total * max_share)
        # At minimum, allow 1 action per subreddit
        max_allowed = max(max_allowed, 1)

        # Find subreddits over the cap
        sub_counts_2: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts_2[sub] = sub_counts_2.get(sub, 0) + 1

        for sub, count in sub_counts_2.items():
            if count > max_allowed:
                # Find actions in this subreddit, sort by risk-adjusted return ascending
                sub_actions = [a for a in result if a.opportunity.subreddit == sub]
                sub_actions.sort(
                    key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
                )

                # Drop the lowest until within cap
                excess = count - max_allowed
                for i in range(excess):
                    action_to_drop = sub_actions[i]
                    result.remove(action_to_drop)
                    rejected.append(
                        (action_to_drop.opportunity, f"subreddit_share_cap: {sub} > {int(max_share * 100)}%")
                    )
                    changed = True
                break  # Recount after modification

    return result, rejected'''

if old_function in content:
    content = content.replace(old_function, new_function)
    with open(filepath, "w") as f:
        f.write(content)
    print("SUCCESS: enforce_subreddit_cap replaced")
else:
    print("ERROR: Could not find old function text")
    # Try to debug
    idx = content.find("def enforce_subreddit_cap")
    if idx >= 0:
        print(f"Found function start at position {idx}")
        print(repr(content[idx:idx+100]))
    else:
        print("Function not found at all!")

"""Default Permission Map — classifies every portal action into a tier.

Tiers:
- self_service: executes immediately without approval
- approval_required: creates ActionRequest, needs internal staff approval
- admin_only: invisible/inaccessible to all client-scoped users
"""

from enum import Enum


class PermissionTier(str, Enum):
    self_service = "self_service"
    approval_required = "approval_required"
    admin_only = "admin_only"


# Action identifiers map 1:1 to portal operations
DEFAULT_PERMISSION_MAP: dict[str, str] = {
    # --- Self-Service (immediate execution) --- [19 actions]
    "add_keyword": "self_service",
    "remove_keyword": "self_service",
    "trigger_pipeline": "self_service",
    "trigger_epg_rebuild": "self_service",
    "trigger_strategy": "self_service",
    "regenerate_draft": "self_service",
    "approve_draft": "self_service",
    "reject_draft": "self_service",
    "edit_draft": "self_service",
    "mark_draft_posted": "self_service",
    "submit_voice_feedback": "self_service",
    "view_avatars": "self_service",
    "view_avatar_detail": "self_service",
    "view_report": "self_service",
    "view_activity_log": "self_service",
    "view_settings": "self_service",
    "view_subreddits": "self_service",
    "view_keywords": "self_service",
    "view_epg_schedule": "self_service",
    # --- Approval Required (creates ActionRequest) --- [5 actions]
    "add_subreddit": "approval_required",
    "remove_subreddit": "approval_required",
    "request_avatar_freeze": "approval_required",
    "request_avatar_unfreeze": "approval_required",
    "change_brand_guardrails": "approval_required",
    # --- Admin Only (hidden from client users) --- [6 actions]
    "deactivate_client": "admin_only",
    "change_plan_type": "admin_only",
    "assign_avatar": "admin_only",
    "remove_avatar": "admin_only",
    "modify_auto_approve_policy": "admin_only",
    "toggle_autopilot": "admin_only",
}


def get_effective_tier(client_matrix: dict, action_id: str) -> str:
    """Resolve the effective permission tier for an action.

    Priority: client override → default map → admin_only fallback.

    - If action_id is in client_matrix AND also in DEFAULT_PERMISSION_MAP,
      the client override takes precedence (provided it's a valid tier value).
    - If action_id is missing from client_matrix, fall back to DEFAULT_PERMISSION_MAP.
    - Unknown actions (not in DEFAULT_PERMISSION_MAP) default to "admin_only".
    """
    # Client override takes precedence if present and action is known
    if action_id in client_matrix and action_id in DEFAULT_PERMISSION_MAP:
        tier = client_matrix[action_id]
        if tier in (
            PermissionTier.self_service.value,
            PermissionTier.approval_required.value,
            PermissionTier.admin_only.value,
        ):
            return tier

    # Fall back to default map; unknown actions default to admin_only
    return DEFAULT_PERMISSION_MAP.get(action_id, "admin_only")

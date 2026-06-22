"""Flow chain definitions for the UX Manual Overlay."""

LIFECYCLE_STAGES = [
    "onboarding",
    "trial",
    "execution",
    "review",
    "billing",
    "monitoring",
    "configuration",
]

FLOWS = {
    "onboarding": {
        "name": "Onboarding",
        "lifecycle_stage": "onboarding",
        "steps": [
            "Website Analysis",
            "ICP Synthesis",
            "Keywords",
            "Subreddits",
            "Avatars",
            "Activate",
        ],
    },
    "daily_operations": {
        "name": "Daily Operations",
        "lifecycle_stage": "execution",
        "steps": [
            "Dashboard",
            "Review Queue",
            "EPG Schedule",
            "Avatars",
            "Reports",
        ],
    },
    "admin_management": {
        "name": "Platform Management",
        "lifecycle_stage": "monitoring",
        "steps": [
            "Dashboard",
            "Clients",
            "Avatars",
            "Pipeline",
            "Analytics",
        ],
    },
    "trial_lifecycle": {
        "name": "Trial Journey",
        "lifecycle_stage": "trial",
        "steps": [
            "Signup",
            "Configure",
            "First Pipeline",
            "Review Results",
            "Upgrade",
        ],
    },
}

"""Billing Plan Enforcement — service layer.

Components:
- state_machine: Core FSM for billing state transitions (pure logic, no Stripe)
- plan_enforcer: Runtime limit checking and counter management
- grace_period_manager: Payment failure → degradation → suspension lifecycle
- billing_service: Stripe API integration (products, checkout, portal, invoices, coupons)
"""

from app.services.billing.state_machine import BillingStateMachine, BillingEvent, TransitionResult
from app.services.billing.plan_enforcer import PlanEnforcer, BudgetStatus
from app.services.billing.grace_period_manager import GracePeriodManager
from app.services.billing.billing_service import (
    BillingService,
    CheckoutResult,
    PortalResult,
    PLAN_TIERS,
    PLAN_MAX_AVATARS,
)

__all__ = [
    "BillingStateMachine",
    "BillingEvent",
    "TransitionResult",
    "PlanEnforcer",
    "BudgetStatus",
    "GracePeriodManager",
    "BillingService",
    "CheckoutResult",
    "PortalResult",
    "PLAN_TIERS",
    "PLAN_MAX_AVATARS",
]

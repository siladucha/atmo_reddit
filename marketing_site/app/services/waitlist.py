from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ab_test_assignment import ABTestAssignment
from app.models.waitlist_signup import WaitlistSignup


def process_signup(
    db: Session,
    email: str,
    company: str | None,
    role: str | None,
    accounts_count: int | None,
    price_tier: str | None,
    feedback: str | None,
    variant_shown: dict | None,
    source_page: str | None,
    visitor_id: UUID | None,
) -> WaitlistSignup:
    """Create or update a waitlist signup record.

    If email already exists, updates the existing record.
    If visitor_id is present, marks matching ab_test_assignments as converted.

    Returns the created/updated WaitlistSignup.
    Raises ValueError on validation failure.
    """
    if not email or not email.strip():
        raise ValueError("Email is required")

    email = email.strip().lower()

    # Query existing signup by email
    stmt = select(WaitlistSignup).where(WaitlistSignup.email == email)
    existing = db.execute(stmt).scalar_one_or_none()

    if existing:
        # Update existing record
        existing.company = company
        existing.role = role
        existing.accounts_count = accounts_count
        existing.price_tier = price_tier
        existing.feedback = feedback
        existing.variant_shown = variant_shown
        existing.source_page = source_page
        existing.updated_at = datetime.now(timezone.utc)
        signup = existing
    else:
        # Insert new record
        signup = WaitlistSignup(
            email=email,
            company=company,
            role=role,
            accounts_count=accounts_count,
            price_tier=price_tier,
            feedback=feedback,
            variant_shown=variant_shown,
            source_page=source_page,
        )
        db.add(signup)

    # Mark conversions if visitor_id is present
    if visitor_id is not None:
        mark_conversions(db, visitor_id)

    db.commit()
    db.refresh(signup)
    return signup


def mark_conversions(db: Session, visitor_id: UUID) -> int:
    """Set converted=True and converted_at on all ab_test_assignments for this visitor.

    Returns the number of records updated.
    """
    now = datetime.now(timezone.utc)

    stmt = select(ABTestAssignment).where(
        ABTestAssignment.visitor_id == visitor_id
    )
    assignments = db.execute(stmt).scalars().all()

    count = 0
    for assignment in assignments:
        assignment.converted = True
        assignment.converted_at = now
        count += 1

    db.commit()
    return count

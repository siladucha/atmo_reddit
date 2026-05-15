"""Pydantic schemas for marketing website: waitlist, A/B testing, analytics."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WaitlistSignupRequest(BaseModel):
    """Waitlist signup form submission."""

    email: str = Field(..., max_length=254)
    company: str | None = Field(None, max_length=100)
    role: str | None = Field(None, max_length=100)
    accounts_count: int | None = Field(None, ge=1, le=10000)
    price_tier: str | None = Field(None, max_length=50)
    feedback: str | None = Field(None, max_length=1000)
    variant_shown: dict | None = None
    source_page: str | None = Field(None, max_length=500)

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        """Validate email: local-part@domain with at least one dot in domain."""
        v = v.strip().lower()
        pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v


class ABAssignmentRecord(BaseModel):
    """Single A/B test variant assignment."""

    test_name: str = Field(..., max_length=100)
    variant_name: str = Field(..., max_length=100)


class RecordAssignmentsRequest(BaseModel):
    """Request to record A/B test variant assignments."""

    visitor_id: UUID
    assignments: list[ABAssignmentRecord]


class AnalyticsEventPayload(BaseModel):
    """Single analytics event."""

    visitor_id: UUID
    event_type: str = Field(..., max_length=100)
    event_data: dict | None = None
    page_path: str | None = Field(None, max_length=500)
    timestamp: datetime


class AnalyticsBatchRequest(BaseModel):
    """Batch of analytics events (max 100)."""

    events: list[AnalyticsEventPayload] = Field(..., max_length=100)

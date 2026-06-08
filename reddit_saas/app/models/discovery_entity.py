"""Discovery Entity model — named entities extracted from client brief.

Entities are the building blocks of the Discovery Engine's hypothesis formation.
They represent concrete business concepts (products, audiences, problems, industries,
competitors, use cases) that the system uses to generate testable Reddit hypotheses.

Each entity belongs to a single DiscoverySession and is either extracted by the LLM
from the client brief or manually added by the operator.

Categories:
- product: specific product/service the client offers
- audience: target customer segment or persona
- problem: pain point the client solves
- industry: vertical/market the client operates in
- competitor: known competitors in the space
- use_case: specific application or scenario

Sources:
- extracted: automatically identified by LLM from client brief
- operator_added: manually added by the operator during entity review
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DiscoveryEntity(Base):
    __tablename__ = "discovery_entities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # product | audience | problem | industry | competitor | use_case
    source: Mapped[str] = mapped_column(String(20), default="extracted")  # extracted | operator_added
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("DiscoverySession", back_populates="entities")

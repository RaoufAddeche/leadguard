from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class LeadEvent(Base):
    """Append-only audit trail: one row per meaningful step of the pipeline."""

    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lead: Mapped["Lead"] = relationship(back_populates="events")  # noqa: F821

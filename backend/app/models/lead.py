from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow
from app.models.enums import CRMSyncStatus, LeadStatus


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-readable reference (LD-2026-0042), assigned once the PK is known.
    public_id: Mapped[str | None] = mapped_column(String(32), unique=True, index=True)

    # --- Raw submitted data ----------------------------------------------
    firstname: Mapped[str] = mapped_column(String(80))
    lastname: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(40), index=True)
    postal_code: Mapped[str] = mapped_column(String(16), index=True)
    country: Mapped[str] = mapped_column(String(2), default="FR", index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    campaign: Mapped[str] = mapped_column(String(120))
    project_description: Mapped[str] = mapped_column(Text)
    owner: Mapped[bool | None] = mapped_column(Boolean)
    budget: Mapped[float | None] = mapped_column(Float)

    # Normalised copies used exclusively for duplicate lookups: indexed so
    # the candidate query stays a cheap index scan instead of a table scan.
    email_normalized: Mapped[str] = mapped_column(String(255), index=True, default="")
    phone_normalized: Mapped[str] = mapped_column(String(40), index=True, default="")

    # --- Consent & traceability (GDPR) ------------------------------------
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    # --- AI extraction ----------------------------------------------------
    ai_project_type: Mapped[str | None] = mapped_column(String(40))
    # The commercial vertical the project rolls up into: this is what selects
    # the eligibility rules and the buying team.
    vertical: Mapped[str] = mapped_column(String(40), default="unknown", index=True)
    # Per-vertical extracted fields (heating age, roof orientation, ...).
    ai_details: Mapped[dict | None] = mapped_column(JSON)
    ai_location: Mapped[str | None] = mapped_column(String(120))
    ai_property_type: Mapped[str | None] = mapped_column(String(40))
    ai_owner_intent: Mapped[bool | None] = mapped_column(Boolean)
    ai_urgency: Mapped[str | None] = mapped_column(String(20))
    ai_purchase_intent: Mapped[str | None] = mapped_column(String(20))
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_provider: Mapped[str | None] = mapped_column(String(40))

    # --- Qualification outcome -------------------------------------------
    score: Mapped[int] = mapped_column(Integer, default=0)
    # Decision produced by the deterministic engine.
    system_status: Mapped[str] = mapped_column(String(20), default=LeadStatus.REVIEW)
    # Decision taken by a human reviewer, when one was needed.
    human_status: Mapped[str | None] = mapped_column(String(20))
    reviewer: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str | None] = mapped_column(Text)

    # Full rule-by-rule breakdown, kept for auditability.
    rule_results: Mapped[list | None] = mapped_column(JSON)

    # --- Duplicate detection ----------------------------------------------
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id"))
    # Denormalised on purpose: a snapshot of the matched lead's reference, so
    # serialising never needs to traverse a self-referential relationship
    # (which cannot be eagerly loaded under the async ORM).
    duplicate_of_public_id: Mapped[str | None] = mapped_column(String(32))
    duplicate_similarity: Mapped[int | None] = mapped_column(Integer)
    duplicate_reason: Mapped[str | None] = mapped_column(String(255))

    # --- Routing & CRM ----------------------------------------------------
    routed_team: Mapped[str | None] = mapped_column(String(120))
    routing_reason: Mapped[str | None] = mapped_column(String(255))
    crm_status: Mapped[str] = mapped_column(String(20), default=CRMSyncStatus.PENDING)
    crm_reference: Mapped[str | None] = mapped_column(String(64))
    crm_error: Mapped[str | None] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    events: Mapped[list["LeadEvent"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="LeadEvent.id",
        lazy="selectin",
    )
    @property
    def final_status(self) -> str:
        """A human decision always overrides the system decision."""
        return self.human_status or self.system_status

    @property
    def full_name(self) -> str:
        return f"{self.firstname} {self.lastname}".strip()

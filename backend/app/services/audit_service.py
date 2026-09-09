"""Append-only audit trail.

Every pipeline step records what happened, when, and with what data. Nothing
here ever updates or deletes a row: the trail is the evidence that a decision
was taken for the stated reasons.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Lead, LeadEvent
from app.models.enums import EventType

logger = logging.getLogger("leadguard.audit")


def record(
    db: AsyncSession,
    lead: Lead,
    event_type: EventType,
    message: str,
    metadata: dict | None = None,
) -> LeadEvent:
    """Stage an audit event. The caller commits, so the trail is atomic with
    the state change it describes."""
    event = LeadEvent(
        lead_id=lead.id,
        event_type=event_type.value,
        message=message,
        event_metadata=metadata,
    )
    db.add(event)
    # Deliberately does NOT touch ``lead.events``: reading that collection on a
    # already-flushed instance would trigger a lazy load, which the async ORM
    # cannot perform outside a greenlet. The pipeline keeps its own list.
    logger.info("[%s] %s: %s", lead.public_id or lead.id, event_type.value, message)
    return event

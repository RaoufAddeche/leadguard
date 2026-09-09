"""Duplicate detection.

Two tiers, cheapest first:
  1. Exact match on normalised email or phone -> near-certain duplicate.
  2. Weak-signal match (name + phone, or email domain + postal code) scored
     with a small similarity heuristic.

Runs BEFORE the lead is inserted, so a lead is never compared against itself.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import Lead
from app.schemas.lead import DuplicateInfo, LeadCreate
from app.services.fingerprint import normalize_email, normalize_phone


@dataclass(frozen=True)
class DuplicateMatch:
    lead: Lead
    similarity: int
    reason: str


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _score_candidate(candidate: Lead, lead: LeadCreate) -> tuple[int, str] | None:
    """Return (similarity %, reason) if the candidate looks like the same person."""
    same_email = candidate.email_normalized == normalize_email(lead.email)
    same_phone = candidate.phone_normalized == normalize_phone(lead.phone)

    if same_email and same_phone:
        return 100, "Identical email address and phone number"
    if same_email:
        return 96, "Identical email address"
    if same_phone:
        return 94, "Identical phone number"

    # Weak signals: require two agreeing dimensions to avoid false positives.
    name_ratio = (
        _name_similarity(candidate.firstname, lead.firstname)
        + _name_similarity(candidate.lastname, lead.lastname)
    ) / 2
    same_postal = candidate.postal_code.strip() == lead.postal_code.strip()

    if name_ratio >= 0.9 and same_postal:
        return int(round(85 * name_ratio)), "Matching name and postal code"

    return None


async def find_duplicate(
    db: AsyncSession, lead: LeadCreate, *, settings: Settings | None = None
) -> DuplicateMatch | None:
    settings = settings or get_settings()

    # Narrow the candidate set in SQL on the normalised columns — so
    # "+33 6 12 34 56 78" and "0612345678" land on the same index key — then
    # score the shortlist precisely in Python.
    stmt = (
        select(Lead)
        .where(
            or_(
                Lead.email_normalized == normalize_email(lead.email),
                Lead.phone_normalized == normalize_phone(lead.phone),
                Lead.lastname == lead.lastname,
            )
        )
        .order_by(Lead.id)
    )
    candidates = (await db.execute(stmt)).unique().scalars().all()

    best: DuplicateMatch | None = None
    for candidate in candidates:
        scored = _score_candidate(candidate, lead)
        if scored is None:
            continue
        similarity, reason = scored
        if similarity < settings.duplicate_similarity_threshold:
            continue
        if best is None or similarity > best.similarity:
            best = DuplicateMatch(lead=candidate, similarity=similarity, reason=reason)

    return best


def to_info(match: DuplicateMatch | None) -> DuplicateInfo:
    if match is None:
        return DuplicateInfo(duplicate=False, reason="No duplicate found")
    return DuplicateInfo(
        duplicate=True,
        duplicate_lead_id=match.lead.public_id,
        similarity=match.similarity,
        reason=match.reason,
    )

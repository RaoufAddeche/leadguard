"""The one and only qualification pipeline.

Both POST /api/leads and POST /api/webhooks/leads call `process_lead`, so the
business logic exists exactly once. The pipeline order is:

    persist -> consent -> duplicates -> AI extraction -> rules -> scoring
            -> decision -> routing -> CRM -> audit

Note the boundary: the AI step only *adds structured fields*. Everything after
it is deterministic and fully auditable.
"""

import logging
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.factory import analyze_safely
from app.config import Settings, get_settings
from app.integrations.crm import CRMClient
from app.models import Lead, LeadEvent
from app.models.base import utcnow
from app.models.enums import CRMSyncStatus, EventType, LeadStatus, Vertical
from app.qualification import qualify
from app.routing import route
from app.schemas.lead import (
    AIAnalysis,
    DuplicateInfo,
    HumanDecision,
    LeadCreate,
    LeadEventOut,
    QualificationResult,
)
from app.services import audit_service
from app.services.duplicate_service import find_duplicate, to_info
from app.services.fingerprint import compute_fingerprint, normalize_email, normalize_phone

logger = logging.getLogger("leadguard.pipeline")


def make_public_id(lead: Lead) -> str:
    return f"LD-{lead.created_at.year}-{lead.id:04d}"


async def process_lead(
    db: AsyncSession,
    payload: LeadCreate,
    ai_provider: AIProvider,
    crm_client: CRMClient | None = None,
    *,
    channel: str = "api",
    settings: Settings | None = None,
) -> QualificationResult:
    settings = settings or get_settings()
    trail: list[LeadEvent] = []

    def log(event_type: EventType, message: str, metadata: dict | None = None) -> None:
        """Record an audit event and keep it for the response payload."""
        trail.append(audit_service.record(db, lead, event_type, message, metadata))

    # --- 0. Duplicate check happens BEFORE insert, so a lead is never
    #        compared against itself.
    match = await find_duplicate(db, payload, settings=settings)
    duplicate_info = to_info(match)

    # --- 1. Persist the raw lead with its consent trail and fingerprint.
    lead = Lead(
        firstname=payload.firstname,
        lastname=payload.lastname,
        email=str(payload.email),
        phone=payload.phone,
        postal_code=payload.postal_code,
        country=payload.country.value,
        email_normalized=normalize_email(payload.email),
        phone_normalized=normalize_phone(payload.phone),
        source=payload.source,
        campaign=payload.campaign,
        project_description=payload.project_description,
        owner=payload.owner,
        budget=payload.budget,
        consent=payload.consent,
        # Consent is timestamped at intake if the caller did not supply one.
        consent_timestamp=payload.consent_timestamp or (utcnow() if payload.consent else None),
        data_fingerprint=compute_fingerprint(payload),
        created_at=utcnow(),
        is_duplicate=match is not None,
        duplicate_of_id=match.lead.id if match else None,
        duplicate_of_public_id=match.lead.public_id if match else None,
        duplicate_similarity=match.similarity if match else None,
        duplicate_reason=match.reason if match else None,
    )
    db.add(lead)
    await db.flush()  # assigns the PK
    lead.public_id = make_public_id(lead)

    log(EventType.RECEIVED,
        f"Lead received from {payload.source} (campaign {payload.campaign}) via {channel}",
        {"channel": channel, "source": payload.source, "campaign": payload.campaign},
    )
    log(EventType.VALIDATED,
        "Validation passed: all required fields present and well-formed",
    )

    # --- 2. Consent & traceability -------------------------------------
    if lead.consent:
        log(EventType.CONSENT_VERIFIED,
            f"Consent verified and timestamped at {lead.consent_timestamp:%Y-%m-%d %H:%M:%S} UTC",
            {"fingerprint": lead.data_fingerprint},
        )
    else:
        log(EventType.CONSENT_VERIFIED,
            "No consent recorded: the lead cannot be contacted for marketing (GDPR)",
            {"fingerprint": lead.data_fingerprint},
        )

    # --- 3. Duplicate detection outcome ---------------------------------
    if match:
        log(EventType.DUPLICATE_CHECK,
            f"Potential duplicate of {match.lead.public_id} "
            f"({match.similarity}% similarity): {match.reason}",
            {"duplicate_lead_id": match.lead.public_id, "similarity": match.similarity},
        )
    else:
        log(EventType.DUPLICATE_CHECK, "Duplicate check passed")

    # --- 4. AI extraction (never decides, only extracts) ----------------
    analysis, ai_error = await analyze_safely(
        ai_provider, payload, timeout=settings.ai_timeout_seconds
    )
    _apply_analysis(lead, analysis)

    if ai_error:
        log(EventType.AI_ANALYSIS,
            f"AI analysis unavailable, continuing on submitted data only: {ai_error}",
            {"error": ai_error},
        )
    else:
        log(EventType.AI_ANALYSIS,
            f"AI analysis completed by '{analysis.provider}': "
            f"project={analysis.project_type}, urgency={analysis.urgency}, "
            f"intent={analysis.purchase_intent}"
            + (f", details={analysis.details}" if analysis.details else ""),
            analysis.model_dump(),
        )

    # --- 5 & 6. Deterministic rules, scoring and decision ---------------
    outcome = qualify(payload, analysis, is_duplicate=match is not None, settings=settings)
    lead.vertical = outcome.vertical.value
    lead.score = outcome.score
    lead.system_status = outcome.status.value
    lead.rule_results = [r.model_dump() for r in outcome.rule_results]

    log(
        EventType.SCORED,
        f"Score calculated: {outcome.score}/{outcome.max_possible} "
        f"({len(outcome.rule_results) - 1} checks: universal + {outcome.vertical.value})"
        + (
            " — no vertical identified, so the eligibility criteria could not be "
            "checked and the lead is capped below the qualification threshold"
            if outcome.vertical is Vertical.UNKNOWN
            else ""
        ),
        {
            "rules": lead.rule_results,
            "vertical": outcome.vertical.value,
            "max_possible": outcome.max_possible,
        },
    )
    log(EventType.STATUS_CHANGED,
        f"Status set to {outcome.status.value}: {outcome.reason}",
        {"status": outcome.status.value, "score": outcome.score},
    )

    # --- 7. Routing: only leads that will reach sales are routed --------
    if outcome.status is not LeadStatus.REJECTED:
        decision = route(payload, analysis, outcome.vertical)
        lead.routed_team = decision.team
        lead.routing_reason = decision.reason
        log(EventType.ROUTED,
            f"Routed to {decision.team}: {decision.reason}",
            {"team": decision.team},
        )

    # --- 8. CRM sync: qualified leads only ------------------------------
    await _sync_to_crm(db, lead, crm_client, outcome.status, log)

    await db.commit()

    return QualificationResult(
        lead_id=lead.id,
        public_id=lead.public_id,
        score=lead.score,
        status=lead.final_status,
        vertical=lead.vertical,
        team=lead.routed_team,
        duplicate=duplicate_info,
        ai_analysis=analysis,
        rule_results=outcome.rule_results,
        crm_status=lead.crm_status,
        events=[LeadEventOut.from_model(e) for e in trail],
    )


def _apply_analysis(lead: Lead, analysis: AIAnalysis) -> None:
    lead.ai_project_type = analysis.project_type
    lead.ai_location = analysis.location
    lead.ai_property_type = analysis.property_type
    lead.ai_owner_intent = analysis.owner_intent
    lead.ai_urgency = analysis.urgency
    lead.ai_purchase_intent = analysis.purchase_intent
    lead.ai_summary = analysis.summary
    lead.ai_provider = analysis.provider
    lead.ai_details = analysis.details or {}


def crm_payload(lead: Lead) -> dict:
    return {
        "lead_id": lead.public_id,
        "firstname": lead.firstname,
        "lastname": lead.lastname,
        "email": lead.email,
        "phone": lead.phone,
        "postal_code": lead.postal_code,
        "score": lead.score,
        "status": lead.final_status,
        "team": lead.routed_team,
        "vertical": lead.vertical,
        "project_type": lead.ai_project_type,
        "source": lead.source,
        "campaign": lead.campaign,
        "consent": lead.consent,
        "ai_summary": lead.ai_summary,
    }


async def _sync_to_crm(
    db: AsyncSession,
    lead: Lead,
    crm_client: CRMClient | None,
    status: LeadStatus,
    log: Callable[..., None],
) -> None:
    """Push to the CRM. A failure is recorded, never raised: the lead is safe in
    LeadGuard and can be re-pushed."""
    if status is not LeadStatus.QUALIFIED:
        lead.crm_status = CRMSyncStatus.SKIPPED.value
        log(EventType.CRM_SYNC,
            f"CRM synchronization skipped: lead is {status.value}, not QUALIFIED",
        )
        return

    if crm_client is None:
        lead.crm_status = CRMSyncStatus.SKIPPED.value
        log(EventType.CRM_SYNC, "CRM synchronization skipped: no CRM client configured"
        )
        return

    result = await crm_client.push_lead(crm_payload(lead))
    if result.success:
        lead.crm_status = CRMSyncStatus.SUCCESS.value
        lead.crm_reference = result.reference
        lead.crm_error = None
        log(EventType.CRM_SYNC,
            f"CRM synchronization successful (reference {result.reference})",
            {"crm_id": result.reference, "attempts": result.attempts},
        )
    else:
        lead.crm_status = CRMSyncStatus.FAILED.value
        lead.crm_error = (result.error or "unknown error")[:255]
        log(EventType.CRM_SYNC,
            f"CRM synchronization failed after {result.attempts} attempts: {lead.crm_error}. "
            "The lead is retained in LeadGuard and can be re-pushed.",
            {"error": lead.crm_error, "attempts": result.attempts},
        )


async def apply_human_decision(
    db: AsyncSession,
    lead: Lead,
    decision: HumanDecision,
    crm_client: CRMClient | None = None,
) -> Lead:
    """Record a reviewer's verdict without ever overwriting the system decision.

    Both decisions are kept side by side: that pair is what lets you audit, and
    later measure, how often humans disagree with the engine.
    """
    trail: list[LeadEvent] = []

    def log(event_type: EventType, message: str, metadata: dict | None = None) -> None:
        trail.append(audit_service.record(db, lead, event_type, message, metadata))

    lead.human_status = decision.decision.value
    lead.reviewer = decision.reviewer
    lead.reviewed_at = utcnow()
    lead.review_reason = decision.reason

    log(EventType.HUMAN_REVIEW,
        f"Human decision by {decision.reviewer}: {decision.decision.value} "
        f"(system had decided {lead.system_status})"
        + (f" - {decision.reason}" if decision.reason else ""),
        {
            "system_status": lead.system_status,
            "human_status": lead.human_status,
            "reviewer": decision.reviewer,
            "reason": decision.reason,
        },
    )

    # A human upgrade to QUALIFIED triggers the same downstream flow as an
    # automatic qualification: route, then push to the CRM.
    if decision.decision is LeadStatus.QUALIFIED:
        if not lead.routed_team:
            payload, analysis = _rebuild_context(lead)
            routing = route(payload, analysis)
            lead.routed_team = routing.team
            lead.routing_reason = routing.reason
            log(EventType.ROUTED,
                f"Routed to {routing.team}: {routing.reason}",
                {"team": routing.team},
            )
        await _sync_to_crm(db, lead, crm_client, LeadStatus.QUALIFIED, log)
    else:
        lead.crm_status = CRMSyncStatus.SKIPPED.value

    await db.commit()
    await db.refresh(lead, ["events"])
    return lead


def _rebuild_context(lead: Lead) -> tuple[LeadCreate, AIAnalysis]:
    """Rehydrate the routing inputs from a stored lead."""
    payload = LeadCreate(
        firstname=lead.firstname,
        lastname=lead.lastname,
        email=lead.email,
        phone=lead.phone,
        postal_code=lead.postal_code,
        source=lead.source,
        campaign=lead.campaign,
        project_description=lead.project_description,
        owner=lead.owner,
        budget=lead.budget,
        consent=lead.consent,
        country=lead.country,
    )
    analysis = AIAnalysis(
        project_type=lead.ai_project_type or "unknown",
        location=lead.ai_location,
        property_type=lead.ai_property_type,
        owner_intent=lead.ai_owner_intent,
        urgency=lead.ai_urgency or "unknown",
        purchase_intent=lead.ai_purchase_intent or "unknown",
        summary=lead.ai_summary or "",
        provider=lead.ai_provider,
        details=lead.ai_details or {},
    )
    return payload, analysis


async def dashboard_stats(db: AsyncSession) -> dict:
    """Counts computed from the database, using the FINAL status of each lead."""
    leads = (await db.execute(select(Lead))).unique().scalars().all()
    total = len(leads)
    counts = {LeadStatus.QUALIFIED: 0, LeadStatus.REVIEW: 0, LeadStatus.REJECTED: 0}
    for lead in leads:
        counts[LeadStatus(lead.final_status)] += 1

    duplicates = sum(1 for lead in leads if lead.is_duplicate)
    average = sum(lead.score for lead in leads) / total if total else 0.0

    # Per-vertical breakdown: a lead-gen business is managed vertical by
    # vertical, because each one is sold to a different client.
    by_vertical: dict[str, list[Lead]] = {}
    for lead in leads:
        by_vertical.setdefault(lead.vertical or "unknown", []).append(lead)

    verticals = [
        {
            "vertical": name,
            "total": len(group),
            "qualified": sum(1 for x in group if x.final_status == LeadStatus.QUALIFIED),
            "review": sum(1 for x in group if x.final_status == LeadStatus.REVIEW),
            "rejected": sum(1 for x in group if x.final_status == LeadStatus.REJECTED),
            "average_score": round(sum(x.score for x in group) / len(group), 1),
        }
        for name, group in sorted(by_vertical.items(), key=lambda kv: -len(kv[1]))
    ]

    return {
        "total": total,
        "qualified": counts[LeadStatus.QUALIFIED],
        "review": counts[LeadStatus.REVIEW],
        "rejected": counts[LeadStatus.REJECTED],
        "duplicates": duplicates,
        "qualification_rate": round(counts[LeadStatus.QUALIFIED] / total * 100, 1) if total else 0.0,
        "average_score": round(average, 1),
        "verticals": verticals,
    }

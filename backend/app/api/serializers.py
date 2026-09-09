"""Model -> response-schema conversion, kept out of the route handlers."""

from app.models import Lead
from app.schemas.lead import (
    AIAnalysis,
    DuplicateInfo,
    LeadDetail,
    LeadEventOut,
    LeadSummary,
    RuleResult,
)


def to_summary(lead: Lead) -> LeadSummary:
    return LeadSummary(
        id=lead.id,
        public_id=lead.public_id,
        full_name=lead.full_name,
        email=lead.email,
        score=lead.score,
        status=lead.final_status,
        system_status=lead.system_status,
        human_status=lead.human_status,
        project_type=lead.ai_project_type,
        vertical=lead.vertical,
        location=lead.ai_location,
        source=lead.source,
        campaign=lead.campaign,
        routed_team=lead.routed_team,
        is_duplicate=lead.is_duplicate,
        created_at=lead.created_at,
    )


def to_detail(lead: Lead) -> LeadDetail:
    analysis = None
    if lead.ai_project_type:
        analysis = AIAnalysis(
            project_type=lead.ai_project_type,
            location=lead.ai_location,
            property_type=lead.ai_property_type,
            owner_intent=lead.ai_owner_intent,
            urgency=lead.ai_urgency or "unknown",
            purchase_intent=lead.ai_purchase_intent or "unknown",
            summary=lead.ai_summary or "",
            provider=lead.ai_provider,
            details=lead.ai_details or {},
        )

    duplicate = DuplicateInfo(
        duplicate=lead.is_duplicate,
        duplicate_lead_id=lead.duplicate_of_public_id,
        similarity=lead.duplicate_similarity,
        reason=lead.duplicate_reason or "No duplicate found",
    )

    return LeadDetail(
        **to_summary(lead).model_dump(),
        firstname=lead.firstname,
        lastname=lead.lastname,
        phone=lead.phone,
        postal_code=lead.postal_code,
        country=lead.country,
        project_description=lead.project_description,
        owner=lead.owner,
        budget=lead.budget,
        consent=lead.consent,
        consent_timestamp=lead.consent_timestamp,
        data_fingerprint=lead.data_fingerprint,
        ai_analysis=analysis,
        ai_provider=lead.ai_provider,
        rule_results=[RuleResult(**r) for r in (lead.rule_results or [])],
        duplicate=duplicate,
        routing_reason=lead.routing_reason,
        crm_status=lead.crm_status,
        crm_reference=lead.crm_reference,
        crm_error=lead.crm_error,
        reviewer=lead.reviewer,
        reviewed_at=lead.reviewed_at,
        review_reason=lead.review_reason,
        events=[LeadEventOut.from_model(e) for e in lead.events],
    )

"""Human-in-the-loop endpoints.

The reviewer's verdict is stored *alongside* the system decision, never on top
of it, so you can always answer "what did the engine say, and what did the
human do about it?".
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CRMClientDep
from app.api.serializers import to_detail, to_summary
from app.db.session import get_db
from app.models import Lead
from app.models.enums import LeadStatus
from app.schemas.lead import HumanDecision, LeadDetail, LeadSummary
from app.services.lead_service import apply_human_decision

router = APIRouter(prefix="/api/reviews", tags=["reviews"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("", response_model=list[LeadSummary], summary="Leads awaiting human review")
async def list_pending_reviews(db: DbDep) -> list[LeadSummary]:
    stmt = (
        select(Lead)
        .where(Lead.system_status == LeadStatus.REVIEW.value, Lead.human_status.is_(None))
        .order_by(Lead.score.desc(), Lead.id.desc())
    )
    leads = (await db.execute(stmt)).unique().scalars().all()
    return [to_summary(lead) for lead in leads]


@router.post("/{lead_id}", response_model=LeadDetail, summary="Record a human decision")
async def review_lead(
    lead_id: int, decision: HumanDecision, db: DbDep, crm_client: CRMClientDep
) -> LeadDetail:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")

    if lead.human_status is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Lead {lead.public_id} was already reviewed by {lead.reviewer} "
                f"({lead.human_status})"
            ),
        )

    lead = await apply_human_decision(db, lead, decision, crm_client)
    return to_detail(lead)

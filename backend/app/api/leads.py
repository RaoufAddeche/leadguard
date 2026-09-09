"""Lead intake and read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AIProviderDep, CRMClientDep, SettingsDep
from app.api.serializers import to_detail, to_summary
from app.db.session import get_db
from app.models import Lead
from app.schemas.lead import (
    DashboardStats,
    LeadCreate,
    LeadDetail,
    LeadSummary,
    QualificationResult,
)
from app.services.lead_service import dashboard_stats, process_lead

router = APIRouter(prefix="/api", tags=["leads"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/leads",
    response_model=QualificationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a lead and run the full qualification pipeline",
)
async def create_lead(
    payload: LeadCreate,
    db: DbDep,
    ai_provider: AIProviderDep,
    crm_client: CRMClientDep,
    settings: SettingsDep,
) -> QualificationResult:
    """Pydantic has already rejected structurally invalid payloads with a 422.

    Business-level problems (bad phone format, missing consent, duplicate) are
    *not* errors here: the lead is stored and scored, and a low score is a
    perfectly valid, auditable outcome.
    """
    return await process_lead(
        db, payload, ai_provider, crm_client, channel="api", settings=settings
    )


@router.get("/leads", response_model=list[LeadSummary], summary="List leads")
async def list_leads(
    db: DbDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[LeadSummary]:
    stmt = select(Lead).order_by(Lead.id.desc()).limit(limit)
    leads = (await db.execute(stmt)).unique().scalars().all()

    if status_filter:
        wanted = status_filter.upper()
        leads = [lead for lead in leads if lead.final_status == wanted]

    return [to_summary(lead) for lead in leads]


@router.get("/leads/stats", response_model=DashboardStats, summary="Dashboard counters")
async def get_stats(db: DbDep) -> DashboardStats:
    return DashboardStats(**await dashboard_stats(db))


@router.get("/leads/{lead_id}", response_model=LeadDetail, summary="Lead detail")
async def get_lead(lead_id: int, db: DbDep) -> LeadDetail:
    lead = await db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    return to_detail(lead)

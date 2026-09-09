"""A stand-in CRM, so the integration path is real end to end.

Leads pushed here are kept in memory only — this exists to prove the outbound
sync works (and to let us break it on purpose), not to store anything.
"""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SettingsDep

logger = logging.getLogger("leadguard.fake_crm")

router = APIRouter(prefix="/api/fake-crm", tags=["fake-crm"])

# In-memory store: reset on restart, which is exactly what a POC wants.
RECEIVED_LEADS: list[dict[str, Any]] = []


@router.post("/leads", status_code=status.HTTP_201_CREATED, summary="Receive a qualified lead")
async def receive_lead(payload: dict, settings: SettingsDep) -> dict:
    # Deterministic outage switch for demoing the retry/failure path.
    if settings.crm_fail_rate >= 1.0:
        logger.error("Fake CRM is simulating an outage (CRM_FAIL_RATE=1)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="CRM temporarily unavailable"
        )

    if not payload.get("lead_id"):
        raise HTTPException(status_code=422, detail="lead_id is required")

    crm_id = f"CRM-{uuid.uuid4().hex[:8].upper()}"
    record = {"crm_id": crm_id, **payload}
    RECEIVED_LEADS.append(record)
    logger.info("Fake CRM accepted %s as %s", payload.get("lead_id"), crm_id)

    return {"crm_id": crm_id, "status": "created", "lead_id": payload.get("lead_id")}


@router.get("/leads", summary="Inspect what the CRM received")
async def list_crm_leads() -> dict:
    return {"count": len(RECEIVED_LEADS), "leads": list(reversed(RECEIVED_LEADS))}

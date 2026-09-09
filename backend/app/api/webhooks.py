"""Inbound webhooks.

Each ad platform posts its own field names, so every source gets a small
*adapter* that maps its payload onto `LeadCreate`. Past that mapping the
webhook calls exactly the same `process_lead` as the manual API — the business
logic is never duplicated.
"""

import logging
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AIProviderDep, CRMClientDep, SettingsDep
from app.db.session import get_db
from app.schemas.lead import LeadCreate, QualificationResult
from app.services.lead_service import process_lead

logger = logging.getLogger("leadguard.webhook")

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

DbDep = Annotated[AsyncSession, Depends(get_db)]


def _get(data: dict, *keys: str, default: Any = None) -> Any:
    """First present, non-empty value among ``keys``."""
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "oui"}:
            return True
        if lowered in {"false", "no", "n", "0", "non"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        # Tolerate "12 000 €" / "12,000" from partner forms.
        cleaned = str(value).replace(" ", "").replace(",", "").replace("€", "").replace("EUR", "")
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _generic_adapter(source: str) -> Callable[[dict], LeadCreate]:
    """Handles the common shapes of Google Ads, Meta Ads and partner forms."""

    def adapt(data: dict) -> LeadCreate:
        # Google Ads lead-form extensions nest the answers in a list.
        if isinstance(data.get("user_column_data"), list):
            data = {**data, **{
                item.get("column_id", ""): item.get("string_value")
                for item in data["user_column_data"]
                if isinstance(item, dict)
            }}
        # Meta Ads uses the same idea under a different key.
        if isinstance(data.get("field_data"), list):
            data = {**data, **{
                item.get("name", ""): (item.get("values") or [None])[0]
                for item in data["field_data"]
                if isinstance(item, dict)
            }}

        return LeadCreate(
            firstname=_get(data, "firstname", "first_name", "FIRST_NAME", "prenom", default=""),
            lastname=_get(data, "lastname", "last_name", "LAST_NAME", "nom", default=""),
            email=_get(data, "email", "EMAIL", "email_address", "mail", default=""),
            phone=_get(data, "phone", "PHONE_NUMBER", "phone_number", "telephone", "tel", default=""),
            postal_code=_get(
                data, "postal_code", "POSTAL_CODE", "zip", "zipcode", "cp", "code_postal", default=""
            ),
            source=_get(data, "source", "platform", default=source),
            campaign=_get(
                data, "campaign", "campaign_name", "CAMPAIGN_NAME", "ad_campaign", default="unknown"
            ),
            project_description=_get(
                data, "project_description", "message", "comments", "description",
                "besoin", "projet", default="",
            ),
            owner=_as_bool(_get(data, "owner", "is_owner", "proprietaire", "homeowner")),
            budget=_as_float(_get(data, "budget", "estimated_budget", "budget_estime")),
            consent=bool(_as_bool(_get(data, "consent", "opt_in", "gdpr_consent", "consentement"))),
            consent_timestamp=_get(data, "consent_timestamp", "opt_in_timestamp"),
        )

    return adapt


# Registry: adding a new traffic source is one entry, no pipeline change.
ADAPTERS: dict[str, Callable[[dict], LeadCreate]] = {
    "google_ads": _generic_adapter("google_ads"),
    "meta_ads": _generic_adapter("meta_ads"),
    "partner_form": _generic_adapter("partner_form"),
    "external": _generic_adapter("external"),
}


@router.post(
    "/leads",
    response_model=QualificationResult,
    status_code=status.HTTP_201_CREATED,
    summary="Receive a lead from an external platform",
)
async def receive_webhook(
    payload: dict,
    db: DbDep,
    ai_provider: AIProviderDep,
    crm_client: CRMClientDep,
    settings: SettingsDep,
) -> QualificationResult:
    """Normalise a third-party payload, then run the shared pipeline.

    A malformed webhook returns 422 (the sender should fix and re-send) rather
    than being silently swallowed.
    """
    raw_source = str(payload.get("source") or payload.get("platform") or "external").lower()
    adapter = ADAPTERS.get(raw_source, ADAPTERS["external"])

    # Some platforms wrap the answers in an envelope.
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(payload.get("lead"), dict):
        data = payload["lead"]

    try:
        lead = adapter({**data, "source": raw_source} if "source" not in data else data)
    except Exception as exc:  # noqa: BLE001 - surface the mapping failure clearly
        logger.warning("Rejected webhook from %s: %s", raw_source, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Webhook payload could not be mapped to a lead: {exc}",
        ) from exc

    return await process_lead(
        db, lead, ai_provider, crm_client, channel=f"webhook:{raw_source}", settings=settings
    )

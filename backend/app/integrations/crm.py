"""Fake CRM client.

Demonstrates a real outbound integration: timeout, bounded retry with backoff,
structured logging, and — most importantly — failure isolation. A CRM outage
must never lose a lead or fail the intake request: the lead stays qualified in
LeadGuard with crm_status=FAILED, ready to be re-pushed.

The client is constructed with an injectable transport so tests can simulate an
outage without any network.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger("leadguard.crm")


@dataclass(frozen=True)
class CRMResult:
    success: bool
    reference: str | None = None
    error: str | None = None
    attempts: int = 0


class CRMClient:
    """POSTs qualified leads to the CRM endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 5.0,
        max_attempts: int = 3,
        backoff: float = 0.2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.backoff = backoff

    async def push_lead(self, payload: dict) -> CRMResult:
        last_error: str | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url, transport=self.transport, timeout=self.timeout
                ) as client:
                    response = await client.post("/api/fake-crm/leads", json=payload)
                    response.raise_for_status()
                    body = response.json()
                logger.info(
                    "CRM sync succeeded for %s on attempt %s", payload.get("lead_id"), attempt
                )
                return CRMResult(
                    success=True, reference=body.get("crm_id"), attempts=attempt
                )

            except Exception as exc:  # noqa: BLE001 - any failure is retryable here
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "CRM sync attempt %s/%s failed for %s: %s",
                    attempt, self.max_attempts, payload.get("lead_id"), last_error,
                )
                if attempt < self.max_attempts:
                    # Exponential backoff; a real system would use a job queue.
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))

        logger.error("CRM sync permanently failed for %s: %s", payload.get("lead_id"), last_error)
        return CRMResult(success=False, error=last_error, attempts=self.max_attempts)


def build_crm_client(
    app=None, settings: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> CRMClient:
    """Build a client. With no explicit CRM_BASE_URL we loop back into this very
    app via an ASGI transport, so the demo needs no second service running."""
    settings = settings or get_settings()

    if settings.crm_base_url:
        base_url, resolved_transport = settings.crm_base_url, transport
    else:
        base_url = "http://leadguard.internal"
        resolved_transport = transport or (
            httpx.ASGITransport(app=app) if app is not None else None
        )

    return CRMClient(
        base_url=base_url,
        transport=resolved_transport,
        timeout=settings.crm_timeout_seconds,
        max_attempts=settings.crm_max_attempts,
        backoff=settings.crm_retry_backoff_seconds,
    )

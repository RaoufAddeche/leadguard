"""CRM integration: it must succeed, retry, and above all fail safely."""

import httpx
import pytest

from app.integrations.crm import CRMClient
from tests.conftest import lead_payload


class FlakyTransport(httpx.AsyncBaseTransport):
    """Fails the first ``fail_times`` calls, then succeeds."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(201, json={"crm_id": "CRM-TEST123"}, request=request)


class DeadTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request):
        self.calls += 1
        raise httpx.ConnectTimeout("the CRM is down", request=request)


class ErrorStatusTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        return httpx.Response(503, json={"detail": "unavailable"}, request=request)


async def test_successful_push_returns_the_crm_reference():
    client = CRMClient("http://crm.test", transport=FlakyTransport(0), backoff=0.0)

    result = await client.push_lead({"lead_id": "LD-2026-0001"})

    assert result.success is True
    assert result.reference == "CRM-TEST123"
    assert result.attempts == 1


async def test_transient_failure_is_retried_and_then_succeeds():
    transport = FlakyTransport(fail_times=2)
    client = CRMClient("http://crm.test", transport=transport, max_attempts=3, backoff=0.0)

    result = await client.push_lead({"lead_id": "LD-2026-0001"})

    assert result.success is True
    assert result.attempts == 3
    assert transport.calls == 3


async def test_retries_are_bounded():
    transport = DeadTransport()
    client = CRMClient("http://crm.test", transport=transport, max_attempts=3, backoff=0.0)

    result = await client.push_lead({"lead_id": "LD-2026-0001"})

    assert result.success is False
    assert transport.calls == 3, "must not retry forever"
    assert "ConnectTimeout" in result.error


async def test_http_error_status_is_treated_as_a_failure():
    client = CRMClient("http://crm.test", transport=ErrorStatusTransport(), max_attempts=1, backoff=0.0)

    result = await client.push_lead({"lead_id": "LD-2026-0001"})

    assert result.success is False
    assert "503" in result.error


async def test_a_crm_outage_does_not_crash_the_intake_request(client, monkeypatch):
    """The critical resilience guarantee: the lead is qualified and kept."""
    from app.main import app as fastapi_app

    fastapi_app.state.crm_client = CRMClient(
        "http://crm.test", transport=DeadTransport(), max_attempts=2, backoff=0.0
    )

    response = await client.post("/api/leads", json=lead_payload())

    # The request still succeeds.
    assert response.status_code == 201
    body = response.json()
    # The lead is fully qualified and routed in LeadGuard...
    assert body["status"] == "QUALIFIED"
    assert body["score"] >= 85
    assert body["team"] == "PAC Lyon"
    # ...and the CRM failure is recorded rather than raised.
    assert body["crm_status"] == "FAILED"

    detail = (await client.get(f"/api/leads/{body['lead_id']}")).json()
    assert detail["crm_error"]
    crm_events = [e for e in detail["events"] if e["event_type"] == "crm_sync"]
    assert "failed" in crm_events[-1]["message"].lower()
    assert "retained in LeadGuard" in crm_events[-1]["message"]


async def test_fake_crm_stores_and_exposes_what_it_received(client):
    await client.post("/api/leads", json=lead_payload())

    crm = (await client.get("/api/fake-crm/leads")).json()

    assert crm["count"] == 1
    record = crm["leads"][0]
    assert record["status"] == "QUALIFIED"
    assert record["team"] == "PAC Lyon"
    assert record["project_type"] == "heat_pump"
    assert record["crm_id"].startswith("CRM-")


async def test_fake_crm_rejects_a_payload_without_a_lead_id(client):
    response = await client.post("/api/fake-crm/leads", json={"firstname": "Thomas"})

    assert response.status_code == 422


async def test_only_qualified_leads_reach_the_crm(client):
    await client.post(
        "/api/leads",
        json=lead_payload(
            firstname="Marco", lastname="Rossi", email="marco.rossi@email.fr",
            phone="123", project_description="Des infos svp",
            owner=None, budget=None, consent=False,
        ),
    )

    crm = (await client.get("/api/fake-crm/leads")).json()

    assert crm["count"] == 0

"""Intake endpoint, validation boundary, audit trail and duplicates."""

import pytest

from app.services.fingerprint import compute_fingerprint
from tests.conftest import lead_create, lead_payload


async def test_excellent_lead_is_qualified_routed_and_synced(client):
    response = await client.post("/api/leads", json=lead_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "QUALIFIED"
    assert 85 <= body["score"] <= 95
    assert body["team"] == "PAC Lyon"
    assert body["public_id"].startswith("LD-")
    assert body["crm_status"] == "SUCCESS"
    assert body["duplicate"]["duplicate"] is False
    assert body["ai_analysis"]["project_type"] == "heat_pump"


async def test_medium_lead_goes_to_human_review_and_is_not_synced(client):
    response = await client.post(
        "/api/leads",
        json=lead_payload(
            firstname="Laura", lastname="Garcia", email="laura.garcia@email.fr",
            phone="0745129863", postal_code="34000",
            project_description=(
                "Je m'intéresse à l'installation de panneaux solaires photovoltaïques "
                "sur le toit de mon logement à Montpellier et je voudrais des renseignements."
            ),
            owner=None, budget=None,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "REVIEW"
    assert 50 <= body["score"] < 80
    # Nothing reaches the CRM until a human has decided.
    assert body["crm_status"] == "SKIPPED"


async def test_bad_lead_is_rejected_but_still_stored(client):
    """A rejection is auditable information, so the lead must be persisted."""
    response = await client.post(
        "/api/leads",
        json=lead_payload(
            firstname="Marco", lastname="Rossi", email="marco.rossi@email.fr",
            phone="123", project_description="Des infos svp",
            owner=None, budget=None, consent=False,
        ),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "REJECTED"
    assert body["score"] < 50
    assert body["team"] is None  # rejected leads are not routed
    assert body["crm_status"] == "SKIPPED"

    # It is retrievable afterwards.
    detail = await client.get(f"/api/leads/{body['lead_id']}")
    assert detail.status_code == 200
    assert detail.json()["consent"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"email": "not-an-email"},
        {"firstname": ""},
        {"project_description": ""},
        {"budget": -100},
    ],
    ids=["bad email", "empty firstname", "empty description", "negative budget"],
)
async def test_structurally_invalid_payloads_are_rejected_with_422(client, overrides):
    """Pydantic guards shape and presence — these never become leads."""
    response = await client.post("/api/leads", json=lead_payload(**overrides))

    assert response.status_code == 422


async def test_missing_required_field_is_rejected_with_422(client):
    payload = lead_payload()
    del payload["email"]

    response = await client.post("/api/leads", json=payload)

    assert response.status_code == 422


async def test_consent_is_timestamped_and_fingerprinted(client):
    response = await client.post("/api/leads", json=lead_payload())
    lead_id = response.json()["lead_id"]

    detail = (await client.get(f"/api/leads/{lead_id}")).json()

    assert detail["consent"] is True
    assert detail["consent_timestamp"] is not None
    # A SHA-256 digest, stable for identical input.
    assert len(detail["data_fingerprint"]) == 64
    assert detail["data_fingerprint"] == compute_fingerprint(lead_create())


async def test_fingerprint_changes_when_identifying_data_changes(client):
    baseline = compute_fingerprint(lead_create())

    assert compute_fingerprint(lead_create(email="other@email.fr")) != baseline
    assert compute_fingerprint(lead_create(phone="0799887766")) != baseline
    # Reformatting the free text must NOT change the identity fingerprint.
    assert compute_fingerprint(lead_create(project_description="Autre texte de projet.")) == baseline


async def test_audit_trail_records_every_pipeline_step(client):
    response = await client.post("/api/leads", json=lead_payload())
    body = response.json()

    recorded = [event["event_type"] for event in body["events"]]
    for expected in [
        "lead_received", "validation_passed", "consent_verified", "duplicate_check",
        "ai_analysis", "score_calculated", "status_changed", "routed", "crm_sync",
    ]:
        assert expected in recorded, f"missing audit event: {expected}"

    # The trail is ordered and each entry explains itself.
    assert recorded.index("lead_received") < recorded.index("score_calculated")
    assert recorded.index("score_calculated") < recorded.index("status_changed")
    assert all(event["message"].strip() for event in body["events"])


async def test_rule_breakdown_is_returned_for_auditability(client):
    body = (await client.post("/api/leads", json=lead_payload())).json()

    rules = {r["rule"]: r for r in body["rule_results"]}
    # Universal rules apply to every lead...
    assert "consent_check" in rules
    # ...and the heat pump eligibility rules apply because of the vertical.
    assert body["vertical"] == "heat_pump"
    assert rules["hp_owner_check"]["passed"] is True
    assert rules["hp_owner_check"]["score"] == 11
    assert rules["hp_owner_check"]["reason"]
    # An IT B2B rule must not appear on a heat pump lead.
    assert "b2b_decision_power_check" not in rules
    # Points never exceed the declared weight.
    for rule in body["rule_results"]:
        assert rule["score"] <= max(rule["max_score"], 0)


async def test_duplicate_is_detected_on_the_second_submission(client):
    first = (await client.post("/api/leads", json=lead_payload())).json()
    second = (await client.post("/api/leads", json=lead_payload())).json()

    assert first["duplicate"]["duplicate"] is False
    assert second["duplicate"]["duplicate"] is True
    assert second["duplicate"]["duplicate_lead_id"] == first["public_id"]
    assert second["duplicate"]["similarity"] >= 80
    # Penalised, and never auto-qualified.
    assert second["score"] < first["score"]
    assert second["status"] == "REVIEW"


async def test_duplicate_matches_on_phone_alone(client):
    first = (await client.post("/api/leads", json=lead_payload())).json()
    second = (
        await client.post(
            "/api/leads",
            json=lead_payload(firstname="Thom", lastname="Marten", email="different@email.fr"),
        )
    ).json()

    assert second["duplicate"]["duplicate"] is True
    assert second["duplicate"]["duplicate_lead_id"] == first["public_id"]


async def test_duplicate_matches_on_email_alone(client):
    first = (await client.post("/api/leads", json=lead_payload())).json()
    second = (
        await client.post("/api/leads", json=lead_payload(phone="0799887766", lastname="Autre"))
    ).json()

    assert second["duplicate"]["duplicate"] is True
    assert second["duplicate"]["duplicate_lead_id"] == first["public_id"]


async def test_phone_formatting_differences_still_match(client):
    """+33 and 0-prefixed forms are the same number."""
    await client.post("/api/leads", json=lead_payload())
    second = (
        await client.post(
            "/api/leads",
            json=lead_payload(email="other@email.fr", lastname="Autre", phone="+33 6 12 34 56 78"),
        )
    ).json()

    assert second["duplicate"]["duplicate"] is True


async def test_distinct_leads_are_not_flagged_as_duplicates(client):
    await client.post("/api/leads", json=lead_payload())
    other = (
        await client.post(
            "/api/leads",
            json=lead_payload(
                firstname="Karim", lastname="Benali", email="karim.benali@email.fr",
                phone="0623987451", postal_code="13008",
            ),
        )
    ).json()

    assert other["duplicate"]["duplicate"] is False


async def test_dashboard_stats_are_computed_from_the_database(client):
    await client.post("/api/leads", json=lead_payload())
    await client.post(
        "/api/leads",
        json=lead_payload(
            firstname="Marco", lastname="Rossi", email="marco.rossi@email.fr",
            phone="123", project_description="Des infos svp",
            owner=None, budget=None, consent=False,
        ),
    )

    stats = (await client.get("/api/leads/stats")).json()

    assert stats["total"] == 2
    assert stats["qualified"] == 1
    assert stats["rejected"] == 1
    assert stats["qualification_rate"] == 50.0


async def test_lead_list_can_be_filtered_by_status(client):
    await client.post("/api/leads", json=lead_payload())

    qualified = (await client.get("/api/leads", params={"status": "QUALIFIED"})).json()
    rejected = (await client.get("/api/leads", params={"status": "REJECTED"})).json()

    assert len(qualified) == 1
    assert rejected == []


async def test_unknown_lead_returns_404(client):
    response = await client.get("/api/leads/9999")

    assert response.status_code == 404

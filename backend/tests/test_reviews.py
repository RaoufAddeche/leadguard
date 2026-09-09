"""Human-in-the-loop: the reviewer's verdict and its historisation."""

from tests.conftest import lead_payload

LAURA = lead_payload(
    firstname="Laura", lastname="Garcia", email="laura.garcia@email.fr",
    phone="0745129863", postal_code="34000",
    project_description=(
        "Je m'intéresse à l'installation de panneaux solaires photovoltaïques sur le "
        "toit de mon logement à Montpellier et je voudrais des renseignements."
    ),
    owner=None, budget=None,
)


async def test_review_queue_lists_only_undecided_review_leads(client):
    await client.post("/api/leads", json=lead_payload())  # QUALIFIED
    await client.post("/api/leads", json=LAURA)           # REVIEW

    queue = (await client.get("/api/reviews")).json()

    assert len(queue) == 1
    assert queue[0]["full_name"] == "Laura Garcia"
    assert queue[0]["system_status"] == "REVIEW"


async def test_human_qualify_updates_status_routes_and_syncs(client):
    created = (await client.post("/api/leads", json=LAURA)).json()
    assert created["crm_status"] == "SKIPPED"

    response = await client.post(
        f"/api/reviews/{created['lead_id']}",
        json={"decision": "QUALIFIED", "reviewer": "demo-user", "reason": "Ownership confirmed by phone"},
    )

    assert response.status_code == 200
    body = response.json()
    # Both decisions are kept side by side.
    assert body["system_status"] == "REVIEW"
    assert body["human_status"] == "QUALIFIED"
    assert body["status"] == "QUALIFIED"  # the human decision wins
    assert body["reviewer"] == "demo-user"
    assert body["reviewed_at"] is not None
    assert body["review_reason"] == "Ownership confirmed by phone"
    # A human upgrade triggers the same downstream flow as an automatic one.
    assert body["routed_team"] == "Solar South"
    assert body["crm_status"] == "SUCCESS"


async def test_human_reject_is_recorded_and_never_synced(client):
    created = (await client.post("/api/leads", json=LAURA)).json()

    body = (
        await client.post(
            f"/api/reviews/{created['lead_id']}",
            json={"decision": "REJECTED", "reviewer": "demo-user", "reason": "Tenant, not the owner"},
        )
    ).json()

    assert body["human_status"] == "REJECTED"
    assert body["status"] == "REJECTED"
    assert body["crm_status"] == "SKIPPED"


async def test_human_decision_is_written_to_the_audit_trail(client):
    created = (await client.post("/api/leads", json=LAURA)).json()

    body = (
        await client.post(
            f"/api/reviews/{created['lead_id']}",
            json={"decision": "QUALIFIED", "reviewer": "alice"},
        )
    ).json()

    review_events = [e for e in body["events"] if e["event_type"] == "human_review"]
    assert len(review_events) == 1
    assert "alice" in review_events[0]["message"]
    assert "QUALIFIED" in review_events[0]["message"]
    # The trail still holds the original automatic decision.
    assert any(e["event_type"] == "status_changed" for e in body["events"])


async def test_the_score_is_never_rewritten_by_a_human_decision(client):
    """The engine's score stays as evidence of what the rules computed."""
    created = (await client.post("/api/leads", json=LAURA)).json()

    body = (
        await client.post(
            f"/api/reviews/{created['lead_id']}", json={"decision": "QUALIFIED", "reviewer": "bob"}
        )
    ).json()

    assert body["score"] == created["score"]


async def test_a_lead_cannot_be_reviewed_twice(client):
    created = (await client.post("/api/leads", json=LAURA)).json()
    await client.post(f"/api/reviews/{created['lead_id']}", json={"decision": "QUALIFIED"})

    second = await client.post(
        f"/api/reviews/{created['lead_id']}", json={"decision": "REJECTED"}
    )

    assert second.status_code == 409


async def test_review_cannot_set_the_status_back_to_review(client):
    created = (await client.post("/api/leads", json=LAURA)).json()

    response = await client.post(f"/api/reviews/{created['lead_id']}", json={"decision": "REVIEW"})

    assert response.status_code == 422


async def test_reviewing_an_unknown_lead_returns_404(client):
    response = await client.post("/api/reviews/9999", json={"decision": "QUALIFIED"})

    assert response.status_code == 404

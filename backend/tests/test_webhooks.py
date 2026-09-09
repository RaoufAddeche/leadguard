"""Webhooks must reuse the pipeline, not re-implement it."""

from tests.conftest import lead_payload


async def test_webhook_and_api_produce_identical_qualification(client):
    """The core guarantee: one pipeline, two entry points."""
    via_api = (await client.post("/api/leads", json=lead_payload())).json()
    via_webhook = (
        await client.post(
            "/api/webhooks/leads",
            json=lead_payload(email="other@email.fr", phone="0700000000", lastname="Dupont"),
        )
    ).json()

    assert via_webhook["score"] == via_api["score"]
    assert via_webhook["status"] == via_api["status"]
    assert via_webhook["team"] == via_api["team"]
    assert [r["rule"] for r in via_webhook["rule_results"]] == [
        r["rule"] for r in via_api["rule_results"]
    ]


async def test_webhook_records_its_channel_in_the_audit_trail(client):
    body = (
        await client.post("/api/webhooks/leads", json=lead_payload(source="google_ads"))
    ).json()

    received = next(e for e in body["events"] if e["event_type"] == "lead_received")
    assert "webhook:google_ads" in received["message"]


async def test_google_ads_lead_form_payload_is_mapped(client):
    """Google Ads nests the answers in user_column_data."""
    response = await client.post(
        "/api/webhooks/leads",
        json={
            "source": "google_ads",
            "campaign_name": "PAC_Lyon",
            "user_column_data": [
                {"column_id": "FIRST_NAME", "string_value": "Thomas"},
                {"column_id": "LAST_NAME", "string_value": "Martin"},
                {"column_id": "EMAIL", "string_value": "thomas.martin@email.fr"},
                {"column_id": "PHONE_NUMBER", "string_value": "0612345678"},
                {"column_id": "POSTAL_CODE", "string_value": "69003"},
            ],
            "project_description": (
                "Je souhaite remplacer ma chaudière fioul par une pompe à chaleur "
                "dans ma maison avant l'hiver."
            ),
            "owner": "true",
            "budget": "12 000 €",
            "consent": "yes",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "QUALIFIED"
    assert body["team"] == "PAC Lyon"

    detail = (await client.get(f"/api/leads/{body['lead_id']}")).json()
    assert detail["firstname"] == "Thomas"
    assert detail["owner"] is True          # "true" coerced
    assert detail["budget"] == 12000.0      # "12 000 €" coerced
    assert detail["consent"] is True        # "yes" coerced


async def test_meta_ads_field_data_payload_is_mapped(client):
    """Meta Ads uses field_data with name/values pairs."""
    response = await client.post(
        "/api/webhooks/leads",
        json={
            "platform": "meta_ads",
            "campaign": "Solaire_Sud",
            "field_data": [
                {"name": "first_name", "values": ["Karim"]},
                {"name": "last_name", "values": ["Benali"]},
                {"name": "email", "values": ["karim.benali@email.fr"]},
                {"name": "phone_number", "values": ["0623987451"]},
                {"name": "zip", "values": ["13008"]},
            ],
            "message": (
                "Je souhaite faire installer des panneaux solaires sur ma maison à "
                "Marseille dès que possible."
            ),
            "is_owner": True,
            "budget": 14000,
            "opt_in": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["ai_analysis"]["project_type"] == "solar"
    assert body["team"] == "Solar South"


async def test_partner_form_with_french_field_names_is_mapped(client):
    response = await client.post(
        "/api/webhooks/leads",
        json={
            "source": "partner_form",
            "campaign": "Partenaire_Isolation",
            "prenom": "Julie",
            "nom": "Petit",
            "mail": "julie.petit@email.fr",
            "telephone": "0699123456",
            "code_postal": "44000",
            "projet": "Je veux faire isoler les combles de ma maison rapidement, budget 9000 euros.",
            "proprietaire": "oui",
            "budget": "9000",
            "consentement": "oui",
        },
    )

    assert response.status_code == 201
    detail = (await client.get(f"/api/leads/{response.json()['lead_id']}")).json()
    assert detail["firstname"] == "Julie"
    assert detail["consent"] is True
    assert detail["ai_analysis"]["project_type"] == "insulation"


async def test_envelope_wrapped_payload_is_unwrapped(client):
    response = await client.post(
        "/api/webhooks/leads",
        json={"source": "external", "data": lead_payload(email="wrapped@email.fr")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "QUALIFIED"


async def test_unmappable_webhook_returns_422_rather_than_being_swallowed(client):
    """The sender must learn its payload was wrong."""
    response = await client.post(
        "/api/webhooks/leads", json={"source": "google_ads", "something": "irrelevant"}
    )

    assert response.status_code == 422


async def test_unknown_source_falls_back_to_the_generic_adapter(client):
    response = await client.post(
        "/api/webhooks/leads", json=lead_payload(source="some_new_partner")
    )

    assert response.status_code == 201
    assert response.json()["status"] == "QUALIFIED"


async def test_webhook_detects_duplicates_against_api_submitted_leads(client):
    """Cross-channel dedup: the same person via two different entry points."""
    first = (await client.post("/api/leads", json=lead_payload())).json()
    second = (await client.post("/api/webhooks/leads", json=lead_payload())).json()

    assert second["duplicate"]["duplicate"] is True
    assert second["duplicate"]["duplicate_lead_id"] == first["public_id"]

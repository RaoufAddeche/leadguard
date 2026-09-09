"""Routing: the right team for the right lead.

Routing is keyed on the vertical first — each one is bought by a different
client team — then refined by geography or deal shape where that matters.
"""

import pytest

from app.models.enums import Vertical, vertical_for
from app.routing import route
from app.schemas.lead import AIAnalysis
from tests.conftest import lead_create


def analysis(project_type: str, **details) -> AIAnalysis:
    return AIAnalysis(
        project_type=project_type,
        urgency="high",
        purchase_intent="high",
        summary="test",
        details=details,
    )


@pytest.mark.parametrize(
    "project_type,postal_code,expected_team",
    [
        # Heat pump: a regional installer network.
        ("heat_pump", "69003", "PAC Lyon"),       # Rhône
        ("heat_pump", "38000", "PAC Lyon"),       # Isère, same regional desk
        ("heat_pump", "75011", "PAC Paris"),      # Île-de-France
        ("heat_pump", "29200", "PAC National"),   # outside covered regions
        # Solar: irradiation matters.
        ("solar", "13008", "Solar South"),
        ("solar", "59000", "Solar National"),
        # Energy renovation rolls up three project types.
        ("insulation", "44000", "Renovation National"),
        ("windows", "44000", "Renovation National"),
        ("boiler", "69003", "Renovation National"),
        # Hearing aids: a network of fitting centres.
        ("hearing_aid", "75011", "Audio Île-de-France"),
        ("hearing_aid", "33000", "Audio National"),
        # No vertical -> the general desk.
        ("unknown", "69003", "General Sales"),
    ],
)
def test_routing_picks_the_expected_team(project_type, postal_code, expected_team):
    lead = lead_create(postal_code=postal_code)
    decision = route(lead, analysis(project_type))

    assert decision.team == expected_team
    assert decision.reason.strip(), "a routing decision must be explainable"


@pytest.mark.parametrize(
    "need_type,expected_team",
    [
        ("borrower", "Assurance Emprunteur"),
        ("provident", "Prévoyance"),
        ("health", "Santé Individuelle"),
        (None, "Santé Individuelle"),
    ],
)
def test_health_insurance_routes_on_the_nature_of_the_need(need_type, expected_team):
    """Borrower insurance is sold by a different team from health cover."""
    lead = lead_create(postal_code="31000")
    decision = route(lead, analysis("health_insurance", need_type=need_type))

    assert decision.team == expected_team


@pytest.mark.parametrize(
    "company_size,expected_team",
    [
        ("large", "IT Enterprise"),
        ("mid", "IT Enterprise"),
        ("small", "IT SMB"),
        ("micro", "IT SMB"),
        (None, "IT SMB"),
    ],
)
def test_it_b2b_routes_on_company_size(company_size, expected_team):
    lead = lead_create(postal_code="92100")
    decision = route(lead, analysis("it_b2b", company_size=company_size))

    assert decision.team == expected_team


def test_whole_home_renovation_gets_its_own_desk():
    lead = lead_create(postal_code="59000")

    globally = route(lead, analysis("insulation", works_type="global"))
    single = route(lead, analysis("insulation", works_type="insulation"))

    assert globally.team == "Renovation Global"
    assert single.team == "Renovation National"


@pytest.mark.parametrize(
    "country,expected_team",
    [("ES", "Iberia Desk"), ("IT", "Italy Desk")],
)
def test_non_french_markets_go_to_their_country_desk(country, expected_team):
    """The country desk takes precedence over any French regional split."""
    phones = {"ES": "612345678", "IT": "3401234567"}
    lead = lead_create(country=country, postal_code="08001", phone=phones[country])

    decision = route(lead, analysis("solar"))

    assert decision.team == expected_team


def test_routing_always_returns_a_team():
    """No qualified lead may ever be left unrouted."""
    lead = lead_create(postal_code="99999")

    for project_type in (
        "heat_pump", "solar", "hearing_aid", "health_insurance",
        "insulation", "it_b2b", "unknown", "nonsense",
    ):
        assert route(lead, analysis(project_type)).team


def test_every_vertical_has_at_least_one_dedicated_team():
    """A vertical with no routing rule of its own would silently fall through
    to General Sales, which would look like a bug in production."""
    lead = lead_create(postal_code="69003")

    for vertical in Vertical:
        if vertical is Vertical.UNKNOWN:
            continue
        team = route(lead, analysis(vertical.value), vertical).team
        assert team != "General Sales", f"{vertical.value} falls through to the general desk"


def test_project_types_roll_up_into_the_expected_vertical():
    assert vertical_for("insulation") is Vertical.ENERGY_RENOVATION
    assert vertical_for("windows") is Vertical.ENERGY_RENOVATION
    assert vertical_for("boiler") is Vertical.ENERGY_RENOVATION
    assert vertical_for("heat_pump") is Vertical.HEAT_PUMP
    assert vertical_for("it_b2b") is Vertical.IT_B2B
    # Junk must never raise.
    assert vertical_for("something_new") is Vertical.UNKNOWN
    assert vertical_for(None) is Vertical.UNKNOWN

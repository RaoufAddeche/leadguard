"""Lead routing.

Routing is keyed on the vertical first, because each vertical is bought by a
different client team, and only then refined by geography where that matters.

Declarative rule list, evaluated top to bottom: the first match wins, and the
last entry is an always-true fallback so a qualified lead is never orphaned.
"""

from dataclasses import dataclass
from typing import Callable

from app.models.enums import Country, Vertical, vertical_for
from app.schemas.lead import AIAnalysis, LeadCreate, RoutingDecision

# French départements grouped into regional desks.
RHONE_ALPES = ("69", "38", "73", "74", "01", "42")
ILE_DE_FRANCE = ("75", "77", "78", "91", "92", "93", "94", "95")
SOUTH = ("13", "83", "06", "84", "34", "30", "66", "11")


@dataclass(frozen=True)
class RoutingRule:
    team: str
    reason: str
    matches: Callable[[LeadCreate, AIAnalysis, Vertical], bool]


def _dept(postal_code: str) -> str:
    return postal_code.strip()[:2]


def _is(vertical: Vertical) -> Callable[[LeadCreate, AIAnalysis, Vertical], bool]:
    return lambda lead, ai, v: v is vertical


ROUTING_RULES: list[RoutingRule] = [
    # --- Non-French markets go to their country desk before any French
    #     regional split is considered.
    RoutingRule(
        team="Iberia Desk",
        reason="Spanish market: handled by the Iberia desk",
        matches=lambda lead, ai, v: Country(lead.country) is Country.ES,
    ),
    RoutingRule(
        team="Italy Desk",
        reason="Italian market: handled by the Italy desk",
        matches=lambda lead, ai, v: Country(lead.country) is Country.IT,
    ),

    # --- Heat pump: regional installer network.
    RoutingRule(
        team="PAC Lyon",
        reason="Heat pump project located in the Rhône-Alpes area",
        matches=lambda lead, ai, v: v is Vertical.HEAT_PUMP and _dept(lead.postal_code) in RHONE_ALPES,
    ),
    RoutingRule(
        team="PAC Paris",
        reason="Heat pump project located in the Île-de-France area",
        matches=lambda lead, ai, v: v is Vertical.HEAT_PUMP and _dept(lead.postal_code) in ILE_DE_FRANCE,
    ),
    RoutingRule(
        team="PAC National",
        reason="Heat pump project outside the covered regional areas",
        matches=_is(Vertical.HEAT_PUMP),
    ),

    # --- Solar: irradiation matters, so the south gets its own desk.
    RoutingRule(
        team="Solar South",
        reason="Solar project in a high-irradiation southern département",
        matches=lambda lead, ai, v: v is Vertical.SOLAR and _dept(lead.postal_code) in SOUTH,
    ),
    RoutingRule(
        team="Solar National",
        reason="Solar project outside the southern belt",
        matches=_is(Vertical.SOLAR),
    ),

    # --- Energy renovation: one national desk, split by works type.
    RoutingRule(
        team="Renovation Global",
        reason="Whole-home renovation: handled by the global renovation desk",
        matches=lambda lead, ai, v: (
            v is Vertical.ENERGY_RENOVATION and (ai.details or {}).get("works_type") == "global"
        ),
    ),
    RoutingRule(
        team="Renovation National",
        reason="Single-measure energy renovation project",
        matches=_is(Vertical.ENERGY_RENOVATION),
    ),

    # --- Hearing aids: a network of fitting centres, so geography again.
    RoutingRule(
        team="Audio Île-de-France",
        reason="Hearing aid lead within reach of the Île-de-France fitting centres",
        matches=lambda lead, ai, v: (
            v is Vertical.HEARING_AID and _dept(lead.postal_code) in ILE_DE_FRANCE
        ),
    ),
    RoutingRule(
        team="Audio National",
        reason="Hearing aid lead handled by the national fitting network",
        matches=_is(Vertical.HEARING_AID),
    ),

    # --- Health insurance: split by the nature of the need, since borrower
    #     insurance is sold by a different team from health cover.
    RoutingRule(
        team="Assurance Emprunteur",
        reason="Borrower insurance: handled by the loan insurance team",
        matches=lambda lead, ai, v: (
            v is Vertical.HEALTH_INSURANCE and (ai.details or {}).get("need_type") == "borrower"
        ),
    ),
    RoutingRule(
        team="Prévoyance",
        reason="Income protection need: handled by the provident team",
        matches=lambda lead, ai, v: (
            v is Vertical.HEALTH_INSURANCE and (ai.details or {}).get("need_type") == "provident"
        ),
    ),
    RoutingRule(
        team="Santé Individuelle",
        reason="Complementary health cover for an individual or a family",
        matches=_is(Vertical.HEALTH_INSURANCE),
    ),

    # --- IT B2B: split by company size, since enterprise and SMB are sold
    #     by different teams.
    RoutingRule(
        team="IT Enterprise",
        reason="Mid-sized or large company: handled by the enterprise team",
        matches=lambda lead, ai, v: (
            v is Vertical.IT_B2B and (ai.details or {}).get("company_size") in ("mid", "large")
        ),
    ),
    RoutingRule(
        team="IT SMB",
        reason="Small business IT project",
        matches=_is(Vertical.IT_B2B),
    ),

    # --- Fallback: always matches.
    RoutingRule(
        team="General Sales",
        reason="No vertical could be identified: routed to the general desk",
        matches=lambda lead, ai, v: True,
    ),
]


def route(lead: LeadCreate, ai: AIAnalysis, vertical: Vertical | None = None) -> RoutingDecision:
    vertical = vertical or vertical_for(ai.project_type)
    for rule in ROUTING_RULES:
        if rule.matches(lead, ai, vertical):
            return RoutingDecision(team=rule.team, reason=rule.reason)
    # Unreachable: the last rule always matches.
    return RoutingDecision(team="General Sales", reason="Fallback routing")

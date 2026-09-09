"""Business rules.

Two families, because a lead-generation business does not qualify every
vertical the same way:

* ``UNIVERSAL_RULES`` (68 points) — true of any lead in any vertical:
  consent, contactability, coherence, intent, urgency, and the duplicate
  penalty.
* ``VERTICAL_RULES`` (32 points) — the eligibility criteria specific to one
  line of business. A heat pump lead is worth nothing without property
  ownership; an IT B2B lead is worth nothing without decision-making power.
  Neither criterion means anything in the other vertical.

That split is why ``owner`` no longer costs an IT B2B contact 15 points for
not owning a house.

Every rule is a small pure function with the same signature. Adding, removing
or reweighting one is a one-line change and requires no modification to the
engine.

Invariant, enforced by a test: for every known vertical,
``universal_max + vertical_max == 100``. A lead whose vertical could not be
identified is therefore capped at 68 — it can never be auto-qualified,
because the third of the scale that checks eligibility was never run.
"""

import re
from dataclasses import dataclass, field
from typing import Callable

from app.models.enums import Country, Level, ProjectType, Vertical
from app.schemas.lead import AIAnalysis, LeadCreate, RuleResult

# --- Contactability ------------------------------------------------------
# The platform operates in France, Spain and Italy, so a lead is validated
# against its own country's numbering plan rather than being assumed French.
PHONE_PATTERNS: dict[Country, re.Pattern[str]] = {
    Country.FR: re.compile(r"^(?:\+33|0033|0)\s?[1-9](?:[\s.\-]?\d{2}){4}$"),
    # Spain: 9 digits starting 6/7 (mobile) or 8/9 (landline).
    Country.ES: re.compile(r"^(?:\+34|0034)?\s?[6789](?:[\s.\-]?\d{2}){4}$"),
    # Italy: mobile 3xx (9-10 digits), landline 0x prefixed.
    Country.IT: re.compile(r"^(?:\+39|0039)?\s?(?:3\d{2}[\s.\-]?\d{6,7}|0\d{1,3}[\s.\-]?\d{6,8})$"),
}

POSTAL_PATTERNS: dict[Country, re.Pattern[str]] = {
    Country.FR: re.compile(r"^\d{5}$"),
    Country.ES: re.compile(r"^\d{5}$"),
    Country.IT: re.compile(r"^\d{5}$"),
}

MIN_DESCRIPTION_LENGTH = 40

DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "yopmail.com", "tempmail.com", "guerrillamail.com",
    "10minutemail.com", "trashmail.com",
})

# Reference project cost per vertical, used to check that a stated budget is
# realistic for the work requested rather than merely present. ``None`` means
# budget is not a qualifying criterion for that vertical.
REFERENCE_BUDGET: dict[Vertical, float | None] = {
    Vertical.HEAT_PUMP: 15000,
    Vertical.SOLAR: 12000,
    Vertical.ENERGY_RENOVATION: 9000,
    Vertical.HEARING_AID: None,
    Vertical.HEALTH_INSURANCE: None,
    Vertical.IT_B2B: None,
    Vertical.UNKNOWN: None,
}


def is_valid_phone(phone: str, country: Country | str = Country.FR) -> bool:
    pattern = PHONE_PATTERNS.get(Country(country))
    return bool(pattern and pattern.match(phone.strip()))


def is_valid_postal_code(postal_code: str, country: Country | str = Country.FR) -> bool:
    pattern = POSTAL_PATTERNS.get(Country(country))
    return bool(pattern and pattern.match(postal_code.strip()))


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule is allowed to look at."""

    lead: LeadCreate
    ai: AIAnalysis
    vertical: Vertical = Vertical.UNKNOWN
    is_duplicate: bool = False

    @property
    def details(self) -> dict:
        return self.ai.details or {}

    def detail(self, key: str, default=None):
        return self.details.get(key, default)


@dataclass(frozen=True)
class Rule:
    name: str
    max_score: int
    evaluate: Callable[[RuleContext], tuple[int, bool, str]]

    def run(self, ctx: RuleContext) -> RuleResult:
        score, passed, reason = self.evaluate(ctx)
        # Defensive clamp: a rule can never award more than its declared
        # weight. A negative weight marks a penalty-only rule, whose score is
        # clamped to [max_score, 0] so it can subtract but never add points.
        low, high = (self.max_score, 0) if self.max_score < 0 else (0, self.max_score)
        score = max(low, min(score, high))
        return RuleResult(
            rule=self.name,
            passed=passed,
            score=score,
            max_score=self.max_score,
            reason=reason,
        )


# =========================================================================
#  Universal rules — 68 points, every vertical
# =========================================================================

def _consent_check(ctx: RuleContext) -> tuple[int, bool, str]:
    if ctx.lead.consent:
        return 20, True, "Explicit marketing consent granted"
    return 0, False, "No consent: the lead cannot be contacted (GDPR)"


def _email_check(ctx: RuleContext) -> tuple[int, bool, str]:
    domain = str(ctx.lead.email).split("@")[-1].lower()
    if domain in DISPOSABLE_DOMAINS:
        return 0, False, f"Disposable email domain ({domain})"
    return 8, True, "Valid email address"


def _phone_check(ctx: RuleContext) -> tuple[int, bool, str]:
    country = Country(ctx.lead.country)
    if is_valid_phone(ctx.lead.phone, country):
        return 8, True, f"Valid {country.value} phone number"
    return 0, False, f"Invalid phone number for {country.value} ({ctx.lead.phone})"


def _project_consistency_check(ctx: RuleContext) -> tuple[int, bool, str]:
    known = ctx.vertical is not Vertical.UNKNOWN
    detailed = len(ctx.lead.project_description) >= MIN_DESCRIPTION_LENGTH

    if known and detailed:
        return 12, True, f"Clear, detailed {ctx.vertical.value.replace('_', ' ')} request"
    if known:
        return 7, True, "Vertical identified but the description is very short"
    if detailed:
        return 4, False, "Detailed description but no identifiable vertical"
    return 0, False, "Description is too vague to identify a project"


def _purchase_intent_check(ctx: RuleContext) -> tuple[int, bool, str]:
    match ctx.ai.purchase_intent:
        case Level.HIGH:
            return 10, True, "Strong purchase intent detected"
        case Level.MEDIUM:
            return 5, True, "Moderate purchase intent detected"
        case _:
            return 0, False, "No clear purchase intent detected"


def _urgency_check(ctx: RuleContext) -> tuple[int, bool, str]:
    match ctx.ai.urgency:
        case Level.HIGH:
            return 10, True, "High urgency: prospect has a near-term deadline"
        case Level.MEDIUM:
            return 5, True, "Moderate urgency"
        case _:
            return 0, False, "No time constraint expressed"


def _duplicate_check(ctx: RuleContext) -> tuple[int, bool, str]:
    """Penalty-only rule: it can subtract points but never add any."""
    if ctx.is_duplicate:
        return -40, False, "Duplicate of an existing lead: heavy penalty applied"
    return 0, True, "No duplicate found"


UNIVERSAL_RULES: list[Rule] = [
    Rule("consent_check", 20, _consent_check),
    Rule("email_check", 8, _email_check),
    Rule("phone_check", 8, _phone_check),
    Rule("project_consistency_check", 12, _project_consistency_check),
    Rule("purchase_intent_check", 10, _purchase_intent_check),
    Rule("urgency_check", 10, _urgency_check),
    Rule("duplicate_check", -40, _duplicate_check),
]


# =========================================================================
#  Shared helper: budget realism, where budget is a criterion at all
# =========================================================================

def _budget_rule(points: int) -> Callable[[RuleContext], tuple[int, bool, str]]:
    """Budget checked against the reference cost of the lead's own vertical."""

    def check(ctx: RuleContext) -> tuple[int, bool, str]:
        budget = ctx.lead.budget
        reference = REFERENCE_BUDGET.get(ctx.vertical)

        if not budget:
            return 0, False, "No budget provided"
        if reference is None:
            return points, True, f"Budget of {budget:,.0f} EUR recorded"
        if budget >= reference:
            return points, True, f"Budget of {budget:,.0f} EUR is adequate for this project type"
        if budget >= reference * 0.6:
            return (
                round(points * 0.55),
                True,
                f"Budget of {budget:,.0f} EUR is below the {reference:,.0f} EUR reference "
                "for this project type but remains workable",
            )
        return (
            round(points * 0.25),
            False,
            f"Budget of {budget:,.0f} EUR is unrealistic for this project type "
            f"(reference {reference:,.0f} EUR)",
        )

    return check


# =========================================================================
#  Heat pump — ownership · current heating and its age · surface and type
# =========================================================================

def _hp_owner(ctx: RuleContext) -> tuple[int, bool, str]:
    if ctx.lead.owner is True:
        return 11, True, "Owns the property to be equipped"
    if ctx.lead.owner is False:
        return 0, False, "Not the owner: cannot commission a heat pump installation"
    if ctx.ai.owner_intent is True:
        return 6, True, "Ownership implied by the description (unconfirmed)"
    return 0, False, "Property ownership not confirmed"


# A heat pump replacing oil or old gas is the highest-value case, which is
# why the system AND its age are both needed for full marks.
HIGH_VALUE_HEATING = {"oil_boiler", "gas_boiler", "electric"}


def _hp_current_heating(ctx: RuleContext) -> tuple[int, bool, str]:
    system = ctx.detail("heating_system")
    age = ctx.detail("heating_age_years")

    if system is None:
        return 0, False, "Current heating system not stated"
    label = system.replace("_", " ")
    if system == "heat_pump":
        return 2, False, "Already equipped with a heat pump: low replacement potential"
    if system in HIGH_VALUE_HEATING and age is not None:
        return 8, True, f"Replacing {label} aged {age} years: strong replacement case"
    if system in HIGH_VALUE_HEATING:
        return 5, True, f"Replacing {label}, but its age is unknown"
    return 3, True, f"Current heating is {label}"


def _hp_property(ctx: RuleContext) -> tuple[int, bool, str]:
    surface = ctx.detail("surface_m2")
    property_type = ctx.ai.property_type

    known_type = property_type in ("house", "apartment")
    if surface and known_type:
        return 6, True, f"{property_type.capitalize()} of {surface} m²: sizing is possible"
    if surface:
        return 4, True, f"Surface of {surface} m² given, property type unclear"
    if known_type:
        return 3, True, f"Property type is a {property_type}, surface unknown"
    return 0, False, "Neither surface nor property type could be determined"


# =========================================================================
#  Solar — roof ownership · cover and orientation · self-consumption model
# =========================================================================

def _pv_roof_owner(ctx: RuleContext) -> tuple[int, bool, str]:
    if ctx.lead.owner is True:
        return 11, True, "Owns the roof concerned"
    if ctx.lead.owner is False:
        return 0, False, "Not the owner: cannot authorise work on the roof"
    if ctx.ai.owner_intent is True:
        return 6, True, "Roof ownership implied by the description (unconfirmed)"
    return 0, False, "Roof ownership not confirmed"


GOOD_ORIENTATIONS = {"south", "south_east", "south_west"}
POOR_ORIENTATIONS = {"north"}
UNSUITABLE_COVERS = {"fibre_cement"}


def _pv_roof_profile(ctx: RuleContext) -> tuple[int, bool, str]:
    cover = ctx.detail("roof_cover")
    orientation = ctx.detail("roof_orientation")

    if cover in UNSUITABLE_COVERS:
        return 0, False, f"Roof cover ({cover.replace('_', ' ')}) usually requires removal first"
    if orientation in POOR_ORIENTATIONS:
        return 0, False, "North-facing roof: poor yield"
    if cover and orientation in GOOD_ORIENTATIONS:
        return 7, True, f"{cover.capitalize()} roof facing {orientation.replace('_', '-')}: well suited"
    if orientation in GOOD_ORIENTATIONS:
        return 5, True, f"Roof faces {orientation.replace('_', '-')}, cover unknown"
    if cover:
        return 3, True, f"{cover.capitalize()} roof, orientation unknown"
    return 0, False, "Neither roof cover nor orientation could be determined"


def _pv_usage_model(ctx: RuleContext) -> tuple[int, bool, str]:
    usage = ctx.detail("usage_model")
    if usage == "self_consumption":
        return 7, True, "Self-consumption project: clear, well-defined intent"
    if usage == "surplus_resale":
        return 6, True, "Surplus resale project: clear, well-defined intent"
    return 0, False, "Neither self-consumption nor surplus resale was mentioned"


# =========================================================================
#  Hearing aids — self-declared difficulty · age and support · coverage
# =========================================================================

def _ha_self_declared(ctx: RuleContext) -> tuple[int, bool, str]:
    """The hearing difficulty must be declared by the person themselves.

    A relative enquiring on someone else's behalf is not a qualified lead:
    the person concerned has neither expressed the need nor given consent for
    their health data to be processed. This is the strictest rule in the set.
    """
    declared = ctx.detail("self_declared")
    if declared is True:
        return 12, True, "Hearing difficulty declared by the person themselves"
    if declared is False:
        return 0, False, (
            "Enquiry made on behalf of a third party: the person concerned has not "
            "declared the difficulty themselves"
        )
    return 0, False, "It is unclear whether the person concerned declared the difficulty"


def _ha_age_context(ctx: RuleContext) -> tuple[int, bool, str]:
    bracket = ctx.detail("age_bracket")
    accompanied = ctx.detail("accompanied")

    if bracket is None:
        return 0, False, "Age bracket unknown"
    label = bracket.replace("_", "-")
    if bracket in ("65_74", "75_plus"):
        bonus = 10 if accompanied else 8
        note = " and is accompanied" if accompanied else ""
        return bonus, True, f"In the {label} bracket{note}: strong fitting profile"
    if bracket == "50_64":
        return 7, True, f"In the {label} bracket"
    return 4, True, f"In the {label} bracket: less typical for fitting"


def _ha_coverage(ctx: RuleContext) -> tuple[int, bool, str]:
    coverage = ctx.detail("has_coverage")
    if coverage is True:
        return 10, True, "Has complementary health cover: fitting is partly reimbursed"
    if coverage is False:
        return 2, False, "No complementary health cover: out-of-pocket cost is a barrier"
    return 0, False, "Health cover status unknown"


# =========================================================================
#  Health insurance — need type · household · current contract and renewal
# =========================================================================

def _hi_need_type(ctx: RuleContext) -> tuple[int, bool, str]:
    need = ctx.detail("need_type")
    labels = {
        "health": "complementary health cover",
        "provident": "provident/income protection",
        "borrower": "borrower insurance",
    }
    if need in labels:
        return 11, True, f"Need identified: {labels[need]}"
    return 0, False, "Nature of the insurance need not identified"


def _hi_household(ctx: RuleContext) -> tuple[int, bool, str]:
    beneficiaries = ctx.detail("beneficiaries")
    household = ctx.detail("household")

    if beneficiaries:
        return 10, True, f"{beneficiaries} beneficiaries to cover: quotable as-is"
    if household:
        return 6, True, "Family situation described, exact number of beneficiaries unknown"
    return 0, False, "Household situation and beneficiaries unknown"


def _hi_contract_timing(ctx: RuleContext) -> tuple[int, bool, str]:
    has_contract = ctx.detail("has_current_contract")
    end_known = ctx.detail("contract_end_known")

    if has_contract and end_known:
        return 11, True, "Current contract identified with a known renewal date: timing is actionable"
    if has_contract:
        return 6, True, "Currently insured, but the renewal date is unknown"
    if has_contract is False:
        return 9, True, "Not currently insured: no cancellation window to wait for"
    return 0, False, "Current insurance situation unknown"


# =========================================================================
#  Energy renovation — owner-occupier or landlord · property age · works
# =========================================================================

def _er_owner_type(ctx: RuleContext) -> tuple[int, bool, str]:
    owner_type = ctx.detail("owner_type")
    if owner_type == "owner_occupier":
        return 10, True, "Owner-occupier: eligible for the main renovation schemes"
    if owner_type == "landlord":
        return 8, True, "Landlord: eligible, under a different scheme"
    if owner_type == "tenant":
        return 0, False, "Tenant: cannot commission renovation work"
    if ctx.lead.owner is True:
        return 7, True, "Declared owner, occupier or landlord status unclear"
    return 0, False, "Owner-occupier or landlord status not established"


def _er_property_age(ctx: RuleContext) -> tuple[int, bool, str]:
    age = ctx.detail("property_age_years")
    year = ctx.detail("build_year")

    if age is None:
        return 0, False, "Property age unknown"
    # Pre-1990 stock is where energy renovation pays off most.
        # (kept inline: the threshold is a business assumption, not a constant)
    built = f" (built {year})" if year else ""
    if age >= 35:
        return 8, True, f"Property is {age} years old{built}: strong renovation potential"
    if age >= 15:
        return 6, True, f"Property is {age} years old{built}: moderate potential"
    return 3, True, f"Property is only {age} years old{built}: limited potential"


def _er_works_type(ctx: RuleContext) -> tuple[int, bool, str]:
    works = ctx.detail("works_type")
    if works == "global":
        return 7, True, "Whole-home renovation: highest value project"
    if works:
        return 6, True, f"Planned works identified: {works.replace('_', ' ')}"
    return 0, False, "Nature of the planned works not identified"


# =========================================================================
#  IT B2B — role and decision power · company size and sector · project
# =========================================================================

def _b2b_decision_power(ctx: RuleContext) -> tuple[int, bool, str]:
    """In B2B the contact's authority is the single strongest predictor."""
    role = ctx.detail("contact_role")
    if role == "decision_maker":
        return 12, True, "Contact holds decision-making authority"
    if role == "influencer":
        return 4, False, "Contact influences but does not decide: a decision-maker is still needed"
    return 0, False, "Contact's role and decision-making power unknown"


def _b2b_company_profile(ctx: RuleContext) -> tuple[int, bool, str]:
    size = ctx.detail("company_size")
    headcount = ctx.detail("headcount")
    sector = ctx.detail("sector")

    if size and sector:
        return 10, True, (
            f"{size.capitalize()} company"
            + (f" ({headcount} staff)" if headcount else "")
            + f" in {sector.replace('_', ' ')}"
        )
    if size:
        return 7, True, f"{size.capitalize()} company, sector unknown"
    if sector:
        return 5, True, f"Sector is {sector.replace('_', ' ')}, company size unknown"
    return 0, False, "Company size and sector unknown"


def _b2b_project_type(ctx: RuleContext) -> tuple[int, bool, str]:
    project = ctx.detail("it_project")
    labels = {
        "cybersecurity": "cybersecurity",
        "managed_services": "managed IT services",
        "software": "software or business application",
        "cloud": "cloud migration or hosting",
    }
    if project in labels:
        return 10, True, f"Project scoped as {labels[project]}"
    return 0, False, "Nature of the IT project not identified"


# =========================================================================
#  Registry
# =========================================================================

VERTICAL_RULES: dict[Vertical, list[Rule]] = {
    Vertical.HEAT_PUMP: [
        Rule("hp_owner_check", 11, _hp_owner),
        Rule("hp_current_heating_check", 8, _hp_current_heating),
        Rule("hp_property_check", 6, _hp_property),
        Rule("hp_budget_check", 7, _budget_rule(7)),
    ],
    Vertical.SOLAR: [
        Rule("pv_roof_owner_check", 11, _pv_roof_owner),
        Rule("pv_roof_profile_check", 7, _pv_roof_profile),
        Rule("pv_usage_model_check", 7, _pv_usage_model),
        Rule("pv_budget_check", 7, _budget_rule(7)),
    ],
    Vertical.HEARING_AID: [
        Rule("ha_self_declared_check", 12, _ha_self_declared),
        Rule("ha_age_context_check", 10, _ha_age_context),
        Rule("ha_coverage_check", 10, _ha_coverage),
    ],
    Vertical.HEALTH_INSURANCE: [
        Rule("hi_need_type_check", 11, _hi_need_type),
        Rule("hi_household_check", 10, _hi_household),
        Rule("hi_contract_timing_check", 11, _hi_contract_timing),
    ],
    Vertical.ENERGY_RENOVATION: [
        Rule("er_owner_type_check", 10, _er_owner_type),
        Rule("er_property_age_check", 8, _er_property_age),
        Rule("er_works_type_check", 7, _er_works_type),
        Rule("er_budget_check", 7, _budget_rule(7)),
    ],
    Vertical.IT_B2B: [
        Rule("b2b_decision_power_check", 12, _b2b_decision_power),
        Rule("b2b_company_profile_check", 10, _b2b_company_profile),
        Rule("b2b_project_type_check", 10, _b2b_project_type),
    ],
    # No vertical: no eligibility criteria can be run, so the lead is capped
    # at the universal maximum and can never be auto-qualified.
    Vertical.UNKNOWN: [],
}


def rules_for(vertical: Vertical) -> list[Rule]:
    """The full rule set applied to a lead in ``vertical``."""
    return UNIVERSAL_RULES + VERTICAL_RULES.get(vertical, [])


UNIVERSAL_MAX = sum(rule.max_score for rule in UNIVERSAL_RULES if rule.max_score > 0)


def max_score_for(vertical: Vertical) -> int:
    return sum(rule.max_score for rule in rules_for(vertical) if rule.max_score > 0)


# Kept as an alias so existing imports and the /api/config endpoint keep
# working; it lists every rule that exists, across all verticals.
RULES: list[Rule] = UNIVERSAL_RULES + [
    rule for rules in VERTICAL_RULES.values() for rule in rules
]
MAX_POSITIVE_SCORE = 100

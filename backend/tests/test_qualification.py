"""Rules, scoring and the score -> status decision.

These are pure unit tests: no database, no HTTP, no AI call.
"""

import pytest

from app.ai.mock_provider import MockAIProvider
from app.config import Settings
from app.models.enums import Country, LeadStatus, Vertical
from app.qualification import (
    UNIVERSAL_MAX,
    UNIVERSAL_RULES,
    VERTICAL_RULES,
    aggregate_score,
    decide_status,
    max_score_for,
    qualify,
    rules_for,
)
from app.qualification.rules import RuleContext, is_valid_phone
from app.schemas.lead import AIAnalysis, RuleResult
from tests.conftest import lead_create


async def _analyse(**overrides):
    lead = lead_create(**overrides)
    return lead, await MockAIProvider().analyze_lead(lead)


# =====================================================================
#  The weight invariant
# =====================================================================

@pytest.mark.parametrize(
    "vertical", [v for v in Vertical if v is not Vertical.UNKNOWN], ids=lambda v: v.value
)
def test_every_vertical_totals_one_hundred(vertical):
    """Universal + vertical-specific weights must always sum to 100.

    This is what lets the score be read as a percentage regardless of which
    line of business the lead belongs to.
    """
    vertical_max = sum(r.max_score for r in VERTICAL_RULES[vertical] if r.max_score > 0)

    assert UNIVERSAL_MAX + vertical_max == 100, (
        f"{vertical.value}: {UNIVERSAL_MAX} universal + {vertical_max} vertical"
    )
    assert max_score_for(vertical) == 100


def test_an_unidentified_vertical_can_never_be_auto_qualified():
    """No vertical means the eligibility rules never ran, so the lead is
    capped below the qualification threshold by construction."""
    assert max_score_for(Vertical.UNKNOWN) == UNIVERSAL_MAX
    assert UNIVERSAL_MAX < Settings().qualified_threshold + 20  # sanity on the design
    assert VERTICAL_RULES[Vertical.UNKNOWN] == []


def test_every_vertical_defines_its_own_eligibility_rules():
    for vertical in Vertical:
        if vertical is Vertical.UNKNOWN:
            continue
        assert VERTICAL_RULES[vertical], f"{vertical.value} has no eligibility rules"


def test_rule_names_are_unique_within_a_vertical():
    """Duplicate names would silently collide in the audit trail."""
    for vertical in Vertical:
        names = [r.name for r in rules_for(vertical)]
        assert len(names) == len(set(names)), vertical.value


# =====================================================================
#  Ownership is a vertical criterion, not a universal one
# =====================================================================

def test_ownership_is_not_a_universal_rule():
    """Regression: an IT B2B contact must not be penalised for not owning a
    house, and a homeowner must not be credited on a B2B lead."""
    universal_names = {r.name for r in UNIVERSAL_RULES}

    assert not any("owner" in name for name in universal_names)


async def test_owner_flag_is_ignored_outside_property_verticals():
    payload = {
        "firstname": "Sylvie", "lastname": "Chen", "email": "s.chen@entreprise.fr",
        "phone": "0155667788", "postal_code": "92100", "source": "partner_form",
        "campaign": "IT",
        "project_description": (
            "Je suis DSI d'une industrie de 180 salariés et je décide du budget. "
            "Nous cherchons un prestataire pour l'infogérance de notre parc informatique "
            "dès que possible."
        ),
        "budget": None, "consent": True,
    }

    as_owner, ai_owner = await _analyse(**payload, owner=True)
    as_unknown, ai_unknown = await _analyse(**payload, owner=None)

    owner_score = qualify(as_owner, ai_owner).score
    unknown_score = qualify(as_unknown, ai_unknown).score

    assert owner_score == unknown_score, "owner must be irrelevant to an IT B2B lead"


# =====================================================================
#  The three scripted personas
# =====================================================================

async def test_excellent_heat_pump_lead_is_qualified():
    lead, ai = await _analyse()
    outcome = qualify(lead, ai)

    assert outcome.vertical is Vertical.HEAT_PUMP
    assert outcome.status is LeadStatus.QUALIFIED
    assert 85 <= outcome.score <= 95, f"expected the 85-95 band, got {outcome.score}"


async def test_incomplete_solar_lead_needs_human_review():
    """The roof profile is clear; roof ownership — the first solar criterion —
    is not, so the engine must not decide alone."""
    from app.db.seed import LAURA

    ai = await MockAIProvider().analyze_lead(LAURA)
    outcome = qualify(LAURA, ai)

    assert outcome.vertical is Vertical.SOLAR
    assert outcome.status is LeadStatus.REVIEW
    assert 50 <= outcome.score < 80

    by_rule = {r.rule: r for r in outcome.rule_results}
    assert by_rule["pv_roof_owner_check"].passed is False
    assert by_rule["pv_budget_check"].passed is False
    # ...but what she did say was extracted and credited.
    assert by_rule["pv_roof_profile_check"].passed is True
    assert by_rule["pv_usage_model_check"].passed is True


async def test_vague_lead_has_no_vertical_and_is_rejected():
    from app.db.seed import MARCO

    ai = await MockAIProvider().analyze_lead(MARCO)
    outcome = qualify(MARCO, ai)

    assert outcome.vertical is Vertical.UNKNOWN
    assert outcome.status is LeadStatus.REJECTED
    assert outcome.score < 50
    assert outcome.max_possible == UNIVERSAL_MAX


# =====================================================================
#  Per-vertical eligibility criteria
# =====================================================================

async def test_heat_pump_credits_the_current_heating_and_its_age():
    """The second heat pump criterion is the system AND its age."""
    _, ai_with_age = await _analyse(
        project_description=(
            "Je souhaite remplacer ma chaudière fioul de 22 ans par une pompe à chaleur "
            "dans ma maison de 120m2 avant l'hiver."
        )
    )
    assert ai_with_age.details["heating_system"] == "oil_boiler"
    assert ai_with_age.details["heating_age_years"] == 22

    lead_full, ai_full = await _analyse(
        project_description=(
            "Je souhaite remplacer ma chaudière fioul de 22 ans par une pompe à chaleur "
            "dans ma maison de 120m2 avant l'hiver."
        )
    )
    lead_partial, ai_partial = await _analyse()  # no age stated

    full = next(r for r in qualify(lead_full, ai_full).rule_results if r.rule == "hp_current_heating_check")
    partial = next(r for r in qualify(lead_partial, ai_partial).rule_results if r.rule == "hp_current_heating_check")

    assert full.score > partial.score
    assert full.score == 8
    assert "age is unknown" in partial.reason


async def test_heat_pump_lead_already_equipped_scores_almost_nothing():
    lead, ai = await _analyse(
        project_description=(
            "J'ai déjà une pompe à chaleur existante dans ma maison de 100m2 "
            "et je voudrais un entretien."
        )
    )
    rule = next(r for r in qualify(lead, ai).rule_results if r.rule == "hp_current_heating_check")

    assert rule.passed is False
    assert "low replacement potential" in rule.reason


async def test_solar_rejects_a_north_facing_roof():
    lead, ai = await _analyse(
        project_description=(
            "Je veux installer des panneaux photovoltaïques sur ma toiture en ardoise "
            "orientée nord, en autoconsommation."
        )
    )
    rule = next(r for r in qualify(lead, ai).rule_results if r.rule == "pv_roof_profile_check")

    assert rule.passed is False
    assert rule.score == 0
    assert "North-facing" in rule.reason


async def test_hearing_aid_requires_the_person_themselves_to_declare_it():
    """A relative enquiring on someone else's behalf is not a qualified lead:
    the person concerned has neither expressed the need nor consented."""
    from app.db.seed import BERNARD, HELENE

    provider = MockAIProvider()

    herself = qualify(HELENE, await provider.analyze_lead(HELENE))
    third_party = qualify(BERNARD, await provider.analyze_lead(BERNARD))

    assert herself.status is LeadStatus.QUALIFIED
    assert third_party.status is not LeadStatus.QUALIFIED

    blocking = next(r for r in third_party.rule_results if r.rule == "ha_self_declared_check")
    assert blocking.passed is False
    assert blocking.score == 0
    assert "third party" in blocking.reason


async def test_hearing_aid_without_cover_is_penalised_not_rejected():
    lead, ai = await _analyse(
        project_description=(
            "J'ai 68 ans et j'entends mal en réunion, je souhaite un appareillage "
            "auditif. Je n'ai pas de mutuelle actuellement."
        )
    )
    rule = next(r for r in qualify(lead, ai).rule_results if r.rule == "ha_coverage_check")

    assert rule.passed is False
    assert "out-of-pocket" in rule.reason


async def test_health_insurance_values_a_known_renewal_date():
    lead, ai = await _analyse(
        project_description=(
            "Je suis mariée avec 3 enfants, nous avons un contrat de mutuelle en cours "
            "mais l'échéance est en décembre. Je souhaite comparer une complémentaire "
            "santé pour 5 bénéficiaires."
        )
    )
    outcome = qualify(lead, ai)
    by_rule = {r.rule: r for r in outcome.rule_results}

    assert outcome.vertical is Vertical.HEALTH_INSURANCE
    assert by_rule["hi_need_type_check"].passed is True
    assert by_rule["hi_contract_timing_check"].passed is True
    assert "actionable" in by_rule["hi_contract_timing_check"].reason


async def test_energy_renovation_rejects_a_tenant():
    lead, ai = await _analyse(
        owner=False,
        project_description=(
            "Je loue mon logement et je me demande si l'isolation des combles est "
            "possible, je cherche des informations."
        ),
    )
    outcome = qualify(lead, ai)
    rule = next(r for r in outcome.rule_results if r.rule == "er_owner_type_check")

    assert outcome.vertical is Vertical.ENERGY_RENOVATION
    assert rule.passed is False
    assert "Tenant" in rule.reason


async def test_it_b2b_weights_decision_power_above_everything():
    """An influencer without authority cannot be auto-qualified."""
    from app.db.seed import KEVIN, SYLVIE

    provider = MockAIProvider()

    decider = qualify(SYLVIE, await provider.analyze_lead(SYLVIE))
    influencer = qualify(KEVIN, await provider.analyze_lead(KEVIN))

    assert decider.status is LeadStatus.QUALIFIED
    assert influencer.status is not LeadStatus.QUALIFIED

    rule = next(r for r in influencer.rule_results if r.rule == "b2b_decision_power_check")
    assert rule.passed is False
    assert "decision-maker is still needed" in rule.reason


async def test_budget_is_only_a_criterion_where_it_makes_sense():
    """No budget rule exists for hearing aids, health insurance or IT B2B."""
    for vertical in (Vertical.HEARING_AID, Vertical.HEALTH_INSURANCE, Vertical.IT_B2B):
        names = [r.name for r in VERTICAL_RULES[vertical]]
        assert not any("budget" in n for n in names), vertical.value

    for vertical in (Vertical.HEAT_PUMP, Vertical.SOLAR, Vertical.ENERGY_RENOVATION):
        names = [r.name for r in VERTICAL_RULES[vertical]]
        assert any("budget" in n for n in names), vertical.value


# =====================================================================
#  Universal rules
# =====================================================================

async def test_missing_consent_costs_the_largest_single_penalty():
    lead, ai = await _analyse()
    with_consent = qualify(lead, ai).score

    lead_no_consent, ai2 = await _analyse(consent=False)
    without_consent = qualify(lead_no_consent, ai2).score

    assert with_consent - without_consent == 20
    rule = next(r for r in qualify(lead_no_consent, ai2).rule_results if r.rule == "consent_check")
    assert rule.passed is False
    assert rule.score == 0


async def test_invalid_phone_scores_zero_but_does_not_reject_the_request():
    """A bad phone is a business signal, not a transport error."""
    lead, ai = await _analyse(phone="123")
    outcome = qualify(lead, ai)

    rule = next(r for r in outcome.rule_results if r.rule == "phone_check")
    assert rule.passed is False
    assert rule.score == 0
    # The rest of the lead is still evaluated.
    assert outcome.score > 50


@pytest.mark.parametrize(
    "country,phone,valid",
    [
        ("FR", "0612345678", True),
        ("FR", "06 12 34 56 78", True),
        ("FR", "+33612345678", True),
        ("FR", "01.23.45.67.89", True),
        ("FR", "123", False),
        ("FR", "06123456789", False),   # one digit too many
        ("FR", "0012345678", False),    # invalid leading digit
        ("FR", "abcdefghij", False),
        ("ES", "612345678", True),
        ("ES", "+34612345678", True),
        ("ES", "912345678", True),
        ("ES", "112345678", False),     # Spanish numbers never start with 1
        ("IT", "3401234567", True),
        ("IT", "+393401234567", True),
        ("IT", "0612345678", True),     # Rome landline
        ("IT", "12345", False),
    ],
)
def test_phone_validation_is_country_aware(country, phone, valid):
    """The platform operates in France, Spain and Italy: a Spanish number must
    not be judged against the French numbering plan."""
    assert is_valid_phone(phone, country) is valid


async def test_a_french_number_is_invalid_when_the_lead_is_declared_spanish():
    lead, ai = await _analyse(phone="0612345678", country="ES")
    rule = next(r for r in qualify(lead, ai).rule_results if r.rule == "phone_check")

    assert rule.passed is False
    assert "ES" in rule.reason


# =====================================================================
#  Duplicates, clamping, thresholds
# =====================================================================

async def test_duplicate_applies_a_heavy_penalty():
    lead, ai = await _analyse()
    clean = qualify(lead, ai, is_duplicate=False)
    duplicated = qualify(lead, ai, is_duplicate=True)

    assert duplicated.score == clean.score - 40
    assert duplicated.status is LeadStatus.REVIEW  # never auto-qualified


async def test_score_is_always_within_zero_and_one_hundred():
    """Every rule combination, in every vertical, must stay inside 0-100."""
    provider = MockAIProvider()
    descriptions = [
        "Je souhaite remplacer ma chaudière fioul de 30 ans par une pompe à chaleur, maison 200m2.",
        "Panneaux photovoltaïques sur toiture tuiles plein sud en autoconsommation.",
        "J'ai 80 ans, j'entends mal, j'ai une mutuelle avec prise en charge.",
        "Mutuelle pour 6 bénéficiaires, contrat en cours, échéance en mars.",
        "Propriétaire, maison de 1960, rénovation globale avec isolation.",
        "Je suis DSI de 900 salariés dans l'industrie, je décide, projet cybersécurité.",
        "Des infos",
    ]

    for description in descriptions:
        for consent in (True, False):
            for owner in (True, False, None):
                for budget in (None, 0, 50, 12000, 10**9):
                    for duplicate in (True, False):
                        lead = lead_create(
                            project_description=description, consent=consent,
                            owner=owner, budget=budget,
                        )
                        ai = await provider.analyze_lead(lead)
                        outcome = qualify(lead, ai, is_duplicate=duplicate)
                        assert 0 <= outcome.score <= 100, (description, outcome.score)


def test_penalty_rule_can_never_award_points():
    """Regression: the clamp must not turn a negative weight into a bonus."""
    penalty_rules = [r for r in UNIVERSAL_RULES if r.max_score < 0]
    assert penalty_rules, "expected at least one penalty-only rule"

    for rule in penalty_rules:
        for is_duplicate in (True, False):
            ctx = RuleContext(
                lead=lead_create(),
                ai=AIAnalysis(
                    project_type="heat_pump", urgency="high",
                    purchase_intent="high", summary="",
                ),
                vertical=Vertical.HEAT_PUMP,
                is_duplicate=is_duplicate,
            )
            assert rule.run(ctx).score <= 0


def test_aggregate_score_clamps_both_ends():
    def result(score: int) -> RuleResult:
        return RuleResult(rule="x", passed=True, score=score, max_score=100, reason="")

    assert aggregate_score([result(80), result(60)]) == 100
    assert aggregate_score([result(10), result(-90)]) == 0
    assert aggregate_score([]) == 0


def test_thresholds_are_configurable():
    """Business stakeholders can retune the bands without touching the rules.

    Setting the qualification threshold above 100 is how you switch the whole
    platform to "every lead is validated by a person" — no code change.
    """
    strict = Settings(qualified_threshold=95, review_threshold=70)

    assert decide_status(90, settings=strict)[0] is LeadStatus.REVIEW
    assert decide_status(96, settings=strict)[0] is LeadStatus.QUALIFIED
    assert decide_status(65, settings=strict)[0] is LeadStatus.REJECTED

    always_human = Settings(qualified_threshold=101, review_threshold=1)
    assert decide_status(100, settings=always_human)[0] is LeadStatus.REVIEW


def test_decision_boundaries_are_inclusive():
    default = Settings()

    assert decide_status(80, settings=default)[0] is LeadStatus.QUALIFIED
    assert decide_status(79, settings=default)[0] is LeadStatus.REVIEW
    assert decide_status(50, settings=default)[0] is LeadStatus.REVIEW
    assert decide_status(49, settings=default)[0] is LeadStatus.REJECTED


def test_every_rule_reports_points_verdict_and_reason():
    """The audit trail is only useful if each rule explains itself."""
    for vertical in Vertical:
        ctx = RuleContext(
            lead=lead_create(),
            ai=AIAnalysis(
                project_type="heat_pump", urgency="high", purchase_intent="high", summary=""
            ),
            vertical=vertical,
        )
        for rule in rules_for(vertical):
            result = rule.run(ctx)
            assert result.rule == rule.name
            assert isinstance(result.passed, bool)
            assert result.reason.strip(), f"{rule.name} gave no reason"

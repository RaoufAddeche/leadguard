"""AI extraction: the provider abstraction and the mock's parsing."""

import pytest

from app.ai.base import AIProvider
from app.ai.factory import analyze_safely, build_provider
from app.ai.mock_provider import MockAIProvider
from app.config import Settings
from app.schemas.lead import AIAnalysis
from tests.conftest import lead_create


async def test_extraction_parses_the_reference_example():
    """The brief's worked example, end to end."""
    lead = lead_create(
        project_description=(
            "J'ai acheté une maison près de Lyon et je voudrais remplacer ma "
            "chaudière fioul par une pompe à chaleur avant l'hiver."
        )
    )
    analysis = await MockAIProvider().analyze_lead(lead)

    assert analysis.project_type == "heat_pump"
    assert analysis.location == "Lyon"
    assert analysis.property_type == "house"
    assert analysis.owner_intent is True
    assert analysis.urgency == "high"
    assert analysis.purchase_intent == "high"
    assert analysis.summary


async def test_extraction_is_accent_insensitive():
    """'pompe a chaleur' without accents must still be recognised."""
    lead = lead_create(project_description="Je veux installer une pompe a chaleur chez moi avant l'hiver.")
    analysis = await MockAIProvider().analyze_lead(lead)

    assert analysis.project_type == "heat_pump"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Je souhaite installer des panneaux solaires photovoltaïques sur mon toit.", "solar"),
        ("Je voudrais faire isoler les combles de ma maison rapidement.", "insulation"),
        ("Je veux remplacer mes fenêtres par du double vitrage.", "windows"),
        ("Je cherche une nouvelle chaudière gaz à condensation pour ma maison.", "boiler"),
        ("Je souhaite une mutuelle santé pour ma famille.", "health_insurance"),
        ("J'entends mal et je cherche un appareil auditif.", "hearing_aid"),
        ("Nous cherchons un prestataire pour l'infogérance de notre parc informatique.", "it_b2b"),
        ("Bonjour, merci de me rappeler.", "unknown"),
    ],
)
async def test_project_type_categorisation(description, expected):
    lead = lead_create(project_description=description)
    analysis = await MockAIProvider().analyze_lead(lead)

    assert analysis.project_type == expected


async def test_vague_request_yields_low_signals_not_a_guess():
    """The extractor must not invent intent it cannot see."""
    lead = lead_create(project_description="Des infos svp")
    analysis = await MockAIProvider().analyze_lead(lead)

    assert analysis.project_type == "unknown"
    assert analysis.urgency == "low"
    assert analysis.purchase_intent == "low"


async def test_tenant_is_detected_as_non_owner():
    lead = lead_create(project_description="Je loue mon logement et je voudrais isoler les combles.")
    analysis = await MockAIProvider().analyze_lead(lead)

    assert analysis.owner_intent is False


async def test_extraction_is_deterministic():
    """A live demo needs reproducible numbers."""
    lead = lead_create()
    provider = MockAIProvider()

    first = await provider.analyze_lead(lead)
    second = await provider.analyze_lead(lead)

    assert first == second


async def test_ai_failure_degrades_gracefully_and_keeps_the_lead():
    """A provider outage must never break the pipeline."""

    class BrokenProvider(AIProvider):
        name = "broken"

        async def analyze_lead(self, lead):
            raise RuntimeError("upstream 503")

    analysis, error = await analyze_safely(BrokenProvider(), lead_create())

    assert error is not None and "upstream 503" in error
    assert isinstance(analysis, AIAnalysis)
    # Neutral output: no invented signal.
    assert analysis.project_type == "unknown"
    assert analysis.urgency == "unknown"


async def test_ai_timeout_degrades_gracefully():
    import asyncio

    class SlowProvider(AIProvider):
        name = "slow"

        async def analyze_lead(self, lead):
            await asyncio.sleep(5)
            raise AssertionError("should have timed out")

    analysis, error = await analyze_safely(SlowProvider(), lead_create(), timeout=0.05)

    assert error is not None
    assert analysis.project_type == "unknown"


def test_factory_defaults_to_the_mock_so_no_api_key_is_needed():
    provider = build_provider(Settings(ai_provider="mock"))

    assert isinstance(provider, MockAIProvider)
    assert provider.name == "mock"


def test_real_providers_fail_loudly_when_the_key_is_missing():
    """Better a clear startup error than silent, unexplained AI results."""
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(Settings(ai_provider="anthropic", anthropic_api_key=None))

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_provider(Settings(ai_provider="openai", openai_api_key=None))


def test_all_providers_share_one_contract():
    """Swapping vendors must not change the pipeline's expectations."""
    from app.ai.anthropic_provider import AnthropicProvider
    from app.ai.openai_provider import OpenAIProvider

    for cls in (MockAIProvider, AnthropicProvider, OpenAIProvider):
        assert issubclass(cls, AIProvider)
        assert hasattr(cls, "analyze_lead")


# --- Real-provider response parsing --------------------------------------
# We cannot call OpenAI or Anthropic without a key, but we CAN verify that the
# parsing of their JSON is robust — which is where a real key actually breaks.


def test_parse_analysis_accepts_a_well_formed_response():
    from app.ai.base import parse_analysis

    analysis = parse_analysis(
        {
            "project_type": "heat_pump",
            "location": "Lyon",
            "property_type": "house",
            "owner_intent": True,
            "urgency": "high",
            "purchase_intent": "high",
            "summary": "Owner replacing an oil boiler with a heat pump.",
        },
        "openai",
    )

    assert analysis.project_type == "heat_pump"
    assert analysis.location == "Lyon"
    assert analysis.owner_intent is True
    assert analysis.provider == "openai"


def test_parse_analysis_survives_a_sloppy_response():
    """Missing keys, nulls, odd casing and a stray key must not look like an outage."""
    from app.ai.base import parse_analysis

    analysis = parse_analysis(
        {
            "project_type": "HEAT_PUMP",
            "location": "   ",
            "urgency": "very urgent",       # outside the allowed set
            "purchase_intent": None,
            "owner_intent": "yes",          # not a bool
            "provider": "hallucinated",     # the model must not name itself
            "confidence": 0.9,              # unexpected extra key
        },
        "openai",
    )

    assert analysis.project_type == "heat_pump"   # normalised
    assert analysis.location is None              # blank becomes None
    assert analysis.urgency == "unknown"          # unrecognised label
    assert analysis.purchase_intent == "unknown"
    assert analysis.owner_intent is None          # non-bool is not guessed
    assert analysis.provider == "openai"          # we decide, not the model
    assert analysis.summary                       # always a usable string


def test_parse_analysis_rejects_a_non_object():
    from app.ai.base import parse_analysis

    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_analysis(["not", "an", "object"], "openai")


# --- The prompt must stay in sync with the verticals ---------------------
# Regression guard: the prompt was once written for an older set of project
# types and asked for no per-vertical fields at all. With a real provider that
# silently returned an empty `details` bag, so every eligibility rule scored 0.
# No network needed — this is a structural check on the prompt text.


def test_prompt_offers_every_project_type_the_engine_knows():
    from app.ai.base import EXTRACTION_PROMPT
    from app.models.enums import ProjectType

    for project_type in ProjectType:
        assert f'"{project_type.value}"' in EXTRACTION_PROMPT, (
            f"the prompt never offers {project_type.value}, so a real provider "
            "can never return it"
        )


def test_prompt_asks_for_every_detail_field_a_rule_reads():
    """Every field the rules score must be a field the prompt asks for."""
    from app.ai.base import EXTRACTION_PROMPT

    # The fields read by the per-vertical rules, by vertical.
    required = {
        "heating_system", "heating_age_years", "surface_m2",
        "roof_cover", "roof_orientation", "usage_model",
        "self_declared", "age_years", "accompanied", "has_coverage",
        "need_type", "household", "beneficiaries",
        "has_current_contract", "contract_end_known",
        "owner_type", "build_year", "works_type",
        "contact_role", "headcount", "sector", "it_project",
    }
    missing = {field for field in required if field not in EXTRACTION_PROMPT}

    assert not missing, f"the prompt never asks for: {sorted(missing)}"


def test_prompt_forbids_the_model_from_deciding():
    from app.ai.base import EXTRACTION_PROMPT

    lowered = EXTRACTION_PROMPT.lower()
    assert "do not judge, score or qualify" in lowered
    assert "business rules" in lowered


def test_details_are_normalised_and_unknown_keys_dropped():
    from app.ai.base import normalize_details

    details = normalize_details({
        "surface_m2": "120 m2",        # coerced from a string
        "heating_age_years": 22.0,     # coerced from a float
        "self_declared": "yes",        # coerced from a string
        "roof_cover": "Tiles",         # lowercased
        "roof_orientation": "south-east",  # normalised separator
        "invented_field": "whatever",  # dropped: no rule reads it
    })

    assert details["surface_m2"] == 120
    assert details["heating_age_years"] == 22
    assert details["self_declared"] is True
    assert details["roof_cover"] == "tiles"
    assert details["roof_orientation"] == "south_east"
    assert "invented_field" not in details


def test_derived_buckets_are_computed_by_the_code_not_the_model():
    """Age brackets and company sizes are business definitions, so the code
    owns them — and a model's own guess is overwritten."""
    from app.ai.base import normalize_details

    hearing = normalize_details({"age_years": 72, "age_bracket": "young"})
    assert hearing["age_bracket"] == "65_74", "the model's bucket must not win"

    b2b = normalize_details({"headcount": 180, "company_size": "tiny"})
    assert b2b["company_size"] == "mid"

    renovation = normalize_details({"build_year": 1975})
    assert renovation["property_age_years"] == 51


def test_both_providers_derive_identical_buckets():
    """The mock and the real providers must agree on derived values, or the
    demo numbers would not be comparable."""
    from app.ai.base import age_bracket, company_size

    for age, expected in [(30, "under_50"), (55, "50_64"), (72, "65_74"), (80, "75_plus")]:
        assert age_bracket(age) == expected
    for headcount, expected in [(5, "micro"), (30, "small"), (180, "mid"), (900, "large")]:
        assert company_size(headcount) == expected
    assert age_bracket(None) is None
    assert company_size(None) is None

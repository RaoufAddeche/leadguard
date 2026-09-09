"""The AI boundary.

The provider is deliberately given ONE job: turn unstructured free text into
structured fields. It never sees the score, the thresholds or the decision.
That separation is the whole point of the architecture — see README.
"""

import re
from abc import ABC, abstractmethod

from app.schemas.lead import AIAnalysis, LeadCreate

# Prompt shared by every real provider, so their outputs stay comparable.
EXTRACTION_PROMPT = """You are an information-extraction component in a lead \
qualification pipeline. Extract structured data from the prospect's message.

Return ONLY a JSON object with these keys:
- project_type: one of ["heat_pump", "solar", "insulation", "windows", "boiler", \
"hearing_aid", "health_insurance", "it_b2b", "unknown"]
- location: the city or area mentioned, or null
- property_type: one of ["house", "apartment", "unknown"]
- owner_intent: true if the prospect implies they own the property, false if they \
imply they rent, null if unclear
- urgency: one of ["high", "medium", "low", "unknown"]
- purchase_intent: one of ["high", "medium", "low", "unknown"]
- summary: one short factual sentence (max 25 words)
- details: an object holding ONLY the fields listed below for the project_type you \
chose. Use null for anything the message does not state.

details fields by project_type:

* heat_pump:
  - heating_system: one of ["oil_boiler", "gas_boiler", "electric", "wood", "heat_pump"] or null
  - heating_age_years: integer age of the CURRENT heating system, or null
  - surface_m2: integer living area in m², or null

* solar:
  - roof_cover: one of ["tiles", "slate", "fibre_cement", "flat"] or null
  - roof_orientation: one of ["south", "south_east", "south_west", "east_west", "north"] or null
  - usage_model: "self_consumption" if they want to consume their own production, \
"surplus_resale" if they want to sell the surplus, else null
  - surface_m2: integer roof or living area in m², or null

* insulation, windows, boiler (all energy renovation):
  - owner_type: one of ["owner_occupier", "landlord", "tenant"] or null
  - build_year: 4-digit construction year of the property, or null
  - works_type: one of ["insulation", "windows", "heating", "global"] or null \
("global" means a whole-home renovation)
  - surface_m2: integer living area in m², or null

* hearing_aid:
  - self_declared: true if the person WRITING declares their own hearing difficulty, \
false if they are enquiring on behalf of someone else (a parent, spouse, relative), null if unclear
  - age_years: integer age of the person CONCERNED, or null
  - accompanied: true if a relative helps or accompanies them, else null
  - has_coverage: true if they mention complementary health cover or reimbursement, \
false if they state they have none, null if unclear

* health_insurance:
  - need_type: one of ["health", "provident", "borrower"] or null \
("borrower" = loan/mortgage insurance, "provident" = income protection, death, disability)
  - household: true if they describe a family or couple situation, else null
  - beneficiaries: integer number of people to cover, or null
  - has_current_contract: true if they already have a policy, false if they state \
they have none, null if unclear
  - contract_end_known: true if they mention a renewal, expiry or cancellation date, else null

* it_b2b:
  - contact_role: "decision_maker" if the contact can decide or approve the budget, \
"influencer" if they cannot, null if unclear
  - headcount: integer number of employees at the company, or null
  - sector: one of ["industry", "retail", "healthcare", "services", "construction", "public"] or null
  - it_project: one of ["cybersecurity", "managed_services", "software", "cloud"] or null

* unknown: return an empty object {{}}

Do not judge, score or qualify the lead. Do not decide whether it is a good or bad \
lead — that is done downstream by business rules. Do not invent facts that are not in \
the message: null is always better than a guess. If the message is too vague to \
identify a project, use "unknown", "low" and an empty details object.

Prospect message:
{description}
"""


# Values we accept for the two graded scales; anything else becomes "unknown".
_LEVELS = {"high", "medium", "low", "unknown"}

# The current year, used to turn a construction year into an age.
REFERENCE_YEAR = 2026


def age_bracket(age: int | None) -> str | None:
    """Bucket an age. A business definition, so the code owns it — never the LLM.

    The model is asked for the raw age; the bracket is derived here so every
    provider produces identical buckets and the boundaries can be changed in
    one place.
    """
    if age is None:
        return None
    if age < 50:
        return "under_50"
    if age < 65:
        return "50_64"
    if age < 75:
        return "65_74"
    return "75_plus"


def company_size(headcount: int | None) -> str | None:
    """Bucket a headcount. Same reasoning as ``age_bracket``."""
    if headcount is None:
        return None
    if headcount < 10:
        return "micro"
    if headcount < 50:
        return "small"
    if headcount < 250:
        return "mid"
    return "large"


def _as_int(value: object) -> int | None:
    """Coerce a model's answer to an int, tolerating "120 m2" and 120.0.

    Takes the FIRST run of digits rather than every digit in the string:
    "120 m2" is 120, not 1202.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _as_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "oui"}:
            return True
        if lowered in {"false", "no", "non"}:
            return False
    return None


def _as_label(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    return text or None


# Every detail field the prompt can ask for, with how to coerce it.
_DETAIL_FIELDS: dict[str, str] = {
    "heating_system": "label",
    "heating_age_years": "int",
    "surface_m2": "int",
    "roof_cover": "label",
    "roof_orientation": "label",
    "usage_model": "label",
    "owner_type": "label",
    "build_year": "int",
    "works_type": "label",
    "self_declared": "bool",
    "age_years": "int",
    "accompanied": "bool",
    "has_coverage": "bool",
    "need_type": "label",
    "household": "bool",
    "beneficiaries": "int",
    "has_current_contract": "bool",
    "contract_end_known": "bool",
    "contact_role": "label",
    "headcount": "int",
    "sector": "label",
    "it_project": "label",
}

_COERCERS = {"int": _as_int, "bool": _as_bool, "label": _as_label}


def normalize_details(raw: object) -> dict:
    """Clean a model's ``details`` object and add the derived buckets.

    Unknown keys are dropped: a rule can only score fields it knows about, and
    letting a model invent field names would silently do nothing.
    """
    if not isinstance(raw, dict):
        return {}

    details: dict = {}
    for key, kind in _DETAIL_FIELDS.items():
        if key in raw:
            details[key] = _COERCERS[kind](raw[key])

    # Derived, never delegated.
    if "age_years" in details:
        details["age_bracket"] = age_bracket(details["age_years"])
    if "headcount" in details:
        details["company_size"] = company_size(details["headcount"])
    if details.get("build_year"):
        details["property_age_years"] = REFERENCE_YEAR - details["build_year"]

    return details


def parse_analysis(data: dict, provider_name: str) -> AIAnalysis:
    """Turn a model's JSON object into an AIAnalysis, tolerantly.

    Real LLMs occasionally return a stray key, a null where a string was asked
    for, or a label outside the allowed set. None of that should look like an
    outage, so we normalise here instead of letting Pydantic raise and silently
    degrade the lead to a neutral analysis.
    """
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")

    # The model does not get to name itself: we know which provider ran.
    data = {k: v for k, v in data.items() if k != "provider"}

    def level(value: object) -> str:
        text = str(value).strip().lower() if value is not None else "unknown"
        return text if text in _LEVELS else "unknown"

    def text_or_none(value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    return AIAnalysis(
        project_type=(text_or_none(data.get("project_type")) or "unknown").lower(),
        location=text_or_none(data.get("location")),
        property_type=(text_or_none(data.get("property_type")) or "unknown").lower(),
        owner_intent=data.get("owner_intent") if isinstance(data.get("owner_intent"), bool) else None,
        urgency=level(data.get("urgency")),
        purchase_intent=level(data.get("purchase_intent")),
        summary=text_or_none(data.get("summary")) or "No summary returned by the provider.",
        provider=provider_name,
        details=normalize_details(data.get("details")),
    )


class AIProvider(ABC):
    """Abstraction so the pipeline is not coupled to any single vendor."""

    name: str = "base"

    @abstractmethod
    async def analyze_lead(self, lead: LeadCreate) -> AIAnalysis:
        """Extract structured information from ``lead.project_description``."""

    def _prompt(self, lead: LeadCreate) -> str:
        return EXTRACTION_PROMPT.format(description=lead.project_description)

"""Domain enumerations shared by models, schemas and the engine."""

from enum import StrEnum


class LeadStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"


class Vertical(StrEnum):
    """A line of business.

    Each vertical is bought by a different client, with its own eligibility
    criteria — which is why the qualification rules are split per vertical
    rather than being one flat list.
    """

    HEAT_PUMP = "heat_pump"
    SOLAR = "solar"
    HEARING_AID = "hearing_aid"
    HEALTH_INSURANCE = "health_insurance"
    ENERGY_RENOVATION = "energy_renovation"
    IT_B2B = "it_b2b"
    UNKNOWN = "unknown"


class ProjectType(StrEnum):
    """The fine-grained project the prospect described.

    Several project types roll up into one commercial vertical: insulation,
    windows and boiler replacement are all sold as energy renovation.
    """

    HEAT_PUMP = "heat_pump"
    SOLAR = "solar"
    INSULATION = "insulation"
    WINDOWS = "windows"
    BOILER = "boiler"
    HEARING_AID = "hearing_aid"
    HEALTH_INSURANCE = "health_insurance"
    IT_B2B = "it_b2b"
    UNKNOWN = "unknown"


# Fine-grained project type -> commercial vertical.
PROJECT_TO_VERTICAL: dict[ProjectType, Vertical] = {
    ProjectType.HEAT_PUMP: Vertical.HEAT_PUMP,
    ProjectType.SOLAR: Vertical.SOLAR,
    ProjectType.INSULATION: Vertical.ENERGY_RENOVATION,
    ProjectType.WINDOWS: Vertical.ENERGY_RENOVATION,
    ProjectType.BOILER: Vertical.ENERGY_RENOVATION,
    ProjectType.HEARING_AID: Vertical.HEARING_AID,
    ProjectType.HEALTH_INSURANCE: Vertical.HEALTH_INSURANCE,
    ProjectType.IT_B2B: Vertical.IT_B2B,
    ProjectType.UNKNOWN: Vertical.UNKNOWN,
}


def vertical_for(project_type: str | None) -> Vertical:
    """Resolve a project type string to its vertical, tolerating junk."""
    try:
        return PROJECT_TO_VERTICAL[ProjectType(project_type or "unknown")]
    except ValueError:
        return Vertical.UNKNOWN


class Level(StrEnum):
    """Shared scale for urgency and purchase intent."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Country(StrEnum):
    FR = "FR"
    ES = "ES"
    IT = "IT"


class PropertyType(StrEnum):
    HOUSE = "house"
    APARTMENT = "apartment"
    UNKNOWN = "unknown"


class CRMSyncStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class EventType(StrEnum):
    RECEIVED = "lead_received"
    VALIDATED = "validation_passed"
    CONSENT_VERIFIED = "consent_verified"
    DUPLICATE_CHECK = "duplicate_check"
    AI_ANALYSIS = "ai_analysis"
    SCORED = "score_calculated"
    STATUS_CHANGED = "status_changed"
    ROUTED = "routed"
    CRM_SYNC = "crm_sync"
    HUMAN_REVIEW = "human_review"

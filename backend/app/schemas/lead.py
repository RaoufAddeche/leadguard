"""Transport-level contracts.

Design note: Pydantic validates *shape and presence* only. Whether a phone
number is a real French number, or whether consent was actually granted, are
*business* questions answered by the rules engine — a lead with a bad phone or
no consent is still stored, scored and REJECTED, because that rejection is
itself auditable information.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Country, LeadStatus


class LeadCreate(BaseModel):
    firstname: str = Field(min_length=1, max_length=80)
    lastname: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=40)
    postal_code: str = Field(min_length=1, max_length=16)
    country: Country = Country.FR
    source: str = Field(min_length=1, max_length=64)
    campaign: str = Field(min_length=1, max_length=120)
    project_description: str = Field(min_length=1)
    owner: bool | None = None
    budget: float | None = Field(default=None, ge=0)
    consent: bool = False
    consent_timestamp: datetime | None = None

    @field_validator("firstname", "lastname", "phone", "postal_code", "source", "campaign")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("project_description")
    @classmethod
    def _strip_description(cls, v: str) -> str:
        return v.strip()


class RuleResult(BaseModel):
    """What every business rule returns: points, verdict and a reason."""

    rule: str
    passed: bool
    score: int
    max_score: int
    reason: str


class AIAnalysis(BaseModel):
    """Structured output extracted from free text by the AI provider."""

    project_type: str
    location: str | None = None
    property_type: str | None = None
    owner_intent: bool | None = None
    urgency: str
    purchase_intent: str
    summary: str
    provider: str | None = None
    # Fields that only matter for one vertical (roof orientation, heating age,
    # decision-making power...). Kept as a bag rather than twenty nullable
    # columns, because each vertical uses a different handful.
    details: dict = Field(default_factory=dict)


class DuplicateInfo(BaseModel):
    duplicate: bool
    duplicate_lead_id: str | None = None
    similarity: int | None = None
    reason: str | None = None


class RoutingDecision(BaseModel):
    team: str
    reason: str


class LeadEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    message: str
    created_at: datetime

    @classmethod
    def from_model(cls, event) -> "LeadEventOut":
        return cls(
            id=event.id,
            event_type=event.event_type,
            message=event.message,
            created_at=event.created_at,
        )


class LeadSummary(BaseModel):
    """Compact shape for dashboard lists."""

    id: int
    public_id: str | None
    full_name: str
    email: str
    score: int
    status: str
    system_status: str
    human_status: str | None
    project_type: str | None
    vertical: str | None
    location: str | None
    source: str
    campaign: str
    routed_team: str | None
    is_duplicate: bool
    created_at: datetime


class LeadDetail(LeadSummary):
    """Everything a reviewer needs on one screen."""

    firstname: str
    lastname: str
    phone: str
    postal_code: str
    country: str
    project_description: str
    owner: bool | None
    budget: float | None
    consent: bool
    consent_timestamp: datetime | None
    data_fingerprint: str
    ai_analysis: AIAnalysis | None
    ai_provider: str | None
    rule_results: list[RuleResult]
    duplicate: DuplicateInfo
    routing_reason: str | None
    crm_status: str
    crm_reference: str | None
    crm_error: str | None
    reviewer: str | None
    reviewed_at: datetime | None
    review_reason: str | None
    events: list[LeadEventOut]


class QualificationResult(BaseModel):
    """Immediate feedback returned by POST /api/leads and the webhook."""

    lead_id: int
    public_id: str | None
    score: int
    status: str
    vertical: str
    team: str | None
    duplicate: DuplicateInfo
    ai_analysis: AIAnalysis | None
    rule_results: list[RuleResult]
    crm_status: str
    events: list[LeadEventOut]


class HumanDecision(BaseModel):
    decision: LeadStatus
    reviewer: str = Field(default="demo-user", max_length=120)
    reason: str | None = None

    @field_validator("decision")
    @classmethod
    def _reviewable(cls, v: LeadStatus) -> LeadStatus:
        if v is LeadStatus.REVIEW:
            raise ValueError("A human decision must be QUALIFIED or REJECTED")
        return v


class VerticalStats(BaseModel):
    vertical: str
    total: int
    qualified: int
    review: int
    rejected: int
    average_score: float


class DashboardStats(BaseModel):
    total: int
    qualified: int
    review: int
    rejected: int
    duplicates: int
    qualification_rate: float
    average_score: float
    verticals: list[VerticalStats] = Field(default_factory=list)

"""Score aggregation and the score → status decision.

Kept separate from the rules so thresholds can be tuned without touching the
business logic, and vice versa.
"""

from app.config import Settings, get_settings
from app.models.enums import LeadStatus
from app.schemas.lead import RuleResult


def aggregate_score(results: list[RuleResult]) -> int:
    """Sum the rule points and clamp to the 0-100 range."""
    total = sum(result.score for result in results)
    return max(0, min(100, total))


def decide_status(
    score: int, *, is_duplicate: bool = False, settings: Settings | None = None
) -> tuple[LeadStatus, str]:
    """Map a score to a status. Deterministic, auditable, no AI involved."""
    settings = settings or get_settings()

    if score >= settings.qualified_threshold:
        status, reason = LeadStatus.QUALIFIED, (
            f"Score {score} is at or above the qualification threshold "
            f"({settings.qualified_threshold})"
        )
    elif score >= settings.review_threshold:
        status, reason = LeadStatus.REVIEW, (
            f"Score {score} falls in the human review band "
            f"({settings.review_threshold}-{settings.qualified_threshold - 1})"
        )
    else:
        status, reason = LeadStatus.REJECTED, (
            f"Score {score} is below the review threshold ({settings.review_threshold})"
        )

    # A suspected duplicate is never auto-qualified: a human confirms whether
    # it is a genuine re-engagement or a double submission.
    if (
        is_duplicate
        and settings.duplicate_blocks_qualification
        and status is LeadStatus.QUALIFIED
    ):
        return LeadStatus.REVIEW, (
            f"{reason}, but the lead is a suspected duplicate and requires human review"
        )

    return status, reason

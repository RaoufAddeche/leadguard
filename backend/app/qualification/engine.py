"""The qualification engine: run the rules, aggregate, decide.

This is the only place that turns facts into a verdict, and it contains no I/O
whatsoever — which makes it trivially unit-testable.
"""

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.models.enums import LeadStatus, Vertical, vertical_for
from app.qualification.rules import RuleContext, max_score_for, rules_for
from app.qualification.scoring import aggregate_score, decide_status
from app.schemas.lead import AIAnalysis, LeadCreate, RuleResult


@dataclass(frozen=True)
class QualificationOutcome:
    score: int
    status: LeadStatus
    reason: str
    rule_results: list[RuleResult]
    vertical: Vertical = Vertical.UNKNOWN
    # The maximum this lead could have scored. Equals 100 for any identified
    # vertical; lower when no vertical could be determined, because the
    # eligibility rules could not be run at all.
    max_possible: int = 100

    @property
    def passed_rules(self) -> list[RuleResult]:
        return [r for r in self.rule_results if r.passed]

    @property
    def failed_rules(self) -> list[RuleResult]:
        return [r for r in self.rule_results if not r.passed]


def qualify(
    lead: LeadCreate,
    ai: AIAnalysis,
    *,
    is_duplicate: bool = False,
    settings: Settings | None = None,
) -> QualificationOutcome:
    settings = settings or get_settings()

    # The vertical selects which eligibility rules apply, so it is resolved
    # before anything is scored.
    vertical = vertical_for(ai.project_type)
    ctx = RuleContext(lead=lead, ai=ai, vertical=vertical, is_duplicate=is_duplicate)

    results = [rule.run(ctx) for rule in rules_for(vertical)]
    score = aggregate_score(results)
    status, reason = decide_status(score, is_duplicate=is_duplicate, settings=settings)

    return QualificationOutcome(
        score=score,
        status=status,
        reason=reason,
        rule_results=results,
        vertical=vertical,
        max_possible=max_score_for(vertical),
    )

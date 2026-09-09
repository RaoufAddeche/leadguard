"""Provider selection + graceful degradation."""

import asyncio
import logging

from app.ai.base import AIProvider
from app.ai.mock_provider import MockAIProvider
from app.config import Settings, get_settings
from app.schemas.lead import AIAnalysis, LeadCreate

logger = logging.getLogger(__name__)


def build_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()

    if settings.ai_provider == "anthropic":
        from app.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=settings.anthropic_api_key or "",
            model=settings.anthropic_model,
            timeout=settings.ai_timeout_seconds,
        )

    if settings.ai_provider == "openai":
        from app.ai.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.openai_api_key or "",
            model=settings.openai_model,
            timeout=settings.ai_timeout_seconds,
        )

    return MockAIProvider()


async def analyze_safely(
    provider: AIProvider, lead: LeadCreate, timeout: float = 20.0
) -> tuple[AIAnalysis, str | None]:
    """Run the extraction without ever letting an AI failure break the pipeline.

    A provider outage must not lose a lead. On failure we return a neutral
    analysis: the deterministic rules still score the structured fields the
    prospect submitted, and the lead simply lands in human REVIEW.

    Returns ``(analysis, error_message)``.
    """
    try:
        analysis = await asyncio.wait_for(provider.analyze_lead(lead), timeout=timeout)
        return analysis, None
    except Exception as exc:  # noqa: BLE001 - degradation is the whole point
        logger.warning("AI analysis failed (%s): %s", provider.name, exc)
        neutral = AIAnalysis(
            project_type="unknown",
            location=None,
            property_type="unknown",
            owner_intent=None,
            urgency="unknown",
            purchase_intent="unknown",
            summary="AI analysis unavailable; lead scored on submitted data only.",
            provider=f"{provider.name} (unavailable)",
        )
        return neutral, str(exc)

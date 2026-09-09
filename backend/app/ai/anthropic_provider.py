"""Anthropic provider.

Thin on purpose: same prompt, same output schema as every other provider, so it
is a drop-in replacement for the mock. Uses the HTTP API directly to avoid an
extra SDK dependency in a POC.
"""

import json
import logging

import httpx

from app.ai.base import AIProvider, parse_analysis
from app.schemas.lead import AIAnalysis, LeadCreate

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for AI_PROVIDER=anthropic. "
                "Use AI_PROVIDER=mock to run without a key."
            )
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def analyze_lead(self, lead: LeadCreate) -> AIAnalysis:
        payload = {
            "model": self.model,
            "max_tokens": 512,
            # Structured output: pre-fill the assistant turn with "{" so the
            # model can only continue with JSON.
            "messages": [
                {"role": "user", "content": self._prompt(lead)},
                {"role": "assistant", "content": "{"},
            ],
        }
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        text = "{" + body["content"][0]["text"]
        return parse_analysis(json.loads(text), self.name)

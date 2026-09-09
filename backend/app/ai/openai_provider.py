"""OpenAI provider — same contract, different vendor."""

import json
import logging

import httpx

from app.ai.base import AIProvider, parse_analysis
from app.schemas.lead import AIAnalysis, LeadCreate

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required for AI_PROVIDER=openai. "
                "Use AI_PROVIDER=mock to run without a key."
            )
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def analyze_lead(self, lead: LeadCreate) -> AIAnalysis:
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": self._prompt(lead)}],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(API_URL, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        return parse_analysis(json.loads(body["choices"][0]["message"]["content"]), self.name)

"""Central configuration.

Every threshold, weight and toggle that a business stakeholder might want to
change lives here rather than being buried inside the rules engine.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LeadGuard"
    app_subtitle: str = "AI-assisted Lead Qualification & Routing"

    # sqlite+aiosqlite for a zero-setup local demo, postgresql+asyncpg in Docker.
    database_url: str = "sqlite+aiosqlite:///./leadguard.db"

    # --- AI ---------------------------------------------------------------
    # "mock" keeps the whole application working without any API key.
    ai_provider: Literal["mock", "anthropic", "openai"] = "mock"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    ai_timeout_seconds: float = 20.0

    # --- Decision thresholds ---------------------------------------------
    qualified_threshold: int = 80
    review_threshold: int = 50

    # --- Duplicate handling ----------------------------------------------
    duplicate_penalty: int = 40
    # A duplicate is never auto-qualified: it is capped at REVIEW so a human
    # decides whether it is a genuine re-engagement or a double submission.
    duplicate_blocks_qualification: bool = True
    duplicate_similarity_threshold: int = 80

    # --- Fake CRM integration --------------------------------------------
    crm_base_url: str | None = None  # None => call the in-process fake CRM
    crm_timeout_seconds: float = 5.0
    crm_max_attempts: int = 3
    crm_retry_backoff_seconds: float = 0.2
    # Deterministic failure hook so the demo can show a CRM outage.
    crm_fail_rate: float = 0.0

    # Populate the demo data on boot, so `docker compose up` is the only
    # command needed to get a working dashboard.
    seed_on_startup: bool = False

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()

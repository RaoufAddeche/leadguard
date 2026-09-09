"""LeadGuard application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.factory import build_provider
from app.api import fake_crm, leads, reviews, webhooks
from app.config import get_settings
from app.db.session import init_db
from app.integrations.crm import build_crm_client
from app.qualification import MAX_POSITIVE_SCORE

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s"
)
logger = logging.getLogger("leadguard")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.ai_provider = build_provider(settings)
    # With no external CRM configured the client loops back into this app, so
    # the demo runs as a single process.
    app.state.crm_client = build_crm_client(app=app, settings=settings)
    logger.info(
        "%s ready | ai_provider=%s | db=%s | thresholds=%s/%s | max_rule_score=%s",
        settings.app_name,
        app.state.ai_provider.name,
        settings.database_url.split("://")[0],
        settings.qualified_threshold,
        settings.review_threshold,
        MAX_POSITIVE_SCORE,
    )

    if settings.seed_on_startup:
        # Imported here so the seed module (which imports this app) does not
        # create a circular import at module load time.
        from app.db.seed import seed

        await seed()

    yield


app = FastAPI(
    title=settings.app_name,
    description=settings.app_subtitle,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(leads.router)
app.include_router(webhooks.router)
app.include_router(reviews.router)
app.include_router(fake_crm.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "ai_provider": settings.ai_provider,
        "thresholds": {
            "qualified": settings.qualified_threshold,
            "review": settings.review_threshold,
        },
    }


@app.get("/api/config", tags=["meta"])
async def config() -> dict:
    """Live configuration for the frontend.

    Thresholds, the rule weights and the demo personas are all served from here
    so the UI never hardcodes a number the backend owns — change a weight in
    `config.py` and the dashboard follows.
    """
    from app.db.seed import DEMO_PERSONAS
    from app.models.enums import Vertical
    from app.qualification import UNIVERSAL_MAX, UNIVERSAL_RULES, VERTICAL_RULES, max_score_for

    def describe(rules):
        return [{"rule": r.name, "max_score": r.max_score} for r in rules]

    return {
        "app_name": settings.app_name,
        "app_subtitle": settings.app_subtitle,
        "ai_provider": settings.ai_provider,
        "qualified_threshold": settings.qualified_threshold,
        "review_threshold": settings.review_threshold,
        "max_score": MAX_POSITIVE_SCORE,
        "universal_max": UNIVERSAL_MAX,
        "rules": describe(UNIVERSAL_RULES),
        # The eligibility criteria per line of business: this is what makes the
        # same pipeline serve six different clients.
        "verticals": {
            vertical.value: {
                "rules": describe(VERTICAL_RULES[vertical]),
                "max_score": max_score_for(vertical),
            }
            for vertical in Vertical
        },
        # Prefill payloads for the demo: typing 11 fields live is where demos die.
        "personas": {
            key: persona.model_dump(mode="json", exclude={"consent_timestamp"})
            for key, persona in DEMO_PERSONAS.items()
        },
    }

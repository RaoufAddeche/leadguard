"""Test fixtures.

The whole suite runs against an in-memory SQLite database with the MockAI
provider, so it needs no network, no API key and no Postgres.
"""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai.mock_provider import MockAIProvider
from app.api import fake_crm
from app.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.crm import CRMClient
from app.main import app as fastapi_app
from app.models import Base
from app.schemas.lead import LeadCreate


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        ai_provider="mock",
        crm_max_attempts=2,
        crm_retry_backoff_seconds=0.0,
    )


@pytest_asyncio.fixture
async def engine():
    # StaticPool keeps ONE connection alive, otherwise every session would get
    # a fresh (empty) in-memory database.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(engine):
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
def ai_provider() -> MockAIProvider:
    return MockAIProvider()


@pytest_asyncio.fixture
async def client(engine, settings, ai_provider):
    """An HTTP client bound to the real app, with the DB, AI provider and CRM
    client all swapped for test doubles."""
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    fake_crm.RECEIVED_LEADS.clear()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[get_settings] = lambda: settings

    transport = httpx.ASGITransport(app=fastapi_app)
    fastapi_app.state.ai_provider = ai_provider
    # The CRM client loops back into the app under test: a real HTTP round trip
    # through ASGI, with no socket.
    fastapi_app.state.crm_client = CRMClient(
        base_url="http://test", transport=transport, max_attempts=2, backoff=0.0
    )

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client

    fastapi_app.dependency_overrides.clear()


# --- Payload builders ----------------------------------------------------

def lead_payload(**overrides) -> dict:
    """An excellent lead by default; override fields to degrade it."""
    payload = {
        "firstname": "Thomas",
        "lastname": "Martin",
        "email": "thomas.martin@email.fr",
        "phone": "0612345678",
        "postal_code": "69003",
        "country": "FR",
        "source": "google_ads",
        "campaign": "PAC_Lyon",
        "project_description": (
            "Je souhaite remplacer ma chaudière fioul par une pompe à chaleur "
            "dans ma maison de 120m2 avant l'hiver."
        ),
        "owner": True,
        "budget": 12000,
        "consent": True,
    }
    payload.update(overrides)
    return payload


def lead_create(**overrides) -> LeadCreate:
    return LeadCreate(**lead_payload(**overrides))

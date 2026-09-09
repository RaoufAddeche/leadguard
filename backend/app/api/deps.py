"""FastAPI dependencies.

Both the AI provider and the CRM client are injected, which is what lets the
test suite swap in a failing CRM or a fixed AI without any network.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.ai.base import AIProvider
from app.config import Settings, get_settings
from app.integrations.crm import CRMClient


def get_ai_provider(request: Request) -> AIProvider:
    return request.app.state.ai_provider


def get_crm_client(request: Request) -> CRMClient:
    return request.app.state.crm_client


SettingsDep = Annotated[Settings, Depends(get_settings)]
AIProviderDep = Annotated[AIProvider, Depends(get_ai_provider)]
CRMClientDep = Annotated[CRMClient, Depends(get_crm_client)]

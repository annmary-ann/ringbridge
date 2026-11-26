"""Request-scoped dependencies."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ringbridge_server.db import session_scope
from ringbridge_server.models import DEFAULT_PROJECT_ID
from ringbridge_server.settings import Settings
from ringbridge_server.telephony import SipControl


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async for session in session_scope(request.app.state.sessionmaker):
        yield session


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_project_id() -> uuid.UUID:
    """Single-tenant mode. Multi-tenancy (#46) resolves the project from the API key instead."""
    return DEFAULT_PROJECT_ID


SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ProjectDep = Annotated[uuid.UUID, Depends(get_project_id)]


def get_sip(request: Request) -> SipControl:
    sip: SipControl = request.app.state.sip
    return sip


SipDep = Annotated[SipControl, Depends(get_sip)]

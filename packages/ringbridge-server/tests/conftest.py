"""Fixtures for server tests.

Integration tests need Postgres. They use a throwaway `ringbridge_test` database on the server
named by RINGBRIDGE_TEST_DATABASE_URL (default: the dev stack on port 5435) and are skipped when
it is unreachable, unless RINGBRIDGE_REQUIRE_DB=1 (set in CI) turns that into a failure.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from ringbridge_server import migrate
from ringbridge_server.app import create_app
from ringbridge_server.settings import Settings
from ringbridge_server.testing import InMemorySip

TEST_DB = "ringbridge_test"
WORKER_TOKEN = "test-worker-token"
DEFAULT_ADMIN_URL = "postgresql://ringbridge:ringbridge@localhost:5435/ringbridge"
REPO = Path(__file__).resolve().parents[3]
EXAMPLE_SPEC = REPO / "examples" / "dental-clinic" / "agent.yaml"
TENANT_TABLES = ("call_events", "calls", "phone_numbers", "sip_trunks", "agent_versions", "agents")


async def _recreate_database(admin_url: str, name: str) -> None:
    conn = await asyncpg.connect(admin_url, timeout=3)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database_url() -> str:
    admin = make_url(os.environ.get("RINGBRIDGE_TEST_DATABASE_URL", DEFAULT_ADMIN_URL))
    plain_admin = admin.set(drivername="postgresql").render_as_string(hide_password=False)
    try:
        asyncio.run(_recreate_database(plain_admin, TEST_DB))
    except (OSError, TimeoutError, asyncpg.PostgresError) as e:
        reason = f"Postgres is not reachable ({type(e).__name__}): start it with `poe up`"
        if os.environ.get("RINGBRIDGE_REQUIRE_DB") == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    url = admin.set(drivername="postgresql", database=TEST_DB).render_as_string(hide_password=False)
    migrate.upgrade(url)
    return url


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url, log_json=False, worker_token=SecretStr(WORKER_TOKEN))


async def _truncate(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(TENANT_TABLES)} CASCADE"))


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    app = create_app(settings)
    engine: AsyncEngine = app.state.engine
    await _truncate(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
def sip() -> InMemorySip:
    return InMemorySip()


@pytest.fixture
async def client(settings: Settings, sip: InMemorySip) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, sip=sip)
    await _truncate(app.state.engine)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await app.state.engine.dispose()


@pytest.fixture
def spec_text() -> str:
    return EXAMPLE_SPEC.read_text(encoding="utf-8")

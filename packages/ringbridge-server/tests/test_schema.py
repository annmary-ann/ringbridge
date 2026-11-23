"""Migrations, model/migration drift, constraints and immutability triggers."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ringbridge_server import migrate
from ringbridge_server.models import DEFAULT_PROJECT_ID, Base

pytestmark = pytest.mark.integration


def test_migrations_run_down_and_up_again(database_url: str) -> None:
    migrate.downgrade(database_url, "base")
    migrate.upgrade(database_url)
    migrate.downgrade(database_url, "base")
    migrate.upgrade(database_url)


def _diff(conn: Connection) -> list[Any]:
    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    return list(compare_metadata(ctx, Base.metadata))


@pytest.mark.anyio
async def test_models_match_migrations(engine: AsyncEngine) -> None:
    """Fails when a model changes without a migration (`python -m ringbridge_server revision`)."""
    async with engine.connect() as conn:
        diff = await conn.run_sync(_diff)
    assert diff == []


@pytest.mark.anyio
async def test_default_project_exists(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        slug = await conn.scalar(
            text("SELECT slug FROM projects WHERE id = :id"), {"id": DEFAULT_PROJECT_ID}
        )
    assert slug == "default"


async def _agent_version(conn: Any) -> uuid.UUID:
    agent_id = await conn.scalar(
        text("INSERT INTO agents (project_id, name) VALUES (:p, 'a') RETURNING id"),
        {"p": DEFAULT_PROJECT_ID},
    )
    version_id: uuid.UUID = await conn.scalar(
        text(
            "INSERT INTO agent_versions (project_id, agent_id, version, api_version, spec, "
            "source, spec_sha256) VALUES (:p, :a, 1, 'v', '{}', '', repeat('0', 64)) RETURNING id"
        ),
        {"p": DEFAULT_PROJECT_ID, "a": agent_id},
    )
    return version_id


@pytest.mark.anyio
async def test_agent_versions_reject_updates(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        version_id = await _agent_version(conn)
        with pytest.raises(DBAPIError, match="agent_versions rows are immutable"):
            await conn.execute(
                text("UPDATE agent_versions SET source = 'changed' WHERE id = :id"),
                {"id": version_id},
            )


@pytest.mark.anyio
async def test_call_events_are_append_only_and_idempotent(engine: AsyncEngine) -> None:
    insert_event = text(
        "INSERT INTO call_events (project_id, call_id, event_id, seq, type, occurred_at) "
        "VALUES (:p, :c, 'turn-1', 1, 'turn', now())"
    )
    async with engine.connect() as conn:
        call_id = await conn.scalar(
            text("INSERT INTO calls (project_id, direction) VALUES (:p, 'inbound') RETURNING id"),
            {"p": DEFAULT_PROJECT_ID},
        )
        await conn.execute(insert_event, {"p": DEFAULT_PROJECT_ID, "c": call_id})
        await conn.commit()

        with pytest.raises(IntegrityError):  # same event id twice
            await conn.execute(insert_event, {"p": DEFAULT_PROJECT_ID, "c": call_id})
        await conn.rollback()

        with pytest.raises(DBAPIError, match="call_events rows are immutable"):
            await conn.execute(text("UPDATE call_events SET seq = 2"))
        await conn.rollback()

        status = await conn.scalar(text("SELECT status FROM calls WHERE id = :c"), {"c": call_id})
        assert status == "queued"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO phone_numbers (project_id, e164) VALUES (:p, '0471234567')",
        "INSERT INTO phone_numbers (project_id, e164) VALUES (:p, '+0123456789')",
        "INSERT INTO calls (project_id, direction) VALUES (:p, 'sideways')",
        "INSERT INTO calls (project_id, direction, status) VALUES (:p, 'inbound', 'lost')",
        "INSERT INTO sip_trunks (project_id, name, direction) VALUES (:p, 't', 'up')",
        "INSERT INTO agents (project_id, name) VALUES (:p, 'Not A Slug')",
    ],
)
async def test_check_constraints(engine: AsyncEngine, statement: str) -> None:
    async with engine.connect() as conn:
        with pytest.raises(IntegrityError):
            await conn.execute(text(statement), {"p": DEFAULT_PROJECT_ID})


@pytest.mark.anyio
async def test_valid_phone_number_and_trunk(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        trunk = await conn.scalar(
            text(
                "INSERT INTO sip_trunks (project_id, name, direction) "
                "VALUES (:p, 'main', 'inbound') RETURNING id"
            ),
            {"p": DEFAULT_PROJECT_ID},
        )
        await conn.execute(
            text(
                "INSERT INTO phone_numbers (project_id, e164, sip_trunk_id) "
                "VALUES (:p, '+914842000123', :t)"
            ),
            {"p": DEFAULT_PROJECT_ID, "t": trunk},
        )

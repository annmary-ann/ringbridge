"""Core tables (docs/architecture.md section 9).

Every tenant table carries `project_id`. Row-level security on top of it arrives with
multi-tenancy (#46); until then the server runs in single-tenant mode with one default project.
Enumerations are text columns with CHECK constraints, so adding a value is a one-line migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_PROJECT_SLUG = "default"

SLUG_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"
E164_PATTERN = r"^\+[1-9][0-9]{6,14}$"

TRUNK_DIRECTIONS = ("inbound", "outbound", "both")
SYNC_STATUSES = ("pending", "synced", "error", "not_applicable")
CALL_DIRECTIONS = ("inbound", "outbound", "web")
CALL_STATUSES = (
    "queued",
    "ringing",
    "in_progress",
    "completed",
    "no_answer",
    "busy",
    "failed",
    "canceled",
)

# Tables whose rows may never change once written (enforced by trigger in the migrations).
IMMUTABLE_TABLES = ("agent_versions", "call_events")

# Stable constraint names, so Alembic migrations can refer to them on every database.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _project_fk(*, index: bool = True) -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=index
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint(f"slug ~ '{SLUG_PATTERN}'", name="slug_format"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        CheckConstraint(f"name ~ '{SLUG_PATTERN}'", name="name_format"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # The (project_id, name) unique index serves project lookups too.
    project_id: Mapped[uuid.UUID] = _project_fk(index=False)
    name: Mapped[str] = mapped_column(String(63))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentVersion(Base):
    """A published spec. Immutable: a database trigger rejects every UPDATE."""

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("char_length(spec_sha256) = 64", name="sha256_length"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT")
    )
    version: Mapped[int] = mapped_column(Integer)
    api_version: Mapped[str] = mapped_column(String(100))
    # The validated spec with defaults filled in: exactly what a worker will run.
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # The document as submitted (YAML comments included), for editors and diffs.
    source: Mapped[str] = mapped_column(Text)
    spec_sha256: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SipTrunk(Base):
    __tablename__ = "sip_trunks"
    __table_args__ = (
        UniqueConstraint("project_id", "name"),
        CheckConstraint(_in("direction", TRUNK_DIRECTIONS), name="direction"),
        CheckConstraint(_in("sync_status", SYNC_STATUSES), name="sync_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk(index=False)
    name: Mapped[str] = mapped_column(String(100))
    direction: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str | None] = mapped_column(String(50))
    sip_address: Mapped[str | None] = mapped_column(String(255))
    livekit_trunk_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    # Inbound only: who may send calls (IPs or CIDRs) and optional digest auth username.
    # The password goes straight to LiveKit and is never stored here.
    allowed_addresses: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=text("'{}'")
    )
    auth_username: Mapped[str | None] = mapped_column(String(100))
    livekit_dispatch_rule_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    sync_status: Mapped[str] = mapped_column(String(16), server_default="pending")
    sync_error: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class PhoneNumber(Base):
    """A number on a trunk. Inbound calls route to `agent_id`, pinned to a version if set."""

    __tablename__ = "phone_numbers"
    __table_args__ = (CheckConstraint(f"e164 ~ '{E164_PATTERN}'", name="e164_format"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk()
    e164: Mapped[str] = mapped_column(String(16), unique=True)
    label: Mapped[str | None] = mapped_column(String(100))
    sip_trunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sip_trunks.id", ondelete="SET NULL")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(_in("direction", CALL_DIRECTIONS), name="direction"),
        CheckConstraint(_in("status", CALL_STATUSES), name="status"),
        Index("ix_calls_project_id_created_at", "project_id", text("created_at DESC")),
        # One call per LiveKit room: makes call creation by workers idempotent.
        Index(
            "uq_calls_livekit_room",
            "livekit_room",
            unique=True,
            postgresql_where=text("livekit_room IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = _project_fk(index=False)
    direction: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="queued")
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL")
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    from_number: Mapped[str | None] = mapped_column(String(32))
    to_number: Mapped[str | None] = mapped_column(String(32))
    livekit_room: Mapped[str | None] = mapped_column(String(128))
    trace_id: Mapped[str | None] = mapped_column(String(32))
    end_reason: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class CallEvent(Base):
    """Append-only call history. `event_id` makes ingestion idempotent; UPDATE is rejected."""

    __tablename__ = "call_events"
    __table_args__ = (
        UniqueConstraint("call_id", "event_id"),
        Index("ix_call_events_call_id_seq", "call_id", "seq"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = _project_fk()
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE")
    )
    event_id: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _created_at()

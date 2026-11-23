"""Core tables, immutability triggers and the default project (#9).

Revision ID: 0001
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of model constants: a migration must not change when the models do.
DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_PROJECT_SLUG = "default"
IMMUTABLE_TABLES = ("agent_versions", "call_events")

FORBID_UPDATE_FN = """
CREATE FUNCTION ringbridge_forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'", name=op.f("ck_projects_slug_format")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("slug", name=op.f("uq_projects_slug")),
    )
    op.create_table(
        "agents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=63), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "name ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'", name=op.f("ck_agents_name_format")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agents_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_agents_project_id_name")),
    )
    op.create_table(
        "sip_trunks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("sip_address", sa.String(length=255), nullable=True),
        sa.Column("livekit_trunk_id", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'both')", name=op.f("ck_sip_trunks_direction")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_sip_trunks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sip_trunks")),
        sa.UniqueConstraint("livekit_trunk_id", name=op.f("uq_sip_trunks_livekit_trunk_id")),
        sa.UniqueConstraint("project_id", "name", name=op.f("uq_sip_trunks_project_id_name")),
    )
    op.create_table(
        "agent_versions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("api_version", sa.String(length=100), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("spec_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(spec_sha256) = 64", name=op.f("ck_agent_versions_sha256_length")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_agent_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_versions_agent_id_agents"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agent_versions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.UniqueConstraint("agent_id", "version", name=op.f("uq_agent_versions_agent_id_version")),
    )
    op.create_index(
        op.f("ix_agent_versions_project_id"), "agent_versions", ["project_id"], unique=False
    )
    op.create_table(
        "phone_numbers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("e164", sa.String(length=16), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("sip_trunk_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "e164 ~ '^\\+[1-9][0-9]{6,14}$'", name=op.f("ck_phone_numbers_e164_format")
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_phone_numbers_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("fk_phone_numbers_agent_version_id_agent_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_phone_numbers_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sip_trunk_id"],
            ["sip_trunks.id"],
            name=op.f("fk_phone_numbers_sip_trunk_id_sip_trunks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_phone_numbers")),
        sa.UniqueConstraint("e164", name=op.f("uq_phone_numbers_e164")),
    )
    op.create_index(
        op.f("ix_phone_numbers_project_id"), "phone_numbers", ["project_id"], unique=False
    )
    op.create_table(
        "calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("agent_version_id", sa.UUID(), nullable=True),
        sa.Column("phone_number_id", sa.UUID(), nullable=True),
        sa.Column("from_number", sa.String(length=32), nullable=True),
        sa.Column("to_number", sa.String(length=32), nullable=True),
        sa.Column("livekit_room", sa.String(length=128), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('inbound', 'outbound', 'web')", name=op.f("ck_calls_direction")
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'ringing', 'in_progress', 'completed', "
            "'no_answer', 'busy', 'failed', 'canceled')",
            name=op.f("ck_calls_status"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("fk_calls_agent_version_id_agent_versions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["phone_number_id"],
            ["phone_numbers.id"],
            name=op.f("fk_calls_phone_number_id_phone_numbers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_calls_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calls")),
    )
    op.create_index(
        "ix_calls_project_id_created_at",
        "calls",
        ["project_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "call_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["call_id"], ["calls.id"], name=op.f("fk_call_events_call_id_calls"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_call_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_call_events")),
        sa.UniqueConstraint("call_id", "event_id", name=op.f("uq_call_events_call_id_event_id")),
    )
    op.create_index("ix_call_events_call_id_seq", "call_events", ["call_id", "seq"], unique=False)
    op.create_index(op.f("ix_call_events_project_id"), "call_events", ["project_id"], unique=False)

    # Published agent versions and call events are history: rows may be added or deleted
    # (retention), never changed.
    op.execute(FORBID_UPDATE_FN)
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION ringbridge_forbid_update()"
        )

    # Single-tenant mode: everything belongs to this project until multi-tenancy (#46).
    op.execute(
        sa.text(
            "INSERT INTO projects (id, slug, name) VALUES (:id, :slug, 'Default project')"
        ).bindparams(
            sa.bindparam("id", DEFAULT_PROJECT_ID, type_=sa.UUID(as_uuid=False)),
            sa.bindparam("slug", DEFAULT_PROJECT_SLUG),
        )
    )


def downgrade() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS ringbridge_forbid_update()")
    op.drop_index(op.f("ix_call_events_project_id"), table_name="call_events")
    op.drop_index("ix_call_events_call_id_seq", table_name="call_events")
    op.drop_table("call_events")
    op.drop_index("ix_calls_project_id_created_at", table_name="calls")
    op.drop_table("calls")
    op.drop_index(op.f("ix_phone_numbers_project_id"), table_name="phone_numbers")
    op.drop_table("phone_numbers")
    op.drop_index(op.f("ix_agent_versions_project_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_table("sip_trunks")
    op.drop_table("agents")
    op.drop_table("projects")

"""SIP trunk sync state with LiveKit, allowed addresses and auth username (#12).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sip_trunks",
        sa.Column(
            "allowed_addresses",
            postgresql.ARRAY(sa.String(length=64)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column("sip_trunks", sa.Column("auth_username", sa.String(length=100), nullable=True))
    op.add_column(
        "sip_trunks", sa.Column("livekit_dispatch_rule_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "sip_trunks",
        sa.Column("sync_status", sa.String(length=16), server_default="pending", nullable=False),
    )
    op.add_column("sip_trunks", sa.Column("sync_error", sa.Text(), nullable=True))
    op.add_column("sip_trunks", sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint(
        op.f("uq_sip_trunks_livekit_dispatch_rule_id"), "sip_trunks", ["livekit_dispatch_rule_id"]
    )
    op.create_check_constraint(
        op.f("ck_sip_trunks_sync_status"),
        "sip_trunks",
        "sync_status IN ('pending', 'synced', 'error', 'not_applicable')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_sip_trunks_sync_status"), "sip_trunks", type_="check")
    op.drop_constraint(op.f("uq_sip_trunks_livekit_dispatch_rule_id"), "sip_trunks", type_="unique")
    op.drop_column("sip_trunks", "synced_at")
    op.drop_column("sip_trunks", "sync_error")
    op.drop_column("sip_trunks", "sync_status")
    op.drop_column("sip_trunks", "livekit_dispatch_rule_id")
    op.drop_column("sip_trunks", "auth_username")
    op.drop_column("sip_trunks", "allowed_addresses")

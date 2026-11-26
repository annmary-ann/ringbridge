"""One call per LiveKit room, so workers can create calls idempotently (#13).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_calls_livekit_room",
        "calls",
        ["livekit_room"],
        unique=True,
        postgresql_where=sa.text("livekit_room IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_calls_livekit_room",
        table_name="calls",
        postgresql_where=sa.text("livekit_room IS NOT NULL"),
    )

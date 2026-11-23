"""Programmatic Alembic: the migrations ship inside the package, so no alembic.ini is needed."""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

SCRIPT_LOCATION = "ringbridge_server:migrations"


def alembic_config(database_url: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", SCRIPT_LOCATION)
    cfg.set_main_option("path_separator", "os")
    if database_url is not None:
        cfg.attributes["database_url"] = database_url
    return cfg


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:  # pragma: no cover - the package always ships migrations
        raise RuntimeError("no migrations found")
    return head


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None, revision: str) -> None:
    command.downgrade(alembic_config(database_url), revision)


def revision(message: str, database_url: str | None = None, *, autogenerate: bool = True) -> None:
    command.revision(alembic_config(database_url), message=message, autogenerate=autogenerate)

"""Server configuration, read from RINGBRIDGE_* environment variables and an optional .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_ASYNC_DRIVER = "postgresql+asyncpg://"
_PLAIN_SCHEMES = ("postgresql://", "postgres://", "postgresql+psycopg://", "postgresql+psycopg2://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RINGBRIDGE_", env_file=".env", extra="ignore", populate_by_name=True
    )

    # repr=False keeps the password out of logs and tracebacks.
    database_url: str = Field(
        default="postgresql://ringbridge:ringbridge@localhost:5435/ringbridge", repr=False
    )
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    log_level: LogLevel = "INFO"
    log_json: bool = True
    host: str = "127.0.0.1"
    port: int = Field(default=8088, ge=1, le=65535)
    max_spec_bytes: int = Field(default=1_000_000, ge=1)
    # Shared secret agent workers send as `Authorization: Bearer ...` on /internal routes.
    # Unset disables the internal API. Short-lived per-worker tokens replace it later.
    worker_token: SecretStr | None = None
    worker_token_ttl_s: int = Field(default=900, ge=60, le=86_400)

    # LiveKit: the standard LIVEKIT_* names work too. Defaults match the dev stack.
    livekit_url: str = Field(
        default="ws://localhost:7880",
        validation_alias=AliasChoices("RINGBRIDGE_LIVEKIT_URL", "LIVEKIT_URL", "livekit_url"),
    )
    livekit_api_key: str = Field(
        default="devkey",
        validation_alias=AliasChoices(
            "RINGBRIDGE_LIVEKIT_API_KEY", "LIVEKIT_API_KEY", "livekit_api_key"
        ),
    )
    livekit_api_secret: SecretStr = Field(
        default=SecretStr("devsecret-devsecret-devsecret-devsecret"),
        validation_alias=AliasChoices(
            "RINGBRIDGE_LIVEKIT_API_SECRET", "LIVEKIT_API_SECRET", "livekit_api_secret"
        ),
    )
    # The LiveKit Agents worker name that dispatch rules send calls to.
    agent_name: str = "ringbridge"

    @property
    def async_database_url(self) -> str:
        """The URL with the asyncpg driver, whatever scheme was configured."""
        return to_async_url(self.database_url)


def to_async_url(url: str) -> str:
    if url.startswith(_ASYNC_DRIVER):
        return url
    for scheme in _PLAIN_SCHEMES:
        if url.startswith(scheme):
            return _ASYNC_DRIVER + url[len(scheme) :]
    raise ValueError("database_url must be a PostgreSQL URL (postgresql://...)")


@lru_cache
def get_settings() -> Settings:
    return Settings()

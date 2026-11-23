"""Server configuration, read from RINGBRIDGE_* environment variables and an optional .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

_ASYNC_DRIVER = "postgresql+asyncpg://"
_PLAIN_SCHEMES = ("postgresql://", "postgres://", "postgresql+psycopg://", "postgresql+psycopg2://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RINGBRIDGE_", env_file=".env", extra="ignore")

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

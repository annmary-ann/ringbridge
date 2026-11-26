"""App factory, health endpoints, settings, logging and the command line. No database needed
except where a test asks for the `client` fixture."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import httpx
import pytest

from ringbridge_server import __main__ as cli
from ringbridge_server import migrate, settings
from ringbridge_server.app import create_app
from ringbridge_server.logs import JsonFormatter, configure_logging
from ringbridge_server.migrate import head_revision
from ringbridge_server.settings import Settings, to_async_url

UNREACHABLE = "postgresql://nobody:nothing@127.0.0.1:1/none"


def _offline_client(**overrides: Any) -> httpx.AsyncClient:
    app = create_app(Settings(database_url=UNREACHABLE, **overrides))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@h:5/db",
        "postgres://u:p@h:5/db",
        "postgresql+psycopg://u:p@h:5/db",
        "postgresql+asyncpg://u:p@h:5/db",
    ],
)
def test_any_postgres_url_gets_the_async_driver(url: str) -> None:
    assert to_async_url(url) == "postgresql+asyncpg://u:p@h:5/db"


def test_non_postgres_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        to_async_url("mysql://u:p@h/db")


def test_settings_repr_hides_the_database_password() -> None:
    s = Settings(database_url="postgresql://u:hunter2@h/db")
    assert "hunter2" not in repr(s)
    assert s.async_database_url.startswith("postgresql+asyncpg://")


# ------------------------------------------------------------------ logging


def test_json_formatter_includes_extra_fields_and_exceptions() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.getLogger("t").makeRecord(
            "t", logging.ERROR, __file__, 1, "failed %s", ("x",), sys.exc_info()
        )
    record.request_id = "abc"
    out = json.loads(JsonFormatter().format(record))
    assert out["msg"] == "failed x"
    assert out["level"] == "error"
    assert out["request_id"] == "abc"
    assert "RuntimeError: boom" in out["exc"]


@pytest.mark.parametrize("json_lines", [True, False])
def test_configure_logging_installs_one_handler(json_lines: bool) -> None:
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        configure_logging("DEBUG", json_lines)
        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter) is json_lines
        assert logging.getLogger("uvicorn.access").disabled
    finally:
        root.handlers[:], level = saved
        root.setLevel(level)
        logging.getLogger("uvicorn.access").disabled = False


# ------------------------------------------------------------------ health


@pytest.mark.anyio
async def test_healthz_needs_no_database() -> None:
    async with _offline_client() as client:
        r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.anyio
async def test_readyz_is_503_when_the_database_is_down() -> None:
    async with _offline_client() as client:
        r = await client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["reason"].startswith("database unavailable")


@pytest.mark.anyio
@pytest.mark.integration
async def test_readyz_checks_the_schema_revision(client: httpx.AsyncClient) -> None:
    assert (await client.get("/readyz")).json() == {"status": "ready", "schema": head_revision()}
    app: Any = client._transport.app  # type: ignore[attr-defined]
    app.state.schema_head = "9999"
    r = await client.get("/readyz")
    assert r.status_code == 503
    assert "expected 9999" in r.json()["reason"]


@pytest.mark.anyio
async def test_request_id_is_echoed_or_generated(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ringbridge.server")
    async with _offline_client() as client:
        given = await client.get("/v1/nothing", headers={"x-request-id": "req-1"})
        made = await client.get("/healthz")
    assert given.headers["x-request-id"] == "req-1"
    assert len(made.headers["x-request-id"]) == 32
    logged = [r for r in caplog.records if r.getMessage() == "request"]
    assert [getattr(r, "request_id", None) for r in logged] == ["req-1"]  # health not logged


@pytest.mark.anyio
async def test_openapi_documents_the_spec_body() -> None:
    async with _offline_client() as client:
        doc = (await client.get("/openapi.json")).json()
    publish = doc["paths"]["/v1/agents/{agent_id}/versions"]["post"]
    assert set(publish["requestBody"]["content"]) == {"application/yaml", "application/json"}
    assert {"200", "201", "422"} <= set(publish["responses"])


# ------------------------------------------------------------------ command line


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    seen: list[tuple[Any, ...]] = []
    monkeypatch.setenv("RINGBRIDGE_DATABASE_URL", "postgresql://u:p@h/db")
    settings.get_settings.cache_clear()
    for name in ("upgrade", "downgrade", "revision"):
        monkeypatch.setattr(
            migrate, name, lambda *a, _n=name, **k: seen.append((_n, *a, *k.values()))
        )
    return seen


def test_cli_migration_commands(calls: list[tuple[Any, ...]]) -> None:
    url = "postgresql://u:p@h/db"
    assert cli.main(["migrate"]) == 0
    assert cli.main(["downgrade", "-1"]) == 0
    assert cli.main(["revision", "-m", "add things"]) == 0
    assert cli.main(["revision", "-m", "by hand", "--empty"]) == 0
    assert calls == [
        ("upgrade", url, "head"),
        ("downgrade", url, "-1"),
        ("revision", "add things", url, True),
        ("revision", "by hand", url, False),
    ]


def test_cli_serve(calls: list[tuple[Any, ...]], monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    served: dict[str, Any] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: served.update(kw, app=app))
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        assert cli.main(["serve", "--port", "9999", "--migrate"]) == 0
    finally:
        root.handlers[:], level = saved
        root.setLevel(level)
        logging.getLogger("uvicorn.access").disabled = False
    assert served["port"] == 9999
    assert served["host"] == "127.0.0.1"
    assert served["app"].title == "Ringbridge control plane"
    assert calls == [("upgrade", "postgresql://u:p@h/db")]


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


@pytest.mark.anyio
async def test_internal_api_is_disabled_without_a_worker_token() -> None:
    async with _offline_client() as client:
        r = await client.post("/internal/calls", json={"direction": "web", "livekit_room": "r"})
    assert r.status_code == 503
    assert "RINGBRIDGE_WORKER_TOKEN" in r.json()["detail"]

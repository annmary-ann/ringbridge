"""Agents and immutable agent versions over HTTP, against a real Postgres."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
import yaml

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

NAME = "smile-dental-receptionist"
YAML = {"content-type": "application/yaml"}


async def _agent(client: httpx.AsyncClient, name: str = NAME) -> str:
    r = await client.post("/v1/agents", json={"name": name, "description": "Front desk"})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _variant(spec_text: str, n: int) -> str:
    """The example spec with a different description, so it hashes differently."""
    old = "  description: Front desk for a dental clinic in Kochi; English and Hindi."
    assert old in spec_text
    return spec_text.replace(old, f"  description: Variant {n}")


async def test_create_get_and_list_agents(client: httpx.AsyncClient) -> None:
    agent_id = await _agent(client)
    await _agent(client, "aaa-first-by-name")

    r = await client.get(f"/v1/agents/{agent_id}")
    assert r.status_code == 200
    assert r.json() | {"created_at": None} == {
        "id": agent_id,
        "name": NAME,
        "description": "Front desk",
        "created_at": None,
        "latest_version": None,
    }

    names = [a["name"] for a in (await client.get("/v1/agents")).json()]
    assert names == ["aaa-first-by-name", NAME]
    page = (await client.get("/v1/agents", params={"limit": 1, "offset": 1})).json()
    assert [a["name"] for a in page] == [NAME]


async def test_duplicate_agent_name_conflicts(client: httpx.AsyncClient) -> None:
    await _agent(client)
    r = await client.post("/v1/agents", json={"name": NAME})
    assert r.status_code == 409
    assert NAME in r.json()["detail"]


@pytest.mark.parametrize("name", ["Has-Caps", "-leading", "trailing-", "", "a" * 64, "sp ace"])
async def test_agent_name_must_be_a_slug(client: httpx.AsyncClient, name: str) -> None:
    r = await client.post("/v1/agents", json={"name": name})
    assert r.status_code == 422


async def test_unknown_agent_is_404(client: httpx.AsyncClient, spec_text: str) -> None:
    missing = uuid.uuid4()
    assert (await client.get(f"/v1/agents/{missing}")).status_code == 404
    assert (await client.get(f"/v1/agents/{missing}/versions")).status_code == 404
    r = await client.post(f"/v1/agents/{missing}/versions", content=spec_text, headers=YAML)
    assert r.status_code == 404


async def test_publish_yaml_stores_an_immutable_snapshot(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    agent_id = await _agent(client)
    r = await client.post(f"/v1/agents/{agent_id}/versions", content=spec_text, headers=YAML)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 1
    assert body["api_version"] == "ringbridge.dev/v1alpha1"
    assert len(body["spec_sha256"]) == 64
    assert body["source"] == spec_text  # comments and formatting kept
    assert body["spec"]["metadata"]["name"] == NAME
    assert body["spec"]["apiVersion"] == "ringbridge.dev/v1alpha1"  # stored by alias
    assert isinstance(body["warnings"], list)

    got = (await client.get(f"/v1/agents/{agent_id}/versions/1")).json()
    assert got["spec"] == body["spec"]
    assert got["source"] == spec_text
    assert (await client.get(f"/v1/agents/{agent_id}")).json()["latest_version"] == 1


async def test_republishing_the_same_spec_is_idempotent(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    agent_id = await _agent(client)
    url = f"/v1/agents/{agent_id}/versions"
    first = await client.post(url, content=spec_text, headers=YAML)
    assert first.status_code == 201

    # Same content as JSON and with different YAML comments: same hash, no new version.
    as_json = json.dumps(yaml.safe_load(spec_text), indent=2)
    again = await client.post(url, content=as_json, headers={"content-type": "application/json"})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    recommented = await client.post(url, content="# edited\n" + spec_text, headers=YAML)
    assert recommented.status_code == 200

    changed = await client.post(url, content=_variant(spec_text, 2), headers=YAML)
    assert changed.status_code == 201
    assert changed.json()["version"] == 2

    versions = (await client.get(url)).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert "spec" not in versions[0]  # summaries only


async def test_concurrent_publishes_get_consecutive_versions(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    agent_id = await _agent(client)
    url = f"/v1/agents/{agent_id}/versions"
    results = await asyncio.gather(
        *(client.post(url, content=_variant(spec_text, n), headers=YAML) for n in range(6))
    )
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    assert sorted(r.json()["version"] for r in results) == [1, 2, 3, 4, 5, 6]


async def test_invalid_spec_lists_every_error_with_lines(client: httpx.AsyncClient) -> None:
    agent_id = await _agent(client)
    doc = "apiVersion: ringbridge.dev/v1alpha1\nkind: Agent\nmetadata: {name: x}\nspec: {}\n"
    r = await client.post(f"/v1/agents/{agent_id}/versions", content=doc, headers=YAML)
    assert r.status_code == 422
    body = r.json()
    assert body["detail"] == "the spec has 5 errors"
    paths = {i["path"] for i in body["issues"]}
    assert {"spec.language", "spec.voice", "spec.graph"} <= paths
    assert all(i["line"] == 4 and i["severity"] == "error" for i in body["issues"])
    assert (await client.get(f"/v1/agents/{agent_id}/versions")).json() == []


async def test_broken_yaml_is_422(client: httpx.AsyncClient) -> None:
    agent_id = await _agent(client)
    r = await client.post(
        f"/v1/agents/{agent_id}/versions", content="kind: [unclosed\n", headers=YAML
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "the spec has 1 error"
    assert r.json()["issues"][0]["message"].startswith("invalid YAML")


async def test_spec_for_another_agent_is_rejected(
    client: httpx.AsyncClient, spec_text: str
) -> None:
    other = await _agent(client, "someone-else")
    r = await client.post(f"/v1/agents/{other}/versions", content=spec_text, headers=YAML)
    assert r.status_code == 422
    [issue] = r.json()["issues"]
    assert issue["path"] == "metadata.name"
    assert "someone-else" in issue["message"]


async def test_body_limits(client: httpx.AsyncClient) -> None:
    agent_id = await _agent(client)
    url = f"/v1/agents/{agent_id}/versions"
    too_big = b"#" * 1_000_001
    assert (await client.post(url, content=too_big, headers=YAML)).status_code == 413
    assert (await client.post(url, content=b"\xff\xfe", headers=YAML)).status_code == 400


async def test_unknown_version_is_404(client: httpx.AsyncClient) -> None:
    agent_id = await _agent(client)
    assert (await client.get(f"/v1/agents/{agent_id}/versions/7")).status_code == 404

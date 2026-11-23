import json
from pathlib import Path

import pytest
import yaml

from ringbridge_core.spec import AgentSpec, json_schema, json_schema_text, load_file, load_text
from ringbridge_core.spec.semantic import _identifiers

REPO = Path(__file__).resolve().parents[3]
EXAMPLES = sorted((REPO / "examples").glob("*/agent.yaml"))
SCHEMA_FILE = REPO / "docs" / "schema" / "agent-v1alpha1.json"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.parent.name)
def test_examples_are_valid_without_warnings(path: Path) -> None:
    report = load_file(path)
    assert report.ok, report.format()
    assert report.warnings == [], report.format()


def test_examples_exist() -> None:
    assert EXAMPLES, "no examples/*/agent.yaml found"


def test_committed_schema_matches_models() -> None:
    committed = SCHEMA_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == json_schema_text(), "schema is stale: run `uv run poe schema`"


def test_schema_uses_camelcase_api_version_and_forbids_extra_keys() -> None:
    schema = json_schema()
    assert "apiVersion" in schema["properties"]
    assert schema["additionalProperties"] is False


def test_json_input_works_like_yaml() -> None:
    data = yaml.safe_load(EXAMPLES[0].read_text(encoding="utf-8"))
    report = load_text(json.dumps(data), source="agent.json")
    assert report.ok, report.format()


def test_round_trip_through_model_dump() -> None:
    spec = load_file(EXAMPLES[0]).spec
    assert spec is not None
    again = AgentSpec.model_validate(spec.model_dump(by_alias=True))
    assert again == spec


def test_specs_are_immutable() -> None:
    spec = load_file(EXAMPLES[0]).spec
    assert spec is not None
    with pytest.raises(Exception, match="frozen"):
        spec.kind = "Agent"  # type: ignore[misc]


def test_unreadable_file_is_an_error(tmp_path: Path) -> None:
    report = load_file(tmp_path / "missing.yaml")
    assert not report.ok
    assert "cannot read file" in report.errors[0].message


@pytest.mark.parametrize(
    ("expr", "names"),
    [
        ("outcome == 'booked'", ["outcome"]),
        ("outcome == 'no answer' and attempt < 3", ["outcome", "attempt"]),
        ('urgent is true or lead_status in ("new", "qualified")', ["urgent", "lead_status"]),
        ("not urgent", ["urgent"]),
    ],
)
def test_condition_identifiers_ignore_keywords_and_strings(expr: str, names: list[str]) -> None:
    assert _identifiers(expr) == names


def test_issue_paths_are_readable() -> None:
    report = load_text("apiVersion: x\nkind: Agent\n")
    dotted = {i.dotted for i in report.errors}
    assert "apiVersion" in dotted
    assert "metadata" in dotted

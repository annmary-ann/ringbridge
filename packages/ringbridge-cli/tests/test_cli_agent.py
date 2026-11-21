import json
from pathlib import Path

import pytest

from ringbridge_cli.main import main

REPO = Path(__file__).resolve().parents[3]
EXAMPLE = str(REPO / "examples" / "dental-clinic" / "agent.yaml")
FIXTURES = REPO / "packages" / "ringbridge-core" / "tests" / "fixtures" / "spec"
INVALID = str(FIXTURES / "invalid" / "start-missing.yaml")
WARNING = str(FIXTURES / "warning" / "unreachable-node.yaml")


def test_validate_valid_file_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agent", "validate", EXAMPLE]) == 0
    assert "ok" in capsys.readouterr().out


def test_validate_invalid_file_exits_one_with_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agent", "validate", INVALID]) == 1
    out = capsys.readouterr().out
    assert "start-missing.yaml:" in out
    assert "error: spec.graph.start" in out
    assert "FAIL" in out


def test_warnings_pass_unless_strict() -> None:
    assert main(["agent", "validate", WARNING]) == 0
    assert main(["agent", "validate", "--strict", WARNING]) == 1


def test_validate_json_output(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agent", "validate", "--json", EXAMPLE, INVALID]) == 1
    result = json.loads(capsys.readouterr().out)
    assert [r["ok"] for r in result] == [True, False]
    issue = result[1]["issues"][0]
    assert issue["severity"] == "error"
    assert isinstance(issue["line"], int)


def test_schema_command_prints_json_schema(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["agent", "schema"]) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "Ringbridge AgentSpec v1alpha1"

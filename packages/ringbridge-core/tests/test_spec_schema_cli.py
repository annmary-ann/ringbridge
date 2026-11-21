import json
from pathlib import Path

import pytest

from ringbridge_core.spec import json_schema_text
from ringbridge_core.spec.__main__ import main


def test_writes_schema_with_lf_line_endings(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "agent.json"
    assert main([str(target)]) == 0
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert raw.decode("utf-8") == json_schema_text()


def test_prints_schema_without_a_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert json.loads(capsys.readouterr().out)["title"] == "Ringbridge AgentSpec v1alpha1"

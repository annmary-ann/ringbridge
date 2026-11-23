"""Golden tests: every fixture states what must be reported, and on which line (`# <- here`)."""

from pathlib import Path

import pytest

from ringbridge_core.spec import Issue, load_file

FIXTURES = Path(__file__).parent / "fixtures" / "spec"
INVALID = sorted((FIXTURES / "invalid").glob("*.yaml"))
WARNING = sorted((FIXTURES / "warning").glob("*.yaml"))


def _expectation(path: Path) -> tuple[str, int | None]:
    lines = path.read_text(encoding="utf-8").splitlines()
    expect = lines[0].removeprefix("# expect:").strip()
    marked = [n for n, line in enumerate(lines, start=1) if line.rstrip().endswith("# <- here")]
    return expect, (marked[0] if marked else None)


def _matches(issue: Issue, expect: str) -> bool:
    return expect in f"{issue.dotted}: {issue.message}"


def test_fixture_counts() -> None:
    assert len(INVALID) >= 20
    assert len(WARNING) >= 5


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixture_reports_expected_error(path: Path) -> None:
    expect, line = _expectation(path)
    report = load_file(path)
    assert not report.ok, f"{path.name} should be invalid"
    hits = [i for i in report.errors if _matches(i, expect)]
    assert hits, f"expected error containing {expect!r}; got:\n{report.format()}"
    if line is not None:
        assert any(i.line == line for i in hits), (
            f"expected the error on line {line}; got:\n{report.format()}"
        )


@pytest.mark.parametrize("path", WARNING, ids=lambda p: p.stem)
def test_warning_fixture_is_valid_but_warns(path: Path) -> None:
    expect, line = _expectation(path)
    report = load_file(path)
    assert report.ok, f"{path.name} should have no errors; got:\n{report.format()}"
    hits = [i for i in report.warnings if _matches(i, expect)]
    assert hits, f"expected warning containing {expect!r}; got:\n{report.format()}"
    if line is not None:
        assert any(i.line == line for i in hits), f"expected line {line}; got:\n{report.format()}"


def test_minimal_valid_spec_has_no_issues() -> None:
    report = load_file(FIXTURES / "valid-minimal.yaml")
    assert report.ok
    assert report.issues == []

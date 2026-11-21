"""Load an AgentSpec from YAML or JSON and report every problem with its line number."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path as FsPath
from typing import Any

import yaml
from pydantic import ValidationError

from ringbridge_core.spec import semantic
from ringbridge_core.spec.issues import Issue, Path
from ringbridge_core.spec.models import AgentSpec


@dataclass
class Report:
    source: str
    spec: AgentSpec | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        return "\n".join(i.format(self.source) for i in self.issues)


def load_file(path: str | FsPath) -> Report:
    p = FsPath(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        return Report(str(path), issues=[Issue("error", (), f"cannot read file: {e.strerror}")])
    return load_text(text, source=str(path))


def load_text(text: str, source: str = "<string>") -> Report:
    report = Report(source)
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        problem = getattr(e, "problem", None) or str(e)
        report.issues.append(Issue("error", (), f"invalid YAML: {problem}", line))
        return report

    if not isinstance(data, dict):
        line = node.start_mark.line + 1 if node is not None else 1
        report.issues.append(
            Issue("error", (), "the document must be a mapping (apiVersion, kind, ...)", line)
        )
        return report

    lines = _line_map(node)
    try:
        report.spec = AgentSpec.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            path = _clean_loc(err["loc"])
            report.issues.append(Issue("error", path, _message(err), _line_for(lines, path)))
        return report

    for issue in semantic.check(report.spec):
        report.issues.append(issue.at(_line_for(lines, issue.path)))
    report.issues.sort(key=lambda i: (i.line or 0, i.severity != "error"))
    return report


def _message(err: Any) -> str:
    kind, msg = err["type"], err["msg"]
    if kind == "extra_forbidden":
        return "unknown field (check the spelling; see docs/schema/agent-v1alpha1.json)"
    if kind == "missing":
        return "required field is missing"
    if kind == "value_error":
        return str(msg).removeprefix("Value error, ")
    if kind == "string_pattern_mismatch":
        return f"invalid format: {err.get('input')!r} does not match {err['ctx']['pattern']}"
    return str(msg)


def _clean_loc(loc: tuple[Any, ...]) -> Path:
    # Pydantic adds validator names (e.g. "function-after[...]") to some locations; drop them.
    return tuple(p for p in loc if not (isinstance(p, str) and "[" in p and p.endswith("]")))


def _line_map(node: yaml.Node | None) -> dict[Path, int]:
    lines: dict[Path, int] = {}

    def walk(n: yaml.Node, path: Path) -> None:
        if isinstance(n, yaml.MappingNode):
            for k, v in n.value:
                p = (*path, k.value)
                lines[p] = k.start_mark.line + 1
                walk(v, p)
        elif isinstance(n, yaml.SequenceNode):
            for i, v in enumerate(n.value):
                p = (*path, i)
                lines[p] = v.start_mark.line + 1
                walk(v, p)

    if node is not None:
        lines[()] = node.start_mark.line + 1
        walk(node, ())
    return lines


def _line_for(lines: dict[Path, int], path: Path) -> int | None:
    # Missing fields have no line of their own: report the closest parent that exists.
    for n in range(len(path), -1, -1):
        if path[:n] in lines:
            return lines[path[:n]]
    return None

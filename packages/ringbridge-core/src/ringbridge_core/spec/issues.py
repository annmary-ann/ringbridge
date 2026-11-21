"""Validation issues reported for an AgentSpec, with a path into the document and a line."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Severity = Literal["error", "warning"]
Path = tuple[str | int, ...]


@dataclass(frozen=True)
class Issue:
    severity: Severity
    path: Path
    message: str
    line: int | None = None

    def at(self, line: int | None) -> Issue:
        return replace(self, line=line)

    @property
    def dotted(self) -> str:
        out = ""
        for part in self.path:
            out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
        return out or "(document)"

    def format(self, source: str) -> str:
        where = f"{source}:{self.line}" if self.line else source
        return f"{where}: {self.severity}: {self.dotted}: {self.message}"

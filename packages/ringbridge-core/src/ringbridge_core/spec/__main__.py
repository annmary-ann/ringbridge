"""Write the AgentSpec JSON Schema: `python -m ringbridge_core.spec [path]` (stdout if no path)."""

import sys
from pathlib import Path

from ringbridge_core.spec import json_schema_text


def main(argv: list[str]) -> int:
    text = json_schema_text()
    if not argv:
        sys.stdout.write(text)
        return 0
    target = Path(argv[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")  # LF on every OS
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

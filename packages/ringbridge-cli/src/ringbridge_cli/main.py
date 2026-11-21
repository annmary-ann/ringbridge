"""Entry point for the `ringbridge` command.

More subcommands (init, agent publish, numbers, call, sim) arrive in #16.
"""

import argparse
import json
import sys
from collections.abc import Sequence

from ringbridge_cli import __version__
from ringbridge_core import spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ringbridge",
        description="Open-source voice agents for businesses.",
    )
    parser.add_argument("--version", action="version", version=f"ringbridge {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    agent = sub.add_parser("agent", help="work with agent specs")
    agent_sub = agent.add_subparsers(dest="agent_command", metavar="<subcommand>", required=True)

    validate = agent_sub.add_parser("validate", help="check agent spec files")
    validate.add_argument("files", nargs="+", help="AgentSpec YAML or JSON files")
    validate.add_argument("--strict", action="store_true", help="treat warnings as errors")
    validate.add_argument("--json", action="store_true", help="machine-readable output")
    validate.set_defaults(func=cmd_validate)

    schema = agent_sub.add_parser("schema", help="print the AgentSpec JSON Schema")
    schema.set_defaults(func=cmd_schema)
    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    reports = [spec.load_file(f) for f in args.files]
    failed = [r for r in reports if r.errors or (args.strict and r.warnings)]
    if args.json:
        out = [
            {
                "file": r.source,
                "ok": r not in failed,
                "issues": [
                    {"severity": i.severity, "path": i.dotted, "line": i.line, "message": i.message}
                    for i in r.issues
                ],
            }
            for r in reports
        ]
        print(json.dumps(out, indent=2))
    else:
        for r in reports:
            if r.issues:
                print(r.format())
            status = "FAIL" if r in failed else "ok"
            counts = f"{len(r.errors)} error(s), {len(r.warnings)} warning(s)"
            print(f"{status}  {r.source}  ({counts})")
    return 1 if failed else 0


def cmd_schema(_: argparse.Namespace) -> int:
    sys.stdout.write(spec.json_schema_text())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result

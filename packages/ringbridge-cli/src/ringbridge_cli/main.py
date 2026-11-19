"""Entry point for the `ringbridge` command.

Subcommands (init, agent, numbers, call, sim) arrive in later issues; see #16.
"""

import argparse
from collections.abc import Sequence

from ringbridge_cli import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ringbridge",
        description="Open-source voice agents for businesses.",
    )
    parser.add_argument("--version", action="version", version=f"ringbridge {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0

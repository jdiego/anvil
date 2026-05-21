from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from anvil.doctor import Status, doctor_report
from anvil.logging import configure_logging
from anvil.server import run_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anvil",
        description=(
            "Secure MCP platform for coding agents, developer workflows, "
            "and multi-context integrations."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="Run the MCP server (default).")
    sub.add_parser("doctor", help="Diagnose local configuration, secrets, and upstreams.")
    return parser


def _run_doctor() -> int:
    configure_logging()
    report = asyncio.run(doctor_report())
    sys.stdout.write(report.as_text() + "\n")
    return 0 if report.overall is Status.OK else 1


def _run_serve() -> int:
    run_server()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    command = args.command or "serve"
    if command == "doctor":
        return _run_doctor()
    if command == "serve":
        return _run_serve()

    parser.error(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())

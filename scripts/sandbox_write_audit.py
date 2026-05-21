#!/usr/bin/env python3
"""Static WRITE_SANDBOX coverage audit.

The live runner exercises commands against the Yandex Direct sandbox. This
script only audits the command matrix and runner coverage so it can run in CI
without credentials or live API calls.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from direct_cli.smoke_matrix import WRITE_SANDBOX, commands_for_category  # noqa: E402

PASS = "PASS"
SANDBOX_LIMITATION = "SANDBOX_LIMITATION"
DANGEROUS = "DANGEROUS"
NOT_COVERED = "NOT_COVERED"

ALLOWED_STATUSES = {PASS, SANDBOX_LIMITATION, DANGEROUS, NOT_COVERED}

FOLLOW_UP_ISSUES: dict[str, str] = {}

DEFAULT_JSON_OUTPUT = ROOT_DIR / "build" / "sandbox_audit.json"


@dataclass(frozen=True)
class AuditRow:
    """One static audit row for a WRITE_SANDBOX command."""

    group: str
    subcommand: str
    command: str
    status: str
    evidence: str
    follow_up: str


def load_live_runner_module():
    """Load sandbox_write_live.py without requiring it to be importable package code."""
    runner_path = ROOT_DIR / "scripts" / "sandbox_write_live.py"
    spec = importlib.util.spec_from_file_location("sandbox_write_live", runner_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {runner_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def split_command(command: str) -> tuple[str, str]:
    """Split a smoke-matrix command into CLI group and subcommand."""
    if "." not in command:
        return command, ""
    return command.split(".", 1)


def row_for_command(command: str, handler: Callable[..., object] | None) -> AuditRow:
    """Classify one WRITE_SANDBOX command from static runner coverage."""
    group, subcommand = split_command(command)
    if handler is None:
        return AuditRow(
            group=group,
            subcommand=subcommand,
            command=command,
            status=NOT_COVERED,
            evidence="missing LiveSandboxRunner handler",
            follow_up=FOLLOW_UP_ISSUES.get(command, ""),
        )

    handler_name = getattr(handler, "__name__", repr(handler))
    evidence = f"LiveSandboxRunner.{handler_name}"
    if handler_name == "run_not_covered":
        return AuditRow(
            group=group,
            subcommand=subcommand,
            command=command,
            status=NOT_COVERED,
            evidence=evidence,
            follow_up=FOLLOW_UP_ISSUES.get(command, ""),
        )

    return AuditRow(
        group=group,
        subcommand=subcommand,
        command=command,
        status=PASS,
        evidence=evidence,
        follow_up="",
    )


def build_rows() -> list[AuditRow]:
    """Build the full static WRITE_SANDBOX audit table."""
    module = load_live_runner_module()
    commands = commands_for_category(WRITE_SANDBOX)
    runner = module.LiveSandboxRunner(
        commands=commands,
        timeout=1,
        verbose=False,
        report_file=None,
    )
    try:
        handlers = runner.handlers()
        return [row_for_command(command, handlers.get(command)) for command in commands]
    finally:
        runner.close()


def validate_rows(rows: list[AuditRow]) -> list[str]:
    """Return validation errors that should fail CI."""
    errors: list[str] = []
    for row in rows:
        if row.status not in ALLOWED_STATUSES:
            errors.append(f"{row.command}: unknown status {row.status}")
        if row.status == NOT_COVERED and not row.follow_up:
            errors.append(f"{row.command}: NOT_COVERED row has no follow-up issue")
    return errors


def markdown_table(rows: list[AuditRow]) -> str:
    """Render the audit as a Markdown table for issue comments and chat output."""
    lines = [
        "| group | subcommand | status | evidence | follow_up |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        follow_up = row.follow_up or ""
        lines.append(
            "| "
            f"{row.group} | "
            f"{row.subcommand} | "
            f"{row.status} | "
            f"`{row.evidence}` | "
            f"{follow_up} |"
        )
    return "\n".join(lines)


def write_json(rows: list[AuditRow], path: Path) -> None:
    """Write the machine-readable audit artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {status: 0 for status in sorted(ALLOWED_STATUSES)}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    payload = {
        "summary": {
            "category": WRITE_SANDBOX,
            "total": len(rows),
            "counts": counts,
            "ok": not validate_rows(rows),
        },
        "rows": [asdict(row) for row in rows],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Audit WRITE_SANDBOX live-runner coverage without live API calls."
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help="Path for the JSON audit artifact.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the static audit."""
    args = parse_args()
    rows = build_rows()
    errors = validate_rows(rows)
    write_json(rows, args.json_output)
    print(markdown_table(rows))
    if errors:
        print("\nValidation errors:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

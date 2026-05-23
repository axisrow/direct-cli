#!/usr/bin/env python3
"""Build the soft WSDL optional-field audit table for issue #239."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from direct_cli.cli import cli  # noqa: E402
from direct_cli.wsdl_coverage import (  # noqa: E402
    fetch_cached_wsdl,
    get_operation_request_schema,
    iter_container_item_fields,
)
from tests.test_wsdl_parity_gate import (  # noqa: E402
    COMMAND_WSDL_MAP,
    INTERNAL_VALIDATION,
    OPTIONAL_FIELD_AUDIT,
    OPTIONAL_FIELD_CLI_OPTIONS,
    OPTIONAL_FIELD_DEFAULT_FOLLOWUPS,
    OPTIONAL_FIELD_AUDIT_MAX_DEPTH,
    OPTIONAL_FIELD_AUDIT_REPORT,
)

REPOSITORY_SLUG = "axisrow/direct-cli"


def _click_options(cli_group: str, cli_op: str) -> set[str]:
    group = cli.commands.get(cli_group)
    command = getattr(group, "commands", {}).get(cli_op) if group is not None else None
    if command is None:
        return set()
    options = set()
    for param in command.params:
        options.update(getattr(param, "opts", []))
    return options


def _issue_link(issue: str) -> str:
    if issue.startswith("#") and issue[1:].isdigit():
        return f"[{issue}](https://github.com/{REPOSITORY_SLUG}/issues/{issue[1:]})"
    return issue


def _format_audit_entry(entry: dict[str, str]) -> str:
    issue = entry.get("issue", "")
    issue_text = f" {_issue_link(issue)}" if issue else ""
    return f"{entry.get('note', '')}{issue_text}".strip()


def _audit_entry_for_path(
    cli_group: str,
    cli_op: str,
    wsdl_path: str,
) -> tuple[str, dict[str, str]] | None:
    parts = wsdl_path.split(".")
    for size in range(len(parts), 0, -1):
        prefix = ".".join(parts[:size])
        entry = OPTIONAL_FIELD_AUDIT.get((cli_group, cli_op, prefix))
        if entry is not None:
            return prefix, entry
    return None


def _classify_row(
    cli_group: str,
    cli_op: str,
    row: dict[str, Any],
    command_options: set[str],
) -> tuple[str, str]:
    key = (cli_group, cli_op, row["path"])
    audit_entry = _audit_entry_for_path(cli_group, cli_op, row["path"])
    if audit_entry is not None:
        matched_path, override = audit_entry
        evidence = _format_audit_entry(override)
        if matched_path != row["path"]:
            evidence = f"{evidence}; inherited from `{matched_path}`"
        return override["status"], evidence

    configured_options = OPTIONAL_FIELD_CLI_OPTIONS.get(key)
    if configured_options is not None:
        matched = sorted(configured_options & command_options)
        if matched:
            return "supported", ", ".join(matched)
        missing = ", ".join(sorted(configured_options))
        return (
            "untriaged",
            f"configured option(s) missing from Click command: {missing}",
        )

    if row.get("min_occurs", 1) >= 1 and row.get("depth") == 1:
        return "supported", "covered by minOccurs>=1 parity gate"

    if (cli_group, cli_op, row["name"]) in INTERNAL_VALIDATION:
        return "supported", "internal UsageError validation"

    default = OPTIONAL_FIELD_DEFAULT_FOLLOWUPS.get((cli_group, cli_op))
    if default is not None:
        return "missing_followup", _format_audit_entry(default)

    return "untriaged", "no explicit audit classification"


def collect_rows() -> list[dict[str, Any]]:
    """Return WSDL field audit rows for all mapped mutating commands."""
    rows: list[dict[str, Any]] = []
    for (cli_group, cli_op), (
        api_service,
        wsdl_op,
        container,
    ) in sorted(COMMAND_WSDL_MAP.items()):
        schema = get_operation_request_schema(fetch_cached_wsdl(api_service), wsdl_op)
        command_options = _click_options(cli_group, cli_op)
        for field in iter_container_item_fields(
            schema, container, max_depth=OPTIONAL_FIELD_AUDIT_MAX_DEPTH
        ):
            status, evidence = _classify_row(cli_group, cli_op, field, command_options)
            rows.append(
                {
                    "cli_command": f"{cli_group}.{cli_op}",
                    "api_operation": f"{api_service}.{wsdl_op}",
                    "container": container,
                    "path": field["path"],
                    "type": field.get("type") or "",
                    "min_occurs": field.get("min_occurs", 1),
                    "max_occurs": field.get("max_occurs", "1"),
                    "depth": field.get("depth", 1),
                    "status": status,
                    "evidence": evidence,
                }
            )
    return rows


def _escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _unclassified_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["status"] not in {"supported", "missing_followup", "not_applicable"}
    ]


def render_markdown(rows: list[dict[str, Any]]) -> str:
    """Render the committed Markdown audit document."""
    counts = Counter(row["status"] for row in rows)
    confirmed = [
        row for row in rows if row["status"] in {"missing_followup", "not_applicable"}
    ]
    depth_label = (
        "unbounded"
        if OPTIONAL_FIELD_AUDIT_MAX_DEPTH is None
        else str(OPTIONAL_FIELD_AUDIT_MAX_DEPTH)
    )

    lines = [
        "# WSDL Optional Field Audit",
        "",
        "Generated by `python3 scripts/build_wsdl_optional_field_audit.py --write`.",
        f"Max audited nesting depth below each item container: `{depth_label}`.",
        "",
        "This is a soft gate for issue #239, but every audited row must now",
        "be classified as `supported`, `missing_followup`, or `not_applicable`.",
        "`missing_followup` rows are linked to GitHub follow-up issues.",
        "",
        "## Summary",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for status, count in sorted(counts.items()):
        lines.append(f"| `{status}` | {count} |")

    lines.extend(
        [
            "",
            "## Confirmed Follow-Ups",
            "",
            "| CLI command | WSDL path | Issue / note |",
            "|---|---|---|",
        ]
    )
    for row in confirmed:
        lines.append(
            "| "
            f"`{_escape(row['cli_command'])}` | "
            f"`{_escape(row['path'])}` | "
            f"{_escape(row['evidence'])} |"
        )

    lines.extend(
        [
            "",
            "## Field Table",
            "",
            "| CLI command | API op | Path | Type | min | max | Status | Evidence |",
            "|---|---|---|---|---:|---:|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            f"`{_escape(row['cli_command'])}` | "
            f"`{_escape(row['api_operation'])}` | "
            f"`{_escape(row['path'])}` | "
            f"`{_escape(row['type'])}` | "
            f"{_escape(row['min_occurs'])} | "
            f"{_escape(row['max_occurs'])} | "
            f"`{_escape(row['status'])}` | "
            f"{_escape(row['evidence'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Update audit Markdown")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the committed audit Markdown is stale",
    )
    args = parser.parse_args()

    rows = collect_rows()
    rendered = render_markdown(rows)
    unclassified = _unclassified_rows(rows)
    if unclassified:
        preview = "\n".join(
            f"- {row['cli_command']} {row['path']}: {row['evidence']}"
            for row in unclassified[:20]
        )
        print(
            "Optional-field audit has unclassified rows:\n"
            f"{preview}\n"
            "Add exact support evidence, a missing_followup issue, or "
            "a not_applicable audit entry.",
            file=sys.stderr,
        )
        return 1

    if args.write:
        OPTIONAL_FIELD_AUDIT_REPORT.write_text(rendered, encoding="utf-8")
        print(f"Wrote {OPTIONAL_FIELD_AUDIT_REPORT}")
        return 0

    if args.check:
        try:
            current = OPTIONAL_FIELD_AUDIT_REPORT.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(
                f"{OPTIONAL_FIELD_AUDIT_REPORT} is missing; run with --write",
                file=sys.stderr,
            )
            return 1
        if current != rendered:
            print(
                f"{OPTIONAL_FIELD_AUDIT_REPORT} is stale; run with --write",
                file=sys.stderr,
            )
            return 1
        print(f"{OPTIONAL_FIELD_AUDIT_REPORT} is current")
        return 0

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

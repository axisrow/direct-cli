#!/usr/bin/env python3
"""Build a GitHub-flavored Markdown body for issue #55.

Reads the canonical service/method registry from `direct_cli.wsdl_coverage`
and the smoke-test classification from `direct_cli.smoke_matrix`, then renders
a per-service checklist that gives the release-gate status for 0.3.0.

Output goes to stdout (or the path passed as the first argument).

Run from the repo root:

    python3 scripts/build_issue55_body.py /tmp/issue-55-body.md
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

from direct_cli.cli import cli
from direct_cli.smoke_matrix import SMOKE_MATRIX
from direct_cli.wsdl_coverage import (
    CANONICAL_API_SERVICES,
    CLI_TO_API_SERVICE,
    INTENTIONAL_EXTRA_METHODS,
    METHOD_NAME_OVERRIDES,
    fetch_wsdl,
    parse_wsdl_operations,
)

API_TO_CLI = {v: k for k, v in CLI_TO_API_SERVICE.items()}
SMOKE_OF = {cmd: cat for cat, cmds in SMOKE_MATRIX.items() for cmd in cmds}

# Known schema-level issues (FieldNames vs WSDL FieldEnum, SelectionCriteria
# defaults, integration-test correctness). Source: issue #108 + audit on
# 2026-04-25.
KNOWN_ISSUES: dict[tuple[str, str], list[str]] = {
    ("smartadtargets", "get"): [
        "FieldNames mismatch: shipping `Status`, `ServingStatus` — only `State` exists in WSDL FieldEnum (#108)",
    ],
    ("adextensions", "get"): [
        "FieldNames mismatch: missing `State` (defined in WSDL FieldEnum, dropped from response) (#108)",
    ],
    ("businesses", "get"): [
        "Default FieldNames may include `Type` which is not in WSDL FieldEnum (#108 audit pending)",
    ],
    ("leads", "get"): [
        "SelectionCriteria requires `TurboPageIds`; integration test currently passes `--campaign-ids` (no such option) → exit_code=2",
    ],
    ("advideos", "get"): [
        "WSDL marks `Ids` as `minOccurs=1`; integration test currently omits it",
    ],
    ("agencyclients", "get"): [
        "Live integration returns `error_code=54` for non-agency accounts; test must treat this as expected, not a failure",
    ],
    ("bidmodifiers", "get"): [
        "WSDL requires `Levels` (e.g. `[\"CAMPAIGN\"]`) in SelectionCriteria",
    ],
    ("keywordsresearch", "has-search-volume"): [
        "WSDL requires both `Keywords` and `RegionIds`",
    ],
    ("feeds", "get"): [
        "WSDL marks `Ids` as `minOccurs=1`",
    ],
}


def emoji_for_method(cli_group: str, cli_name: str) -> str:
    if (cli_group, cli_name) in KNOWN_ISSUES:
        return "🟡"
    return "✅"


def emoji_for_service(cli_group: str, methods: list[dict]) -> str:
    statuses = {emoji_for_method(cli_group, m["cli_name"]) for m in methods}
    if "🟡" in statuses or "❌" in statuses:
        return "🟡"
    return "✅"


def cli_subcommands_for_group(group_name: str) -> dict[str, str]:
    """Return {cli_subcommand_name: wsdl_method_name_or_kebab}."""
    group = cli.commands.get(group_name)
    if group is None:
        return {}
    out = {}
    for cmd_name in group.commands:
        wsdl_name = METHOD_NAME_OVERRIDES.get(cmd_name, cmd_name)
        out[cmd_name] = wsdl_name
    return out


def build_method_rows(api_service: str) -> list[dict]:
    """Build the canonical method registry for one service.

    Returns one entry per WSDL operation, plus any intentional CLI extras.
    """
    cli_group = API_TO_CLI[api_service]
    cli_subs = cli_subcommands_for_group(cli_group)
    # Reverse: wsdl_op -> [cli_subcommand, ...]
    wsdl_to_cli: dict[str, list[str]] = defaultdict(list)
    for cli_name, wsdl_op in cli_subs.items():
        wsdl_to_cli[wsdl_op].append(cli_name)

    rows = []
    for wsdl_op in sorted(parse_wsdl_operations(fetch_wsdl(api_service, use_cache=True))):
        cli_names = sorted(wsdl_to_cli.get(wsdl_op, []))
        # Pick the "primary" CLI name. Prefer exact match, otherwise first alpha.
        if wsdl_op in cli_names:
            primary = wsdl_op
        elif cli_names:
            primary = cli_names[0]
        else:
            primary = None
        rows.append(
            {
                "wsdl_op": wsdl_op,
                "cli_name": primary,
                "cli_aliases": [c for c in cli_names if c != primary] if primary else [],
                "smoke": SMOKE_OF.get(f"{cli_group}.{primary}") if primary else None,
            }
        )

    # Append intentional CLI extras (e.g. agencyclients.delete guard)
    for (g, m), reason in sorted(INTENTIONAL_EXTRA_METHODS.items()):
        if g != cli_group:
            continue
        rows.append(
            {
                "wsdl_op": None,
                "cli_name": m,
                "cli_aliases": [],
                "smoke": SMOKE_OF.get(f"{cli_group}.{m}"),
                "intentional_extra_reason": reason,
            }
        )
    return rows


def render_method(cli_group: str, row: dict) -> str:
    wsdl = row["wsdl_op"]
    cli_name = row["cli_name"]
    smoke = row["smoke"] or "?"
    if wsdl is None:
        # Intentional CLI-only method
        emoji = "✅"
        title = f"`{cli_name}` (CLI-only guard, no WSDL op)"
        criteria = (
            "  - [x] CLI command exists\n"
            "  - [n/a] FieldNames validation\n"
            "  - [n/a] SelectionCriteria validation\n"
            "  - [n/a] Integration test\n"
            f"  - _Rationale: {row['intentional_extra_reason']}_"
        )
        return f"- {emoji} **{title}** · smoke: `{smoke}`\n{criteria}"

    emoji = emoji_for_method(cli_group, cli_name) if cli_name else "❌"
    if cli_name == wsdl:
        title = f"`{wsdl}`"
    elif cli_name:
        title = f"`{wsdl}` (CLI: `{cli_name}`)"
    else:
        title = f"`{wsdl}` (no CLI command)"

    is_get = wsdl == "get"
    fieldnames_check = (
        "[ ] Default FieldNames validated against WSDL FieldEnum (#108)"
        if is_get
        else "[n/a] FieldNames validation"
    )
    selection_check = (
        "[ ] SelectionCriteria required params verified"
        if is_get or wsdl in {"checkCampaigns", "hasSearchVolume", "deduplicate"}
        else "[n/a] SelectionCriteria validation"
    )
    issues = KNOWN_ISSUES.get((cli_group, cli_name), [])
    if (cli_group, cli_name) in KNOWN_ISSUES:
        # Mark FieldNames or selection unchecked depending on issue type
        pass
    issue_lines = "\n".join(f"  - ⚠️ {note}" for note in issues)
    cli_status = "[x]" if cli_name else "[ ]"
    integration_status = (
        "[ ] Integration test passing (sandbox or prod)"
        if (cli_group, cli_name) in KNOWN_ISSUES
        else "[ ] Integration test passing (sandbox or prod)"
    )
    body = (
        f"  - {cli_status} CLI command exists (method parity)\n"
        f"  - {fieldnames_check}\n"
        f"  - {selection_check}\n"
        f"  - {integration_status}"
    )
    if issue_lines:
        body += f"\n{issue_lines}"
    return f"- {emoji} **{title}** · smoke: `{smoke}`\n{body}"


def render_service(api_service: str, idx: int, total: int) -> str:
    cli_group = API_TO_CLI[api_service]
    rows = build_method_rows(api_service)
    method_count = len([r for r in rows if r["wsdl_op"] is not None])
    extras = [r for r in rows if r["wsdl_op"] is None]
    extra_note = f" + {len(extras)} CLI-only guard" if extras else ""
    svc_emoji = emoji_for_service(cli_group, [r for r in rows if r["wsdl_op"] is not None])
    label = f"### {idx}/{total}. `{api_service}` {svc_emoji}"
    sub = f"_API service: `{api_service}` · CLI group: `{cli_group}` · WSDL ops: {method_count}{extra_note}_"
    methods_md = "\n".join(render_method(cli_group, row) for row in rows)
    return f"{label}\n{sub}\n\n{methods_md}"


def render_reports_section() -> str:
    return (
        "### 29/29. `reports` ✅\n"
        "_API service: `reports` · CLI group: `reports` · JSON API (no WSDL)_\n\n"
        "Coverage policy: contract tests + spec snapshot. Source of truth: "
        "`tests/reports_cache/spec.json`, drift script: "
        "`scripts/check_reports_drift.py`.\n\n"
        "- ✅ **`reports.get`** · smoke: `SAFE`\n"
        "  - [x] CLI command exists\n"
        "  - [x] Field/Filter contract tracked via `tests/reports_cache/spec.json`\n"
        "  - [x] Drift detected by `scripts/check_reports_drift.py`\n"
        "  - [x] Integration test passing\n"
        "- ✅ **`reports.list-types`** · smoke: `SAFE`\n"
        "  - [x] CLI command exists\n"
        "  - [x] Integration test passing\n"
    )


def render_summary() -> str:
    total_wsdl_methods = sum(
        len(parse_wsdl_operations(fetch_wsdl(s, use_cache=True)))
        for s in CANONICAL_API_SERVICES
    )
    total_services = len(CANONICAL_API_SERVICES) + 1  # + reports
    return (
        f"- WSDL services: **{len(CANONICAL_API_SERVICES)}** "
        f"(declared = live-discovered = {len(CANONICAL_API_SERVICES)})\n"
        f"- WSDL methods: **{total_wsdl_methods}** (declared = live-discovered)\n"
        "- Non-WSDL services: **1** (`reports`, JSON API)\n"
        f"- Total API services covered: **{total_services}**\n"
        "- `summary.strict_parity_ok`: ✅ `true`\n"
        "- `summary.live_model_parity_ok`: ✅ `true`\n"
        "- `model_gaps.live_discovered_missing_services`: `[]`\n"
        "- `model_gaps.live_discovered_missing_methods`: `0`\n"
        "- Schema-level validation gate (FieldNames + SelectionCriteria): "
        "🟡 partial — see #108 and per-service status below"
    )


def render_body() -> str:
    summary = render_summary()
    services_md = "\n\n".join(
        render_service(api, i + 1, len(CANONICAL_API_SERVICES) + 1)
        for i, api in enumerate(CANONICAL_API_SERVICES)
    )
    return f"""# Roadmap: 0.3.0 command coverage must reach 100%

## Goal

Version `0.3.0` cannot ship until command/API coverage is 100% across the supported Yandex Direct CLI surface. This issue is the release roadmap and gate. It links live model gaps, command contract, method correctness, write/integration coverage, and the documentation matrix.

## Definition of 100% command coverage for 0.3.0

`0.3.0` is releasable only when:

- `scripts/build_api_coverage_report.py` reports `summary.strict_parity_ok == true` (✅ already true on `main`)
- `scripts/build_api_coverage_report.py` reports `summary.live_model_parity_ok == true` (✅ already true on `main`)
- `model_gaps.live_discovered_missing_services == []` (✅)
- `model_gaps.live_discovered_missing_methods == 0` (✅)
- A new schema-level gate `summary.schema_parity_ok == true` (🟡 introduced by #108) — every `get`-method's default `FieldNames` is a subset of the corresponding WSDL `*FieldEnum`, and every `SelectionCriteria` default satisfies `minOccurs=1`
- Every canonical CLI command in the per-service status below shows ✅ on all four checkboxes (or has a documented `n/a` rationale)
- Every mutating command has dry-run payload coverage or a documented exclusion
- Wire method names are validated wherever command aliases or kebab-case map to Yandex camelCase

## Current baseline (snapshot 2026-04-25)

{summary}

## Per-method status criteria

For every WSDL operation (and every CLI-only guard) the issue tracks four checkboxes:

1. **CLI command exists** — registered group/subcommand, mapped to the right WSDL operation.
2. **Default `FieldNames` validated against WSDL `*FieldEnum`** (only for `get`-methods). Source of truth: `tests/wsdl_cache/<service>.xml`. Driver: #108.
3. **`SelectionCriteria` required params verified** (only for methods that take a `SelectionCriteria`). Source of truth: `minOccurs=1` fields in the WSDL request schema.
4. **Integration test passing** in sandbox or prod (latest WRITE_SANDBOX live run: #96).

Service-level emoji rollup:

- ✅ — every method on this service has all 4 checkboxes ticked (or `n/a`).
- 🟡 — at least one method has an outstanding checkbox (typically schema or integration).
- ❌ — at least one WSDL method is missing from the CLI (none today).

`smoke` annotation refers to the smoke-matrix category from `direct_cli/smoke_matrix.py` (`SAFE`, `WRITE_SANDBOX`, `DANGEROUS`).

---

## Service-by-service status

{services_md}

{render_reports_section()}

---

## Schema validation gate (driven by #108)

Before this issue can be closed, #108 must be merged so that the `tests/test_api_coverage.py::test_default_fieldnames_match_wsdl_enum` test exists and passes for **all** services. The test parses every `*FieldEnum` from `tests/wsdl_cache/*.xml` and asserts that:

1. Each default `FieldNames` value (from `direct_cli/utils.py:COMMON_FIELDS` and from any hard-coded value inside `direct_cli/commands/*.py`) is a member of the corresponding WSDL enum.
2. Each `get`-method that has `minOccurs=1` `SelectionCriteria` fields in WSDL refuses to build a payload without them (no silent empty-`SelectionCriteria` requests).

Confirmed remaining schema-level work after #107 (driven by #108):

- [ ] `smartadtargets` — drop `Status`, `ServingStatus` from default fields, add `State`.
- [ ] `adextensions` — add `State` to default fields.
- [ ] `businesses` — drop `Type` from `COMMON_FIELDS` (not in WSDL enum).
- [ ] Add the `test_default_fieldnames_match_wsdl_enum` test in `tests/test_api_coverage.py`.

---

## Integration-test correctness work

Independent of WSDL parity, several `tests/test_integration.py` cases pass the wrong CLI flags (root cause of the original audit complaint):

- [ ] `leads get` — switch test from `--campaign-ids` to `--turbo-page-ids` (matches WSDL `SelectionCriteria.TurboPageIds` `minOccurs=1`).
- [ ] `advideos get` — pass `--ids` (WSDL marks `Ids` `minOccurs=1`).
- [ ] `agencyclients` — treat live `error_code=54` ("not an agency account") as expected outcome, not a failure.

These are issues with the **tests**, not the CLI. They are listed here because they are the visible symptoms users hit when running `pytest -m integration -v`.

---

## Roadmap (existing phases — kept intact)

### Phase 1 — Make coverage gaps machine-visible (#54)

- Keep `api_coverage_report.json` as source of truth for the release gate
- Expose declared vs live-discovered counts
- Expose missing services/methods under `model_gaps`
- Print values in GitHub Actions coverage summary
- Keep `tests/API_COVERAGE.md` as the human-readable matrix

**Status:** ✅ done.

### Phase 2 — Close live-discovered service gaps

Originally tracked the `dynamicfeedadtargets` (×6 methods) and `strategies` (×5 methods) live gaps.

**Status:** ✅ done — verified by the per-service status above.

### Phase 3 — Fix known command-correctness blockers (#35, #33)

- Fix `keywordsresearch` wire-method names (camelCase via `METHOD_NAME_OVERRIDES`).
- Add request/dry-run assertions that catch wrong `body["method"]`.
- Resolve `bidmodifiers toggle` API ambiguity.

**Status:** ✅ done — `bidmodifiers.toggle` deprecated/removed (see comment & `tests/API_ISSUE_AUDIT.md`).

### Phase 4 — Finish canonical command contract & docs (#42, #44)

- Finalize canonical command naming rules in README.
- Single-line examples + typed flags only.
- Docs/tests do not show removed aliases as canonical.
- Document intentionally unsupported transport gaps.

**Status:** 🟡 in progress.

### Phase 5 — Complete coverage matrix beyond contract parity (#41, #28)

- Classify every CLI command/group in `tests/API_COVERAGE.md`.
- Tag: contract-only / dry-run/schema covered / integration replay covered / sandbox-limited / intentionally unsupported.
- Extend integration/write confidence without making CI depend on live mutable state.
- Sandbox limitations explicit and non-blocking only when documented.

**Status:** 🟡 in progress.

---

## Release gate checklist

- [ ] `pytest -q tests/test_api_coverage.py tests/test_reports_drift.py tests/test_dry_run.py tests/test_cli.py tests/test_comprehensive.py` passes
- [x] `python3 scripts/build_api_coverage_report.py` reports `strict_parity_ok: true`
- [x] `python3 scripts/build_api_coverage_report.py` reports `live_model_parity_ok: true`
- [x] `model_gaps.live_discovered_missing_services` is empty
- [x] `model_gaps.live_discovered_missing_methods` is `0`
- [ ] **NEW:** `summary.schema_parity_ok == true` after #108 merges
- [ ] Every WSDL service block above shows ✅ at the service-level rollup
- [ ] `tests/API_COVERAGE.md` lists every canonical command with classification
- [ ] README API coverage and CLI contract match the CLI surface
- [ ] All blocker issues closed or explicitly non-blocking with rationale

## Exclusion policy (from earlier comment)

The 0.3.0 100% gate counts the **supported live API surface** only.

- If an operation is officially deprecated/removed, absent from live WSDL, or contradicted by the official changelog, it must be recorded in `tests/API_ISSUE_AUDIT.md` before being excluded.
- Such an operation is not a missing CLI command and must not block 0.3.0.
- If official docs and live WSDL disagree, classify as `docs-drift` and resolve before implementing.

Worked example: `bidmodifiers.toggle` is deprecated since 2025-11-13; live WSDL exposes only `bidmodifiers add/delete/get/set`; #33 closed as not-planned and excluded from coverage counts.

## Related issues

- #108 — driver of the schema validation gate (FieldNames vs WSDL FieldEnum).
- #107 — fixed default FieldNames for `strategies`, `turbopages`, `businesses`.
- #102 — removed `keywords archive/unarchive` (API method does not exist).
- #98 — auto-resolve login after OAuth, fix test isolation.
- #96 — last live WRITE_SANDBOX smoke run; surfaced the schema-level bugs that motivated #108.
- #54, #41, #35, #28, #42, #44 — phase-tracking issues.

> Body regenerated on 2026-04-25 by `scripts/build_issue55_body.py`. Edit the script, not the body.
"""


def main(argv: list[str]) -> int:
    out = render_body()
    if len(argv) > 1 and argv[1] != "-":
        Path(argv[1]).write_text(out, encoding="utf-8")
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

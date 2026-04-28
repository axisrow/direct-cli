# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CLI for the Yandex Direct API, built with Python and Click. Installed via pip, published to PyPI.

## Commands

```bash
pip install -e ".[dev]"              # Install in dev mode
pytest                               # Unit tests (no token needed)
pytest -m integration -v             # Integration tests (needs .env with token)
pytest tests/test_cli.py::TestCLI::test_cli_help  # Single test
pytest -k "campaigns"                # Pattern match
black .                              # Format
flake8 direct_cli tests              # Lint
```

## Architecture

Click group-of-groups. Each Yandex Direct API resource = one file in `direct_cli/commands/` with a Click group and subcommands (`get`, `add`, `update`, `delete`, `suspend`, `resume`, etc.). All groups registered in `direct_cli/cli.py` via `cli.add_command()`.

**Request flow:** `cli.py` → `auth.py` (resolves token/login) → `api.py` (`create_client`) → `tapi_yandex_direct.YandexDirect` → Yandex API → `output.py` (format/print).

**Credentials priority:** CLI flags (`--token`, `--login`) > env vars (`YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_LOGIN`) > `.env` file. `load_dotenv()` runs at `cli.py` import time.

**Shared utilities** (`utils.py`): `parse_ids`, `parse_json`, `build_selection_criteria`, `build_common_params`, `get_default_fields`, `COMMON_FIELDS` dict. All command modules import from here — don't duplicate.

**Output** (`output.py`): `format_output()` supports json (default), table, csv, tsv. Colored helpers: `print_success`, `print_error`, `print_warning`, `print_info`.

## Key Conventions

**Adding a new command module:**
1. Create `direct_cli/commands/<resource>.py` with `@click.group()` + subcommands.
2. Register in `cli.py` with `cli.add_command(...)`.
3. Add command name to `TestCommandsRegistered.EXPECTED_COMMANDS` in `tests/test_comprehensive.py`.

**`--dry-run`:** `add`/`update` commands print request JSON without calling the API. Use as test seam.

**Runtime-deprecated methods:** WSDL-visible methods that Yandex rejects at runtime belong in `RUNTIME_DEPRECATED_METHODS` (`direct_cli/wsdl_coverage.py`) and must fail with `click.UsageError` before request construction. `agencyclients add` is blocked this way; use `agencyclients add-passport-organization`.

**SelectionCriteria:** Resources like `adgroups`, `ads`, `keywords` require at least one of `Ids`, `CampaignIds`, or `AdGroupIds` — otherwise API error 4001.

**Error handling:** All commands wrap API calls in `try/except Exception` → `print_error(str(e))` + `raise click.Abort()`.

**Default fields:** `COMMON_FIELDS` in `utils.py` maps resource names to default `*FieldNames`. Most entries are `list[str]`; multi-`*FieldNames` resources use `dict[str, list[str]]` keyed by WSDL request param (for example `FieldNames`, `TextAdFieldNames`, `SearchFieldNames`). Not all fields are valid for all resources (e.g., `adimages` uses `AdImageHash`, not `Id`).

**WSDL imports:** Imported schemas used by request validation are cached in `tests/wsdl_cache/imports/` and registered in `IMPORTED_XSD_REGISTRY`. Keep imported nested types resolved; empty `item_fields` for registered imports is coverage drift.

**Smoke probes:** Live ID discovery for safe-smoke and integration tests lives in `direct_cli/_smoke_probes.py`. Functions like `advideo_probe_id()` query the live API to find a real resource ID (env override `YANDEX_DIRECT_TEST_ADVIDEO_ID`, fallback through `creatives.get`) and return `None` on any failure — smoke scripts treat `None` as a benign skip, not a fatal error. CLI entry: `python3 -m direct_cli._smoke_probes advideo`.

## Tests

- **Unit** (`test_cli.py`, `test_comprehensive.py`) — no API calls, no token needed.
- **Integration** (`test_integration.py`, `@pytest.mark.integration`) — require `.env` with `YANDEX_DIRECT_TOKEN` and `YANDEX_DIRECT_LOGIN`. Auto-skip if absent.

## Dangerous Commands — Never Auto-Test

Smoke command safety is tracked in `direct_cli/smoke_matrix.py`. Every CLI
subcommand belongs to exactly one category:

- **SAFE:** production read-only smoke tests in `scripts/test_safe_commands.sh`.
- **WRITE_SANDBOX:** live mutating smoke tests through
  `scripts/test_sandbox_write.sh`; these must call only `direct --sandbox ...`
  and must not touch production data.
- **DANGEROUS:** manual-only checklist in `scripts/test_dangerous_commands.sh`;
  the script exits with status 1 by design and must not be used as an
  automated runner.

Never auto-test production mutations: agency client changes, live bid changes,
moderation, lifecycle operations, `clients update`, or any `delete` without
`--sandbox`.

Client update payloads (`clients update` and `agencyclients update`) must use
the shared typed helpers in `direct_cli/utils.py`; do not expose raw JSON for
general client update fields or nested client update payloads.

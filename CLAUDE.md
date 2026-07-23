# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CLI for the Yandex Direct API, built with Python and Click. Installed via pip, published to PyPI.

## Commands

```bash
pip install -e ".[dev]"              # Install in dev mode
pytest                               # Offline tests, parallel via xdist (no token needed)
pytest -n0                           # Same offline tests, sequential (for pdb / -s / debugging)
pytest -m integration -v             # Integration tests (needs .env with token)
pytest tests/test_cli.py::TestCLI::test_cli_help  # Single test
pytest -k "campaigns"                # Pattern match
black .                              # Format
flake8 direct_cli tests              # Lint
```

## Architecture

Click group-of-groups. Each Yandex Direct API resource = one file in `direct_cli/commands/` with a Click group and subcommands (`get`, `add`, `update`, `delete`, `suspend`, `resume`, etc.). All groups registered in `direct_cli/cli.py` via `cli.add_command()`.

**Campaigns split (issue #602):** `campaigns.py` is being decomposed incrementally. Step 1 moved all shared constants, validators, payload builders and the reusable TextCampaign strategy option groups into a sibling `direct_cli/commands/_campaigns_base.py`; `campaigns.py` re-imports every name, so the CLI surface is unchanged. Subsequent steps will move per-campaign-type logic (`text`, `unified`, `dynamic`, `smart`, `mobile_app`, `cpm_banner`) into the same package — never edit shared helpers in `campaigns.py`, edit `_campaigns_base.py`.

**Request flow:** `cli.py` → `auth.py` (resolves token/login) → `api.py` (`create_client`) → `tapi_yandex_direct.YandexDirect` → Yandex API → `output.py` (format/print).

**Credentials priority (CLI):** explicit CLI flags (`--token`, `--login`, `--profile`) > base env/current working directory `.env` (`YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_LOGIN`) > active profile from `direct auth login` / `direct auth use` > 1Password/Bitwarden refs. Explicit `--profile` is isolated and does not fall back to base `.env` login. See `direct_cli/auth.py` (`get_credentials`) and README table for the full chain.

**Credentials priority (tests):** env vars/current working directory `.env` > active profile > skip. Tests must not silently hit production when a developer has an active `direct auth` profile, so env vars take precedence over the profile (see `tests/test_v4_live_contracts.py::_credentials`).

**Shared utilities** (`utils.py`): `parse_ids`, `parse_json`, `build_selection_criteria`, `build_common_params`, `get_default_fields`, `COMMON_FIELDS` dict. All command modules import from here — don't duplicate.

**Output** (`output.py`): `format_output()` supports json (default), table, csv, tsv, and `text` (human-readable plain blocks via `format_text`). Colored helpers: `print_success`, `print_error`, `print_warning`, `print_info`.

**Reference commands** (local value lists / templates, e.g. `trackingparams`, `dictionaries list-names`) default to the human-readable `text` format and expose `--format {text,json,table,csv,tsv}` / `--output` via the shared `reference_output_options` decorator (`utils.py`, sibling of `v4_output_options`). API-data commands keep `json` default. New reference commands should use this decorator.

## Key Conventions

**Adding a new command module:**
1. Create `direct_cli/commands/<resource>.py` with `@click.group()` + subcommands.
2. Register in `cli.py` with `cli.add_command(...)`.
3. Add command name to `TestCommandsRegistered.EXPECTED_COMMANDS` in `tests/test_comprehensive.py`.

**`--dry-run`:** `add`/`update` commands print request JSON without calling the API. Use as test seam.

**No legacy CLI flag aliases.** A CLI option must be exactly the kebab-case form of the WSDL request parameter (`SitelinkFieldNames` → `--sitelink-field-names`). If an existing flag uses a different name for the same WSDL parameter, rename it as a **breaking change** — do not keep the old form as a second `@click.option` name on the same variable. Document the rename in `CHANGELOG.md` under a `BREAKING CHANGES` heading and bump the version accordingly.

**Runtime-deprecated methods:** WSDL-visible methods that Yandex rejects at runtime belong in `RUNTIME_DEPRECATED_METHODS` (`direct_cli/wsdl_coverage.py`) and must fail with `click.UsageError` before request construction. `agencyclients add` is blocked this way; use `agencyclients add-passport-organization`.

**Strict WSDL parity:** `DRY_RUN_PAYLOAD_EXCLUSIONS` in `tests/api_coverage_payloads.py` must NOT contain any entry whose rationale claims the CLI surface is a «helper», «legacy», or «not part of strict WSDL parity». If the WSDL declares the operation, the CLI mirrors it 1:1 with a `PAYLOAD_CASES` fixture. Legitimate permanent exclusions are limited to:
- read-path `*.get` (covered by SelectionCriteria tests);
- runtime-deprecated methods (see `RUNTIME_DEPRECATED_METHODS`);
- v4 methods that have no v5 WSDL (covered by `direct_cli/v4_contracts.py`);
- custom non-RPC endpoints (e.g. `reports.get` — TSV stream);
- methods explicitly covered by a `test_<service>_<op>_payload` test in the `tests/test_dry_run_*.py` module suite.

A guard in `tests/test_api_coverage.py::test_dry_run_exclusions_have_no_helper_or_legacy_rationale` enforces this — any rationale outside those five categories that uses the banned phrasing is a mis-classification: write a `PAYLOAD_CASES` fixture instead. See post-mortem in issue #199.

**WSDL parity gate:** `tests/test_wsdl_parity_gate.py` runs four hard invariant checks across every `add`/`update`/`set` command in `WRITE_SANDBOX`, plus one soft optional-field audit:

1. *Empty subtype no-op* — a mutating command with only the resource ID must refuse to send the payload (no silent no-op on the live API).
2. *Silent data loss* — a typed flag that does not belong to the chosen `--type` must raise `UsageError`, not be dropped.
3. *WSDL `minOccurs=1` not validated* — every required WSDL item field must be enforced either via Click `required=True` *or* a documented `UsageError` body check (listed in `INTERNAL_VALIDATION`).
4. *Strategy enum drift* — `STRATEGY_TYPES` (`direct_cli/commands/strategies.py`) must equal the subtype-of-one field names in `StrategyAddItem`.
5. *Optional-field visibility* — `scripts/build_wsdl_optional_field_audit.py --check` compares cached WSDL item fields (including `minOccurs=0`, at unbounded nesting depth) with `tests/WSDL_OPTIONAL_FIELD_AUDIT.md`. Confirmed misses stay soft-gated as `missing_followup` rows linked to GitHub issues; they do not fail CI as missing CLI flags until implemented.

Adding a new mutating command requires extending `COMMAND_WSDL_MAP` in `tests/test_wsdl_parity_gate.py` (the coverage test fails otherwise) and, if the WSDL request has a non-mechanical field name, also `WSDL_FIELD_TO_CLI_OPTION`. Tracked in issue #198.

**SelectionCriteria:** Resources like `adgroups`, `ads`, `keywords` require at least one of `Ids`, `CampaignIds`, or `AdGroupIds` — otherwise API error 4001.

**Error handling:** All commands wrap API calls in `try/except Exception` → `print_error(str(e))` + `raise click.Abort()`.

**Default fields:** `COMMON_FIELDS` in `utils.py` maps resource names to default `*FieldNames`. Most entries are `list[str]`; multi-`*FieldNames` resources use `dict[str, list[str]]` keyed by WSDL request param (for example `FieldNames`, `TextAdFieldNames`, `SearchFieldNames`). Not all fields are valid for all resources (e.g., `adimages` uses `AdImageHash`, not `Id`).

**WSDL imports:** Imported schemas used by request validation are cached in `tests/wsdl_cache/imports/` and registered in `IMPORTED_XSD_REGISTRY`. Keep imported nested types resolved; empty `item_fields` for registered imports is coverage drift.

**Smoke probes:** Live ID discovery for safe-smoke and integration tests lives in `direct_cli/_smoke_probes.py`. Functions like `advideo_probe_id()` query the live API to find a real resource ID (env override `YANDEX_DIRECT_TEST_ADVIDEO_ID`, fallback through `creatives.get`) and return `None` on any failure — smoke scripts treat `None` as a benign skip, not a fatal error. CLI entry: `python3 -m direct_cli._smoke_probes advideo`.

**No URL literals outside the registry.** Every Yandex docs/API URL is declared once — either in `direct_cli/_vendor/tapi_yandex_direct/resource_mapping.py` (`docs`, `docs_pages.*`) or in `direct_cli/reports_coverage.py::REPORTS_SPEC_URLS`. Tests and scripts import these constants; never write the URL as a string literal anywhere else. Captcha-poisoning of the docs cache (#426) was possible only because the same URL was duplicated in a hard-coded test assertion. Don't repeat that.

**Docs/cache freshness guard.** `direct_cli.reports_coverage.fetch_reports_spec` and `direct_cli.wsdl_coverage.fetch_wsdl` both refuse responses that look like a Yandex SmartCaptcha gate (markers `showcaptcha`, `smartcaptcha`, `<title>Captcha`) or are suspiciously short (<30 KB for HTML, <3 KB for WSDL). The matching tests `test_reports_cache_files_are_real_content` and `test_wsdl_cache_files_are_real_content` enforce the same invariant on committed cache files.

## PyPI Release

Release is two-phase on purpose. Yandex frequently rate-limits the docs host with a SmartCaptcha gateway, which is an external rate-limit on our IP — not evidence that an URL is gone. Mixing docs-health checks into the publish path made releases non-deterministic, so they live in a separate preflight script.

**Phase 1 — preflight (manual, network-dependent):**

```
bash scripts/preflight_check.sh
```

Runs three checks:

1. `python scripts/check_all_docs_urls.py` — every Yandex docs URL in `RESOURCE_MAPPING_V5` and `REPORTS_SPEC_URLS` must be reachable. The probe falls back from `HEAD` to `GET` on 4xx (some CDNs reject `HEAD`), then verifies real content. **Hard fail:** confirmed 3xx-to-different-path or 4xx (canonical move / gone). **Soft warning (does not block):** 5xx or persistent captcha — treated as a transient Yandex rate-limit; re-run later to confirm.
2. `pytest TestReportsCoverage TestWsdlCacheFreshness -v` — read-only check that the committed Reports/WSDL/XSD caches are real content (not captcha).
3. `git diff --quiet -- tests/reports_cache tests/wsdl_cache` — refuses to proceed with an uncommitted cache refresh. If Yandex changed docs since the last snapshot, run `scripts/refresh_reports_cache.py` separately, review the diff, and commit it before releasing.

**Phase 2 — release (deterministic, no Yandex network calls):**

```
bash scripts/release_pypi.sh all
```

Builds dist artifacts, runs twine checks, uploads to TestPyPI + PyPI. Does **not** re-run docs/cache checks — if the captcha rate-limit was active during preflight, that should not block a release of an already-verified artifact.

## Tests

- **Unit** (`test_cli.py`, `test_comprehensive.py`) — no API calls, no token needed.
- **Dry-run payload tests** (`tests/test_dry_run_*.py`) — split by command type (issue #604): `test_dry_run.py` is the guard module (rationale + a `test_dry_run_module_is_importable` sanity check); `test_dry_run_shared.py` holds the `_dry_run`/`_read_dry_run`/`_rejected`/`_failing_run`/`_ids_csv`/`_write_jsonl` invocation helpers; `test_dry_run_<resource>.py` modules hold the per-service payload assertions. Add a new dry-run test to the owning module and import the helpers from `test_dry_run_shared`.
- **Parallel by default:** `addopts` runs the offline tier with `-n auto` (pytest-xdist) across CPU cores; the suite is process-parallel-safe (env/cwd via `monkeypatch`, filesystem via `tmp_path`, the shared orphan store only in the excluded live tiers). Use `pytest -n0` to run sequentially for `pdb`/`-s`/debugging. The live tiers (`integration`/`v4_live_read`/`integration_live_write`) are **not** parallel-safe (real API + shared `~/.direct-cli` orphan store + ordered resource lifecycles); a `pytest_xdist_auto_num_workers` hook in `tests/conftest.py` auto-resolves `-n auto` to a single worker whenever a live marker is selected, so an explicit `pytest -m integration_live_write` stays serial.
- **Integration** (`test_integration.py`, `@pytest.mark.integration`) — require `.env` with `YANDEX_DIRECT_TOKEN` and `YANDEX_DIRECT_LOGIN`. Auto-skip if absent.
- **Credential resolution in tests:** env vars/current working directory `.env` first, then active `direct auth` profile, then skip. This matches the safe CLI default for base env vs. active profile: a developer machine with an active profile must not silently hit production on a plain `pytest`.

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

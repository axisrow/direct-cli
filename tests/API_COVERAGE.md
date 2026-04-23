# API Coverage Matrix

This document is the human-readable companion to
`scripts/build_api_coverage_report.py`.

## Coverage Surfaces

| Surface | Source of truth | Status field |
|---|---|---|
| Declared WSDL-backed SOAP services | `direct_cli.wsdl_coverage.CLI_TO_API_SERVICE` and cached `tests/wsdl_cache/*.xml` | `summary.strict_parity_ok` |
| Live-discovered model gaps | `direct_cli.wsdl_coverage.LIVE_DISCOVERED_API_SERVICES` compared with the declared model | `summary.live_model_parity_ok` |
| Non-WSDL Reports API | `tests/reports_cache/spec.json` and `direct_cli.reports_coverage` | `reports.summary.*` |
| Intentional CLI helpers | `direct_cli.wsdl_coverage.INTENTIONAL_EXTRA_METHODS` | `cli_helpers` |

`strict_parity_ok` means the CLI fully covers the currently declared canonical
API model. It does not prove that the declared model includes every live
Yandex Direct API service. Live service omissions are reported separately in
`model_gaps`.

## Current Coverage Metrics

All previously live-discovered gaps (`dynamicfeedadtargets`, `strategies`) are
now implemented and included in the canonical model. The expected coverage
report values:

| Metric | Expected current value |
|---|---:|
| Declared WSDL services | 29 |
| Live-discovered services | 29 |
| Declared WSDL operations | 112 |
| Non-WSDL API services | 1 |
| Supported API services including Reports | 30 |
| CLI top-level groups including auth | 31 |
| CLI subcommands including auth | 122 |
| API CLI subcommands excluding auth | 118 |
| Live-discovered missing services | 0 |
| Live-discovered missing methods | 0 |

## Smoke Command Matrix

Every registered Click subcommand is classified exactly once in
`direct_cli/smoke_matrix.py`:

| Category | Runner | Purpose |
|---|---|---|
| `SAFE` | `scripts/test_safe_commands.sh` | Production read-only smoke tests |
| `WRITE_SANDBOX` | `scripts/test_sandbox_write.sh` | Live mutating sandbox smoke tests with per-command `PASS` / `FAIL` / `SANDBOX_LIMITATION` / `NOT_COVERED` report |
| `DANGEROUS` | `scripts/test_dangerous_commands.sh` | Manual-only checklist; exits 1 by design |

`tests/test_smoke_matrix.py` fails if a CLI command is missing from the matrix,
appears in multiple categories, or if the current service/command counts drift.

## Maintenance Rules

- When a missing service is implemented, add it to `CLI_TO_API_SERVICE`,
  `CANONICAL_API_SERVICES`, `tests/wsdl_cache/`, CLI registration, and command
  tests in the same change.
- Keep `LIVE_DISCOVERED_API_SERVICES` conservative and explicit. Do not scrape
  Yandex documentation navigation in fast tests.
- Use `scripts/check_wsdl_drift.py` for method/schema drift in already declared
  services.
- Use `scripts/build_api_coverage_report.py` for the machine-readable artifact
  that combines declared parity, Reports coverage, CLI helpers, and model gaps.
- Before treating an issue as a coverage blocker, check
  `tests/API_ISSUE_AUDIT.md`. Closed issues may contain official API-status
  evidence that supersedes an older implementation assumption.

## Sandbox Category Split (issues #28 / #56)

The Yandex Direct sandbox intentionally disables some endpoints and
structurally does not support others. Every class marked
`@pytest.mark.sandbox_limitation(category=...)` in
`tests/test_integration_write.py` declares which category it belongs to.

### Category A — disabled (codes 8800 / 1000 / 5004)

Live API supports these; sandbox returns errors. Periodic sandbox re-check
recommended per release to detect if Yandex restores them.

| Scenario | Symptom | Error code | Test class |
|---|---|---|---|
| ads add/update/delete | adgroup not persisted after creation | 8800 | `TestWriteAds` |
| keywords add/update/delete | adgroup not persisted after creation | 8800 | `TestWriteKeywords` |
| bids set | keyword chain not persisted (cascade from adgroup) | 8800 | `TestWriteBids` |
| keywordbids set | keyword chain not persisted (cascade from adgroup) | 8800 | `TestWriteKeywordBids` |
| audiencetargets add/delete | retargeting list + adgroup not persisted | 8800 | `TestWriteAudienceTargets` |
| sitelinks add/delete | service permanently unavailable in sandbox | 1000 | `TestWriteSitelinks` |
| adimages add/delete | valid 450×450 PNG rejected | 5004 | `TestWriteAdImages` |

Testing strategy: guarded live-write tier via `tests/test_integration_live_write.py`
(issue #56) is the current workaround; sandbox rewrite per release to detect fixes.

### Category B — unsupported (code 3500)

Sandbox architecturally does not support these campaign/group types.
Live API also rejects them on standard advertiser accounts — creation returns
`3500 Not supported`. A dedicated agency or pilot account is required.
Sandbox re-check is not useful — this is an account-tier limitation.

| Scenario | Symptom | Error code | Test class |
|---|---|---|---|
| dynamicads | `DYNAMIC_TEXT_CAMPAIGN` creation rejected | 3500 | `TestWriteDynamicAds` |
| smartadtargets | `SMART_CAMPAIGN` creation rejected | 3500 | `TestWriteSmartAdTargets` |

Testing strategy: manual-only on an account where DYNAMIC_TEXT_CAMPAIGN and
SMART_CAMPAIGN are enabled. See `tests/MANUAL_COVERAGE.md`.

Originally classified in
[#28 issuecomment-4275359621](https://github.com/axisrow/direct-cli/issues/28#issuecomment-4275359621)
and
[#56 issuecomment-4275359702](https://github.com/axisrow/direct-cli/issues/56#issuecomment-4275359702)
— those comments serve as historical reference; the tables above are canonical.

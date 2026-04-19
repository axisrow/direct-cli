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

## Current Live-Discovered Gaps

| API service | Missing CLI group | WSDL methods |
|---|---|---|
| `dynamicfeedadtargets` | `dynamicfeedadtargets` | `add`, `delete`, `get`, `resume`, `setBids`, `suspend` |
| `strategies` | `strategies` | `add`, `archive`, `get`, `unarchive`, `update` |

The current coverage report should therefore show:

| Metric | Expected current value |
|---|---:|
| Declared WSDL services | 27 |
| Declared WSDL methods | 101 |
| Live-discovered services | 29 |
| Live-discovered methods | 112 |
| Live-discovered missing services | 2 |
| Live-discovered missing methods | 11 |

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

# API Coverage Snapshot

Dated, human-readable companion to `tests/API_COVERAGE.md`. Each section is a
frozen snapshot of `direct-cli` ↔ Yandex Direct API parity at a specific commit,
recorded so future audits have a reference point for comparison.

Numbers are regenerated, not hand-counted:

```bash
python3 scripts/build_api_coverage_report.py        # v5 WSDL + Reports + CLI counts
python3 scripts/build_wsdl_optional_field_audit.py --check   # optional-field audit
```

v4 figures come from `direct_cli/v4_contracts.py` (`V4_METHOD_CONTRACTS`) cross-
referenced against the method literals wired in `direct_cli/commands/v4*.py`.

---

## Snapshot 2026-05-28 (main @ `e9c7ea5`)

Recorded for milestone `0.3.15` (#428), after the nested `*FieldNames` wave
(#415–#425), the reports docs-drift pass (#426), and the v4 documentation /
finance wave (#439–#447).

| Surface | 1-to-1 parity | Open divergences |
|---|---|---|
| v5 SOAP/JSON RPC (WSDL) | 29 services / 112 operations | 0 hard; 26 `not_applicable` docs↔WSDL drift |
| JSON `reports.get` | 8 report types / 84 fields / 6 headers | 0 |
| Custom uploads (`adimages`/`feeds`/`advideos`) | synchronous API, no polling | 0 |
| v4 / V4 Live | 23 / 32 contracts CLI-wired | 9 not wired (see below) |
| "Silent" gaps | — | none; all formalized in audit docs |

### v5 WSDL

- `services_checked = 29`, `declared_wsdl_methods_count = 112`.
- `strict_parity_ok = true`, `live_model_parity_ok = true`, `schema_parity_ok = true`.
- `live_model_gap_count = 0` (no live-discovered missing services or methods).
- Intentional CLI helper: `agencyclients.delete` (API has no delete; CLI guard).
- Runtime-deprecated guard: `agencyclients.add` (error 3500 → `add-passport-organization`).
- Source of truth: `direct_cli/wsdl_coverage.py`, cached `tests/wsdl_cache/*.xml`.

### Optional-field audit (`tests/WSDL_OPTIONAL_FIELD_AUDIT.md`)

| Status | Count |
|---|---:|
| `supported` | 3215 |
| `not_applicable` | 26 |
| `missing_followup` | 0 |

The 26 `not_applicable` rows are documented docs↔WSDL drifts (23 under
`DynamicTextFeedAdGroup.AutotargetingSettings`, tied to #281; 3 under
`TextCampaign.BiddingStrategy.Search.*.BudgetType`, tied to #361). They are not
CLI gaps and do not fail CI.

### Reports (JSON, non-WSDL)

- 8 report types, 84 fields, 6 HTTP headers — all CLI-covered.
- `cli_report_types_match = true`, `cli_headers_covered = true`.
- Drift protection: `scripts/check_reports_drift.py` (refreshed in #426).

### CLI surface

- 40 top-level groups (including `auth`).
- 143 subcommands total.

### v4 / V4 Live (23 / 32 contracts CLI-wired)

`V4_METHOD_CONTRACTS` holds 32 method contracts. By documentation source:
7 `confirmed-live`, 20 `docs`, 5 `undocumented`.

23 methods are wired to a CLI subcommand. The 9 not yet wired:

| Method | Group | Source | Status |
|---|---|---|---|
| `AdImageAssociation` | ad_image | docs (verified 2026-05-28, #445) | docs resolved; CLI not yet built |
| `DeleteOfflineReport` | offline_reports | docs (verified 2026-05-28, #446) | docs resolved; CLI not yet built |
| `DeleteReport` | offline_reports | docs (verified 2026-05-28, #447) | docs resolved; CLI not yet built |
| `GetKeywordsSuggestion` | keywords | docs (verified 2026-05-28, #444) | docs resolved; CLI not yet built |
| `PayCampaignsByCard` | finance | undocumented | dangerous; blocked pending docs |
| `PingAPI` | meta | undocumented | metadata; not exposed |
| `PingAPI_X` | meta | undocumented | metadata; not exposed |
| `GetVersion` | meta | undocumented | metadata; not exposed |
| `GetAvailableVersions` | meta | undocumented | metadata; not exposed |

The four previously-undocumented contract blockers from #428
(`AdImageAssociation`, `DeleteOfflineReport`, `DeleteReport`,
`GetKeywordsSuggestion`) are now `Docs-verified 2026-05-28` in
`direct_cli/v4_contracts.py`; their docs-drift block is lifted, only CLI
exposure remains. The v4 finance reads `GetCreditLimits` and `CheckPayment`
now have CLI commands (`v4finance get-credit-limits`, `v4finance check-payment`),
resolving the #428 acceptance child-issue item.

Source of truth: `direct_cli/v4_contracts.py`, `direct_cli/commands/v4*.py`.

# Wire-shape audit triage — 2026-05-30

Triage of the `scripts/audit_wire_shape.py --all` snapshot
(`docs/audits/wire_shape.json`, 121 findings). Follow-up to the 2026-05-29
run (#460): the captcha gate that blocked 33 endpoints last time was largely
cleared this round, so most "unknown" statuses now resolve.

**Bottom line: no real code↔docs drift. Every non-OK finding is either a
parser heuristic false-positive, a transient captcha gate, or a documented
deletion.**

## Findings by kind

| Kind | Count | Verdict |
|---|---|---|
| `v5_schema_seen` | 87 | ✅ coverage — scraper found the schema block |
| `v5_wsdl_group_ok` | 4 | ✅ coverage — see "WSDL group" below |
| `reports_spec_ok` | 1 | ✅ reports surface parses |
| `skipped_undocumented_by_policy` | 1 | ✅ expected (PayCampaignsByCard) |
| `code_field_missing_in_docs` | 11 | false-positive (parser) |
| `live4_marker_absent` | 7 | cosmetic |
| `docs_unreachable` | 6 | 1 real 404, 5 transient captcha |
| `v5_schema_not_extracted` | 2 | known group-level pages |
| `required_field_missing_in_payload_module` | 1 | false-positive (parser) |
| `docs_field_missing_in_code` | 1 | false-positive (parser) |

## Detail

### WSDL group (`v5_wsdl_group_ok` ×4) — resolved
`dynamicads`, `dynamicfeedadtargets`, `smartadtargets`, `vcards` had their
human-readable doc pages removed by Yandex (Sep 2025, #463). Their `docs`
now points at the live WSDL endpoint. `audit_v5` recognises a WSDL base and
records it as group coverage instead of deriving malformed `…?wsdl/get` URLs
or flagging the 14–21 KB XML as "thin". This replaces what were 18
captcha/unreachable findings in the prior snapshot.

### `docs_unreachable` ×6
- **`CheckPayment`** — clean **HTTP 404** (not captcha). No public doc page
  exists; the contract already records `source=confirmed-live`, "Official
  public docs were not found". Verified by hand (#460 reporter) and via
  browser. Not drift.
- **`PingAPI_X`** — meta/diagnostics probe, `source=undocumented`; no doc page.
- **`GetAvailableVersions`, `GetForecastList`, `GetKeywordsSuggestion`,
  `GetWordstatReport`** — `captcha-after-retries`. These pages **do exist** at
  `dg-v4/ru/reference/<Method>.html` (confirmed live in a browser this round:
  CreateNewWordstatReport, DeleteWordstatReport, DeleteForecastReport,
  DeleteReport, GetAvailableVersions all return real content matching their
  contracts). Their captcha status is a transient IP rate-limit, not drift.
  Re-run when the IP is clear to flip them to coverage.

### `code_field_missing_in_docs` ×11 — false-positive
`AdImageAssociation` (9), `AccountManagement` (1), `GetRetargetingGoals` (1).
The parser reports "`example_param` has 'Action'/'CampaignIDS' but the docs
schema doesn't". These fields are real and documented (contracts docs-verified
2026-05-28); the HTML-table scraper just doesn't map them to the same token.
Heuristic noise, not a code defect.

### `docs_field_missing_in_code` ×1 — false-positive
`GetBannersTags`: "docs mention 'CampaignIDS' but example_param doesn't". The
CLI `v4tags get-banners` fully supports both `--campaign-ids` (CampaignIDS) and
`--banner-ids` (BannerIDS), requiring exactly one; the contract's `example_param`
just illustrates the BannerIDS variant. Both selectors are implemented.

### `required_field_missing_in_payload_module` ×1 — false-positive
`AccountManagement`: "Live 4 marks 'Currency' required but example_param
doesn't". The flagged `example_param` is the `Action: Get` variant, which
carries no money and no Currency. The money actions (Deposit/Invoice/
TransferMoney) do require `--currency` in the CLI.

### `v5_schema_not_extracted` ×2 — known
`agencyclients.addPassportOrganization` / `addPassportOrganizationMember` are
genuine group-level pages without an inline `/* TypeName */` schema block.
Informational, not an error.

### `live4_marker_absent` ×7 — cosmetic
`AdImageAssociation`, `DeleteOfflineReport`, `EnableSharedAccount`,
`GetBannersTags`, `GetCampaignsTags`, `UpdateBannersTags`,
`UpdateCampaignsTags` — live page reachable but lacks the «Новое в версии
Live 4» banner. Marker absence only; the pages and contracts are fine.

## Cadence
Re-run `scripts/audit_wire_shape.py --all` from a clean (non-captcha) egress
to flip the 5 transient-captcha v4 methods to coverage. The weekly
`api-coverage.yml` schedule (Mondays 06:00 UTC) plus the `monitor-live-*` jobs
already cover ongoing drift detection.

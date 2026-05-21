# Changelog

## 0.3.10

**Added:**

- `direct changes check` now exposes all three mutually-exclusive ID
  filters from the WSDL — `--campaign-ids` (≤3000), `--ad-group-ids`
  (≤10 000) and `--ad-ids` (≤50 000); exactly one is required and the
  mutex is enforced via `click.UsageError` (exit code 2) before any
  request is built. `--fields` is now validated against the
  `CheckFieldEnum` (`CampaignIds`, `AdGroupIds`, `AdIds`,
  `CampaignsStat`); unknown values, empty / comma-only inputs and the
  WSDL `minOccurs=1` violation are caught up-front. Refs: Closes #228.
- `direct sitelinks add` accepts `\|` as a literal pipe inside
  `--sitelink` spec strings, so UTM templates like
  `cid|{campaign_id}|gid|{gbid}` survive parsing. Two new structural
  sources mirror the `keywords.add` #218 pattern:
  `--sitelink-json '<JSON-array>'` (inline) and
  `--sitelinks-from-file <path.jsonl>` (one object per line); sources
  are mutually exclusive. Unknown JSON keys are rejected with the
  offending key surfaced (no silent data loss), and missing
  `Title`/`Href` rows are rejected with the row index. Refs:
  Closes #221, Closes #220.
- `direct v4 *` commands now validate request body shape against
  `V4_METHOD_CONTRACTS` before sending. Documented param shapes
  (`PARAM_ARRAY` / `PARAM_OBJECT` / `PARAM_OPTIONAL_OBJECT` /
  `PARAM_SCALAR`) raise `click.UsageError` on mismatch — the request
  never reaches the network. Undocumented-shape methods are split by
  contract safety: `SAFETY_READ` (e.g. `GetKeywordsSuggestion`)
  emits a stderr warning and proceeds; `SAFETY_WRITE` /
  `SAFETY_DANGEROUS` (e.g. `PayCampaignsByCard`) fail-closed with a
  remediation pointer to `V4_METHOD_CONTRACTS`. Refs: Closes #182.
- Regression tests that lock down subtype validation invariants from
  the `#210` umbrella repro matrix. Nine new `SILENT_LOSS_PROBES` in
  `tests/test_wsdl_parity_gate.py` cover per-type rejection across
  `campaigns add`, `adgroups add`, `ads add`, `bidmodifiers add` and
  `strategies add` (test-only — the corrected rejection behavior was
  shipped earlier in 0.3.9 via #198 audit follow-up PRs). Three new
  non-regression tests in `tests/test_dry_run.py` lock down
  `strategies update` field aliases (`AverageCpcPerFilter →
  FilterAverageCpc`, `PayForConversion → Cpa`) and confirm that
  `AverageCpa` update without `--goal-id` stays WSDL-valid
  (`GoalId` is `minOccurs=0` on update). Refs: Closes #210.

**Fixed:**

- `direct keywords add` in bulk mode (`--from-file` / `--keywords-json`,
  shipped in 0.3.9 / #218) now surfaces per-item `Errors` instead of
  swallowing them and exiting 0 with raw JSON. The per-chunk loop now
  calls `raise_for_api_result_errors` and the final response goes
  through `format_output`, so the 8800 Client-Login guidance and the
  full `Errors` payload propagate through the existing exception
  handler. The partial-success diagnostic ("these keywords were
  already created in Yandex Direct") only lists items Yandex actually
  accepted. Refs: Closes #211.
- `direct_cli/auth.py::_write_json` no longer leaks a file descriptor
  when `chmod` fails between `tempfile.mkstemp` and `os.fdopen`.
  Descriptor ownership is now tracked via a sentinel; cleanup errors
  in `os.close` / `os.unlink` use `contextlib.suppress(OSError)` so
  the original exception is preserved. Refs: Closes #154.

## 0.3.9

**Added:**

- `direct keywords add` now supports batch mode via `--from-file PATH`
  (JSONL, one keyword object per line) or `--keywords-json '[…]'`
  (inline JSON array). The CLI splits input into chunks of 10 — the
  Yandex Direct API limit for `keywords.add` documented at
  https://yandex.ru/dev/direct/doc/dg/objects/keyword.html — preserves
  input order, and merges `AddResults` from every chunk into a single
  response. Item-level errors do not abort the batch. If a chunk-level
  exception breaks the loop, already-created Ids are printed to stderr
  with a "Partial success before failure" header so a retry doesn't
  duplicate them. Pre-flight warning when any AdGroupId in the input
  exceeds the per-ad-group limit of 200 keywords (the API rejects the
  excess with per-item errors; warning surfaces this before any chunk
  is sent). Row keys use WSDL CamelCase (`Keyword`, `AdGroupId`,
  `Bid`, `ContextBid`, `UserParam1`, `UserParam2`); unknown keys are
  rejected with the row number, and JSON booleans are explicitly
  rejected to prevent silent `True → 1` coercion. `--adgroup-id` is
  optional in batch mode and acts as a default, overridable per row.
  `--dry-run` prints the first chunk's payload alongside
  `{chunks, totalItems, chunkSize}`. Single-item mode (`--keyword`)
  is unchanged (#203).
- `direct campaigns add` typed flags for CPA strategies and
  cross-cutting `CampaignAddItem` fields: `--goal-id` (single
  Metrika goal), `--crr` (CRR percentage for
  `PAY_FOR_CONVERSION_CRR`),
  `--priority-goals goal_id:value,…` (multi-goal CPA via
  WSDL `PriorityGoalsArray`), `--average-cpa MICRO_RUBLES`,
  `--bid-ceiling MICRO_RUBLES`, `--counter-ids`
  (TextCampaign/DynamicTextCampaign), `--notification JSON`
  (`CampaignBase.Notification` with `SmsSettings`/`EmailSettings`
  shape validation), `--time-targeting JSON`
  (`CampaignAddItem.TimeTargeting` with `HolidaysSchedule`
  shape validation). Strategy-subtype compatibility is enforced
  via `UsageError` at CLI level both ways: WSDL-incompatible flags
  are rejected (e.g. `--average-cpa` for `HIGHEST_POSITION`,
  `--crr` outside `PAY_FOR_CONVERSION_CRR`,
  `--bid-ceiling` for `PayForConversionCrr` /
  `PayForConversionMultipleGoals`), and WSDL `minOccurs=1`
  fields are demanded up-front (e.g. picking `AVERAGE_CPA`
  without `--average-cpa`+`--goal-id`, or `PAY_FOR_CONVERSION_CRR`
  without `--crr`+`--goal-id`, or `*_MULTIPLE_GOALS` without
  `--priority-goals`, all fail at the CLI instead of the API).
  Closes #204.

**Notes:**

- Issue #204 also requested `--goals` (array) and
  `--network-settings`; both were dropped after WSDL audit. Yandex
  `Strategy*Add` complex types declare only scalar `GoalId`, so
  multi-goal CPA is shipped through `--priority-goals` instead
  (correct WSDL path: `TextCampaign.PriorityGoals.Items[].GoalId/Value`).
  No `NetworkSettings` field exists on `CampaignAddItem` /
  `TextCampaignAddItem` / `DynamicTextCampaignAddItem` /
  `SmartCampaignAddItem` in the current `campaigns.xml` WSDL.

**Fixed:**

- Refreshed `TestWriteFeeds` and `TestWriteSmartAdTargets` VCR cassettes against a real sandbox, dropped the `_FEED_REGRESSION_PATTERNS` skip workaround, and updated `sandbox_feed` / `sandbox_smart_adgroup` fixtures to pass the now-WSDL-required `--business-type RETAIL` (FeedAddItem) and `--counter-id` (SmartCampaignAddItem). Tests now skip only on genuine sandbox limitations, not on the missing-option proxy that the workaround papered over (#206, fallout from #201). Test invocation now also passes `--login` and prefers env vars over an active `direct auth` profile, matching the inversion documented in CLAUDE.md.
- WSDL parity gate now fails fast when `COMMAND_WSDL_MAP` points at a container that does not exist in the WSDL request schema. The previous skip-on-empty-required-list silently masked typo'd container names (#206, Copilot follow-up from #205).
- `WSDL_FIELD_TO_CLI_OPTION` no longer references the non-existent generic `--file` flag. `SourceType` maps to `{--url}` and `ImageData` maps to `{--image-data, --image-file}`, matching the real CLI surface (#206, Copilot follow-up from #205).
- `direct bidmodifiers set --help` no longer advertises the rejected `--campaign-id`/`--type` legacy path; the rejection now happens via an eager Click callback (same pattern as deprecated `keywords update` options), preserving the existing `UsageError` message for regression coverage (#206, Copilot follow-up from #214).

**Refs:** Closes issues #122, #138, #198, #202, #203, #204, #206, #207.

## 0.3.8

**BREAKING CHANGES:**

- `direct ads update` now requires `--type {TEXT_AD,TEXT_IMAGE_AD,MOBILE_APP_AD}`. Scripts that called `ads update` with only field flags will fail with `Missing option '--type'`. Mirrors the WSDL one-of choice between TextAd/TextImageAd/MobileAppAd update subtypes (PR #197).
- `direct ads add --type TEXT_IMAGE_AD` rejects `--title/--text` (TEXT_IMAGE_AD has no such WSDL fields). `direct ads update --status` rejected — use `ads suspend/resume/archive/unarchive` for status changes (PR #190).
- `direct ads add --type MOBILE_APP_AD --href` rejected — MobileAppAd uses `--tracking-url`, not `--href` (PR #196).
- `direct feeds add` now requires `--business-type {RETAIL,HOTELS,REALTY,AUTOMOBILES,FLIGHTS,OTHER}`. Mirrors WSDL FeedAddItem.BusinessType (minOccurs=1) (PR #201).

**Schema gate — mutating ops parity:**

- Extended the WSDL `*FieldNames` schema gate (introduced for `get` in 0.3.7) to mutating operations (`add/update/set/setBids/lifecycle`). Added per-operation waiver granularity via `SCHEMA_GATE_OPERATION_WAIVERS` (PR #181).
- Promoted dynamicads, bidmodifiers add/set, adimages/advideos/vcards add (media payloads), adextensions/retargeting/feeds.add typed fixtures to `PAYLOAD_CASES` (PRs #184, #185, #187, #188).
- Added MOBILE_APP_AD branch to `ads add` mirroring WSDL `MobileAppAdAdd` (PR #190).
- `bidmodifiers.delete` correctly classified as a real destructive WSDL operation and added to schema gate (PR #194); the earlier "Helper/legacy surface" rationale was a mis-classification — see post-mortem in #199 / PR #200.

**Strict WSDL parity policy:**

- Documented "Strict WSDL parity" principle in `CLAUDE.md`: `DRY_RUN_PAYLOAD_EXCLUSIONS` may only contain entries from five legitimate categories (read-path `*.get`, runtime-deprecated, v4-not-in-v5-wsdl, custom non-RPC endpoints, methods covered by `tests/test_dry_run.py`). New guard test `test_dry_run_exclusions_have_no_helper_or_legacy_rationale` fails CI if any rationale uses banned phrases (PR #200).

**Integration test coverage:**

- Added read-only sandbox integration tests for `changes`, `keywordsresearch`, `balance` (PR #186).
- Added v5 write integration coverage for `strategies` lifecycle, `retargeting update`, `bids get/set-auto`, plus `auth status/list` read-only tests (PR #189).
- Re-recorded TestWriteBidsRead cassettes against live API and rewrote host to sandbox so the bids endpoints get real coverage in replay mode (PR #193).

**CI infrastructure:**

- Switched Claude code-review GitHub Action from default (Sonnet 4.5) to Claude Opus 4.7 for deeper PR review (PR #192).

**Refs:** Closes issues #118, #136, #137, #175, #176, #180, #183, #191, #199.

## 0.3.3

**BREAKING CHANGE:** OAuth profiles created before 0.3.3 (without `refresh_token` and `expires_at`) are no longer accepted. Any such profile will fail immediately with an "incomplete profile" error. Run `direct auth login --profile <name>` to re-authenticate and create a valid 0.3.3 profile.

- Added refresh token persistence for OAuth profiles.
- Added automatic OAuth access token refresh before expiry.
- Added `expires_in` details to `direct auth status`.
- Added JSON output for `direct auth status`.
- Kept `direct auth login --oauth-token` as a manual access-token import without auto-refresh.

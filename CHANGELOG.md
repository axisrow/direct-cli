# Changelog

## 0.3.9 (Unreleased)

**Fixed:**

- Refreshed `sandbox_feed` VCR cassette to pass `--business-type RETAIL`; removed the `_FEED_REGRESSION_PATTERNS` skip workaround so feed-backed smart-adgroup integration tests run again instead of silently skipping (#206, fallout from #201).
- WSDL parity gate now fails fast when `COMMAND_WSDL_MAP` points at a container that does not exist in the WSDL request schema. The previous skip-on-empty-required-list silently masked typo'd container names (#206, Copilot follow-up from #205).
- `WSDL_FIELD_TO_CLI_OPTION` no longer references the non-existent generic `--file` flag. `SourceType` maps to `{--url}` and `ImageData` maps to `{--image-data, --image-file}`, matching the real CLI surface (#206, Copilot follow-up from #205).
- `direct bidmodifiers set --help` no longer advertises the rejected `--campaign-id`/`--type` legacy path; the rejection now happens via an eager Click callback (same pattern as deprecated `keywords update` options), preserving the existing `UsageError` message for regression coverage (#206, Copilot follow-up from #214).

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

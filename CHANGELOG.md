# Changelog

## 0.4.1 (unreleased)

Russian-default CLI localization across all command modules (epic #466).

**Added — scalable i18n mechanism (#467):**

- Source-string-keyed translation catalog: the English `help=` / docstring /
  epilog text is the catalog key, with Russian translations in external
  `direct_cli/translations/*.json` files (one per module, plus shared
  `common.json`). No `cls=`/`help_key` edits in command modules —
  `cli._apply_directcli_classes` retypes every plain `click.Option` to
  `LocalizedOption` and localizes command/group docstrings and epilogs at
  render time.
- `t()` is now source-keyed and context-free safe (`set_active_locale`), so
  `print_*` runtime messages localize too. `--locale` is eager so the root
  `--help` epilog honors an inline `--locale`.
- `tests/test_i18n.py` gains a `LOCALIZED_GROUPS` registry with two enforced
  invariants per localized module: translation completeness (no silent English
  leak under the Russian default) and `print_*` runtime-message wrapping.
- `v4finance` migrated to the new mechanism and fully localized as the
  reference module.

**Localized — Core search (#468):**

- Russian help/docstrings for `campaigns`, `ads`, `adgroups`, `keywords`,
  `keywordbids`, and `bids` (510 unique strings across the six modules).
  WSDL field paths, enum values, and flag names are kept verbatim; only
  human-readable text is translated. These groups join `LOCALIZED_GROUPS`,
  so their translation completeness is now enforced by `test_i18n.py`.

**Localized — Targeting & creatives (#469):**

- Russian help/docstrings for `strategies`, `bidmodifiers`, `smartadtargets`,
  `vcards`, `feeds`, `dynamicads`, `audiencetargets`, `dynamicfeedadtargets`,
  `retargeting`, `negativekeywordsharedsets`, `adextensions`, `adimages`,
  `sitelinks`, `creatives`, `advideos`, and `turbopages` (247 unique strings
  across the sixteen modules). WSDL field paths, enum values, and flag names
  are kept verbatim; only human-readable text is translated. These groups
  join `LOCALIZED_GROUPS`, so their translation completeness is now enforced
  by `test_i18n.py`.

**Localized — Account, clients, reporting (#470):**

- Russian help/docstrings for `clients`, `agencyclients`, `reports`, `changes`,
  `auth`, `leads`, `dictionaries`, `keywordsresearch`, `businesses`, and
  `balance` (142 source strings across the ten modules). WSDL field paths,
  enum values, and flag names are kept verbatim; only human-readable text is
  translated.
- First modules with localized **runtime messages**: `print_*` calls carrying a
  human-readable literal (`auth` interactive prompts, the `agencyclients delete`
  not-supported notice) are now wrapped in `t()` so they follow the active
  locale. `print_error(str(e))` API-error passthroughs are unchanged. These
  groups join `LOCALIZED_GROUPS`, enforcing both translation completeness and
  the runtime-message wrapping invariant.

## 0.4.0

Milestone release closing the 0.4.0 roadmap (#123): typed Yandex Direct
API **v4 Live** CLI support and completion of the post-0.3.0 write-command
coverage gates. All public v4 input stays typed and canonical — no `--json`
passthrough — and mirrors `dg-v4/live/*` wire shapes 1:1.

**Added — typed v4 Live CLI:**

- v4 Live command foundation with typed Click groups and a `--dry-run`
  seam that prints the `{method, param}` body before token/locale
  enrichment (#124, closes #111 — typed CLI, not raw JSON passthrough).
- `v4finance` and `v4account` typed finance and shared-account commands
  (#125).
- `v4goals`, `v4events`, `v4wordstat`, and `v4forecast` typed commands
  (#126).
- `v4events get-events-log` and `v4forecast create-new-forecast` now expose
  every documented input field (#456).
- Russian-default CLI help with English opt-in, starting with `v4finance`
  (#458).

**Changed — write-command coverage gates:**

- Extended the WSDL schema gate to mutating operations; `keywordbids.set`
  is now enum-validated against its WSDL `*FieldEnum` (#118).
- Per-method `WRITE_SANDBOX` integration coverage completed — zero
  unexplained `NOT_COVERED` commands in `direct_cli/smoke_matrix.py`
  (#122).
- Closed the remaining mutating `DRY_RUN_PAYLOAD_EXCLUSIONS`; every
  declared WSDL operation now has a `PAYLOAD_CASES` fixture or a
  documented technical exclusion (#127).

**Tests / tooling:**

- Offline VCR cassettes for all v5 read-only commands (#455).
- v4 Live read cassettes and a fix for an unbounded retry-loop (#457,
  closes #454).
- Docs/wire-shape scanner with the 2026-05-29 sweep (#451).

`strict_parity_ok`, `live_model_parity_ok`, and `schema_parity_ok` all
report `true` in `scripts/build_api_coverage_report.py`.

## 0.3.16

**BREAKING CHANGES (regression fix — reverts 0.3.15 wire-shape changes):**

- `direct v4finance transfer-money` now requires `--currency` again and
  re-emits `Currency` on every `FromCampaigns` / `ToCampaigns` item.
  The 0.3.15 removal verified against `dg-v4/reference/TransferMoney`
  (legacy v4); the actual Live 4 docs at
  `dg-v4/live/TransferMoney` define `PayCampElement` with
  `CampaignID`, `Sum`, and `Currency`, and explicitly mark `Currency` as
  obligatory in the Live 4 changelog. The CLI now matches the live
  docs 1:1. See audit comment on #125 for the reproducible diff.
- `direct v4finance pay-campaigns` now requires `--currency` again and
  re-emits `Currency` on every `Payments[]` item. Same root cause:
  `dg-v4/reference/PayCampaigns` (legacy) lacks `Currency`,
  `dg-v4/live/PayCampaigns` (Live 4) requires it.
- `direct v4finance pay-campaigns` accepts `--pay-method Overdraft`
  again. The Live 4 changelog explicitly adds `Overdraft` for direct
  advertisers (paired with `Bank` for agencies). Only `Bank` keeps the
  `--contract-id` requirement.
- `direct v4finance create-invoice` now requires `--currency` again and
  re-emits `Currency` on every `Payments[]` item, mirroring
  `dg-v4/live/CreateInvoice`.

This release reverts the wire-shape changes shipped by PRs #441, #442,
#443 (which closed #432, #433, #434). The CLI lives in the `v4finance`
Live group and must mirror `dg-v4/live/*`, not `dg-v4/reference/*`.

## 0.3.15

**BREAKING CHANGES:**

- `direct v4finance transfer-money` no longer accepts `--currency`, and
  the wire-body no longer carries `Currency` on `FromCampaigns`/
  `ToCampaigns` items. The official v4 docs
  (`dg-v4/reference/TransferMoney`) define `PayCampElement` with only
  `CampaignID` and `Sum`; `Sum` is in conventional units. The CLI now
  matches the docs 1:1. Closes #432.
- `direct v4finance pay-campaigns` no longer accepts `--currency`. The
  v4 documentation (`dg-v4/reference/PayCampaigns`) defines
  `PayCampElement` with only `CampaignID` and `Sum` — `Currency` is not
  part of the wire-body and was never forwarded to the API. The option
  is removed entirely to make the CLI surface 1:1 with the docs.
- `direct v4finance pay-campaigns` no longer accepts `--pay-method
  Overdraft`. The v4 documentation
  (`dg-v4/reference/PayCampaigns#PayMethod`) lists only `"Bank"` as a
  supported value; `Overdraft` was a historical undocumented value
  retained by the CLI for sandbox flow. Strict 1:1 docs alignment
  drops it.
- `direct v4finance create-invoice` no longer accepts `--currency`. The
  v4 documentation (`dg-v4/reference/CreateInvoice`) defines
  `PayCampElement` with only `CampaignID` and `Sum` — `Currency` is not
  part of the wire-body and was never forwarded to the API. The option
  is removed entirely to make the CLI surface 1:1 with the docs.

## 0.3.14

**Fixed:**

- Reports drift checker now points at the canonical Yandex docs URLs
  (`/ru/type`, `/ru/period`, `/ru/fields-list`, `/ru/spec`) after Yandex
  retired the `/ru/reports/<page>` path layout and renamed `spec.html`
  to `spec`. The pre-existing `tests/reports_cache/raw/` had silently
  been captcha-poisoned for three of those pages (~14.6 KB Yandex
  SmartCaptcha gateway in place of real docs); cache is now refetched
  from the live canonical URLs and `spec.json` is byte-equivalent to
  the pre-migration snapshot except for one updated description string.
- Five `RESOURCE_MAPPING_V5[*]["docs"]` URLs that Yandex moved from the
  legacy `…/ru/<group>/<group>` to `…/ru/<group>` single-segment form
  (`dynamictextadtargets`, `dynamicfeedadtargets`, `reports`,
  `smartadtargets`, `vcards`). Closes #426.

**Added (drift protection):**

- `direct_cli/reports_coverage.py::fetch_reports_spec` and
  `direct_cli/wsdl_coverage.py::fetch_wsdl` / `fetch_live_wsdl` now
  refuse responses that look like a Yandex SmartCaptcha gateway (markers
  `showcaptcha`, `smartcaptcha`, `<title>Captcha`) or are suspiciously
  short. This prevents silently poisoning the docs/WSDL cache with
  rate-limited captcha HTML.
- `tests/test_api_coverage.py::TestReportsCoverage::test_reports_cache_files_are_real_content`
  and `TestWsdlCacheFreshness::test_wsdl_cache_files_are_real_content`
  guard the committed cache files against the same poisoning.
- `scripts/check_all_docs_urls.py` — health-checks every URL in
  `RESOURCE_MAPPING_V5` and `REPORTS_SPEC_URLS`. Hard-fails on
  redirect-to-captcha, canonical move (`Location` with a different path
  segment), 4xx, or captcha body; soft-warns on 5xx; paces requests to
  avoid Yandex rate-limit. Wired into `scripts/release_pypi.sh` as a
  mandatory pre-release gate together with `refresh_reports_cache.py`
  and a focused pytest pass.

**Contract** (`CLAUDE.md`):

- New rule "No URL literals outside the registry" — every Yandex
  docs/API URL is declared once in `RESOURCE_MAPPING_V5` or
  `REPORTS_SPEC_URLS`; importers reference the constant.
- New rule "Docs/cache freshness guard" — fetchers and cache files
  enforce minimum-size and no-captcha invariants.
- New section "PyPI Release" — documents the three pre-release health
  checks executed by `release_pypi.sh`.

**Breaking changes:**

- `direct ads get` flag `--text-ad-fields` is **renamed** to the
  WSDL-canonical `--text-ad-field-names` form matching the
  `TextAdFieldNames` request parameter declared by `AdsGetRequest`.
  The old `--text-ad-fields` form is no longer accepted — update
  scripts and automation accordingly. Closes #406.
- `direct campaigns add` / `direct campaigns update` and `direct
  strategies add` / `direct strategies update` now reject `--priority-goals`
  / `--priority-goal` values below 100,000 (0.1 unit in micro-currency).
  Per Yandex Direct API (add-text-campaign, strategies-types),
  `PriorityGoalsItem.Value` is `xsd:long` in advertiser currency
  multiplied by 1,000,000 — the same contract as `--budget`,
  `--average-cpa`, and other money flags after #399/#400. The error
  message suggests the micro-currency conversion (e.g. `Did you mean
  500000000?`). Negative values are also rejected up-front rather than
  reaching the API. Both parsers share a single
  `validate_priority_goal_value` helper. Closes #387.

**Added:**

- `direct sitelinks get` now exposes `--sitelink-field-names` for the
  separate WSDL `SitelinkFieldNames` request parameter
  (`SitelinkFieldEnum`: `Title`, `Href`, `Description`, `TurboPageId`).
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the nested `Sitelinks[]` projection could not be
  controlled from CLI.
- `direct keywordbids get` now exposes `--fields`,
  `--search-field-names`, and `--network-field-names` for the
  separate `FieldNames`, `SearchFieldNames`, and `NetworkFieldNames`
  request parameters declared by `KeywordBidsGetRequest`. Defaults
  from `COMMON_FIELDS` are preserved when flags are absent.
- Regression test `test_every_nested_fieldnames_param_has_cli_option`
  (`tests/test_api_coverage.py`) scans every cached WSDL `get`
  request type for `*FieldNames` parameters and verifies that each
  one has a matching kebab-case CLI option. Acknowledged remaining
  gaps are tracked in `NESTED_FIELDNAMES_EXCLUSIONS` and #402 so
  future additions cannot silently slip in.
- `direct feeds get` now exposes `--file-feed-field-names` and
  `--url-feed-field-names` for the separate WSDL `FileFeedFieldNames`
  (`FileFeedFieldEnum`: `Filename`) and `UrlFeedFieldNames`
  (`UrlFeedFieldEnum`: `Login`, `Url`, `RemoveUtmTags`) request
  parameters declared by `FeedsGetRequest`. Previously only the
  top-level `--fields` (mapping to `FieldNames`) was available, so
  the nested `FileFeed` / `UrlFeed` projections could not be
  controlled from CLI. Closes #412.
- `direct keywords get` now exposes
  `--autotargeting-settings-brand-options-field-names`
  (`AutotargetingBrandOptionsFieldEnum`: `WithoutBrands`,
  `WithAdvertiserBrand`, `WithCompetitorsBrand`) and
  `--autotargeting-settings-categories-field-names`
  (`AutotargetingCategoriesFieldEnum`: `Exact`, `Narrow`,
  `Alternative`, `Accessory`, `Broader`) for the separate WSDL
  `*FieldNames` request parameters declared by
  `KeywordsGetRequest`. Previously only the top-level `--fields`
  (mapping to `FieldNames`) was available, so the nested
  `AutotargetingSettings.BrandOptions` / `Categories` projections
  could not be controlled from CLI. Closes #413.
- `direct creatives get` now exposes
  `--cpc-video-creative-field-names`,
  `--cpm-video-creative-field-names`,
  `--smart-creative-field-names`, and
  `--video-extension-creative-field-names` for the four nested
  WSDL `*FieldNames` request parameters declared by
  `CreativesGetRequest` (`CpcVideoCreativeFieldEnum`,
  `CpmVideoCreativeFieldEnum`, `SmartCreativeFieldEnum`,
  `VideoExtensionCreativeFieldEnum`). Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-subtype projections could not be controlled from CLI.
  Closes #411.
- `direct clients get` now exposes `--contract-field-names`,
  `--contragent-field-names`, `--contragent-tin-info-field-names`,
  `--organization-field-names`, and `--tin-info-field-names` for
  the five nested WSDL `*FieldNames` request parameters declared
  by `ClientsGetRequest` (`ContractInfoFieldEnum`,
  `ContragentInfoFieldEnum`, `TinInfoFieldEnum`,
  `OrgInfoFieldEnum`, `TinInfoFieldEnum`). The command also gains
  `--dry-run` for parity with other read-path commands.
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the per-subtype ERIR projections could not be
  controlled from CLI. Closes #410.
- `direct agencyclients get` now exposes `--contract-field-names`,
  `--contragent-field-names`, `--contragent-tin-info-field-names`,
  `--organization-field-names`, and `--tin-info-field-names` for
  the five nested WSDL `*FieldNames` request parameters declared
  by `AgencyClientsGetRequest` (`ContractInfoFieldEnum`,
  `ContragentInfoFieldEnum`, `TinInfoFieldEnum`,
  `OrgInfoFieldEnum`, `TinInfoFieldEnum`). The command also gains
  `--dry-run` for parity with other read-path commands.
  Previously only the top-level `--fields` (mapping to `FieldNames`)
  was available, so the per-subtype ERIR projections could not be
  controlled from CLI. Closes #407.
- `direct adgroups get` now exposes eight additional
  `--*-field-names` flags for the separate WSDL `*FieldNames`
  request parameters declared by `AdGroupsGetRequest`:
  `--autotargeting-settings-brand-options-field-names`,
  `--autotargeting-settings-categories-field-names`,
  `--dynamic-text-ad-group-field-names`,
  `--dynamic-text-feed-ad-group-field-names`,
  `--mobile-app-ad-group-field-names`,
  `--smart-ad-group-field-names`,
  `--text-ad-group-feed-params-field-names`, and
  `--unified-ad-group-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-subtype ad-group projections could not be controlled from
  CLI. Closes #405.
- `direct ads get` now exposes sixteen additional `--*-field-names`
  flags for the separate WSDL `*FieldNames` request parameters
  declared by `AdsGetRequest`: `--cpc-video-ad-builder-ad-field-names`,
  `--cpm-banner-ad-builder-ad-field-names`,
  `--cpm-video-ad-builder-ad-field-names`,
  `--dynamic-text-ad-field-names`, `--listing-ad-field-names`,
  `--mobile-app-ad-builder-ad-field-names`,
  `--mobile-app-ad-field-names`,
  `--mobile-app-cpc-video-ad-builder-ad-field-names`,
  `--mobile-app-image-ad-field-names`,
  `--responsive-ad-field-names`, `--shopping-ad-field-names`,
  `--smart-ad-builder-ad-field-names`,
  `--text-ad-builder-ad-field-names`,
  `--text-ad-field-names`,
  `--text-ad-price-extension-field-names`, and
  `--text-image-ad-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) and non-canonical
  `--text-ad-fields` were available, so the per-ad-subtype projections
  could not be controlled from CLI. Closes #406.

**BREAKING CHANGES:**

- `direct campaigns get` flags `--text-campaign-fields`,
  `--mobile-app-campaign-fields`, `--dynamic-text-campaign-fields`,
  `--cpm-banner-campaign-fields`, `--smart-campaign-fields`,
  `--unified-campaign-fields`,
  `--text-campaign-search-strategy-placement-types-fields`,
  `--dynamic-text-campaign-search-strategy-placement-types-fields`,
  `--unified-campaign-search-strategy-placement-types-fields`, and
  `--unified-campaign-package-bidding-strategy-platforms-fields`
  are **renamed** to their kebab-case WSDL-canonical `*-field-names`
  form (`--text-campaign-field-names`,
  `--mobile-app-campaign-field-names`, ...), matching the parameter
  names declared by `CampaignsGetRequest`. The old `--*-fields`
  forms are no longer accepted — update scripts and automation
  accordingly. Closes #409.

**Additional features:**

- `direct bidmodifiers get` now exposes thirteen additional
  `--*-adjustment-field-names` flags for the per-adjustment-subtype
  WSDL `*FieldNames` request parameters declared by
  `BidModifiersGetRequest`: `--ad-group-adjustment-field-names`,
  `--demographics-adjustment-field-names`,
  `--desktop-adjustment-field-names`,
  `--desktop-only-adjustment-field-names`,
  `--income-grade-adjustment-field-names`,
  `--mobile-adjustment-field-names`,
  `--regional-adjustment-field-names`,
  `--retargeting-adjustment-field-names`,
  `--serp-layout-adjustment-field-names`,
  `--smart-ad-adjustment-field-names`,
  `--smart-tv-adjustment-field-names`,
  `--tablet-adjustment-field-names`, and
  `--video-adjustment-field-names`. Previously only the top-level
  `--fields` (mapping to `FieldNames`) was available, so the
  per-adjustment projections could not be controlled from CLI.
  Closes #408.
- `direct strategies get` now exposes sixteen additional
  `--strategy-*-field-names` flags for the separate WSDL
  `*FieldNames` request parameters declared by `StrategiesGetRequest`,
  including `--strategy-average-cpa-field-names`,
  `--strategy-average-cpa-multiple-goals-field-names`,
  `--strategy-average-cpc-field-names`,
  `--strategy-maximum-clicks-field-names`,
  `--strategy-maximum-conversion-rate-field-names`,
  `--strategy-pay-for-conversion-field-names`, and the remaining
  per-campaign / per-filter strategy projections. The command also
  gains `--dry-run` for read-path payload tests. Previously only the
  top-level `--fields` (mapping to `FieldNames`) was available, so
  per-strategy-subtype projections could not be controlled from CLI.
  Closes #414.

Closes #360.

**Tests:**

- `tests/test_integration.py` now gracefully skips the seven read-only
  classes that rely on live-API probes (`TestReadOnlyAdGroups`,
  `TestReadOnlyAds`, `TestReadOnlyKeywords`,
  `TestReadOnlyDynamicFeedAdTargets`, `TestReadOnlyLeads`,
  `TestReadOnlyBusinesses`, `TestReadOnlyAdVideos`) when the probe
  raises — previously a temporary API outage crashed `setUpClass`
  with an opaque traceback.
- `invoke_get` in `tests/test_integration.py` now passes the resolved
  test credentials as explicit `--token`/`--login` flags so the
  integration suite cannot silently fall through to a developer's
  active `direct auth` profile (priority 1 in the CLI credential
  chain wins over the profile, matching CLAUDE.md guidance).
- `tests/test_comprehensive.py` slimmed down: `TestCLIHelp` (full
  duplicate of `tests/test_cli.py`) removed; the unique
  `TestCommandsRegistered`, `TestUtils`, `TestOutputFormatters`,
  `TestAuth`, and `TestErrorHandling` classes are kept.
- `tests/test_smoke_matrix.py` no longer hard-codes
  `total_cli_subcommands == 144` or `wsdl_operations == 112`. Counts
  are derived from the live Click registry and parsed WSDLs.
- `tests/test_sandbox_write_audit.py` no longer hard-codes
  `total == 83`. The count derives from `commands_for_category`.

Closes #396.

## 0.3.13

**Breaking changes:**

- `direct campaigns add` and `direct campaigns update` now require all
  bidding-strategy money flags to be passed directly in micro-rubles,
  matching the existing `--budget`, `--average-cpa`, `--bid-ceiling`, and
  `--filter-average-cpc` contract. The CLI no longer accepts decimal currency
  values or performs unit conversion for campaign money
  inputs. Closes #399.
- `direct ads add` and `direct ads update` now apply the same API-native
  micro-ruble contract to `--price-extension-price` and
  `--price-extension-old-price`; price-extension values are no longer parsed
  as decimal currency amounts.

## 0.3.12

**Added:**

- `direct ads update` now exposes `--callouts-add`, `--callouts-remove`,
  and `--callouts-set` for managing the
  `TextAdUpdateBase.CalloutSetting` field
  (`ext:AdExtensionSetting`). Each flag accepts a comma-separated list
  of `CALLOUT`-type ad-extension IDs; `--callouts-set` replaces the
  full callout list and is mutually exclusive with the incremental
  `--callouts-add` / `--callouts-remove` pair (enforced via
  `click.UsageError` before any request is built). Flags are
  TEXT_AD-only — per-subtype validation rejects them on `TEXT_IMAGE_AD`
  / `MOBILE_APP_AD` with the standard "not compatible with --type"
  message. Empty CSV input is rejected up-front rather than silently
  producing a no-op payload. Closes #238.
- `direct adgroups add` and `direct adgroups update` now expose
  `--tracking-params` for the top-level `AdGroup*.TrackingParams`
  field. Values are limited to the documented 1024-character maximum;
  `update` does not require `--type` because the field belongs to the
  ad group item itself, not a subtype block. Closes #242.
- `direct adgroups add` and `direct adgroups update` now expose
  `--negative-keywords` and `--negative-keyword-shared-set-ids` for
  `NegativeKeywords.Items` and `NegativeKeywordSharedSetIds.Items`.
  Empty list input is rejected, shared-set IDs are parsed as integers,
  and `update` treats either flag as a meaningful field for the
  no-op guard. Closes #243.
- `direct ads update --type TEXT_AD` now exposes
  `--video-extension-creative-id` for `TextAd.VideoExtension.CreativeId`
  and `--price-extension-price`, `--price-extension-old-price`,
  `--price-extension-price-qualifier`, and
  `--price-extension-price-currency` for `TextAd.PriceExtension`.
  These flags are TEXT_AD-only and are rejected on other ad subtypes
  before any request is built. Closes #245.
- `direct vcards add` now exposes `--instant-messenger-client` and
  `--instant-messenger-login` for `InstantMessenger.MessengerClient`
  and `InstantMessenger.MessengerLogin`, plus the six
  `--point-on-map-*` coordinate flags for `PointOnMap`. Partial
  `InstantMessenger` or `PointOnMap` input is rejected with
  `click.UsageError` so required nested WSDL fields are not omitted.
  Closes #246.
- `direct feeds add` and `direct feeds update` now expose
  `--remove-utm-tags`, `--feed-login`, and `--feed-password` for
  `UrlFeed.RemoveUtmTags`, `UrlFeed.Login`, and `UrlFeed.Password`.
  `feeds update` also exposes `--clear-feed-login` and
  `--clear-feed-password` for the nillable credential fields, with
  mutual-exclusion checks against the corresponding set flags.
  `FileFeed` upload/base64 support was split to follow-up #264.
  Closes #253.
- `direct retargeting add` and `direct retargeting update` now expose
  `--description` for the optional retargeting-list `Description`
  field. Description input is validated against the documented maximum
  length before building the request, and update-only description
  changes satisfy the no-op guard. Closes #256.
- `direct sitelinks add` now supports `TurboPageId` for
  `SitelinkAddItem.TurboPageId` through the canonical `--sitelink`
  pipe spec by accepting an optional fourth segment after
  `Title|Href|Description`. Rows must provide either `Href` or
  `TurboPageId`, so Turbo-only sitelinks are accepted without relaxing
  empty-row validation. Closes #257.

**Changed:**

- WSDL parity now includes a soft optional-field audit for issue #239.
  `scripts/build_wsdl_optional_field_audit.py --check` regenerates and
  compares `tests/WSDL_OPTIONAL_FIELD_AUDIT.md`, covering cached mutating
  WSDL item fields at unbounded nesting depth. Confirmed `minOccurs=0`
  gaps are tracked as linked `missing_followup` rows instead of being
  invisible to the required-field gate.

## 0.3.11

**Added:**

- `direct campaigns add` and `direct campaigns update` now expose
  `--tracking-params` for the campaign-level tracking query string
  (`TextCampaign` / `DynamicTextCampaign` / `SmartCampaign` `.TrackingParams`).
  `campaigns update` gained an optional `--type` discriminator —
  required when `--tracking-params` is set, validated against
  the three subtypes supported by the CLI. Backward compatible:
  existing `campaigns update --id N --name X` calls without `--type`
  keep working unchanged. Closes #230.
- `direct v4account account-management` now supports `--action Get`,
  `Deposit`, `Invoice`, and `TransferMoney` in addition to `Update`,
  matching the official v4 Live docs
  (<https://yandex.ru/dev/direct/doc/dg-v4/reference/AccountManagement-docpage/>).
  `Get` is read-only and accepts optional `--logins` / `--account-ids`
  filters. `Deposit`, `Invoice`, and `TransferMoney` are financial
  mutations: they need `--finance-token` (or `--master-token` +
  `--operation-num` + `--finance-login`) and respect the existing
  dry-run-unless-sandbox rule. A Click-side allow-list rejects flags
  that do not belong to the chosen action before any body is built.
  Refs #125.

**Fixed:**

- `direct v4 *` command wrappers now let `click.ClickException`
  (including `UsageError` from `call_v4` shape validation) propagate to
  Click instead of swallowing it in the generic `except Exception`.
  Shape-validation errors keep their usage hint and exit with code 2,
  matching Click's contract; non-Click runtime errors still surface
  through `print_error` + `Abort` (exit 1). Closes #227.

**Breaking changes:**

- `direct v4finance get-credit-limits` no longer accepts `--logins`; the
  request body now omits `param` per the official v4 Live docs
  (<https://yandex.ru/dev/direct/doc/dg-v4/reference/GetCreditLimits.html>),
  which define the body as `method`, `finance_token`, and `operation_num`
  only. Refs #125.

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

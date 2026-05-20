# Issue #198 Mutating WSDL Audit

Date: 2026-05-20
Branch: `codex/reopen-198-full-mutating-audit`
Base observed before work: `main` at `8f2a9e3` or newer

## Scope

This pass treats `#198` as incomplete until the full current
`direct_cli.smoke_matrix.WRITE_SANDBOX` surface is accounted for:

- 83 write-class commands total.
- 32 v5 `add` / `update` / `set` commands covered by
  `tests/test_wsdl_parity_gate.py::COMMAND_WSDL_MAP`.
- 43 v5 lifecycle / other write commands covered by dry-run payload fixtures or
  focused dry-run tests.
- 8 v4 write-class commands checked against `direct_cli/v4_contracts.py` and
  focused v4 tests, not v5 WSDL.

The old "7 Med + 4 Low" table could not be recovered from the repo, GitHub
issue text, or targeted local transcript search available in this workspace.
This artifact therefore records a fresh regenerated audit against cached WSDL,
current CLI code, and dry-run payload evidence. The confirmed remaining tail
from that pass is tracked here as `#198/#210` subtype compatibility plus the
`smartadtargets` gate-map gap found while building this table.

## Confirmed Findings Fixed In This Pass

- `campaigns add`: reject smart-only flags on non-smart campaign types and
  reject `--filter-average-cpc` unless the smart network strategy is
  `AVERAGE_CPC_PER_FILTER`.
- `adgroups add`: reject dynamic/smart subtype flags when `--type` selects a
  different WSDL subtype.
- `ads add`: preserve WSDL-valid `TextAd.AdImageHash` and reject incompatible
  subtype flags instead of silently dropping them.
- `bidmodifiers add`: reject incompatible extra flags, emit
  `IncomeGradeAdjustments[].Grade`, and expose WSDL `SmartTvAdjustment`.
- `bidmodifiers set`: reject the legacy `CampaignId + Type + BidModifier`
  shape locally; WSDL `BidModifierSetItem` supports only `Id + BidModifier`.
- `strategies add/update`: validate typed strategy flags against the selected
  WSDL subtype. `--spend-limit` is rejected for now because WSDL exposes that
  value only inside `CustomPeriodBudget`, which also requires dates and
  `AutoContinue`.
- `smartadtargets add/update`: fix the parity gate map from the stale
  `Webpages` container to the actual `SmartAdTargets` WSDL container.

## Audit Table

| command | API/WSDL operation | request shape | CLI flags checked | dry-run evidence | verdict | issue/fix PR |
|---|---|---|---|---|---|---|
| adextensions.add | adextensions.add | params.AdExtensions[] | --callout-text | PAYLOAD_CASES dry-run: method=add; params=AdExtensions | pass: no confirmed Med/Low drift in this pass | n/a |
| adextensions.delete | adextensions.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| adgroups.add | adgroups.add | params.AdGroups[] | --campaign-id --name --type --domain-url --region-ids | PAYLOAD_CASES dry-run: method=add; params=AdGroups | fixed: subtype flag validation (#198/#210) | this PR |
| adgroups.delete | adgroups.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| adgroups.update | adgroups.update | params.AdGroups[] | --id --name --region-ids | PAYLOAD_CASES dry-run: method=update; params=AdGroups | pass: no confirmed Med/Low drift in this pass | n/a |
| adimages.add | adimages.add | params.AdImages[] | --name --image-data | PAYLOAD_CASES dry-run: method=add; params=AdImages | pass: no confirmed Med/Low drift in this pass | n/a |
| adimages.delete | adimages.delete | params.SelectionCriteria.Ids[] | --hash | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.add | ads.add | params.Ads[] | --adgroup-id --type --title --text --action | PAYLOAD_CASES dry-run: method=add; params=Ads | fixed: TextAd.AdImageHash + subtype validation (#198/#210) | this PR |
| ads.archive | ads.archive | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=archive; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.delete | ads.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.moderate | ads.moderate | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=moderate; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.resume | ads.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.suspend | ads.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.unarchive | ads.unarchive | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=unarchive; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| ads.update | ads.update | params.Ads[] | --id --type --title --text --href | PAYLOAD_CASES dry-run: method=update; params=Ads | pass: prior #212 + expanded subtype gate | this PR |
| advideos.add | advideos.add | params.AdVideos[] | --url --name | PAYLOAD_CASES dry-run: method=add; params=AdVideos | pass: no confirmed Med/Low drift in this pass | n/a |
| audiencetargets.add | audiencetargets.add | params.AudienceTargets[] | --adgroup-id --retargeting-list-id --bid --priority | PAYLOAD_CASES dry-run: method=add; params=AudienceTargets | pass: no confirmed Med/Low drift in this pass | n/a |
| audiencetargets.delete | audiencetargets.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| audiencetargets.resume | audiencetargets.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| audiencetargets.set-bids | audiencetargets.setBids | typed setter array/criteria per dry-run fixture | --id --context-bid --priority | PAYLOAD_CASES dry-run: method=setBids; params=Bids | pass: no confirmed Med/Low drift in this pass | n/a |
| audiencetargets.suspend | audiencetargets.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| bidmodifiers.add | bidmodifiers.add | params.BidModifiers[] | --campaign-id --type --value | PAYLOAD_CASES dry-run: method=add; params=BidModifiers | fixed: extra-flag validation, Grade, SmartTvAdjustment (#198/#210) | this PR |
| bidmodifiers.delete | bidmodifiers.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| bidmodifiers.set | bidmodifiers.set | params.BidModifiers[] | --id --value | PAYLOAD_CASES dry-run: method=set; params=BidModifiers | fixed: legacy CampaignId+Type shape rejected (#198/#210) | this PR |
| bids.set | bids.set | params.Bids[] | --keyword-id --bid | PAYLOAD_CASES dry-run: method=set; params=Bids | pass: no confirmed Med/Low drift in this pass | n/a |
| bids.set-auto | bids.setAuto | typed setter array/criteria per dry-run fixture | --keyword-id --max-bid --position --scope | PAYLOAD_CASES dry-run: method=setAuto; params=Bids | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.add | campaigns.add | params.Campaigns[] | --name --start-date --type --budget --search-strategy --network-strategy --setting | PAYLOAD_CASES dry-run: method=add; params=Campaigns | fixed: subtype flag validation (#198/#210) | this PR |
| campaigns.archive | campaigns.archive | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=archive; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.delete | campaigns.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.resume | campaigns.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.suspend | campaigns.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.unarchive | campaigns.unarchive | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=unarchive; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| campaigns.update | campaigns.update | params.Campaigns[] | --id --name --budget --end-date | PAYLOAD_CASES dry-run: method=update; params=Campaigns | pass: no confirmed Med/Low drift in this pass | n/a |
| clients.update | clients.update | params.Clients[] | --client-info --phone --notification-email --notification-lang --email-subscription --setting --tin-type --tin | PAYLOAD_CASES dry-run: method=update; params=Clients | pass: no confirmed Med/Low drift in this pass | n/a |
| creatives.add | creatives.add | params.Creatives[] | --video-id | PAYLOAD_CASES dry-run: method=add; params=Creatives | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicads.add | dynamictextadtargets.add | params.Webpages[] | --adgroup-id --name --condition --bid --context-bid --priority | PAYLOAD_CASES dry-run: method=add; params=Webpages | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicads.delete | dynamicads.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicads.resume | dynamicads.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicads.set-bids | dynamicads.setBids | typed setter array/criteria per dry-run fixture | --id --bid --context-bid --priority | PAYLOAD_CASES dry-run: method=setBids; params=Bids | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicads.suspend | dynamicads.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicfeedadtargets.add | dynamicfeedadtargets.add | params.DynamicFeedAdTargets[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_dynamicfeedadtargets_add_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicfeedadtargets.delete | dynamicfeedadtargets.delete | params.SelectionCriteria.Ids[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_dynamicfeedadtargets_delete_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicfeedadtargets.resume | dynamicfeedadtargets.resume | params.SelectionCriteria.Ids[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_dynamicfeedadtargets_resume_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicfeedadtargets.set-bids | dynamicfeedadtargets.setBids | typed setter array/criteria per dry-run fixture | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_dynamicfeedadtargets_set_bids_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| dynamicfeedadtargets.suspend | dynamicfeedadtargets.suspend | params.SelectionCriteria.Ids[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_dynamicfeedadtargets_suspend_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| feeds.add | feeds.add | params.Feeds[] | --name --url --business-type | PAYLOAD_CASES dry-run: method=add; params=Feeds | pass: no confirmed Med/Low drift in this pass | n/a |
| feeds.delete | feeds.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| feeds.update | feeds.update | params.Feeds[] | --id --name | PAYLOAD_CASES dry-run: method=update; params=Feeds | pass: no confirmed Med/Low drift in this pass | n/a |
| keywordbids.set | keywordbids.set | params.KeywordBids[] | --keyword-id --search-bid --network-bid | PAYLOAD_CASES dry-run: method=set; params=KeywordBids | pass: no confirmed Med/Low drift in this pass | n/a |
| keywordbids.set-auto | keywordbids.setAuto | typed setter array/criteria per dry-run fixture | --keyword-id --target-traffic-volume --increase-percent --bid-ceiling | PAYLOAD_CASES dry-run: method=setAuto; params=KeywordBids | pass: no confirmed Med/Low drift in this pass | n/a |
| keywords.add | keywords.add | params.Keywords[] | --adgroup-id --keyword --bid --context-bid --user-param-1 --user-param-2 | PAYLOAD_CASES dry-run: method=add; params=Keywords | pass: no confirmed Med/Low drift in this pass | n/a |
| keywords.delete | keywords.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| keywords.resume | keywords.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| keywords.suspend | keywords.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| keywords.update | keywords.update | params.Keywords[] | --id --keyword --user-param-1 --user-param-2 | PAYLOAD_CASES dry-run: method=update; params=Keywords | pass: no confirmed Med/Low drift in this pass | n/a |
| negativekeywordsharedsets.add | negativekeywordsharedsets.add | params.NegativeKeywordSharedSets[] | --name --keywords | PAYLOAD_CASES dry-run: method=add; params=NegativeKeywordSharedSets | pass: no confirmed Med/Low drift in this pass | n/a |
| negativekeywordsharedsets.delete | negativekeywordsharedsets.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| negativekeywordsharedsets.update | negativekeywordsharedsets.update | params.NegativeKeywordSharedSets[] | --id --keywords | PAYLOAD_CASES dry-run: method=update; params=NegativeKeywordSharedSets | pass: no confirmed Med/Low drift in this pass | n/a |
| retargeting.add | retargetinglists.add | params.RetargetingLists[] | --name --type --rule | PAYLOAD_CASES dry-run: method=add; params=RetargetingLists | pass: no confirmed Med/Low drift in this pass | n/a |
| retargeting.delete | retargeting.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| retargeting.update | retargetinglists.update | params.RetargetingLists[] | --id --name --rule | PAYLOAD_CASES dry-run: method=update; params=RetargetingLists | pass: no confirmed Med/Low drift in this pass | n/a |
| sitelinks.add | sitelinks.add | params.SitelinksSets[] | --sitelink | PAYLOAD_CASES dry-run: method=add; params=SitelinksSets | pass: no confirmed Med/Low drift in this pass | n/a |
| sitelinks.delete | sitelinks.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| smartadtargets.add | smartadtargets.add | params.SmartAdTargets[] | --adgroup-id --name --audience --condition --average-cpc --priority | PAYLOAD_CASES dry-run: method=add; params=SmartAdTargets | fixed gate map: SmartAdTargets container checked (#198) | this PR |
| smartadtargets.delete | smartadtargets.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| smartadtargets.resume | smartadtargets.resume | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=resume; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| smartadtargets.set-bids | smartadtargets.setBids | typed setter array/criteria per dry-run fixture | --id --average-cpc --average-cpa --priority | PAYLOAD_CASES dry-run: method=setBids; params=Bids | pass: no confirmed Med/Low drift in this pass | n/a |
| smartadtargets.suspend | smartadtargets.suspend | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=suspend; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |
| smartadtargets.update | smartadtargets.update | params.SmartAdTargets[] | --id --name --average-cpc --priority | PAYLOAD_CASES dry-run: method=update; params=SmartAdTargets | fixed gate map: SmartAdTargets container checked (#198) | this PR |
| strategies.add | strategies.add | params.Strategies[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_strategies_add_payload. | fixed: WSDL field allow-list, no raw SpendLimit (#198/#210) | this PR |
| strategies.archive | strategies.archive | params.SelectionCriteria.Ids[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_strategies_archive_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| strategies.unarchive | strategies.unarchive | params.SelectionCriteria.Ids[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_strategies_unarchive_payload. | pass: no confirmed Med/Low drift in this pass | n/a |
| strategies.update | strategies.update | params.Strategies[] | focused dry-run/v4 test flags | Covered by test_dry_run.py::test_strategies_update_payload. | fixed: WSDL update field allow-list (#198/#210) | this PR |
| v4account.account-management | v4_contracts.py / accountManagement | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4account.enable-shared-account | v4_contracts.py / enableSharedAccount | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4forecast.create | v4_contracts.py / create | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4forecast.delete | v4_contracts.py / delete | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4tags.update-banners | v4_contracts.py / updateBanners | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4tags.update-campaigns | v4_contracts.py / updateCampaigns | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4wordstat.create-report | v4_contracts.py / createReport | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| v4wordstat.delete-report | v4_contracts.py / deleteReport | V4 Live request contract; dry-run only for write-class commands | typed v4 flags in focused v4 tests | tests/test_v4_* + DRY_RUN_PAYLOAD_EXCLUSIONS | pass: v4 contract, out of v5 WSDL | n/a |
| vcards.add | vcards.add | params.VCards[] | --campaign-id --country --city --company-name --work-time --phone-country-code --phone-city-code --phone-number | PAYLOAD_CASES dry-run: method=add; params=VCards | pass: no confirmed Med/Low drift in this pass | n/a |
| vcards.delete | vcards.delete | params.SelectionCriteria.Ids[] | --id | PAYLOAD_CASES dry-run: method=delete; params=SelectionCriteria | pass: no confirmed Med/Low drift in this pass | n/a |

## Verification Log

- `python3 -m pytest tests/test_wsdl_parity_gate.py -q`: 46 passed, 6 skipped.
- `python3 -m pytest tests/test_dry_run.py tests/test_low_coverage_payloads.py tests/test_api_coverage.py tests/test_smoke_matrix.py -q`: 355 passed.
- `python3 -m pytest -m "not integration"`: 760 passed, 44 skipped, 32 deselected.
- `python3 scripts/build_api_coverage_report.py > /tmp/api_coverage_report.json`:
  `summary.schema_parity_ok == true`; `schema.nested_schema_violations == []`.
- `python3 -m ruff check .`: pass.
- `mypy .`: pass.
- `git diff --check`: pass.
- `python3 -m black --check` on changed Python files: pass.
- `python3 scripts/sandbox_write_audit.py --json-output /tmp/sandbox_audit.json`:
  83 WRITE_SANDBOX rows audited; live-runner static coverage has 80 PASS and
  3 NOT_COVERED rows tracked separately in `#213`.

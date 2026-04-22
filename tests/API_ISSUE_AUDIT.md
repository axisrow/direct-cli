# API Issue Audit

This document tracks issue-level API status evidence for Direct CLI coverage
planning. It exists to prevent stale issue assumptions from becoming release
blockers after Yandex changes, removes, or deprecates an API method.

## Audit Rules

Use this checklist before moving any API-related issue into a milestone or
counting it as a missing command.

1. Read the open issue, comments, linked closed issues, and linked PRs.
2. Identify every referenced `service.method` and CLI command.
3. Check the live WSDL at `https://api.direct.yandex.com/v5/{service}?wsdl`.
4. Check the cached WSDL in `tests/wsdl_cache/`.
5. Check the official Yandex service page and changelog.
6. Classify the issue as one of:
   - `supported`
   - `deprecated`
   - `removed`
   - `not-in-wsdl`
   - `sandbox-limited`
   - `docs-drift`
   - `unknown`
7. Choose one action:
   - implement
   - fix payload or method name
   - document unsupported
   - close obsolete
   - split issue
   - needs live probe

Official docs and changelog have priority over old issue text. Live WSDL has
priority for WSDL-backed services. If docs and WSDL disagree, classify the item
as `docs-drift` and do not treat it as an implementation blocker until the
status is resolved.

## Current Audit Register

| Issue | API surface | Official status | Evidence | Recommended action |
|---|---|---|---|---|
| #33 | `bidmodifiers.toggle` / historical `direct bidmodifiers toggle` | `deprecated`, `not-in-wsdl` | Official BidModifiers page lists only `add`, `delete`, `get`, `set` and says `toggle` is no longer supported since 2025-11-13; official changelog says the same; live WSDL has no `toggle`; live prod/sandbox calls returned error 55 in #33/#31 | Close as obsolete implementation task; document unsupported; do not count as missing 0.3.0 coverage |
| #31 | `bidmodifiers.toggle` cassette | `deprecated`, `not-in-wsdl`, historical `sandbox-limited` evidence | Closed issue contains sandbox error 55 and stale cassette context; now superseded by official deprecation evidence | Keep closed as evidence linked from #33/#41 |
| #30 | `bidmodifiers.toggle` fix assumption | superseded by `deprecated`, `not-in-wsdl` | Closed issue and PR #29 assumed the documented `toggle` method was still valid; later #31/#33 plus official docs/changelog invalidate that assumption | Keep closed; do not use as current implementation guidance |
| #35 | `keywordsresearch.hasSearchVolume`, `keywordsresearch.deduplicate` | `supported` | Cached WSDL declares camelCase operations; issue points to wrong PascalCase request body methods | Keep as real implementation blocker: fix wire method names and add request-body assertions |
| #54 | Live-discovered model gaps | `supported` coverage tooling | Live-discovered WSDL services include `dynamicfeedadtargets` and `strategies`; not represented in declared model yet | Keep as coverage/reporting work |
| #55 | 0.3.0 release gate | tracking | Release gate must distinguish supported API gaps from deprecated/removed methods | Update gate language: deprecated/removed/not-in-WSDL operations are exclusions only when evidence is recorded here |
| #28 | Write integration gaps | mixed | 7 Category-A classes (codes 8800/1000/5004, live-API candidates via #56 live tier) + 2 Category-B classes (code 3500, sandbox-structural); each class carries `@pytest.mark.sandbox_limitation(category=...)`; split documented in `API_COVERAGE.md` "Sandbox Category Split" section | Resolved: category split codified in `tests/test_integration_write.py`; periodic sandbox recheck via `pytest -m integration_write --record-mode=rewrite` per release |
| #56 | Live API draft campaign lifecycle (opt-in) | `supported` | `tests/test_integration_live_write.py` + cassette `test_live_draft_campaign_create_get_delete.yaml`; guarded by `YANDEX_DIRECT_LIVE_WRITE=1`; mirrored as `TestWriteCampaignDraftLifecycle` in sandbox suite | Resolved: live-write root fixture in place; follow-up live-write expansion tracked as separate future issues |
| #41 | Broader coverage matrix | tracking | Needs explicit API status categories to avoid repeating #33 | Link to this audit and require evidence-backed status for every ambiguous command |
| #69 | `adgroups.suspend/resume`, `audiencetargets.update`, `dynamicads.update`, `dynamicfeedadtargets`, `bidmodifiers.toggle` | mixed: unsupported methods + one transport mapping gap | Live API routing returned error 55 for unsupported methods; WSDL confirms no `adgroups.suspend/resume`, no `audiencetargets.update`, no `dynamictextadtargets.update`, and no `bidmodifiers.toggle`; `dynamicfeedadtargets` exists in live API/WSDL and was missing from the `axisrow/tapi-yandex-direct` transport mapping | Do not add unsupported CLI commands; fix `axisrow/tapi-yandex-direct` mapping/extraction for `dynamicfeedadtargets`, pin direct-cli to the fixed fork revision, and close after regression coverage |
| #49 | `direct auth_login` | out of API surface | OAuth CLI UX issue, not a Yandex Direct resource method | Keep outside API method coverage audit unless it references Yandex OAuth deprecation/status changes |
| #44 | Canonical CLI contract docs/tests | out of API surface | Documentation/test contract work; no specific Yandex API method status claim | Keep milestone planning separate from API support classification |
| #42 | Canonical naming convention | out of API surface | CLI naming policy; no specific Yandex API method status claim | Keep milestone planning separate from API support classification |

## Official References

- BidModifiers service page: `https://yandex.ru/dev/direct/doc/en/bidmodifiers/bidmodifiers`
- API v5 changelog: `https://yandex.ru/dev/direct/doc/en/changelog`
- Russian changelog mirror: `https://yandex.ru/dev/direct/doc/ru/changelog`

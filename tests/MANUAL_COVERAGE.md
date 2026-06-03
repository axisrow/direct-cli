# Manual-Only Coverage Gaps

Commands that cannot be covered by automated tests due to side effects,
account requirements, or external dependencies.

## Irreversible Operations

- **ads moderate** — submits ads for moderation; cannot be undone. A
  smoke-test would leave real ads in a moderation queue.
- **campaigns/ads suspend/resume/archive/unarchive on ACCEPTED
  objects** — changes live traffic. Live-write tests only exercise these
  on DRAFT-state objects (Sandbox Limitation category A).

## Account-Scoped Operations

- **agencyclients add/update/delete** — requires an agency-type account.
  Non-agency accounts receive 403. The current sandbox agency account can
  read agency clients, but creation returns error 3001: "No rights to create
  clients".
- **agencyclients add-passport-organization** — creates a real Passport
  organization linked to the account. The current sandbox agency account is
  sandbox-limited for this operation with error 3001.
- **agencyclients add-passport-organization-member** — sends an invitation
  email to an external user.

## Financial Operations

- **bids set** / **keywordbids set** / **bidmodifiers set** on existing
  non-draft objects — spends real budget. Live-write tests only verify
  request assembly via `--dry-run`.
- **v4finance create/pay/transfer operations** — `CreateInvoice`,
  `PayCampaigns`, and `TransferMoney` are financial side-effect operations.
  `TransferMoney` and `PayCampaigns` remain dry-run-only in the public CLI.
  `CreateInvoice` is exposed with typed `--payment CAMPAIGN_ID=AMOUNT` flags
  and is live-capable when `--dry-run` is omitted. The live write test is
  guarded by `YANDEX_DIRECT_LIVE_FINANCE_WRITE=1`,
  `YANDEX_DIRECT_TEST_CAMPAIGN_ID`, financial credentials, and
  `YANDEX_DIRECT_OPERATION_NUM`; without financial credentials sandbox returns
  `error_code=350 Invalid financial transaction token`.
- **v4finance check-payment** — read-only. Official public docs were not found;
  sandbox v4 Live confirms `CustomTransactionID` (32 latin alphanumeric
  characters), not `PaymentID`. A dummy valid transaction ID returns
  `error_code=370 Transaction does not exist`, which is accepted as request
  shape proof.

## Campaign-Type Restrictions (Category B)

Some campaign types are only available on agency or pilot accounts.
Live tests skip gracefully when the API returns error 3500.

- **DYNAMIC_TEXT_CAMPAIGN** — `dynamicads` add/update/delete/suspend/resume
  require an account where DYNAMIC_TEXT_CAMPAIGN is enabled. Standard
  advertiser accounts receive 3500.
- **SMART_CAMPAIGN** — `smartadtargets` add/update/delete/suspend/resume
  require SMART_CAMPAIGN support. Standard accounts receive 3500.

## Audience Target Restrictions (Category A)

- **audiencetargets add/suspend/resume** — requires an adgroup that is
  visible in the `audiencetargets` context. On some accounts, adgroups
  created in draft campaigns return 8800 (Object not found). Live tests
  skip gracefully on 8800.

## Ad Image Restrictions (Category A)

- **adimages add** — some accounts reject PNG uploads with error 5004
  (Invalid image file type). Live tests skip gracefully on 5004.

## External Dependencies

- **advideos add** — requires a valid, publicly accessible video URL. The
  Yandex API rejects placeholder URLs (e.g. `example.com`). A real video
  must be hosted externally; this cannot be automated. No cleanup possible
  via CLI — `advideos` has no `delete` subcommand.
- **creatives add** — depends on a valid `video_id` from `advideos add`,
  so it inherits the same limitation.

## Sandbox-Unreachable, Covered Live (Phase 6)

These mutating commands cannot run in the sandbox (it returns 8800/6000) but
are exercised against the live draft API in `test_v5_live_write.py`. Notes
captured while recording the cassettes — re-recording must honour them:

- **feeds add/update/delete** — sandbox rejects `feeds update` (8800); live
  records the full lifecycle. Standard URL feed, no external dependency, fully
  reversible (delete removes the feed).
- **retargeting add/update/delete** — a `RETARGETING` rule argument needs a
  Metrica goal id **_and_ a MembershipLifeSpan** (`--rule ALL:<goal>:<days>`);
  a bare `ALL:<goal>` is rejected with error 5000 ("Not specified time for goal
  or segment"). The test uses a **synthetic placeholder goal** (`ALL:12345:30`,
  the same convention as the audiencetargets smoke tests) — no real account goal
  id is ever hardcoded — so the live API returns 8800 ("Object not found") and
  the test skips. Records the request shape, not a passing lifecycle.
- **strategies add/update/archive/unarchive** — a shared strategy must be made
  public, which requires a shared-account wallet; accounts without one are
  rejected with error 6000 and the test skips. **The Yandex Direct API has no
  `Strategies.delete` operation** (the service exposes only add/update/get/
  archive/unarchive), so a strategy created by the test cannot be removed via
  the API — cleanup archives it (`StatusArchived=YES`, non-serving). On an
  account with a wallet the test leaves one archived strategy behind; this is
  an API limitation, not a test defect.

## Summary

| Command | Reason | Risk |
|---|---|---|
| ads moderate | Irreversible | Moderate |
| campaigns/ads suspend/resume (live) | Traffic impact | High |
| agencyclients add/update/delete | Account type / sandbox rights (403 or 3001) | None (skip) |
| agencyclients add-passport-organization* | External state / sandbox rights (3001) | Moderate |
| bids/keywordbids/bidmodifiers set | Financial | High |
| dynamicads (all) | Account type (3500) | None (skip) |
| smartadtargets (all) | Account type (3500) | None (skip) |
| audiencetargets add/suspend/resume | Account restriction (8800) | None (skip) |
| adimages add | Account restriction (5004) | None (skip) |
| advideos add | External URL required | None (skip) |
| creatives add | Depends on advideos | None (skip) |

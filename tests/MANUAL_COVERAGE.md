# Manual-Only Coverage Gaps

Commands that cannot be covered by automated tests due to side effects,
account requirements, or external dependencies.

## Irreversible Operations

- **ads moderate** — submits ads for moderation; cannot be undone. A
  smoke-test would leave real ads in a moderation queue.
- **campaigns/ads/keywords suspend/resume/archive/unarchive on ACCEPTED
  objects** — changes live traffic. Live-write tests only exercise these
  on DRAFT-state objects (Sandbox Limitation category A).

## Account-Scoped Operations

- **agencyclients add/update/delete** — requires an agency-type account.
  Non-agency accounts receive 403.
- **agencyclients add-passport-organization** — creates a real Passport
  organization linked to the account.
- **agencyclients add-passport-organization-member** — sends an invitation
  email to an external user.

## Financial Operations

- **bids set** / **keywordbids set** / **bidmodifiers set** on existing
  non-draft objects — spends real budget. Live-write tests only verify
  request assembly via `--dry-run`.

## External Dependencies

- **advideos add** — requires a valid, publicly accessible video URL. The
  Yandex API rejects placeholder URLs (e.g. `example.com`). A real video
  must be hosted externally; this cannot be automated.
- **creatives add** — depends on a valid `video_id` from `advideos add`,
  so it inherits the same limitation.

## Summary

| Command | Reason | Risk |
|---|---|---|
| ads moderate | Irreversible | Moderate |
| campaigns/ads suspend/resume (live) | Traffic impact | High |
| agencyclients add/update/delete | Account type | None (403) |
| agencyclients add-passport-organization* | External state | Moderate |
| bids/keywordbids/bidmodifiers set | Financial | High |
| advideos add | External URL required | None (skip) |
| creatives add | Depends on advideos | None (skip) |

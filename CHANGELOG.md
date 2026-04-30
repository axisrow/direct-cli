# Changelog

## 0.3.3

**BREAKING CHANGE:** OAuth profiles created before 0.3.3 (without `refresh_token` and `expires_at`) are no longer accepted. Any such profile will fail immediately with an "incomplete profile" error. Run `direct auth login --profile <name>` to re-authenticate and create a valid 0.3.3 profile.

- Added refresh token persistence for OAuth profiles.
- Added automatic OAuth access token refresh before expiry.
- Added `expires_in` details to `direct auth status`.
- Added JSON output for `direct auth status`.
- Kept `direct auth login --oauth-token` as a manual access-token import without auto-refresh.

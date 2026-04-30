# Changelog

## 0.3.3

- Added refresh token persistence for OAuth profiles.
- Added automatic OAuth access token refresh before expiry.
- Added `expires_in` details to `direct auth status`.
- Added JSON output for `direct auth status`.
- Kept `direct auth login --oauth-token` as a manual access-token import without auto-refresh.

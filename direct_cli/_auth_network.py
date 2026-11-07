"""Network operations for Direct CLI authentication (epic #961, track 6).

Yandex OAuth (PKCE, authorize URL, code exchange, refresh) and the
best-effort login-resolution calls. Disk persistence lives in
:mod:`direct_cli._auth_store`; credential-source selection in
:mod:`direct_cli.auth` (the facade re-exports every name below).
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ._auth_hints import HINT_LOGIN_API
from ._auth_store import (
    DEFAULT_OAUTH_CLIENT_ID,
    load_auth_store,
    save_auth_store,
)

YANDEX_OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"


OAUTH_REFRESH_SKEW_SECONDS = 60


# Hard ceiling for the best-effort client-login resolution network call so it
# can never hang the credential-resolution path (see #480 follow-up).
LOGIN_RESOLVE_TIMEOUT_SECONDS = 8


def _b64_url_nopad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_pkce_pair() -> Tuple[str, str]:
    """Create (verifier, challenge) for OAuth PKCE."""
    verifier = _b64_url_nopad(secrets.token_bytes(32))
    challenge = _b64_url_nopad(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_oauth_authorize_url(
    client_id: str,
    code_challenge: Optional[str] = None,
) -> str:
    """Build Yandex OAuth authorize URL."""
    query: Dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
    }
    if code_challenge:
        query["code_challenge_method"] = "S256"
        query["code_challenge"] = code_challenge
    return f"{YANDEX_OAUTH_AUTHORIZE_URL}?{urllib.parse.urlencode(query)}"


def exchange_oauth_code(
    code: str,
    client_id: str = DEFAULT_OAUTH_CLIENT_ID,
    client_secret: Optional[str] = None,
    code_verifier: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchange OAuth authorization code for access token."""
    payload: Dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    if code_verifier:
        payload["code_verifier"] = code_verifier

    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        YANDEX_OAUTH_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"OAuth token request failed with HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise RuntimeError("OAuth token request timed out") from error
        raise RuntimeError(f"OAuth token request failed: {error.reason}") from error

    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("OAuth token response does not contain access_token")
    refresh_token = result.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("OAuth token response does not contain refresh_token")
    expires_in = result.get("expires_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise RuntimeError("OAuth token response does not contain expires_in")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": expires_in,
    }


def _oauth_profile_incomplete_error(profile: str) -> ValueError:
    return ValueError(
        f"OAuth profile '{profile}' is incomplete. "
        f"Run {HINT_LOGIN_API} --profile {profile} again."
    )


def validate_oauth_profile(profile: str, data: Dict[str, Any]) -> None:
    refresh_token = data.get("refresh_token")
    expires_at = data.get("expires_at")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise _oauth_profile_incomplete_error(profile)
    if not isinstance(expires_at, (int, float)):
        raise _oauth_profile_incomplete_error(profile)


def refresh_access_token(profile: str, path: Optional[Path] = None) -> Dict[str, Any]:
    """Refresh and persist an OAuth profile access token."""
    store = load_auth_store(path=path)
    profiles = store["profiles"]
    item = profiles.get(profile)
    if not isinstance(item, dict):
        raise ValueError(f"Profile '{profile}' is not configured.")
    validate_oauth_profile(profile, item)

    refresh_token = item["refresh_token"]
    client_id = item.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        client_id = DEFAULT_OAUTH_CLIENT_ID
    client_secret = item.get("client_secret")

    payload: Dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    }
    if isinstance(client_secret, str) and client_secret:
        payload["client_secret"] = client_secret
    body = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        YANDEX_OAUTH_TOKEN_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in (400, 401):
            # Concurrent-refresh race: another process may have just rotated
            # the token. Re-read the store and, if a fresher access token is
            # already on disk, return it instead of falsely declaring expiry.
            fresh_store = load_auth_store(path=path)
            fresh_item = fresh_store["profiles"].get(profile)
            if isinstance(fresh_item, dict):
                fresh_expires = fresh_item.get("expires_at")
                if (
                    isinstance(fresh_expires, (int, float))
                    and float(fresh_expires) > time.time() + OAUTH_REFRESH_SKEW_SECONDS
                ):
                    return fresh_item
            raise RuntimeError(
                f"OAuth refresh token expired. "
                f"Run {HINT_LOGIN_API} --profile {profile} again."
            ) from error
        raise RuntimeError(
            f"OAuth refresh request failed with HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise RuntimeError("OAuth refresh request timed out") from error
        raise RuntimeError(f"OAuth refresh request failed: {error.reason}") from error

    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("OAuth refresh response does not contain access_token")
    expires_in = result.get("expires_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        raise RuntimeError("OAuth refresh response does not contain expires_in")

    item["token"] = access_token
    new_refresh_token = result.get("refresh_token")
    if isinstance(new_refresh_token, str) and new_refresh_token:
        item["refresh_token"] = new_refresh_token
    item["expires_at"] = time.time() + expires_in
    item["client_id"] = client_id
    item["source"] = "oauth"
    profiles[profile] = item
    save_auth_store(store, path=path)
    return item


def resolve_login(token: str) -> Optional[str]:
    """Resolve Yandex login from OAuth token via Passport API."""
    request = urllib.request.Request(
        "https://login.yandex.ru/info",
        headers={"Authorization": f"OAuth {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data.get("login")
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        logging.debug("resolve_login failed: %s", exc)
        return None


def _resolve_client_login_via_api(token: str) -> Optional[str]:
    """Return the bare Direct **Client-Login** for *token* via v5 ``clients.get``.

    The Passport ``/info`` login can be a full email (``<login>@yandex.ru``);
    Direct v4 AccountManagement rejects that with ``FaultCode 259`` (issue
    #480). ``clients.get`` (no ``SelectionCriteria``) returns the authoritative
    Client-Login for the token's own account, avoiding any unreliable
    ``split('@')`` guessing. Best-effort: returns ``None`` on any failure.
    """
    try:
        # Lazy import: api.py imports this module, so importing the vendored
        # client at module load would create a cycle. The vendor never imports
        # auth, so a function-local import is safe.
        from ._vendor.tapi_yandex_direct import YandexDirect

        # Best-effort, on the credential-resolution hot path: cap the wait so a
        # slow network or a Yandex SmartCaptcha gateway can never hang the CLI
        # indefinitely (requests defaults to no timeout). Retries are disabled
        # so the ceiling stays a single connect+read window.
        client = YandexDirect(
            access_token=token,
            retry_if_exceeded_limit=False,
            retries_if_server_error=0,
        )
        result = client.clients().post(
            data={"method": "get", "params": {"FieldNames": ["Login"]}},
            timeout=LOGIN_RESOLVE_TIMEOUT_SECONDS,
        )
        data = result().extract()
        clients = data.get("Clients") if isinstance(data, dict) else None
        if clients and isinstance(clients[0], dict):
            login = clients[0].get("Login")
            if login:
                return login
    except Exception as exc:  # noqa: PIE786 - best-effort; never block login on this
        logging.debug("resolve client login via API failed: %s", exc)
    return None


def resolve_account_login(token: str) -> Optional[str]:
    """Resolve the bare Direct Client-Login for an OAuth *token*.

    Prefers the authoritative v5 ``clients.get`` Login (which v4 accepts);
    falls back to the Passport login only when the API call fails (that value
    may be a full email and can break v4 — see :func:`_resolve_client_login_via_api`).
    """
    login = _resolve_client_login_via_api(token)
    if login:
        return login
    return resolve_login(token)

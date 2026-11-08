"""
Authentication module for Direct CLI.

Credential-source selection (the ``get_credentials`` priority ladder) and the
1Password/Bitwarden vault reads it falls back to (epic #961, track 6). Profile
persistence lives in :mod:`direct_cli._auth_store`, the OAuth/login network
operations in :mod:`direct_cli._auth_network`; this module re-exports both so
``from direct_cli.auth import <name>`` keeps working for every pre-split
importer, and patches aimed at this module's namespace keep landing on the
call sites that live here.
"""

import logging
import os
import shutil
import subprocess
import tempfile  # noqa: F401 - tests patch direct_cli.auth.tempfile.mkstemp
import time
import urllib.request  # noqa: F401 - tests patch .auth.urllib.request.urlopen
from typing import Optional, Tuple

from ._auth_hints import HINT_LOGIN_API
from ._auth_store import (  # noqa: F401 - facade re-exports
    AUTH_STORE_PATH as AUTH_STORE_PATH,
    BIND_PROFILE_ENV as BIND_PROFILE_ENV,
    DEFAULT_OAUTH_CLIENT_ID as DEFAULT_OAUTH_CLIENT_ID,
    INHERIT_GLOBAL_ENV as INHERIT_GLOBAL_ENV,
    PENDING_PKCE_TTL_SECONDS as PENDING_PKCE_TTL_SECONDS,
    _format_dotenv_value as _format_dotenv_value,
    _profile_suffix as _profile_suffix,
    _read_json as _read_json,
    _rewrite_env_keys as _rewrite_env_keys,
    _write_json as _write_json,
    get_active_profile as get_active_profile,
    get_env_profile as get_env_profile,
    get_oauth_profile as get_oauth_profile,
    get_pending_pkce as get_pending_pkce,
    inherit_globally_enabled as inherit_globally_enabled,
    list_profiles as list_profiles,
    load_auth_store as load_auth_store,
    load_env_file as load_env_file,
    read_folder_binding as read_folder_binding,
    remove_pending_pkce as remove_pending_pkce,
    save_auth_store as save_auth_store,
    save_env_binding as save_env_binding,
    save_env_credentials as save_env_credentials,
    save_oauth_profile as save_oauth_profile,
    save_pending_confidential_auth as save_pending_confidential_auth,
    save_pending_pkce as save_pending_pkce,
    set_active_profile as set_active_profile,
)
from ._auth_network import (  # noqa: F401 - facade re-exports
    LOGIN_RESOLVE_TIMEOUT_SECONDS as LOGIN_RESOLVE_TIMEOUT_SECONDS,
    OAUTH_REFRESH_SKEW_SECONDS as OAUTH_REFRESH_SKEW_SECONDS,
    YANDEX_OAUTH_AUTHORIZE_URL as YANDEX_OAUTH_AUTHORIZE_URL,
    YANDEX_OAUTH_TOKEN_URL as YANDEX_OAUTH_TOKEN_URL,
    _b64_url_nopad as _b64_url_nopad,
    _oauth_profile_incomplete_error as _oauth_profile_incomplete_error,
    _resolve_client_login_via_api as _resolve_client_login_via_api,
    build_oauth_authorize_url as build_oauth_authorize_url,
    build_pkce_pair as build_pkce_pair,
    exchange_oauth_code as exchange_oauth_code,
    refresh_access_token as refresh_access_token,
    resolve_account_login as resolve_account_login,
    resolve_login as resolve_login,
    validate_oauth_profile as validate_oauth_profile,
)


def op_read(ref: str) -> str:
    """Read a secret from 1Password using the op CLI.

    Args:
        ref: 1Password secret reference (e.g. op://vault/item/field)

    Returns:
        The secret value

    Raises:
        RuntimeError: If op CLI is not found or returns an error
    """
    op_path = shutil.which("op")
    if not op_path:
        raise RuntimeError(
            "1Password CLI (op) not found. "
            "Install it from https://developer.1password.com/docs/cli/"
        )
    try:
        result = subprocess.run(
            [op_path, "read", ref],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("1Password CLI timed out after 10 seconds")
    if result.returncode != 0:
        raise RuntimeError(f"1Password CLI error: {result.stderr.strip()}")
    return result.stdout.strip()


def bw_read(item: str, field: str = "password") -> str:
    """Read a secret from Bitwarden using the bw CLI.

    Args:
        item: Bitwarden item name or ID
        field: Field to read (password, username)

    Returns:
        The secret value

    Raises:
        RuntimeError: If bw CLI is not found or returns an error
    """
    bw_path = shutil.which("bw")
    if not bw_path:
        raise RuntimeError(
            "Bitwarden CLI (bw) not found. "
            "Install it from https://bitwarden.com/help/cli/"
        )
    try:
        result = subprocess.run(
            [bw_path, "get", field, item],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Bitwarden CLI timed out after 10 seconds")
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "locked" in stderr.lower():
            raise RuntimeError(
                f"Bitwarden CLI error: {stderr}. "
                "Ensure your vault is unlocked: "
                "eval $(bw unlock)"
            )
        raise RuntimeError(f"Bitwarden CLI error: {stderr}")
    return result.stdout.strip()


def _resolve_profile_credentials(
    selected_profile: str,
    login: Optional[str],
    allow_login_resolve: bool,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve token/login for one named OAuth or env profile."""
    final_token = None
    final_login = login
    oauth_profile = get_oauth_profile(selected_profile)
    if oauth_profile:
        if oauth_profile.get("source") == "oauth":
            validate_oauth_profile(selected_profile, oauth_profile)
            expires_at = float(oauth_profile["expires_at"])
            if expires_at <= time.time() + OAUTH_REFRESH_SKEW_SECONDS:
                oauth_profile = refresh_access_token(selected_profile)
        final_token = oauth_profile["token"]
        if not final_login:
            final_login = oauth_profile["login"]
        stored_login = oauth_profile.get("login")
        if (
            allow_login_resolve
            and not login
            and oauth_profile.get("source") == "oauth"
            and isinstance(stored_login, str)
            and "@" in stored_login
            and not oauth_profile.get("login_migration_checked")
        ):
            # One-time migration (#480): older OAuth profiles saved the
            # Passport email in `login`, which Direct v4 rejects with
            # FaultCode 259. Resolve the bare Client-Login and rewrite the
            # profile — but only when the stored email's local part matches
            # the resolved login, so agency profiles whose login differs
            # from the token owner are never clobbered. Either way we stamp
            # `login_migration_checked` once the resolver answered, so the
            # network round-trip never repeats per command for profiles that
            # are intentionally left unmigrated (e.g. agency logins).
            resolved = _resolve_client_login_via_api(final_token)
            if resolved:
                matches = stored_login.split("@", 1)[0].lower() == resolved.lower()
                if matches:
                    final_login = resolved
                try:
                    store = load_auth_store()
                    prof = store["profiles"].get(selected_profile)
                    if isinstance(prof, dict):
                        prof["login_migration_checked"] = True
                        if matches:
                            prof["login"] = resolved
                        save_auth_store(store)
                except Exception as exc:  # noqa: PIE786 - best-effort persistence
                    logging.debug("login migration persist failed: %s", exc)

    if not final_token:
        env_token, env_login = get_env_profile(selected_profile)
        final_token = env_token
        if not final_login:
            final_login = env_login
    return final_token, final_login


def _resolve_profile_or_raise(
    selected_profile: str,
    login: Optional[str],
    allow_login_resolve: bool,
) -> Tuple[str, Optional[str]]:
    """Resolve a named profile's credentials or raise if it is unconfigured."""
    final_token, final_login = _resolve_profile_credentials(
        selected_profile, login, allow_login_resolve
    )
    if not final_token:
        raise ValueError(
            f"Profile '{selected_profile}' is not configured. "
            f"Use {HINT_LOGIN_API} --profile NAME or set "
            f"YANDEX_DIRECT_TOKEN_{_profile_suffix(selected_profile)}."
        )
    return final_token, final_login


def get_credentials(
    token: Optional[str] = None,
    login: Optional[str] = None,
    env_path: Optional[str] = None,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    bw_token_ref: Optional[str] = None,
    bw_login_ref: Optional[str] = None,
    profile: Optional[str] = None,
    allow_login_resolve: bool = True,
) -> Tuple[str, Optional[str]]:
    """Resolve (token, login); see :func:`get_credentials_with_source` for
    the priority contract."""
    final_token, final_login, _ = get_credentials_with_source(
        token=token,
        login=login,
        env_path=env_path,
        op_token_ref=op_token_ref,
        op_login_ref=op_login_ref,
        bw_token_ref=bw_token_ref,
        bw_login_ref=bw_login_ref,
        profile=profile,
        allow_login_resolve=allow_login_resolve,
    )
    return final_token, final_login


def get_credentials_with_source(
    token: Optional[str] = None,
    login: Optional[str] = None,
    env_path: Optional[str] = None,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    bw_token_ref: Optional[str] = None,
    bw_login_ref: Optional[str] = None,
    profile: Optional[str] = None,
    allow_login_resolve: bool = True,
    allow_active_profile: bool = True,
) -> Tuple[str, Optional[str], str]:
    """
    Get credentials with priority:
    1. Direct arguments (--token, --login)
    2. Explicit selected profile storage or profile-specific environment variables
    3. Base env vars or cwd .env raw token (YANDEX_DIRECT_TOKEN, YANDEX_DIRECT_LOGIN)
    4. Folder profile link (cwd .env YANDEX_DIRECT_BIND_PROFILE=<name>, issue #917)
    5. Active profile storage or profile-specific environment variables
    6. 1Password (op_token_ref arg or YANDEX_DIRECT_OP_TOKEN_REF env var)
    7. Bitwarden (bw_token_ref arg or YANDEX_DIRECT_BW_TOKEN_REF env var)

    Args:
        token: API access token
        login: Client login (for agency accounts)
        env_path: Path to .env file
        op_token_ref: 1Password secret reference for token
        op_login_ref: 1Password secret reference for login
        bw_token_ref: Bitwarden item name/ID for token
        bw_login_ref: Bitwarden item name/ID for login
        allow_login_resolve: Allow the one-time #480 email->Client-Login
            migration for profile-sourced credentials
        allow_active_profile: Allow rung 5 (silent inheritance of the global
            active profile). The root CLI callback passes the #904 opt-in
            here — without it a folder with partial refs (e.g. an exported
            YANDEX_DIRECT_LOGIN only) would otherwise silently inherit the
            active profile's token and bypass the bind gate.

    Returns:
        Tuple of (token, login, source) where source is one of
        "args", "explicit-profile", "env", "linked-profile", "active-profile",
        "op", "bw" — the winning rung of the priority ladder (issue #904).

    Raises:
        ValueError: If token is not provided
    """
    # Load .env file first
    load_env_file(env_path)

    # Priority: explicit args/profile > base env/.env > active profile > secret refs.
    final_token = token
    final_login = login
    selected_profile = profile
    profile_credentials_selected = False
    source = "args"

    if selected_profile and not final_token:
        final_token, final_login = _resolve_profile_or_raise(
            selected_profile, final_login, allow_login_resolve
        )
        profile_credentials_selected = True
        source = "explicit-profile"

    if not final_token:
        env_token = os.getenv("YANDEX_DIRECT_TOKEN")
        if env_token:
            final_token = env_token
            if not final_login:
                final_login = os.getenv("YANDEX_DIRECT_LOGIN")
            source = "env"

    if not final_token and not selected_profile:
        linked_profile = (os.getenv(BIND_PROFILE_ENV) or "").strip()
        if linked_profile:
            # Issue #917: an explicit folder link names its profile and
            # resolves like --profile against that name. A dangling link
            # raises instead of silently falling through to another rung.
            final_token, final_login = _resolve_profile_or_raise(
                linked_profile, final_login, allow_login_resolve
            )
            profile_credentials_selected = True
            source = "linked-profile"

    if not final_token and not selected_profile and allow_active_profile:
        active_profile = get_active_profile()
        if active_profile:
            final_token, final_login = _resolve_profile_or_raise(
                active_profile, final_login, allow_login_resolve
            )
            profile_credentials_selected = True
            source = "active-profile"

    if not final_token:
        ref = op_token_ref or os.getenv("YANDEX_DIRECT_OP_TOKEN_REF")
        if ref:
            final_token = op_read(ref)
            if final_token:
                source = "op"

    if not final_token:
        ref = bw_token_ref or os.getenv("YANDEX_DIRECT_BW_TOKEN_REF")
        if ref:
            final_token = bw_read(ref, "password")
            if final_token:
                source = "bw"

    if not final_login and not profile_credentials_selected:
        ref = op_login_ref or os.getenv("YANDEX_DIRECT_OP_LOGIN_REF")
        if ref:
            final_login = op_read(ref)

    if not final_login and not profile_credentials_selected:
        ref = bw_login_ref or os.getenv("YANDEX_DIRECT_BW_LOGIN_REF")
        if ref:
            final_login = bw_read(ref, "username")

    if not final_token:
        raise ValueError(
            "API token required. Set YANDEX_DIRECT_TOKEN "
            "environment variable, create .env file, "
            "use --token option, select --profile, or configure 1Password "
            "with --op-token-ref or Bitwarden "
            "with --bw-token-ref."
        )

    return final_token, final_login, source

"""Profile/env persistence for Direct CLI authentication (epic #961, track 6).

Everything that touches disk or environment variables: the JSON auth store
(``~/.direct-cli/auth.json``), the folder ``.env`` binding forms, pending
OAuth state and the merged profile listing. No network calls and no
credential-source policy live here — see :mod:`direct_cli._auth_network`
and :mod:`direct_cli.auth` (the facade re-exports every name below, so the
public import surface is unchanged).
"""

import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import dotenv_values, load_dotenv

from .i18n import t
from .output import print_warning_stderr

AUTH_STORE_PATH = Path.home() / ".direct-cli" / "auth.json"


DEFAULT_OAUTH_CLIENT_ID = "dcf15d9625f6471d94d6d054d52017ba"


PENDING_PKCE_TTL_SECONDS = 600


def load_env_file(env_path: Optional[str] = None) -> None:
    """Load environment variables from an explicit or current-directory .env."""
    dotenv_path = Path(env_path) if env_path else Path.cwd() / ".env"
    load_dotenv(dotenv_path)


INHERIT_GLOBAL_ENV = "YANDEX_DIRECT_INHERIT_GLOBAL"
# Issue #917: a folder link to a global profile. Stores a profile NAME, never
# a secret — the token keeps living in the global store and the folder
# resolves it at command time. This is the default binding form; a raw token
# copy in .env is the explicit fallback form (one binding form per folder).
BIND_PROFILE_ENV = "YANDEX_DIRECT_BIND_PROFILE"


def inherit_globally_enabled() -> bool:
    """Opt-in (issue #904): restore the pre-#904 silent inheritance of the
    global active profile in folders with no explicit credential binding."""
    return (os.getenv(INHERIT_GLOBAL_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _format_dotenv_value(value: str) -> str:
    """Return a dotenv-safe scalar for Direct credential values."""
    if "\n" in value or "\r" in value:
        raise ValueError(".env credential values must be single-line strings.")
    if value and all(char not in value for char in " \t#'\"\\"):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _rewrite_env_keys(
    replacements: Dict[str, Optional[str]], dotenv_path: Path
) -> Path:
    """Atomically upsert/remove *replacements* keys in *dotenv_path*.

    ``None`` removes the key; other keys of the file are kept verbatim. A
    value absent from the file is appended. Refuses to rewrite a symlinked
    .env file, and does not create one when every replacement removes.
    """
    if dotenv_path.is_symlink():
        raise ValueError("Refusing to rewrite a symlinked .env file.")
    existed = dotenv_path.exists()
    if not existed and all(value is None for value in replacements.values()):
        return dotenv_path
    lines = (
        dotenv_path.read_text(encoding="utf-8").splitlines(keepends=True)
        if existed
        else []
    )
    seen = set()
    updated_lines = []

    for line in lines:
        stripped = line.lstrip()
        matched_key = None
        for key in replacements:
            if re.match(rf"(?:export\s+)?{key}\s*=", stripped):
                matched_key = key
                break
        if matched_key is None:
            updated_lines.append(line)
            continue
        seen.add(matched_key)
        if replacements[matched_key] is None:
            continue
        prefix = "export " if stripped.startswith("export ") else ""
        newline = "\n" if line.endswith("\n") else ""
        updated_lines.append(
            f"{prefix}{matched_key}={replacements[matched_key]}{newline}"
        )

    if updated_lines and not updated_lines[-1].endswith("\n"):
        updated_lines[-1] = f"{updated_lines[-1]}\n"
    for key, value in replacements.items():
        if value is not None and key not in seen:
            updated_lines.append(f"{key}={value}\n")

    fd, temporary_path = tempfile.mkstemp(prefix=".direct-env-", dir=dotenv_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as dotenv_file:
            fd = -1
            dotenv_file.write("".join(updated_lines))
        os.replace(temporary_path, dotenv_path)
    except BaseException:
        if fd != -1:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(temporary_path)
        raise
    return dotenv_path


def save_env_credentials(
    token: Optional[str],
    login: Optional[str] = None,
    env_path: Optional[Path] = None,
) -> Path:
    """Write a raw Direct credential pair to the current-directory .env file.

    This is the explicit "copy" binding form (issue #917): the token itself
    lands in the folder's `.env`. It replaces any profile link — a folder
    has one binding form. ``token=None`` removes only the stored pair; the
    profile link, secret refs and the inherit flag belong to other binding
    forms and are left untouched.

    Args:
        token: OAuth access token to store; None removes the stored pair.
        login: Optional Direct client login to store; removes any stale env login
            when omitted.
        env_path: Optional target path, used by tests. Defaults to cwd .env.

    Returns:
        Path to the updated .env file.

    Raises:
        ValueError: If token or login contain newline characters.
    """
    dotenv_path = env_path or Path.cwd() / ".env"
    previous = dotenv_values(dotenv_path) if dotenv_path.exists() else {}
    result = _rewrite_env_keys(
        {
            "YANDEX_DIRECT_TOKEN": (
                _format_dotenv_value(token) if token is not None else None
            ),
            "YANDEX_DIRECT_LOGIN": _format_dotenv_value(login) if login else None,
            # A raw copy replaces the link (#917): one binding form per folder.
            BIND_PROFILE_ENV: None,
        },
        dotenv_path,
    )
    if token is not None and "YANDEX_DIRECT_TOKEN" in previous:
        previous_login = previous.get("YANDEX_DIRECT_LOGIN")
        if previous_login:
            print_warning_stderr(
                t(
                    "Replacing existing YANDEX_DIRECT_TOKEN (was login={login})"
                    " with new credentials."
                ).format(login=previous_login)
            )
        else:
            print_warning_stderr(
                t("Replacing existing YANDEX_DIRECT_TOKEN with new credentials.")
            )
    return result


def save_env_binding(profile: Optional[str], env_path: Optional[Path] = None) -> Path:
    """Bind the current-directory .env to a global profile by name (issue #917).

    The link (``YANDEX_DIRECT_BIND_PROFILE=<name>``) stores no secret: the
    token keeps living in the global profile store and the folder resolves
    it at command time. Writing a link replaces any raw token/login copy —
    a folder has one binding form. ``profile=None`` removes only the link;
    raw copies, secret refs and the inherit flag belong to other binding
    forms and are left for their own owners.

    Returns:
        Path to the updated .env file.
    """
    dotenv_path = env_path or Path.cwd() / ".env"
    if profile is None:
        return _rewrite_env_keys({BIND_PROFILE_ENV: None}, dotenv_path)
    return _rewrite_env_keys(
        {
            BIND_PROFILE_ENV: _format_dotenv_value(profile),
            "YANDEX_DIRECT_TOKEN": None,
            "YANDEX_DIRECT_LOGIN": None,
        },
        dotenv_path,
    )


def read_folder_binding(env_path: Optional[Path] = None) -> Optional[str]:
    """Return the profile name this folder's .env links to, or None."""
    dotenv_path = env_path or Path.cwd() / ".env"
    if not dotenv_path.exists():
        return None
    value = dotenv_values(dotenv_path).get(BIND_PROFILE_ENV)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _profile_suffix(profile: str) -> str:
    """Build an environment variable suffix for a profile name."""
    normalized = []
    for char in profile:
        if char.isalnum():
            normalized.append(char.upper())
        else:
            normalized.append("_")
    return "".join(normalized).strip("_")


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd = -1  # ownership transferred to the file object
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except Exception:
        if fd != -1:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load_auth_store(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load OAuth profile storage."""
    store_path = path or AUTH_STORE_PATH
    data = _read_json(store_path)
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    pending_pkce = data.get("pending_pkce")
    if not isinstance(pending_pkce, dict):
        pending_pkce = {}
    active = data.get("active_profile")
    if active is not None and not isinstance(active, str):
        active = None
    return {
        "profiles": profiles,
        "active_profile": active,
        "pending_pkce": pending_pkce,
    }


def save_auth_store(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    """Persist OAuth profile storage."""
    store_path = path or AUTH_STORE_PATH
    _write_json(store_path, data)


def save_pending_pkce(
    profile: str,
    client_id: str,
    code_verifier: str,
    login: Optional[str] = None,
    created_at: Optional[float] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Save pending PKCE state for a profile."""
    now = time.time() if created_at is None else float(created_at)
    item: Dict[str, Any] = {
        "type": "pkce",
        "client_id": client_id,
        "code_verifier": code_verifier,
        "login": login,
        "created_at": now,
        "expires_at": now + PENDING_PKCE_TTL_SECONDS,
    }
    store = load_auth_store(path=path)
    store["pending_pkce"][profile] = item
    save_auth_store(store, path=path)
    return item


def save_pending_confidential_auth(
    profile: str,
    client_id: str,
    client_secret: str,
    login: Optional[str] = None,
    created_at: Optional[float] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Save pending confidential-client OAuth state for a profile."""
    now = time.time() if created_at is None else float(created_at)
    item: Dict[str, Any] = {
        "type": "confidential",
        "client_id": client_id,
        "client_secret": client_secret,
        "login": login,
        "created_at": now,
        "expires_at": now + PENDING_PKCE_TTL_SECONDS,
    }
    store = load_auth_store(path=path)
    store["pending_pkce"][profile] = item
    save_auth_store(store, path=path)
    return item


def get_pending_pkce(
    profile: str, path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Return pending OAuth state for a profile when it has the expected shape."""
    store = load_auth_store(path=path)
    item = store["pending_pkce"].get(profile)
    if not isinstance(item, dict):
        return None
    client_id = item.get("client_id")
    expires_at = item.get("expires_at")
    if (
        not isinstance(client_id, str)
        or not client_id
        or not isinstance(expires_at, (int, float))
    ):
        return None
    auth_type = item.get("type")
    code_verifier = item.get("code_verifier")
    client_secret = item.get("client_secret")
    if auth_type == "confidential":
        if not isinstance(client_secret, str) or not client_secret:
            return None
    elif not isinstance(code_verifier, str) or not code_verifier:
        return None
    else:
        auth_type = "pkce"
    result = dict(item)
    result["type"] = auth_type
    login = result.get("login")
    if login is not None and not isinstance(login, str):
        result["login"] = None
    return result


def remove_pending_pkce(profile: str, path: Optional[Path] = None) -> None:
    """Remove pending PKCE state for a profile if present."""
    store = load_auth_store(path=path)
    store["pending_pkce"].pop(profile, None)
    save_auth_store(store, path=path)


def save_oauth_profile(
    profile: str,
    token: str,
    login: Optional[str] = None,
    refresh_token: Optional[str] = None,
    expires_at: Optional[float] = None,
    client_id: str = DEFAULT_OAUTH_CLIENT_ID,
    client_secret: Optional[str] = None,
    source: str = "oauth",
    make_active: bool = True,
    overwrite: bool = False,
    path: Optional[Path] = None,
) -> None:
    """Save/update one OAuth profile without exposing secret values."""
    store = load_auth_store(path=path)
    profiles = store["profiles"]
    if profile in profiles and not overwrite:
        raise ValueError(
            f"Profile '{profile}' already exists; "
            "pass overwrite=True to replace its stored credentials"
        )
    item: Dict[str, Any] = {
        "token": token,
        "login": login,
        "source": source,
    }
    if source == "oauth":
        if not refresh_token:
            raise ValueError("OAuth profile requires refresh_token")
        if expires_at is None:
            raise ValueError("OAuth profile requires expires_at")
        item["refresh_token"] = refresh_token
        item["expires_at"] = float(expires_at)
        item["client_id"] = client_id
        if client_secret:
            item["client_secret"] = client_secret
    profiles[profile] = item
    if make_active:
        store["active_profile"] = profile
    save_auth_store(store, path=path)


def set_active_profile(profile: str, path: Optional[Path] = None) -> None:
    """Persist active profile name."""
    store = load_auth_store(path=path)
    store["active_profile"] = profile
    save_auth_store(store, path=path)


def get_active_profile(path: Optional[Path] = None) -> Optional[str]:
    """Read active profile from auth storage."""
    return load_auth_store(path=path).get("active_profile")


def get_oauth_profile(
    profile: str, path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    """Get OAuth profile by name."""
    store = load_auth_store(path=path)
    item = store["profiles"].get(profile)
    if not isinstance(item, dict):
        return None
    token = item.get("token")
    login = item.get("login")
    if not isinstance(token, str) or not token:
        return None
    if login is not None and not isinstance(login, str):
        login = None
    result = dict(item)
    result["token"] = token
    result["login"] = login
    source = result.get("source")
    if not isinstance(source, str):
        result["source"] = "oauth"
    return result


def get_env_profile(profile: str) -> Tuple[Optional[str], Optional[str]]:
    """Read profile token/login from env vars like YANDEX_DIRECT_TOKEN_PROFILE."""
    suffix = _profile_suffix(profile)
    if not suffix:
        return None, None
    token = os.getenv(f"YANDEX_DIRECT_TOKEN_{suffix}")
    login = os.getenv(f"YANDEX_DIRECT_LOGIN_{suffix}")
    return token, login


def list_profiles(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return merged profile list from OAuth store and env profile vars."""
    profiles: Dict[str, Dict[str, Any]] = {}
    store = load_auth_store(path=path)
    active_profile = store.get("active_profile")

    for profile_name, data in store["profiles"].items():
        if not isinstance(profile_name, str):
            continue
        if not isinstance(data, dict):
            continue
        token = data.get("token")
        login = data.get("login")
        if not isinstance(token, str) or not token:
            continue
        source = data.get("source")
        if not isinstance(source, str):
            source = "oauth"
        profiles[profile_name] = {
            "profile": profile_name,
            "source": source,
            "has_token": True,
            "has_login": bool(login),
            "login": login,
            "active": profile_name == active_profile,
        }

    env = os.environ
    for name in env:
        prefix = "YANDEX_DIRECT_TOKEN_"
        if not name.startswith(prefix):
            continue
        suffix = name[len(prefix) :]
        if not suffix:
            continue
        profile_name = suffix.lower()
        login = env.get(f"YANDEX_DIRECT_LOGIN_{suffix}")
        existing = profiles.get(profile_name)
        if existing:
            existing["source"] = f"{existing['source']}+env"
            existing["has_login"] = bool(existing["has_login"] or login)
            existing["login"] = existing["login"] or login
            continue
        profiles[profile_name] = {
            "profile": profile_name,
            "source": "env",
            "has_token": True,
            "has_login": bool(login),
            "login": login or None,
            "active": profile_name == active_profile,
        }

    return sorted(profiles.values(), key=lambda x: x["profile"])

"""
Authentication module for Direct CLI
"""

import base64
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv():
        return None


YANDEX_OAUTH_AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
YANDEX_OAUTH_TOKEN_URL = "https://oauth.yandex.ru/token"
DEFAULT_OAUTH_CLIENT_ID = "dcf15d9625f6471d94d6d054d52017ba"
AUTH_STORE_PATH = Path.home() / ".direct-cli" / "auth.json"


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


def load_env_file(env_path: Optional[str] = None) -> None:
    """Load environment variables from .env file"""
    if load_dotenv:
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()


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
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise


def load_auth_store(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load OAuth profile storage."""
    store_path = path or AUTH_STORE_PATH
    data = _read_json(store_path)
    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}
    active = data.get("active_profile")
    if active is not None and not isinstance(active, str):
        active = None
    return {"profiles": profiles, "active_profile": active}


def save_auth_store(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    """Persist OAuth profile storage."""
    store_path = path or AUTH_STORE_PATH
    _write_json(store_path, data)


def save_oauth_profile(
    profile: str,
    token: str,
    login: Optional[str] = None,
    make_active: bool = True,
    path: Optional[Path] = None,
) -> None:
    """Save/update one OAuth profile without exposing secret values."""
    store = load_auth_store(path=path)
    profiles = store["profiles"]
    profiles[profile] = {
        "token": token,
        "login": login,
        "source": "oauth",
    }
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
) -> Optional[Dict[str, Optional[str]]]:
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
    return {"token": token, "login": login}


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
        profiles[profile_name] = {
            "profile": profile_name,
            "source": "oauth",
            "has_token": True,
            "has_login": bool(login),
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
            existing["source"] = "oauth+env"
            existing["has_login"] = bool(existing["has_login"] or login)
            continue
        profiles[profile_name] = {
            "profile": profile_name,
            "source": "env",
            "has_token": True,
            "has_login": bool(login),
            "active": profile_name == active_profile,
        }

    return sorted(profiles.values(), key=lambda x: x["profile"])


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
) -> str:
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
        details = error.read().decode("utf-8", errors="ignore")
        if details:
            raise RuntimeError(f"OAuth token request failed: {details}") from error
        raise RuntimeError(
            f"OAuth token request failed with HTTP {error.code}"
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"OAuth token request failed: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError("OAuth token request timed out") from error

    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("OAuth token response does not contain access_token")
    # TODO: Persist refresh_token/expires_in and refresh automatically.
    return access_token


def get_credentials(
    token: Optional[str] = None,
    login: Optional[str] = None,
    env_path: Optional[str] = None,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    bw_token_ref: Optional[str] = None,
    bw_login_ref: Optional[str] = None,
    profile: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Get credentials with priority:
    1. Direct arguments (--token, --login)
    2. Selected profile storage or profile-specific environment variables
    3. Environment variables (YANDEX_DIRECT_TOKEN, YANDEX_DIRECT_LOGIN)
    4. .env file
    5. 1Password (op_token_ref arg or YANDEX_DIRECT_OP_TOKEN_REF env var)
    6. Bitwarden (bw_token_ref arg or YANDEX_DIRECT_BW_TOKEN_REF env var)

    Args:
        token: API access token
        login: Client login (for agency accounts)
        env_path: Path to .env file
        op_token_ref: 1Password secret reference for token
        op_login_ref: 1Password secret reference for login
        bw_token_ref: Bitwarden item name/ID for token
        bw_login_ref: Bitwarden item name/ID for login

    Returns:
        Tuple of (token, login)

    Raises:
        ValueError: If token is not provided
    """
    # Load .env file first
    load_env_file(env_path)

    # Priority: explicit args > selected profile > base env/.env > 1Password > Bitwarden
    selected_profile = profile or get_active_profile()
    final_token = token
    final_login = login
    profile_was_selected = bool(selected_profile)

    if selected_profile and not final_token:
        oauth_profile = get_oauth_profile(selected_profile)
        if oauth_profile:
            final_token = oauth_profile["token"]
            if not final_login:
                final_login = oauth_profile["login"]

    if selected_profile and not final_token:
        env_token, env_login = get_env_profile(selected_profile)
        final_token = env_token
        if not final_login:
            final_login = env_login

    if selected_profile and not final_token:
        raise ValueError(
            f"Profile '{selected_profile}' is not configured. "
            "Use direct auth login --profile NAME or set "
            f"YANDEX_DIRECT_TOKEN_{_profile_suffix(selected_profile)}."
        )

    if not final_token:
        final_token = os.getenv("YANDEX_DIRECT_TOKEN")
    if not final_login and not profile_was_selected:
        final_login = os.getenv("YANDEX_DIRECT_LOGIN")

    if not final_token:
        ref = op_token_ref or os.getenv("YANDEX_DIRECT_OP_TOKEN_REF")
        if ref:
            final_token = op_read(ref)

    if not final_token:
        ref = bw_token_ref or os.getenv("YANDEX_DIRECT_BW_TOKEN_REF")
        if ref:
            final_token = bw_read(ref, "password")

    if not final_login and not profile_was_selected:
        ref = op_login_ref or os.getenv("YANDEX_DIRECT_OP_LOGIN_REF")
        if ref:
            final_login = op_read(ref)

    if not final_login and not profile_was_selected:
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

    return final_token, final_login

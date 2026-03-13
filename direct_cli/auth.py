"""
Authentication module for Direct CLI
"""

import os
import shutil
import subprocess
from typing import Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda: None


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
        field: Field to read (password, username, notes)

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
        raise RuntimeError(f"Bitwarden CLI error: {result.stderr.strip()}")
    return result.stdout.strip()


def load_env_file(env_path: Optional[str] = None) -> None:
    """Load environment variables from .env file"""
    if load_dotenv:
        if env_path:
            load_dotenv(env_path)
        else:
            load_dotenv()


def get_credentials(
    token: Optional[str] = None,
    login: Optional[str] = None,
    env_path: Optional[str] = None,
    op_token_ref: Optional[str] = None,
    op_login_ref: Optional[str] = None,
    bw_token_ref: Optional[str] = None,
    bw_login_ref: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """
    Get credentials with priority:
    1. Direct arguments (--token, --login)
    2. Environment variables (YANDEX_DIRECT_TOKEN, YANDEX_DIRECT_LOGIN)
    3. .env file
    4. 1Password (op_token_ref arg or YANDEX_DIRECT_OP_TOKEN_REF env var)
    5. Bitwarden (bw_token_ref arg or YANDEX_DIRECT_BW_TOKEN_REF env var)

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

    # Priority: arguments > env vars > 1Password > Bitwarden
    final_token = token or os.getenv("YANDEX_DIRECT_TOKEN")
    final_login = login or os.getenv("YANDEX_DIRECT_LOGIN")

    if not final_token:
        ref = op_token_ref or os.getenv("YANDEX_DIRECT_OP_TOKEN_REF")
        if ref:
            final_token = op_read(ref)

    if not final_token:
        ref = bw_token_ref or os.getenv("YANDEX_DIRECT_BW_TOKEN_REF")
        if ref:
            final_token = bw_read(ref, "password")

    if not final_login:
        ref = op_login_ref or os.getenv("YANDEX_DIRECT_OP_LOGIN_REF")
        if ref:
            final_login = op_read(ref)

    if not final_login:
        ref = bw_login_ref or os.getenv("YANDEX_DIRECT_BW_LOGIN_REF")
        if ref:
            final_login = bw_read(ref, "username")

    if not final_token:
        raise ValueError(
            "API token required. Set YANDEX_DIRECT_TOKEN "
            "environment variable, create .env file, "
            "use --token option, or configure 1Password "
            "with --op-token-ref or Bitwarden "
            "with --bw-token-ref."
        )

    return final_token, final_login

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
    result = subprocess.run(
        [op_path, "read", ref],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"1Password CLI error: {result.stderr.strip()}"
        )
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
) -> Tuple[str, Optional[str]]:
    """
    Get credentials with priority:
    1. Direct arguments
    2. Environment variables
    3. .env file

    Args:
        token: API access token
        login: Client login (for agency accounts)
        env_path: Path to .env file

    Returns:
        Tuple of (token, login)

    Raises:
        ValueError: If token is not provided
    """
    # Load .env file first
    load_env_file(env_path)

    # Priority: arguments > env vars > 1Password
    final_token = token or os.getenv("YANDEX_DIRECT_TOKEN")
    final_login = login or os.getenv("YANDEX_DIRECT_LOGIN")

    if not final_token:
        op_ref = os.getenv("YANDEX_DIRECT_OP_TOKEN_REF")
        if op_ref:
            final_token = op_read(op_ref)

    if not final_login:
        op_ref = os.getenv("YANDEX_DIRECT_OP_LOGIN_REF")
        if op_ref:
            final_login = op_read(op_ref)

    if not final_token:
        raise ValueError(
            "API token required. Set YANDEX_DIRECT_TOKEN environment variable, "
            "create .env file, use --token option, "
            "or configure 1Password with --op-token-ref."
        )

    return final_token, final_login

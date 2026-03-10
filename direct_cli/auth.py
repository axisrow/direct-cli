"""
Authentication module for Direct CLI
"""

import os
from typing import Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = lambda: None


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

    # Priority: arguments > env vars
    final_token = token or os.getenv("YANDEX_DIRECT_TOKEN")
    final_login = login or os.getenv("YANDEX_DIRECT_LOGIN")

    if not final_token:
        raise ValueError(
            "API token required. Set YANDEX_DIRECT_TOKEN environment variable "
            "or create .env file, or use --token option."
        )

    return final_token, final_login

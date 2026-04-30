"""Runtime endpoints for Yandex Direct API transports."""

from typing import Any, Dict

DIRECT_API_PRODUCTION_ROOT = "https://api.direct.yandex.ru/"
DIRECT_API_SANDBOX_ROOT = "https://api-sandbox.direct.yandex.ru/"
DIRECT_DEBUG_ROOT = "https://"


def get_direct_api_root(api_params: Dict[str, Any]) -> str:
    """Return the Direct API root for production or sandbox requests."""
    if api_params.get("is_sandbox"):
        return DIRECT_API_SANDBOX_ROOT
    return DIRECT_API_PRODUCTION_ROOT

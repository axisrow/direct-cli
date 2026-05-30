"""Runtime endpoints for Yandex Direct API transports.

The v5 JSON API historically uses the ``.com`` TLD while the v4 Live API uses
``.ru``; both hosts are valid Yandex Direct entrypoints. ``get_direct_api_root``
keeps that per-transport distinction via the ``tld`` argument so neither
adapter silently changes the domain its callers rely on.
"""

from typing import Any, Dict

DIRECT_API_PRODUCTION_ROOT = "https://api.direct.yandex.{tld}/"
DIRECT_API_SANDBOX_ROOT = "https://api-sandbox.direct.yandex.{tld}/"
DIRECT_DEBUG_ROOT = "https://"


def get_direct_api_root(api_params: Dict[str, Any], tld: str = "com") -> str:
    """Return the Direct API root for production or sandbox requests.

    ``tld`` selects the top-level domain: ``"com"`` for the v5 JSON API
    (default, preserving the historical host) and ``"ru"`` for the v4 Live API.
    """
    template = (
        DIRECT_API_SANDBOX_ROOT
        if api_params.get("is_sandbox")
        else DIRECT_API_PRODUCTION_ROOT
    )
    return template.format(tld=tld)

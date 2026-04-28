"""Live smoke-test probes for IDs that cannot be hardcoded safely."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from .api import create_client

VIDEO_CREATIVE_TYPES = {
    "VIDEO_EXTENSION_CREATIVE",
    "CPM_VIDEO_CREATIVE",
    "CPC_VIDEO_CREATIVE",
}


def _extract_items(response: Any) -> list[dict[str, Any]]:
    """Return a normalized list from a tapi response object."""
    data = response().extract()
    return data if isinstance(data, list) else []


def _advideo_get_accepts(client: Any, candidate: str) -> bool:
    """Return whether advideos.get accepts the candidate ID."""
    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {"Ids": [candidate]},
            "FieldNames": ["Id", "Status"],
            "Page": {"Limit": 1},
        },
    }
    try:
        _extract_items(client.advideos().post(data=body))
        return True
    except Exception:
        return False


def advideo_probe_id() -> Optional[str]:
    """Return an AdVideos ID accepted by ``advideos.get``, or ``None``.

    Returns ``None`` (never raises) on auth failure, missing credentials,
    or any network/API error — smoke scripts use this in a context where a
    failed probe should be a benign skip, not a fatal error.
    """
    try:
        client = create_client()
    except Exception:
        return None

    env_id = os.getenv("YANDEX_DIRECT_TEST_ADVIDEO_ID")
    if env_id and _advideo_get_accepts(client, env_id):
        return env_id

    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id", "Name", "Type"],
            "Page": {"Limit": 20},
        },
    }
    try:
        creatives = _extract_items(client.creatives().post(data=body))
    except Exception:
        return None

    for creative in creatives:
        if creative.get("Type") not in VIDEO_CREATIVE_TYPES:
            continue
        candidate = creative.get("Id")
        if candidate and _advideo_get_accepts(client, str(candidate)):
            return str(candidate)
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for smoke probes."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv != ["advideo"]:
        print("Usage: python3 -m direct_cli._smoke_probes advideo", file=sys.stderr)
        return 2

    probe_id = advideo_probe_id()
    if not probe_id:
        return 1
    print(probe_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

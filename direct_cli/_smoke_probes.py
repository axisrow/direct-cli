"""Live smoke-test probes for IDs that cannot be hardcoded safely."""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

from .api import create_client, create_v4_client

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


def _first_campaign_id(client: Any) -> Optional[int]:
    """Return the first campaign Id visible to the account, or ``None``."""
    body = {
        "method": "get",
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["Id"],
            "Page": {"Limit": 1},
        },
    }
    try:
        campaigns = _extract_items(client.campaigns().post(data=body))
    except Exception:
        return None
    if not campaigns:
        return None
    cid = campaigns[0].get("Id")
    return cid if isinstance(cid, int) else None


def retargeting_goal_probe_id() -> Optional[str]:
    """Return a real Metrica/retargeting goal id for the account, or ``None``.

    The value is the ``GoalID`` that a retargeting rule references as its
    ``ExternalId`` (``--rule ALL:<goal>:<days>``).  Resolution order mirrors
    :func:`advideo_probe_id`:

    1. ``YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID`` env override (used when
       recording cassettes — the real id is masked to ``12345`` by the VCR
       filter, never committed);
    2. live lookup — the first campaign's retargeting goals via the v4 Live
       ``GetRetargetingGoals`` method.

    Returns ``None`` (never raises) on missing credentials or any API error, so
    callers treat a failed probe as a benign skip.  Never hardcode a real goal
    id in source or cassettes — the repository is public.
    """
    env_id = os.getenv("YANDEX_DIRECT_TEST_RETARGETING_GOAL_ID")
    if env_id:
        return env_id

    try:
        client = create_client()
    except Exception:
        return None

    campaign_id = _first_campaign_id(client)
    if campaign_id is None:
        return None

    try:
        v4_client = create_v4_client()
        result = v4_client.v4live().post(
            data={
                "method": "GetRetargetingGoals",
                "param": {"CampaignIDS": [campaign_id]},
            }
        )
        goals = result().extract()
    except Exception:
        return None

    if isinstance(goals, list):
        for goal in goals:
            goal_id = goal.get("GoalID") if isinstance(goal, dict) else None
            if goal_id:
                return str(goal_id)
    return None


_PROBES = {
    "advideo": advideo_probe_id,
    "retargeting-goal": retargeting_goal_probe_id,
}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for smoke probes."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 1 or argv[0] not in _PROBES:
        names = " | ".join(_PROBES)
        print(
            f"Usage: python3 -m direct_cli._smoke_probes <{names}>",
            file=sys.stderr,
        )
        return 2

    probe_id = _PROBES[argv[0]]()
    if not probe_id:
        return 1
    print(probe_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

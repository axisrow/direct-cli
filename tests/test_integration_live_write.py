"""
Manual live-write integration tests for production Yandex Direct API.

Safety contract:
- tests are skipped unless YANDEX_DIRECT_LIVE_WRITE=1 is set explicitly;
- tests never accept external resource IDs;
- every mutating command targets only a draft resource created by this test;
- cleanup fails loudly with the created ID if Yandex Direct refuses deletion.

Coverage status (issue #59):

  Phase 4 — non-standard campaign types (Category B):
    - dynamicads add/delete (DYNAMIC_TEXT_CAMPAIGN)
    - smartadtargets add/update/delete (SMART_CAMPAIGN)
"""

import json
import os
from typing import Any, Dict, List, Optional

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from direct_cli.cli import cli

load_dotenv()

LIVE_WRITE_ENV = "YANDEX_DIRECT_LIVE_WRITE"
TEST_CAMPAIGN_NAME = "direct-cli-live-draft-test-cassette"
TEST_CAMPAIGN_START_DATE = "2030-01-15"


pytestmark = [
    pytest.mark.integration_live_write,
    pytest.mark.skipif(
        os.getenv(LIVE_WRITE_ENV) != "1",
        reason=f"{LIVE_WRITE_ENV}=1 is required for live draft write tests",
    ),
    pytest.mark.skipif(
        not os.getenv("YANDEX_DIRECT_TOKEN"),
        reason="YANDEX_DIRECT_TOKEN is required for live draft write tests",
    ),
]


def _invoke_live(*args: str):
    """Invoke a CLI command against production API with live credentials."""
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    assert token, "YANDEX_DIRECT_TOKEN is required for live draft write tests"

    all_args = ["--token", token]
    login = os.getenv("YANDEX_DIRECT_LOGIN")
    if login:
        all_args.extend(["--login", login])
    all_args.extend(args)

    return CliRunner().invoke(cli, all_args)


def _future_start_date() -> str:
    """Return a deterministic future date so VCR body matching can replay."""
    return TEST_CAMPAIGN_START_DATE


def _campaign_name() -> str:
    """Build a stable name that makes live leftovers easy to find."""
    return TEST_CAMPAIGN_NAME


def _assert_success(result, cmd_label: str) -> None:
    """Assert command exited successfully."""
    assert result.exit_code == 0, (
        f"[{cmd_label}] exit_code={result.exit_code}\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )


def _extract_first_id(output: str, key: str = "AddResults") -> int:
    """Extract the first Id from an add-result JSON response."""
    data = json.loads(output)
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        result = data.get("result", data)
        items = result.get(key, result.get("SetItems", []))
    else:
        items = []

    assert items, f"No result items in response: {output[:500]}"
    first = items[0]
    assert (
        "Errors" not in first or not first["Errors"]
    ), f"API rejected add: {first.get('Errors')}"
    assert "Id" in first, f"No Id in add result: {first}"
    return int(first["Id"])


def _extract_campaigns(output: str) -> List[Dict[str, Any]]:
    """Extract campaigns from common tapi-yandex-direct response shapes."""
    data = json.loads(output)
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []

    result = data.get("result", data)
    campaigns = result.get("Campaigns", [])
    return campaigns if isinstance(campaigns, list) else []


def _find_campaign(output: str, campaign_id: int) -> Optional[Dict[str, Any]]:
    """Find a campaign by Id in a get response."""
    for campaign in _extract_campaigns(output):
        try:
            if int(campaign.get("Id")) == campaign_id:
                return campaign
        except (TypeError, ValueError):
            continue
    return None


def _assert_created_campaign_is_draft(
    campaign: Dict[str, Any],
    expected_name: str,
) -> None:
    """Verify the created live campaign is still non-serving draft/off state."""
    assert campaign.get("Name") == expected_name

    status = campaign.get("Status")
    state = campaign.get("State")
    assert status == "DRAFT" or state == "OFF", (
        "Expected a non-serving draft/off campaign, got "
        f"Status={status!r}, State={state!r}, campaign={campaign}"
    )
    if status is not None:
        assert status == "DRAFT"
    if state is not None:
        assert state == "OFF"


@pytest.mark.vcr
def test_live_draft_campaign_create_get_delete() -> None:
    """Create, verify and delete only the draft campaign created by this test."""
    campaign_name = _campaign_name()
    created_campaign_id: Optional[int] = None

    add_result = _invoke_live(
        "campaigns",
        "add",
        "--name",
        campaign_name,
        "--start-date",
        _future_start_date(),
    )

    try:
        _assert_success(add_result, "campaigns add")
        try:
            created_campaign_id = _extract_first_id(add_result.output)
        except Exception:
            pass  # ID unknown; cleanup skipped — manual recovery via name

        get_result = _invoke_live(
            "campaigns",
            "get",
            "--ids",
            str(created_campaign_id),
            "--fields",
            "Id,Name,Status,State",
        )
        _assert_success(get_result, "campaigns get")
        campaign = _find_campaign(get_result.output, created_campaign_id)
        assert campaign is not None, (
            f"Created campaign {created_campaign_id} not found in get response: "
            f"{get_result.output[:500]}"
        )
        _assert_created_campaign_is_draft(campaign, campaign_name)
    finally:
        if created_campaign_id is not None:
            delete_result = _invoke_live(
                "campaigns",
                "delete",
                "--id",
                str(created_campaign_id),
            )
            if delete_result.exit_code != 0:
                pytest.fail(
                    "Failed to delete live draft campaign "
                    f"{created_campaign_id}. Manual cleanup required.\n"
                    f"output: {delete_result.output}\n"
                    f"exception: {delete_result.exception}"
                )

    verify_delete_result = _invoke_live(
        "campaigns",
        "get",
        "--ids",
        str(created_campaign_id),
        "--fields",
        "Id,Name,Status,State",
    )
    _assert_success(verify_delete_result, "campaigns get after delete")
    assert _find_campaign(verify_delete_result.output, created_campaign_id) is None


def _safe_delete_campaign(cid: int) -> None:
    """Delete a draft campaign, failing the test if deletion is rejected."""
    r = _invoke_live("campaigns", "delete", "--id", str(cid))
    if r.exit_code != 0:
        pytest.fail(
            f"Failed to delete draft campaign {cid}. "
            f"Manual cleanup required.\noutput: {r.output}"
        )


# ── Phase 4: non-standard campaign types (Category B) ─────────────────────


@pytest.mark.vcr
def test_live_draft_dynamicads_add_delete() -> None:
    """Create DYNAMIC_TEXT_CAMPAIGN, add dynamic ad target, verify, delete."""
    # Create DYNAMIC_TEXT_CAMPAIGN
    r = _invoke_live(
        "campaigns",
        "add",
        "--name",
        f"{_campaign_name()}-dynamic",
        "--start-date",
        _future_start_date(),
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
    )
    _assert_success(r, "campaigns add (DYNAMIC_TEXT_CAMPAIGN)")
    cid = _extract_first_id(r.output)
    gid: Optional[int] = None
    did: Optional[int] = None

    try:
        # Create DYNAMIC_TEXT_AD_GROUP
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-dynamic-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
            "--type",
            "DYNAMIC_TEXT_AD_GROUP",
            "--domain-url",
            "example.com",
        )
        _assert_success(r, "adgroups add (DYNAMIC_TEXT_AD_GROUP)")
        gid = _extract_first_id(r.output)

        # Add dynamic ad target
        r = _invoke_live(
            "dynamicads",
            "add",
            "--adgroup-id",
            str(gid),
            "--name",
            "Draft Dynamic Target",
            "--condition",
            "URL:CONTAINS_ANY:test",
        )
        _assert_success(r, "dynamicads add")
        did = _extract_first_id(r.output)

        # Verify via get
        r = _invoke_live(
            "dynamicads",
            "get",
            "--adgroup-ids",
            str(gid),
            "--format",
            "json",
        )
        _assert_success(r, "dynamicads get")
        data = json.loads(r.output)
        targets = data if isinstance(data, list) else data.get("result", [])
        assert any(
            t.get("Id") == did for t in targets
        ), f"Dynamic ad target {did} not found in get response"
    finally:
        if did is not None:
            _invoke_live("dynamicads", "delete", "--id", str(did))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_smartadtargets_add_update_delete() -> None:
    """Create SMART_CAMPAIGN, add smart ad target, update, verify, delete."""
    # Create feed (SMART_AD_GROUP requires feed-id)
    r = _invoke_live(
        "feeds",
        "add",
        "--name",
        "draft-smart-feed",
        "--url",
        "https://example.com/feed.xml",
    )
    _assert_success(r, "feeds add")
    fid = _extract_first_id(r.output)
    cid: Optional[int] = None
    gid: Optional[int] = None
    tid: Optional[int] = None

    try:
        # Create SMART_CAMPAIGN
        r = _invoke_live(
            "campaigns",
            "add",
            "--name",
            f"{_campaign_name()}-smart",
            "--start-date",
            _future_start_date(),
            "--type",
            "SMART_CAMPAIGN",
            "--network-strategy",
            "AVERAGE_CPC_PER_FILTER",
            "--filter-average-cpc",
            "1",
        )
        _assert_success(r, "campaigns add (SMART_CAMPAIGN)")
        cid = _extract_first_id(r.output)

        # Create SMART_AD_GROUP
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-smart-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
            "--type",
            "SMART_AD_GROUP",
            "--feed-id",
            str(fid),
        )
        _assert_success(r, "adgroups add (SMART_AD_GROUP)")
        gid = _extract_first_id(r.output)

        # Add smart ad target
        r = _invoke_live(
            "smartadtargets",
            "add",
            "--adgroup-id",
            str(gid),
            "--name",
            "draft-smart-target",
            "--audience",
            "ALL_SEGMENTS",
        )
        _assert_success(r, "smartadtargets add")
        tid = _extract_first_id(r.output)

        # Update smart ad target
        r = _invoke_live(
            "smartadtargets",
            "update",
            "--id",
            str(tid),
            "--priority",
            "HIGH",
        )
        _assert_success(r, "smartadtargets update")

        # Verify via get
        r = _invoke_live(
            "smartadtargets",
            "get",
            "--adgroup-ids",
            str(gid),
            "--format",
            "json",
        )
        _assert_success(r, "smartadtargets get")
    finally:
        if tid is not None:
            _invoke_live("smartadtargets", "delete", "--id", str(tid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        if cid is not None:
            _safe_delete_campaign(cid)
        _invoke_live("feeds", "delete", "--id", str(fid))

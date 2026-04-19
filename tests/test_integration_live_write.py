"""
Manual live-write integration tests for production Yandex Direct API.

Safety contract:
- tests are skipped unless YANDEX_DIRECT_LIVE_WRITE=1 is set explicitly;
- tests never accept external resource IDs;
- every mutating command targets only a draft resource created by this test;
- cleanup fails loudly with the created ID if Yandex Direct refuses deletion.

Coverage status (issue #59):

  Phase 3 — nested inside draft campaign (Category A):
    - adgroups add/update/delete
    - ads add/update/delete (never moderate)
    - keywords add/update/delete
    - bids set
    - keywordbids set
    - audiencetargets add/delete
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


def _create_draft_campaign(suffix: str = "") -> int:
    """Create a draft campaign and return its ID. Caller must delete."""
    name = f"{_campaign_name()}-nested{suffix}"
    r = _invoke_live(
        "campaigns", "add", "--name", name, "--start-date", _future_start_date()
    )
    _assert_success(r, "campaigns add (draft)")
    return _extract_first_id(r.output)


def _safe_delete_campaign(cid: int) -> None:
    """Delete a draft campaign, failing the test if deletion is rejected."""
    r = _invoke_live("campaigns", "delete", "--id", str(cid))
    if r.exit_code != 0:
        pytest.fail(
            f"Failed to delete draft campaign {cid}. "
            f"Manual cleanup required.\noutput: {r.output}"
        )


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


# ── Phase 3: nested inside draft campaign ─────────────────────────────────


@pytest.mark.vcr
def test_live_draft_adgroups_add_update_delete() -> None:
    """Create draft campaign, add/update/get/delete adgroup."""
    cid = _create_draft_campaign("-adgroups")
    gid: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-test-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "adgroups",
            "update",
            "--id",
            str(gid),
            "--name",
            "draft-test-group-renamed",
        )
        _assert_success(r, "adgroups update")

        r = _invoke_live("adgroups", "get", "--ids", str(gid), "--format", "json")
        _assert_success(r, "adgroups get after update")
    finally:
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_ads_add_update_delete() -> None:
    """Create draft campaign + adgroup, add/update/get/delete TEXT_AD."""
    cid = _create_draft_campaign("-ads")
    gid: Optional[int] = None
    aid: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-ads-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "ads",
            "add",
            "--adgroup-id",
            str(gid),
            "--title",
            "Draft Test Ad",
            "--text",
            "Test ad text",
            "--href",
            "https://example.com",
        )
        _assert_success(r, "ads add")
        aid = _extract_first_id(r.output)

        r = _invoke_live(
            "ads", "update", "--id", str(aid), "--title", "Updated Draft Ad"
        )
        _assert_success(r, "ads update")

        r = _invoke_live("ads", "get", "--ids", str(aid), "--format", "json")
        _assert_success(r, "ads get after update")
    finally:
        if aid is not None:
            _invoke_live("ads", "delete", "--id", str(aid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_keywords_add_update_delete() -> None:
    """Create draft campaign + adgroup, add/update/get/delete keyword."""
    cid = _create_draft_campaign("-keywords")
    gid: Optional[int] = None
    kid: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-kw-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "keywords",
            "add",
            "--adgroup-id",
            str(gid),
            "--keyword",
            "draft test keyword",
        )
        _assert_success(r, "keywords add")
        kid = _extract_first_id(r.output)

        r = _invoke_live("keywords", "update", "--id", str(kid), "--bid", "10")
        _assert_success(r, "keywords update")

        r = _invoke_live(
            "keywords",
            "get",
            "--campaign-ids",
            str(cid),
            "--format",
            "json",
        )
        _assert_success(r, "keywords get after update")
    finally:
        if kid is not None:
            _invoke_live("keywords", "delete", "--id", str(kid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_bids_set() -> None:
    """Create draft campaign + adgroup + keyword, set bid."""
    cid = _create_draft_campaign("-bids")
    gid: Optional[int] = None
    kid: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-bids-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "keywords",
            "add",
            "--adgroup-id",
            str(gid),
            "--keyword",
            "draft bids keyword",
        )
        _assert_success(r, "keywords add")
        kid = _extract_first_id(r.output)

        r = _invoke_live("bids", "set", "--keyword-id", str(kid), "--bid", "15")
        _assert_success(r, "bids set")
    finally:
        if kid is not None:
            _invoke_live("keywords", "delete", "--id", str(kid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_keywordbids_set() -> None:
    """Create draft campaign + adgroup + keyword, set keywordbid."""
    cid = _create_draft_campaign("-keywordbids")
    gid: Optional[int] = None
    kid: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-kwbids-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "keywords",
            "add",
            "--adgroup-id",
            str(gid),
            "--keyword",
            "draft keywordbids keyword",
        )
        _assert_success(r, "keywords add")
        kid = _extract_first_id(r.output)

        r = _invoke_live(
            "keywordbids",
            "set",
            "--keyword-id",
            str(kid),
            "--search-bid",
            "8",
            "--network-bid",
            "3",
        )
        _assert_success(r, "keywordbids set")
    finally:
        if kid is not None:
            _invoke_live("keywords", "delete", "--id", str(kid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_audiencetargets_add_delete() -> None:
    """Create draft campaign + adgroup + retargeting list, add/delete
    audience target."""
    cid = _create_draft_campaign("-audience")
    gid: Optional[int] = None
    rtg_id: Optional[int] = None
    at_id: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-audience-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
        )
        _assert_success(r, "adgroups add")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "retargeting",
            "add",
            "--name",
            "draft-rtg-test",
            "--type",
            "RETARGETING",
            "--rule",
            "ALL:12345:30",
        )
        _assert_success(r, "retargeting add")
        rtg_id = _extract_first_id(r.output)

        r = _invoke_live(
            "audiencetargets",
            "add",
            "--adgroup-id",
            str(gid),
            "--retargeting-list-id",
            str(rtg_id),
        )
        _assert_success(r, "audiencetargets add")
        at_id = _extract_first_id(r.output)

        r = _invoke_live(
            "audiencetargets", "get", "--ids", str(at_id), "--format", "json"
        )
        _assert_success(r, "audiencetargets get")
    finally:
        if at_id is not None:
            _invoke_live("audiencetargets", "delete", "--id", str(at_id))
        if rtg_id is not None:
            _invoke_live("retargeting", "delete", "--id", str(rtg_id))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)

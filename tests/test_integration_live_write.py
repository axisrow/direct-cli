"""
Manual live-write integration tests for production Yandex Direct API.

Safety contract:
- tests are skipped unless YANDEX_DIRECT_LIVE_WRITE=1 is set explicitly;
- tests never accept external resource IDs;
- every mutating command targets only a draft resource created by this test;
- cleanup fails loudly with the created ID if Yandex Direct refuses deletion.

Coverage status (issue #59):

  Phase 2 — standalone draft assets (low risk):
    - sitelinks add/get/delete
    - adimages add/get/delete
    - advideos add/get (example.com URL rejected — partial coverage, see
      tests/MANUAL_COVERAGE.md)
    - creatives add/get (chain advideo -> creative, same URL limitation)

  Phase 3 — nested inside draft campaign (Category A):
    - adgroups add/update/delete
    - ads add/update/delete (never moderate)
    - keywords add/update/delete
    - bids set
    - keywordbids set
    - audiencetargets add/delete

  Phase 4 — non-standard campaign types (Category B):
    - dynamicads add/delete (DYNAMIC_TEXT_CAMPAIGN)
    - smartadtargets add/update/delete (SMART_CAMPAIGN)

  Phase 5 — suspend/resume smoke tests on draft:
    - keywords/audiencetargets/dynamicads/smartadtargets suspend/resume
    - ads suspend/resume/archive/unarchive
    (draft-state operations may be rejected — tests skip gracefully)
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

# 450x450 solid red PNG — meets Yandex Direct minimum image dimension
# requirements.  Validated: decodes to 1487 bytes, correct PNG header,
# dimensions 450x450 confirmed via IHDR chunk.
_PNG_B64_450X450 = (
    "iVBORw0KGgoAAAANSUhEUgAAAcIAAAHCCAIAAADzel4SAAAGs0lEQVR4nO3OQQkAQRAEsf"
    "Fv+s7DfpqCQATkvjsAnu0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUD"
    "afgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
    "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
    "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
    "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
    "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
    "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGk/"
    "KWgbKQyncKAAAAAASUVORK5CYII="
)

_DRAFT_STATE_PATTERNS = (
    "Invalid object status",
    "is draft",
    "has not been saved",
    "cannot be suspended",
    "cannot be resumed",
    "Operation is not available for object",
)


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


# ── Shared helpers ────────────────────────────────────────────────────────


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


def _extract_first_id(output: str, key: str = "AddResults") -> int | str:
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
    raw = first["Id"]
    try:
        return int(raw)
    except (ValueError, TypeError):
        return raw


def _extract_field(output: str, field: str = "Id", key: str = "AddResults") -> Any:
    """Extract a field value from the first item of an add-result response."""
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
    ), f"API rejected request: {first.get('Errors')}"
    assert field in first, f"No {field} in result: {first}"
    return first[field]


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


def _create_draft_adgroup(suffix: str = "") -> tuple:
    """Create a draft campaign + adgroup. Returns (campaign_id, adgroup_id)."""
    cid = _create_draft_campaign(suffix)
    r = _invoke_live(
        "adgroups",
        "add",
        "--name",
        "draft-group",
        "--campaign-id",
        str(cid),
        "--region-ids",
        "1,225",
    )
    _assert_success(r, "adgroups add")
    return cid, _extract_first_id(r.output)


def _safe_delete_campaign(cid: int) -> None:
    """Delete a draft campaign, failing the test if deletion is rejected."""
    r = _invoke_live("campaigns", "delete", "--id", str(cid))
    if r.exit_code != 0:
        pytest.fail(
            f"Failed to delete draft campaign {cid}. "
            f"Manual cleanup required.\noutput: {r.output}"
        )


def _is_draft_state_error(output: str) -> bool:
    """Check whether output contains a draft-state restriction error."""
    return any(p.lower() in output.lower() for p in _DRAFT_STATE_PATTERNS)


def _assert_draft_or_success(result, cmd_label: str) -> None:
    """Assert success or skip if the API rejected a draft-state operation."""
    if result.exit_code != 0 and _is_draft_state_error(result.output):
        pytest.skip(
            f"{cmd_label} rejected on draft resource (expected): "
            f"{result.output[:200]}"
        )
    _assert_success(result, cmd_label)


# ── Root fixture ──────────────────────────────────────────────────────────


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


# ── Phase 2: standalone draft assets ──────────────────────────────────────


@pytest.mark.vcr
def test_live_draft_sitelinks_add_get_delete() -> None:
    """Create a sitelink set, verify via get, then delete it."""
    r = _invoke_live(
        "sitelinks",
        "add",
        "--sitelink",
        "CLI Test|https://example.com/test",
        "--sitelink",
        "CLI Test 2|https://example.com/test2",
    )
    _assert_success(r, "sitelinks add")
    sitelink_id = _extract_first_id(r.output)

    try:
        r = _invoke_live(
            "sitelinks", "get", "--ids", str(sitelink_id), "--format", "json"
        )
        _assert_success(r, "sitelinks get")
    finally:
        r = _invoke_live("sitelinks", "delete", "--id", str(sitelink_id))
        if r.exit_code != 0:
            pytest.fail(
                f"Failed to delete sitelink set {sitelink_id}. "
                f"Manual cleanup required.\noutput: {r.output}"
            )


@pytest.mark.vcr
def test_live_draft_adimages_add_get_delete() -> None:
    """Upload a test PNG image, verify via get, then delete by hash."""
    r = _invoke_live(
        "adimages",
        "add",
        "--name",
        "draft-test-image.png",
        "--image-data",
        _PNG_B64_450X450,
    )
    # API may reject the image on accounts where image upload is restricted
    # (error 5004). Treat as a documented limitation — see MANUAL_COVERAGE.md.
    if "5004" in r.output:
        pytest.skip("adimages upload rejected (error 5004) — account restriction")
    _assert_success(r, "adimages add")
    img_hash = _extract_field(r.output, field="AdImageHash")

    try:
        r = _invoke_live(
            "adimages",
            "get",
            "--fields",
            "AdImageHash,Name",
            "--format",
            "json",
        )
        _assert_success(r, "adimages get")
        data = json.loads(r.output)
        if isinstance(data, list):
            images = data
        else:
            result_data = data.get("result", data)
            images = result_data.get("AdImages", [])
        hashes_in_response = {
            img.get("AdImageHash") for img in images
        }
        assert (
            img_hash in hashes_in_response
        ), f"Uploaded image hash {img_hash} not found in get response"
    finally:
        r = _invoke_live("adimages", "delete", "--hash", str(img_hash))
        if r.exit_code != 0:
            pytest.fail(
                f"Failed to delete ad image {img_hash}. "
                f"Manual cleanup required.\noutput: {r.output}"
            )


@pytest.mark.vcr
def test_live_draft_advideos_add_get() -> None:
    """Add a video from file and verify via get."""
    video_file = os.path.join(
        os.path.dirname(__file__), "fixtures", "test-video.mp4"
    )
    r = _invoke_live(
        "advideos",
        "add",
        "--video-file",
        video_file,
        "--name",
        "draft-test-video",
    )
    _assert_success(r, "advideos add")
    # advideos API does not expose a delete method — uploaded videos accumulate
    # in the account and cannot be cleaned up programmatically.
    video_id = _extract_first_id(r.output)
    r = _invoke_live("advideos", "get", "--ids", str(video_id), "--format", "json")
    _assert_success(r, "advideos get")


@pytest.mark.vcr
def test_live_draft_creatives_chain_advideo_to_creative() -> None:
    """Chain: add advideo from file -> create creative from it -> verify via get."""
    video_file = os.path.join(
        os.path.dirname(__file__), "fixtures", "test-video.mp4"
    )
    r = _invoke_live(
        "advideos",
        "add",
        "--video-file",
        video_file,
        "--name",
        "draft-creative-video",
    )
    _assert_success(r, "advideos add")
    # advideos API does not expose a delete method — uploaded videos accumulate
    # in the account and cannot be cleaned up programmatically.
    video_id = _extract_first_id(r.output)

    r = _invoke_live("creatives", "add", "--video-id", str(video_id))
    _assert_success(r, "creatives add")
    creative_id = _extract_first_id(r.output)

    r = _invoke_live("creatives", "get", "--ids", str(creative_id), "--format", "json")
    _assert_success(r, "creatives get")


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

        r = _invoke_live(
            "keywords", "update", "--id", str(kid), "--keyword", "draft test keyword updated"
        )
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
        # 8800 = goal_id 12345 not found in account — account restriction.
        if "8800" in r.output:
            pytest.skip("retargeting add rejected (8800) — goal not found in account")
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
        if "8800" in r.output:
            pytest.skip("audiencetargets add rejected (8800) — account restriction")
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


# ── Phase 4: non-standard campaign types (Category B) ────────────────────


@pytest.mark.vcr
def test_live_draft_dynamicads_add_delete() -> None:
    """Create DYNAMIC_TEXT_CAMPAIGN, add dynamic ad target, verify, delete."""
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
    # 3500 = campaign type not supported on this account (agency-only feature)
    # See API_COVERAGE.md Category B and MANUAL_COVERAGE.md.
    if "3500" in r.output:
        pytest.skip("DYNAMIC_TEXT_CAMPAIGN not supported on this account (3500)")
    _assert_success(r, "campaigns add (DYNAMIC_TEXT_CAMPAIGN)")
    cid = _extract_first_id(r.output)
    gid: Optional[int] = None
    did: Optional[int] = None

    try:
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
        if isinstance(data, list):
            targets = data
        else:
            result_data = data.get("result", data)
            targets = result_data.get("DynamicTextAdTargets", [])
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
        # 3500 = campaign type not supported on this account (agency-only feature)
        # See API_COVERAGE.md Category B and MANUAL_COVERAGE.md.
        if "3500" in r.output:
            pytest.skip("SMART_CAMPAIGN not supported on this account (3500)")
        _assert_success(r, "campaigns add (SMART_CAMPAIGN)")
        cid = _extract_first_id(r.output)

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

        r = _invoke_live(
            "smartadtargets",
            "update",
            "--id",
            str(tid),
            "--priority",
            "HIGH",
        )
        _assert_success(r, "smartadtargets update")

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


# ── Phase 5: suspend/resume smoke on draft ────────────────────────────────


@pytest.mark.vcr
def test_live_draft_keywords_suspend_resume() -> None:
    """Smoke-test keywords suspend/resume on draft keyword."""
    cid, gid = _create_draft_adgroup("-kw-sr")
    kid: Optional[int] = None

    try:
        r = _invoke_live(
            "keywords",
            "add",
            "--adgroup-id",
            str(gid),
            "--keyword",
            "draft sr keyword",
        )
        _assert_success(r, "keywords add")
        kid = _extract_first_id(r.output)

        r = _invoke_live("keywords", "suspend", "--id", str(kid))
        _assert_draft_or_success(r, "keywords suspend")

        r = _invoke_live("keywords", "resume", "--id", str(kid))
        _assert_draft_or_success(r, "keywords resume")
    finally:
        if kid is not None:
            _invoke_live("keywords", "delete", "--id", str(kid))
        _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_audiencetargets_suspend_resume() -> None:
    """Smoke-test audiencetargets suspend/resume on draft target."""
    cid, gid = _create_draft_adgroup("-at-sr")
    rtg_id: Optional[int] = None
    at_id: Optional[int] = None

    try:
        r = _invoke_live(
            "retargeting",
            "add",
            "--name",
            "draft-sr-rtg",
            "--type",
            "RETARGETING",
            "--rule",
            "ALL:12345:30",
        )
        if "8800" in r.output:
            pytest.skip("retargeting add rejected (8800) — goal not found in account")
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
        if "8800" in r.output:
            pytest.skip("audiencetargets add rejected (8800) — account restriction")
        _assert_success(r, "audiencetargets add")
        at_id = _extract_first_id(r.output)

        r = _invoke_live("audiencetargets", "suspend", "--id", str(at_id))
        _assert_draft_or_success(r, "audiencetargets suspend")

        r = _invoke_live("audiencetargets", "resume", "--id", str(at_id))
        _assert_draft_or_success(r, "audiencetargets resume")
    finally:
        if at_id is not None:
            _invoke_live("audiencetargets", "delete", "--id", str(at_id))
        if rtg_id is not None:
            _invoke_live("retargeting", "delete", "--id", str(rtg_id))
        _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_dynamicads_suspend_resume() -> None:
    """Smoke-test dynamicads suspend/resume on draft target."""
    r = _invoke_live(
        "campaigns",
        "add",
        "--name",
        f"{_campaign_name()}-dyn-sr",
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
    if "3500" in r.output:
        pytest.skip("DYNAMIC_TEXT_CAMPAIGN not supported on this account (3500)")
    _assert_success(r, "campaigns add (DYNAMIC)")
    cid = _extract_first_id(r.output)
    gid: Optional[int] = None
    did: Optional[int] = None

    try:
        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-dyn-sr-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
            "--type",
            "DYNAMIC_TEXT_AD_GROUP",
            "--domain-url",
            "example.com",
        )
        _assert_success(r, "adgroups add (DYNAMIC)")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "dynamicads",
            "add",
            "--adgroup-id",
            str(gid),
            "--name",
            "SR Dynamic Target",
            "--condition",
            "URL:CONTAINS_ANY:test",
        )
        _assert_success(r, "dynamicads add")
        did = _extract_first_id(r.output)

        r = _invoke_live("dynamicads", "suspend", "--id", str(did))
        _assert_draft_or_success(r, "dynamicads suspend")

        r = _invoke_live("dynamicads", "resume", "--id", str(did))
        _assert_draft_or_success(r, "dynamicads resume")
    finally:
        if did is not None:
            _invoke_live("dynamicads", "delete", "--id", str(did))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)


@pytest.mark.vcr
def test_live_draft_smartadtargets_suspend_resume() -> None:
    """Smoke-test smartadtargets suspend/resume on draft target."""
    r = _invoke_live(
        "feeds",
        "add",
        "--name",
        "draft-sr-smart-feed",
        "--url",
        "https://example.com/feed.xml",
    )
    _assert_success(r, "feeds add")
    fid = _extract_first_id(r.output)
    cid: Optional[int] = None
    gid: Optional[int] = None
    tid: Optional[int] = None

    try:
        r = _invoke_live(
            "campaigns",
            "add",
            "--name",
            f"{_campaign_name()}-smart-sr",
            "--start-date",
            _future_start_date(),
            "--type",
            "SMART_CAMPAIGN",
            "--network-strategy",
            "AVERAGE_CPC_PER_FILTER",
            "--filter-average-cpc",
            "1",
        )
        if "3500" in r.output:
            pytest.skip("SMART_CAMPAIGN not supported on this account (3500)")
        _assert_success(r, "campaigns add (SMART)")
        cid = _extract_first_id(r.output)

        r = _invoke_live(
            "adgroups",
            "add",
            "--name",
            "draft-smart-sr-group",
            "--campaign-id",
            str(cid),
            "--region-ids",
            "1,225",
            "--type",
            "SMART_AD_GROUP",
            "--feed-id",
            str(fid),
        )
        _assert_success(r, "adgroups add (SMART)")
        gid = _extract_first_id(r.output)

        r = _invoke_live(
            "smartadtargets",
            "add",
            "--adgroup-id",
            str(gid),
            "--name",
            "sr-smart-target",
            "--audience",
            "ALL_SEGMENTS",
        )
        _assert_success(r, "smartadtargets add")
        tid = _extract_first_id(r.output)

        r = _invoke_live("smartadtargets", "suspend", "--id", str(tid))
        _assert_draft_or_success(r, "smartadtargets suspend")

        r = _invoke_live("smartadtargets", "resume", "--id", str(tid))
        _assert_draft_or_success(r, "smartadtargets resume")
    finally:
        if tid is not None:
            _invoke_live("smartadtargets", "delete", "--id", str(tid))
        if gid is not None:
            _invoke_live("adgroups", "delete", "--id", str(gid))
        if cid is not None:
            _safe_delete_campaign(cid)
        _invoke_live("feeds", "delete", "--id", str(fid))


@pytest.mark.vcr
def test_live_draft_ads_suspend_resume_archive_unarchive() -> None:
    """Smoke-test ads suspend/resume/archive/unarchive on draft ad."""
    cid, gid = _create_draft_adgroup("-ads-sr")
    aid: Optional[int] = None

    try:
        r = _invoke_live(
            "ads",
            "add",
            "--adgroup-id",
            str(gid),
            "--title",
            "SR Draft Ad",
            "--text",
            "Test ad",
            "--href",
            "https://example.com",
        )
        _assert_success(r, "ads add")
        aid = _extract_first_id(r.output)

        r = _invoke_live("ads", "suspend", "--id", str(aid))
        _assert_draft_or_success(r, "ads suspend")

        r = _invoke_live("ads", "resume", "--id", str(aid))
        _assert_draft_or_success(r, "ads resume")

        r = _invoke_live("ads", "archive", "--id", str(aid))
        _assert_draft_or_success(r, "ads archive")

        r = _invoke_live("ads", "unarchive", "--id", str(aid))
        _assert_draft_or_success(r, "ads unarchive")
    finally:
        if aid is not None:
            _invoke_live("ads", "delete", "--id", str(aid))
        _invoke_live("adgroups", "delete", "--id", str(gid))
        _safe_delete_campaign(cid)

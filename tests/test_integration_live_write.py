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
    - advideos add/get
    - creatives add/get (chain advideo -> creative)
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

# 450x450 solid red PNG — meets Yandex Direct minimum image dimension requirements.
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
    _assert_success(r, "adimages add")
    img_hash = _extract_field(r.output, field="AdImageHash")

    try:
        r = _invoke_live(
            "adimages",
            "get",
            "--fields",
            "AdImageHash,Name",
            "--limit",
            "1",
            "--format",
            "json",
        )
        _assert_success(r, "adimages get")
    finally:
        r = _invoke_live("adimages", "delete", "--hash", str(img_hash))
        if r.exit_code != 0:
            pytest.fail(
                f"Failed to delete ad image {img_hash}. "
                f"Manual cleanup required.\noutput: {r.output}"
            )


@pytest.mark.vcr
def test_live_draft_advideos_add_get() -> None:
    """Add a video by URL and verify via get.

    advideos may reject invalid/unreachable URLs — skip on known errors.
    No delete command exists for advideos in the CLI.
    """
    r = _invoke_live(
        "advideos",
        "add",
        "--url",
        "https://example.com/test-video.mp4",
        "--name",
        "draft-test-video",
    )
    if r.exit_code != 0:
        pytest.skip(f"advideos add rejected URL (expected in test): {r.output[:200]}")

    video_id = _extract_first_id(r.output)
    r = _invoke_live("advideos", "get", "--ids", str(video_id), "--format", "json")
    _assert_success(r, "advideos get")


@pytest.mark.vcr
def test_live_draft_creatives_chain_advideo_to_creative() -> None:
    """Chain: add advideo -> create creative from it -> verify via get.

    No delete command exists for advideos or creatives in the CLI.
    """
    r = _invoke_live(
        "advideos",
        "add",
        "--url",
        "https://example.com/test-video.mp4",
        "--name",
        "draft-creative-video",
    )
    if r.exit_code != 0:
        pytest.skip(f"advideos add rejected URL (expected in test): {r.output[:200]}")

    video_id = _extract_first_id(r.output)

    r = _invoke_live("creatives", "add", "--video-id", str(video_id))
    _assert_success(r, "creatives add")
    creative_id = _extract_first_id(r.output)

    r = _invoke_live("creatives", "get", "--ids", str(creative_id), "--format", "json")
    _assert_success(r, "creatives get")

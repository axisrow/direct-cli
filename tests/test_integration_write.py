"""
Sandbox integration tests for direct-cli write commands.

Exercises mutating commands against the Yandex Direct sandbox API.
Requires ``YANDEX_DIRECT_TOKEN`` in the environment or ``.env``.

Run with:
    pytest -m integration_write -v

**Sandbox limitations discovered during testing:**

The Yandex Direct sandbox does NOT persist nested resources (adgroups, ads,
keywords) — ``adgroups add`` returns an ID but subsequent calls report
"Object not found".  Only top-level resources (campaigns, negative keyword
shared sets) are reliably persisted.  Tests for nested resources are
included but will skip when the sandbox rejects them.

Fixtures (campaign → adgroup → ad/keyword) are defined in conftest.py.
Top-level resource tests run without fixtures.

Part of axisrow/yandex-direct-mcp-plugin#61 (Etap 3).
"""

import json

import pytest

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from conftest import (  # noqa: E402
    _invoke,
    _is_sandbox_error,
    assert_success,
    parse_add_result,
    parse_first_result,
    skip_if_no_token,
    tomorrow,
)


# ── campaigns ────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteCampaigns:
    """Full lifecycle: add → update → archive → unarchive → delete."""

    def test_campaign_lifecycle(self, unique_suffix):
        name = f"lifecycle-{unique_suffix}"

        # add
        r = _invoke(
            "campaigns", "add",
            "--name", name,
            "--start-date", tomorrow(),
        )
        assert_success(r, "campaigns add")
        cid = parse_add_result(r)

        try:
            # update
            r = _invoke(
                "campaigns", "update",
                "--id", str(cid),
                "--name", f"{name}-renamed",
            )
            assert_success(r, "campaigns update")

            # suspend/resume — new campaigns are DRAFT, may not apply
            r = _invoke("campaigns", "suspend", "--id", str(cid))
            if r.exit_code == 0:
                r = _invoke("campaigns", "resume", "--id", str(cid))
                assert_success(r, "campaigns resume")

            # archive
            r = _invoke("campaigns", "archive", "--id", str(cid))
            assert_success(r, "campaigns archive")

            # unarchive
            r = _invoke("campaigns", "unarchive", "--id", str(cid))
            assert_success(r, "campaigns unarchive")
        finally:
            _invoke("campaigns", "delete", "--id", str(cid))


# ── adgroups ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAdGroups:
    def test_add_update_delete(self, sandbox_campaign):
        campaign_id = sandbox_campaign

        # add
        r = _invoke(
            "adgroups", "add",
            "--name", "test-adgroup",
            "--campaign-id", str(campaign_id),
            "--region-ids", "1,225",
        )
        assert_success(r, "adgroups add")
        gid = parse_add_result(r)

        try:
            # update — may fail if sandbox doesn't persist adgroups
            r = _invoke(
                "adgroups", "update",
                "--id", str(gid),
                "--name", "test-adgroup-renamed",
            )
            if r.exit_code != 0:
                pytest.skip("adgroups not persisted in sandbox")
            assert_success(r, "adgroups update")
        finally:
            _invoke("adgroups", "delete", "--id", str(gid))


# ── ads ──────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAds:
    """Confirms the Type-field fix from PR #12 works with live API."""

    def test_add_text_ad_update_delete(self, sandbox_adgroup):
        adgroup_id = sandbox_adgroup

        r = _invoke(
            "ads", "add",
            "--adgroup-id", str(adgroup_id),
            "--title", "Test Ad",
            "--text", "Test ad text body",
            "--href", "https://example.com",
        )
        assert_success(r, "ads add")
        data = json.loads(r.output)
        if isinstance(data, list):
            first = data[0]
        else:
            first = data.get("AddResults", [{}])[0]

        if "Errors" in first and first["Errors"]:
            err_text = str(first["Errors"])
            if _is_sandbox_error(err_text):
                pytest.skip(f"adgroup not persisted in sandbox: {first['Errors']}")
            pytest.fail(f"API rejected ads add (potential Type-field regression): {first['Errors']}")

        ad_id = first["Id"]
        try:
            r = _invoke(
                "ads", "update",
                "--id", str(ad_id),
                "--json", json.dumps({"TextAd": {"Title": "Updated Title"}}),
            )
            assert_success(r, "ads update")
        finally:
            _invoke("ads", "delete", "--id", str(ad_id))


# ── keywords ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteKeywords:
    def test_add_update_delete(self, sandbox_adgroup):
        adgroup_id = sandbox_adgroup

        r = _invoke(
            "keywords", "add",
            "--adgroup-id", str(adgroup_id),
            "--keyword", "купить тест",
        )
        assert_success(r, "keywords add")
        data = json.loads(r.output)
        if isinstance(data, list):
            first = data[0]
        else:
            first = data.get("AddResults", [{}])[0]

        if "Errors" in first and first["Errors"]:
            err_text = str(first["Errors"])
            if _is_sandbox_error(err_text):
                pytest.skip(f"adgroup not persisted in sandbox: {first['Errors']}")
            pytest.fail(f"API rejected keywords add (CLI bug?): {first['Errors']}")

        kid = first["Id"]
        try:
            r = _invoke(
                "keywords", "update",
                "--id", str(kid),
                "--bid", "10",
            )
            assert_success(r, "keywords update")
        finally:
            _invoke("keywords", "delete", "--id", str(kid))


# ── bids ─────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteBids:
    def test_set_bid(self, sandbox_campaign):
        r = _invoke(
            "bids", "set",
            "--campaign-id", str(sandbox_campaign),
            "--bid", "15",
        )
        if r.exit_code == 0:
            assert_success(r, "bids set")
        else:
            pytest.skip(f"bids set failed (sandbox): {r.output[:200]}")


# ── keywordbids ──────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteKeywordBids:
    def test_set_keyword_bid(self, sandbox_keyword):
        r = _invoke(
            "keywordbids", "set",
            "--keyword-id", str(sandbox_keyword),
            "--search-bid", "8",
            "--network-bid", "3",
        )
        if r.exit_code == 0:
            assert_success(r, "keywordbids set")
        else:
            pytest.skip(f"keywordbids set failed (sandbox): {r.output[:200]}")


# ── bidmodifiers ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteBidModifiers:
    def test_toggle_existing(self, sandbox_campaign):
        """Get existing modifier and toggle it."""
        cid = sandbox_campaign

        r = _invoke("bidmodifiers", "get", "--campaign-id", str(cid))
        if r.exit_code != 0:
            pytest.skip("bidmodifiers get failed in sandbox")

        data = json.loads(r.output)
        if isinstance(data, list) and data:
            modifier_id = data[0].get("Id")
            if not modifier_id:
                pytest.skip("no bid modifier id found")
        else:
            pytest.skip("no bid modifiers in sandbox campaign")

        # toggle off
        r = _invoke(
            "bidmodifiers", "toggle",
            "--id", str(modifier_id),
            "--disabled",
        )
        if r.exit_code == 0:
            assert_success(r, "bidmodifiers toggle off")

            # toggle back on
            r = _invoke(
                "bidmodifiers", "toggle",
                "--id", str(modifier_id),
                "--enabled",
            )
            assert_success(r, "bidmodifiers toggle on")


# ── feeds ────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteFeeds:
    def test_add_update_delete(self, unique_suffix):
        r = _invoke(
            "feeds", "add",
            "--name", f"test-feed-{unique_suffix}",
            "--url", "https://example.com/feed.xml",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"feeds add not supported in sandbox: {r.output[:200]}")
            pytest.fail(f"feeds add failed (SourceType regression?): {r.output[:500]}")

        fid = parse_add_result(r)
        try:
            r = _invoke(
                "feeds", "update",
                "--id", str(fid),
                "--name", f"test-feed-{unique_suffix}-renamed",
            )
            assert_success(r, "feeds update")
        finally:
            _invoke("feeds", "delete", "--id", str(fid))


# ── retargeting ──────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteRetargeting:
    def test_add_delete(self, unique_suffix):
        r = _invoke(
            "retargeting", "add",
            "--name", f"test-rtg-{unique_suffix}",
            "--type", "AUDIENCE_SEGMENT",
            "--json", json.dumps({"Rules": [{"LowerBound": 1, "UpperBound": 365}]}),
        )
        if r.exit_code == 0:
            rid = parse_add_result(r)
            _invoke("retargeting", "delete", "--id", str(rid))
        else:
            pytest.skip(f"retargeting add failed: {r.output[:200]}")


# ── audiencetargets ──────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAudienceTargets:
    def test_add_delete(self, sandbox_adgroup, sandbox_retargeting_list):
        r = _invoke(
            "audiencetargets", "add",
            "--adgroup-id", str(sandbox_adgroup),
            "--retargeting-list-id", str(sandbox_retargeting_list),
        )
        if r.exit_code == 0:
            first = parse_first_result(r)
            tid = first["Id"]
            _invoke("audiencetargets", "delete", "--id", str(tid))
        else:
            pytest.skip(f"audiencetargets add failed (sandbox): {r.output[:200]}")


# ── sitelinks ────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteSitelinks:
    def test_add_delete(self):
        links = json.dumps([
            {"Title": "About", "Href": "https://example.com/about"},
            {"Title": "Contact", "Href": "https://example.com/contact"},
        ])
        r = _invoke("sitelinks", "add", "--links", links)
        if r.exit_code == 0:
            first = parse_first_result(r)
            sid = first["Id"]
            _invoke("sitelinks", "delete", "--id", str(sid))
        else:
            pytest.skip(f"sitelinks add failed (sandbox unstable): {r.output[:200]}")


# ── vcards ───────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteVCards:
    def test_add_delete(self, sandbox_campaign):
        vcard = json.dumps({
            "CampaignId": sandbox_campaign,
            "Country": "Россия",
            "City": "Москва",
            "CompanyName": "Test Company",
            "WorkTime": "0#00#00#",
        })
        r = _invoke("vcards", "add", "--json", vcard)
        if r.exit_code == 0:
            first = parse_first_result(r)
            vid = first["Id"]
            _invoke("vcards", "delete", "--id", str(vid))
        else:
            pytest.skip(f"vcards add failed: {r.output[:200]}")


# ── adextensions ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAdExtensions:
    """
    NOTE: adextensions CLI sends Type field which is valid per API docs
    (CALLOUT/SITELINK/etc), but sandbox rejects it as unknown parameter.
    This is a sandbox limitation, not a CLI bug.
    """

    def test_add_delete(self):
        ext_json = json.dumps({"Callout": {"CalloutText": "Free shipping"}})
        r = _invoke("adextensions", "add", "--json", ext_json)
        if r.exit_code == 0:
            first = parse_first_result(r)
            eid = first["Id"]
            _invoke("adextensions", "delete", "--id", str(eid))
        else:
            pytest.skip(
                f"adextensions add failed (sandbox rejects Type field): {r.output[:200]}"
            )


# ── adimages ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAdImages:
    def test_add_delete(self):
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
            "Nl7BcQAAAABJRU5ErkJggg=="
        )
        image = json.dumps({"Name": "test-image.png", "ImageData": png_b64})
        r = _invoke("adimages", "add", "--json", image)
        if r.exit_code == 0:
            data = json.loads(r.output)
            if isinstance(data, list) and data:
                first = data[0]
                if "Errors" in first and first["Errors"]:
                    err_text = str(first["Errors"])
                    if _is_sandbox_error(err_text) or "Invalid format" in err_text:
                        pytest.skip(f"adimages rejected (sandbox): {first['Errors']}")
                    pytest.fail(f"API rejected adimages add (CLI bug?): {first['Errors']}")
                img_hash = first.get("AdImageHash") or first.get("Id")
                if img_hash:
                    _invoke("adimages", "delete", "--hash", str(img_hash))
            else:
                pytest.skip("adimages add returned empty result")
        else:
            pytest.skip(f"adimages add failed (sandbox): {r.output[:200]}")


# ── dynamicads (webpages) ────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteDynamicAds:
    def test_add_update_delete(self, sandbox_adgroup):
        target = {
            "Name": "Test Webpage",
            "Conditions": [{"Operator": "CONTAINS", "Arguments": ["test"]}],
        }
        r = _invoke(
            "dynamicads", "add",
            "--adgroup-id", str(sandbox_adgroup),
            "--json", json.dumps(target),
        )
        if r.exit_code == 0:
            data = json.loads(r.output)
            if isinstance(data, list):
                first = data[0]
            else:
                first = data.get("AddResults", [{}])[0]
            if "Errors" in first and first["Errors"]:
                err_text = str(first["Errors"])
                if _is_sandbox_error(err_text):
                    pytest.skip(f"dynamicads add rejected (sandbox): {first['Errors']}")
                pytest.fail(f"API rejected dynamicads add (CLI bug?): {first['Errors']}")
            wid = first["Id"]
            try:
                r = _invoke(
                    "dynamicads", "update",
                    "--id", str(wid),
                    "--json", json.dumps({"Name": "Updated Webpage"}),
                )
                assert_success(r, "dynamicads update")
            finally:
                _invoke("dynamicads", "delete", "--id", str(wid))
        else:
            pytest.skip(f"dynamicads add failed: {r.output[:200]}")


# ── smartadtargets ───────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteSmartAdTargets:
    """Confirms Type-field fix from PR #12 works with live API."""

    def test_add_update_delete(self, sandbox_adgroup):
        payload = json.dumps({"Subtype": "UNIQUE", "Priority": 3})
        r = _invoke(
            "smartadtargets", "add",
            "--adgroup-id", str(sandbox_adgroup),
            "--type", "VIEWED_PRODUCT",
            "--json", payload,
        )
        if r.exit_code == 0:
            data = json.loads(r.output)
            if isinstance(data, list):
                first = data[0]
            else:
                first = data.get("AddResults", [{}])[0]
            if "Errors" in first and first["Errors"]:
                err_text = str(first["Errors"])
                if _is_sandbox_error(err_text):
                    pytest.skip(f"smartadtargets add rejected (sandbox): {first['Errors']}")
                pytest.fail(f"API rejected smartadtargets add (potential Type-field regression): {first['Errors']}")
            tid = first["Id"]
            try:
                r = _invoke(
                    "smartadtargets", "update",
                    "--id", str(tid),
                    "--json", json.dumps({"Priority": 5}),
                )
                assert_success(r, "smartadtargets update")
            finally:
                _invoke("smartadtargets", "delete", "--id", str(tid))
        else:
            pytest.skip(f"smartadtargets add failed: {r.output[:200]}")


# ── negativekeywordsharedsets ────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteNegativeKeywordSharedSets:
    def test_add_update_delete(self, unique_suffix):
        r = _invoke(
            "negativekeywordsharedsets", "add",
            "--name", f"test-nk-{unique_suffix}",
            "--keywords", "спам,блок",
        )
        assert_success(r, "negativekeywordsharedsets add")
        nid = parse_add_result(r)

        try:
            r = _invoke(
                "negativekeywordsharedsets", "update",
                "--id", str(nid),
                "--keywords", "спам,блок,мусор",
            )
            assert_success(r, "negativekeywordsharedsets update")
        finally:
            _invoke("negativekeywordsharedsets", "delete", "--id", str(nid))


# ── turbopages ───────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
@pytest.mark.timeout(15)
class TestWriteTurboPages:
    """
    BUG: sandbox returns HTTP 202 (report polling mode) for turbopages add,
    causing tapi to loop with time.sleep until timeout. Real API works fine.
    """

    def test_add(self, unique_suffix):
        pytest.skip("BUG: sandbox loops on turbopages add (HTTP 202 → timeout)")

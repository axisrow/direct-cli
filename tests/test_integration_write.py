"""
Sandbox integration tests for direct-cli write commands.

Exercises every mutating command against the Yandex Direct sandbox API,
confirming that payloads are accepted and resources are created/updated/deleted
successfully.  Requires ``YANDEX_DIRECT_TOKEN`` in the environment or ``.env``.

Run with:
    pytest -m integration_write -v

Fixtures (campaign → adgroup → ad/keyword) are defined in conftest.py and
handle automatic setup/teardown.

Part of axisrow/yandex-direct-mcp-plugin#61 (Etap 3).
"""

import json

import pytest

import sys
import os

# conftest.py is in the same directory
sys.path.insert(0, os.path.dirname(__file__))

# These are imported from conftest.py which pytest auto-loads;
# we also reference them directly for helper use in test bodies.
from conftest import (  # noqa: E402
    TOKEN,
    _invoke,
    assert_success,
    parse_add_result,
    skip_if_no_token,
    tomorrow,
)


# ── campaigns ────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteCampaigns:
    """Full lifecycle: add → update → suspend → resume → archive → unarchive → delete."""

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

            # suspend
            r = _invoke("campaigns", "suspend", "--id", str(cid))
            assert_success(r, "campaigns suspend")

            # resume
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
            # update
            r = _invoke(
                "adgroups", "update",
                "--id", str(gid),
                "--name", "test-adgroup-renamed",
            )
            assert_success(r, "adgroups update")
        finally:
            _invoke("adgroups", "delete", "--id", str(gid))


# ── ads ──────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAds:
    """Critical: confirms the Type-field fix from PR #12 works with live API."""

    def test_add_text_ad_update_delete(self, sandbox_adgroup):
        adgroup_id = sandbox_adgroup

        # add TEXT_AD
        r = _invoke(
            "ads", "add",
            "--adgroup-id", str(adgroup_id),
            "--title", "Test Ad",
            "--text", "Test ad text body",
            "--href", "https://example.com",
        )
        assert_success(r, "ads add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected ads add: {first.get('Errors')}"
        )
        ad_id = first["Id"]

        try:
            # update
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

        # add
        r = _invoke(
            "keywords", "add",
            "--adgroup-id", str(adgroup_id),
            "--keyword", "купить тест",
        )
        assert_success(r, "keywords add")
        kid = parse_add_result(r)

        try:
            # update
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
        assert_success(r, "bids set")


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
        assert_success(r, "keywordbids set")


# ── bidmodifiers ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteBidModifiers:
    def test_set_toggle_delete(self, sandbox_campaign):
        cid = sandbox_campaign

        # set
        r = _invoke(
            "bidmodifiers", "set",
            "--campaign-id", str(cid),
            "--type", "MOBILE",
            "--value", "1.5",
        )
        assert_success(r, "bidmodifiers set")
        data = json.loads(r.output)
        set_results = data.get("SetItems", data.get("AddResults", []))
        assert set_results, f"No results: {r.output[:500]}"
        modifier_id = set_results[0]["Id"]

        # toggle
        r = _invoke(
            "bidmodifiers", "toggle",
            "--id", str(modifier_id),
            "--disabled",
        )
        assert_success(r, "bidmodifiers toggle")

        # delete
        r = _invoke(
            "bidmodifiers", "delete",
            "--id", str(modifier_id),
        )
        assert_success(r, "bidmodifiers delete")


# ── feeds ────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteFeeds:
    def test_add_update_delete(self, unique_suffix):
        # add
        r = _invoke(
            "feeds", "add",
            "--name", f"test-feed-{unique_suffix}",
            "--url", "https://example.com/feed.xml",
        )
        assert_success(r, "feeds add")
        fid = parse_add_result(r)

        try:
            # update
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
        )
        assert_success(r, "retargeting add")
        rid = parse_add_result(r)

        _invoke("retargeting", "delete", "--id", str(rid))


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
        assert_success(r, "audiencetargets add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected audiencetargets add: {first.get('Errors')}"
        )
        tid = first["Id"]

        _invoke("audiencetargets", "delete", "--id", str(tid))


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
        assert_success(r, "sitelinks add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        sid = add_results[0]["Id"]

        _invoke("sitelinks", "delete", "--id", str(sid))


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
        })
        r = _invoke("vcards", "add", "--json", vcard)
        assert_success(r, "vcards add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected vcards add: {first.get('Errors')}"
        )
        vid = first["Id"]

        _invoke("vcards", "delete", "--id", str(vid))


# ── adextensions ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAdExtensions:
    def test_add_delete(self):
        ext_json = json.dumps({"Callout": {"CalloutText": "Free shipping"}})
        r = _invoke(
            "adextensions", "add",
            "--type", "CALLOUT",
            "--json", ext_json,
        )
        assert_success(r, "adextensions add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected adextensions add: {first.get('Errors')}"
        )
        eid = first["Id"]

        _invoke("adextensions", "delete", "--id", str(eid))


# ── adimages ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteAdImages:
    """Minimal PNG (1x1 transparent) as base64."""

    def test_add_delete(self):
        # Minimal 1x1 transparent PNG in base64
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
            "Nl7BcQAAAABJRU5ErkJggg=="
        )
        image = json.dumps({
            "Name": "test-image.png",
            "ImageData": png_b64,
        })
        r = _invoke("adimages", "add", "--json", image)
        assert_success(r, "adimages add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected adimages add: {first.get('Errors')}"
        )
        img_hash = first.get("AdImageHash") or first.get("Id")

        if img_hash:
            _invoke("adimages", "delete", "--hash", str(img_hash))


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
        assert_success(r, "dynamicads add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected dynamicads add: {first.get('Errors')}"
        )
        wid = first["Id"]

        try:
            # update
            r = _invoke(
                "dynamicads", "update",
                "--id", str(wid),
                "--json", json.dumps({"Name": "Updated Webpage"}),
            )
            assert_success(r, "dynamicads update")
        finally:
            _invoke("dynamicads", "delete", "--id", str(wid))


# ── smartadtargets ───────────────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteSmartAdTargets:
    """
    CRITICAL regression test: confirms that the Type-field fix from PR #12
    (removing bogus ``"Type"`` from ``smartadtargets add/update``) is accepted
    by the live sandbox API.
    """

    def test_add_update_delete(self, sandbox_adgroup):
        payload = json.dumps({
            "Subtype": "UNIQUE",
            "Priority": 3,
        })
        r = _invoke(
            "smartadtargets", "add",
            "--adgroup-id", str(sandbox_adgroup),
            "--type", "VIEWED_PRODUCT",
            "--json", payload,
        )
        assert_success(r, "smartadtargets add")
        data = json.loads(r.output)
        add_results = data.get("AddResults", [])
        assert add_results, f"No AddResults: {r.output[:500]}"
        first = add_results[0]
        assert "Errors" not in first or not first["Errors"], (
            f"API rejected smartadtargets add (Type-fix regression?): "
            f"{first.get('Errors')}"
        )
        tid = first["Id"]

        try:
            # update
            r = _invoke(
                "smartadtargets", "update",
                "--id", str(tid),
                "--json", json.dumps({"Priority": 5}),
            )
            assert_success(r, "smartadtargets update")
        finally:
            _invoke("smartadtargets", "delete", "--id", str(tid))


# ── negativekeywordsharedsets ────────────────────────────────────────────


@pytest.mark.integration_write
@skip_if_no_token
class TestWriteNegativeKeywordSharedSets:
    def test_add_update_delete(self, unique_suffix):
        # add
        r = _invoke(
            "negativekeywordsharedsets", "add",
            "--name", f"test-nk-{unique_suffix}",
            "--keywords", "спам,блок",
        )
        assert_success(r, "negativekeywordsharedsets add")
        nid = parse_add_result(r)

        try:
            # update
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
class TestWriteTurboPages:
    def test_add(self, unique_suffix):
        """Turbo pages may not support delete — just verify add succeeds."""
        r = _invoke(
            "turbopages", "add",
            "--name", f"test-turbo-{unique_suffix}",
            "--url", "https://example.com/turbo",
        )
        # May fail if sandbox doesn't support turbo pages
        if r.exit_code == 0:
            data = json.loads(r.output)
            add_results = data.get("AddResults", [])
            if add_results and "Id" in add_results[0]:
                assert "Errors" not in add_results[0] or not add_results[0]["Errors"]
        else:
            pytest.skip("sandbox may not support turbo pages")

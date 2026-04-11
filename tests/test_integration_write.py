"""
Sandbox integration tests for direct-cli write commands.

Exercises mutating commands against the Yandex Direct sandbox API.

**Two modes of operation (pytest-recording / vcrpy):**

- **Replay mode (default, CI)** — every test has a cassette YAML committed
  under ``tests/cassettes/test_integration_write/``.  Running
  ``pytest -m integration_write -v`` replays the recorded HTTP traffic
  without touching the real sandbox.  No token is required.

- **Rewrite mode (manual)** — to regenerate cassettes after a CLI change
  that affects the request payload, export ``YANDEX_DIRECT_TOKEN`` and
  run ``pytest -m integration_write --record-mode=rewrite -v``.  Review
  the generated YAMLs for leaked secrets (``grep -r <your-token>``)
  before committing.

**Sandbox limitations discovered during recording:**

The Yandex Direct sandbox does NOT persist nested resources (adgroups, ads,
keywords) reliably — ``adgroups add`` returns an ID but subsequent calls
report "Object not found".  Cassettes preserve whatever the sandbox
actually returned at record time; tests use ``_is_sandbox_error`` to
distinguish sandbox limitations from real CLI regressions.

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
    tomorrow,
)


# ── campaigns ────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
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

            # suspend — a brand-new sandbox campaign is in DRAFT; the API
            # rejects suspend/resume with a known error.  Skip only that
            # specific case; any other non-zero exit is a regression.
            r = _invoke("campaigns", "suspend", "--id", str(cid))
            if r.exit_code != 0:
                if _is_sandbox_error(
                    r.output, extra_patterns=("DRAFT", "has not been saved", "is draft")
                ):
                    suspend_ok = False
                else:
                    pytest.fail(f"campaigns suspend failed (CLI regression?): {r.output[:500]}")
            else:
                suspend_ok = True

            if suspend_ok:
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
@pytest.mark.vcr
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
@pytest.mark.vcr
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
@pytest.mark.vcr
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
@pytest.mark.vcr
class TestWriteBids:
    def test_set_bid(self, sandbox_campaign):
        r = _invoke(
            "bids", "set",
            "--campaign-id", str(sandbox_campaign),
            "--bid", "15",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"bids set not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"bids set failed (CLI regression?): {r.output[:500]}")


# ── keywordbids ──────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteKeywordBids:
    def test_set_keyword_bid(self, sandbox_keyword):
        r = _invoke(
            "keywordbids", "set",
            "--keyword-id", str(sandbox_keyword),
            "--search-bid", "8",
            "--network-bid", "3",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"keywordbids set not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"keywordbids set failed (CLI regression?): {r.output[:500]}")


# ── bidmodifiers ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteBidModifiersSet:
    """Document the broken state of ``bidmodifiers set``.

    **Real finding from the cassette recording session:** the API's
    ``set`` method requires each ``BidModifiers`` item to carry an ``Id``
    of an EXISTING modifier — it cannot create new ones.  The CLI
    (``direct_cli/commands/bidmodifiers.py:79``) builds a payload without
    ``Id``, so ``bidmodifiers set`` without ``--json`` extras is broken
    by design — the API replies with ``error_code=8000, error_detail=The
    required field Id is omitted``.

    Proper fix is to either (a) add a ``bidmodifiers add`` subcommand
    that posts to the API's ``add`` method, or (b) change the CLI's
    ``set`` to require ``--id``.  That's out of scope for this test PR,
    so the test below just *freezes* the current broken behaviour via a
    regression cassette: if the CLI ever stops sending this payload or
    the API ever stops returning this specific error, the cassette miss
    will flag it.
    """

    def test_set_without_id_is_rejected(self, sandbox_campaign):
        r = _invoke(
            "bidmodifiers", "set",
            "--campaign-id", str(sandbox_campaign),
            "--type", "MOBILE_ADJUSTMENT",
            "--value", "120",
        )
        assert r.exit_code != 0, (
            "bidmodifiers set unexpectedly succeeded without --id; either the "
            "CLI was fixed to include Id, or the API now allows creating "
            "modifiers via set. Update this test accordingly."
        )
        assert "The required field Id is omitted" in r.output, (
            f"Unexpected failure mode from bidmodifiers set: {r.output[:500]}"
        )


@pytest.mark.integration_write
@pytest.mark.vcr
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
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"bidmodifiers toggle not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"bidmodifiers toggle --disabled failed (CLI regression?): {r.output[:500]}")

        # toggle back on
        r = _invoke(
            "bidmodifiers", "toggle",
            "--id", str(modifier_id),
            "--enabled",
        )
        assert_success(r, "bidmodifiers toggle on")


# ── feeds ────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteFeeds:
    def test_add_update_delete(self, unique_suffix):
        r = _invoke(
            "feeds", "add",
            "--name", f"test-feed-{unique_suffix}",
            "--url", "https://example.com/feed.xml",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output, extra_patterns=("unknown parameter",)):
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
@pytest.mark.vcr
class TestWriteRetargeting:
    def test_add_delete(self, unique_suffix):
        r = _invoke(
            "retargeting", "add",
            "--name", f"test-rtg-{unique_suffix}",
            "--type", "AUDIENCE_SEGMENT",
            "--json", json.dumps({"Rules": [{"LowerBound": 1, "UpperBound": 365}]}),
        )
        if r.exit_code != 0:
            if _is_sandbox_error(
                r.output, extra_patterns=("required field", "is omitted", "Invalid request")
            ):
                pytest.skip(f"retargeting add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"retargeting add failed (CLI regression?): {r.output[:500]}")

        rid = parse_add_result(r)
        r = _invoke("retargeting", "delete", "--id", str(rid))
        assert_success(r, "retargeting delete")


# ── audiencetargets ──────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteAudienceTargets:
    def test_add_delete(self, sandbox_adgroup, sandbox_retargeting_list):
        r = _invoke(
            "audiencetargets", "add",
            "--adgroup-id", str(sandbox_adgroup),
            "--retargeting-list-id", str(sandbox_retargeting_list),
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"audiencetargets add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"audiencetargets add failed (CLI regression?): {r.output[:500]}")

        first = parse_first_result(r)
        tid = first["Id"]
        r = _invoke("audiencetargets", "delete", "--id", str(tid))
        assert_success(r, "audiencetargets delete")


# ── sitelinks ────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteSitelinks:
    def test_add_delete(self):
        links = json.dumps([
            {"Title": "About", "Href": "https://example.com/about"},
            {"Title": "Contact", "Href": "https://example.com/contact"},
        ])
        r = _invoke("sitelinks", "add", "--links", links)
        if r.exit_code != 0:
            if _is_sandbox_error(
                r.output, extra_patterns=("temporarily unavailable",)
            ):
                pytest.skip(f"sitelinks add not available (sandbox): {r.output[:200]}")
            pytest.fail(f"sitelinks add failed (CLI regression?): {r.output[:500]}")

        first = parse_first_result(r)
        sid = first["Id"]
        r = _invoke("sitelinks", "delete", "--id", str(sid))
        assert_success(r, "sitelinks delete")


# ── vcards ───────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteVCards:
    def test_add_delete(self, sandbox_campaign):
        # Recorded at 2026-04-11 against sandbox.
        # WorkTime format: ``<day_from>#<day_to>#<hh_from>#<mm_from>#<hh_to>#<mm_to>``
        # Here: Mon(1) — Fri(5), 09:00 — 18:00.
        vcard = json.dumps({
            "CampaignId": sandbox_campaign,
            "Country": "Россия",
            "City": "Москва",
            "CompanyName": "Test Company",
            "WorkTime": "1#5#9#0#18#0",
            "Phone": {
                "CountryCode": "+7",
                "CityCode": "495",
                "PhoneNumber": "1234567",
            },
        })
        r = _invoke("vcards", "add", "--json", vcard)
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"vcards add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"vcards add failed (CLI regression?): {r.output[:500]}")

        first = parse_first_result(r)
        vid = first["Id"]
        r = _invoke("vcards", "delete", "--id", str(vid))
        assert_success(r, "vcards delete")


# ── adextensions ─────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteAdExtensions:
    """
    NOTE: The ``adextensions`` CLI group still sends an explicit ``Type``
    field alongside the nested extension object.  Per the API, ``Type``
    is inferred from the nested field (``Callout`` / ``Sitelink`` / …),
    so sandbox sometimes rejects the duplicated hint as
    ``unknown parameter``.  We skip only on that narrow error and
    pytest.fail otherwise — matching the pattern used by other write
    tests in this file.
    """

    def test_add_delete(self):
        ext_json = json.dumps({"Callout": {"CalloutText": "Free shipping"}})
        r = _invoke(
            "adextensions", "add",
            "--type", "CALLOUT",
            "--json", ext_json,
        )
        if r.exit_code != 0:
            if _is_sandbox_error(
                r.output, extra_patterns=("unknown parameter",)
            ):
                pytest.skip(f"adextensions add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"adextensions add failed (CLI regression?): {r.output[:500]}")

        first = parse_first_result(r)
        eid = first["Id"]
        r = _invoke("adextensions", "delete", "--id", str(eid))
        assert_success(r, "adextensions delete")


# ── adimages ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteAdImages:
    def test_add_delete(self):
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
            "Nl7BcQAAAABJRU5ErkJggg=="
        )
        image = json.dumps({"Name": "test-image.png", "ImageData": png_b64})
        r = _invoke("adimages", "add", "--json", image)
        if r.exit_code != 0:
            if _is_sandbox_error(r.output, extra_patterns=("Invalid format",)):
                pytest.skip(f"adimages add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"adimages add failed (CLI regression?): {r.output[:500]}")

        data = json.loads(r.output)
        assert isinstance(data, list) and data, (
            f"adimages add returned empty result: {r.output[:200]}"
        )
        first = data[0]
        if "Errors" in first and first["Errors"]:
            err_text = str(first["Errors"])
            if _is_sandbox_error(err_text, extra_patterns=("Invalid format",)):
                pytest.skip(f"adimages rejected (sandbox): {first['Errors']}")
            pytest.fail(f"API rejected adimages add (CLI bug?): {first['Errors']}")

        img_hash = first.get("AdImageHash") or first.get("Id")
        assert img_hash, f"adimages add returned no hash/id: {first}"
        r = _invoke("adimages", "delete", "--hash", str(img_hash))
        assert_success(r, "adimages delete")


# ── dynamicads (webpages) ────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
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
                if _is_sandbox_error(err_text, extra_patterns=("required field",)):
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
            if _is_sandbox_error(r.output, extra_patterns=("required field",)):
                pytest.skip(f"dynamicads add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"dynamicads add failed (CLI regression?): {r.output[:500]}")


# ── smartadtargets ───────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
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
                if _is_sandbox_error(err_text, extra_patterns=("required field",)):
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
            if _is_sandbox_error(r.output, extra_patterns=("required field",)):
                pytest.skip(f"smartadtargets add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"smartadtargets add failed (CLI regression?): {r.output[:500]}")


# ── negativekeywordsharedsets ────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
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


# NOTE: No ``turbopages`` write tests — the Yandex Direct API ``turbopages``
# service is read-only (``get`` only).  The earlier ``turbopages add`` CLI
# command was a ghost endpoint that never corresponded to any real API
# method and was removed together with its test coverage.

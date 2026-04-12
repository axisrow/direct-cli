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

**Coverage status (issue #20 / #28):**

Covered (passing in replay):
  - campaigns lifecycle (add/update/suspend/resume/archive/unarchive/delete)
  - adgroups add-update-delete
  - bidmodifiers add/delete (mobile adjustment)
  - bidmodifiers set regression guard (no-id rejection)
  - bidmodifiers toggle (add → toggle disabled/enabled)
  - feeds add-update-delete
  - retargeting add-delete
  - vcards add-delete
  - adextensions add-delete
  - negativekeywordsharedsets add-update-delete
  - bids set (uses --keyword-id, requires real keyword)
  - adimages add/delete (uses 450x450 PNG)
  - dynamicads add/update/delete (uses DYNAMIC_TEXT_AD_GROUP fixture)
  - smartadtargets add/update/delete (uses SMART_AD_GROUP fixture)
  - audiencetargets add/delete (retargeting fixture includes MembershipLifeSpan)

Possibly sandbox-limited (require cassette re-record to confirm):
  - ads add/update/delete         — sandbox may not persist adgroups across calls
  - keywords add/update/delete    — same
  - keywordbids set               — depends on keyword persistence
  - sitelinks add/delete          — sandbox service returns error 1000

Part of axisrow/yandex-direct-mcp-plugin#61 (Etap 3).
"""

import json

import pytest

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from conftest import (  # noqa: E402
    _ARCHIVE_PATTERNS,
    _CAMPAIGN_STATUS_PATTERNS,
    _IMAGE_PATTERNS,
    _KEYWORD_PATTERNS,
    _SITELINK_PATTERNS,
    _SMART_AD_PATTERNS,
    _has_result_errors,
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
            # Yandex Direct returns HTTP 200 with embedded SuspendResults
            # Errors for DRAFT campaigns — check both exit_code and body.
            r = _invoke("campaigns", "suspend", "--id", str(cid))
            if r.exit_code != 0 or _has_result_errors(r.output, "SuspendResults"):
                err = r.output
                if _is_sandbox_error(err, extra_patterns=_CAMPAIGN_STATUS_PATTERNS):
                    suspend_ok = False
                else:
                    pytest.fail(f"campaigns suspend failed (CLI regression?): {err[:500]}")
            else:
                suspend_ok = True

            if suspend_ok:
                r = _invoke("campaigns", "resume", "--id", str(cid))
                if r.exit_code != 0 or _has_result_errors(r.output, "ResumeResults"):
                    if not _is_sandbox_error(r.output, extra_patterns=_CAMPAIGN_STATUS_PATTERNS):
                        pytest.fail(f"campaigns resume failed (CLI regression?): {r.output[:500]}")

            # archive — sandbox DRAFT campaigns return embedded
            # ArchiveResults errors (Code 8303) with HTTP 200.
            r = _invoke("campaigns", "archive", "--id", str(cid))
            if r.exit_code != 0 or _has_result_errors(r.output, "ArchiveResults"):
                if not _is_sandbox_error(r.output, extra_patterns=_ARCHIVE_PATTERNS):
                    pytest.fail(f"campaigns archive failed (CLI regression?): {r.output[:500]}")
            else:
                assert_success(r, "campaigns archive")

            # unarchive
            r = _invoke("campaigns", "unarchive", "--id", str(cid))
            if r.exit_code != 0 or _has_result_errors(r.output, "UnarchiveResults"):
                if not _is_sandbox_error(r.output, extra_patterns=_ARCHIVE_PATTERNS):
                    pytest.fail(f"campaigns unarchive failed (CLI regression?): {r.output[:500]}")
            else:
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
                if _is_sandbox_error(r.output):
                    pytest.skip(f"adgroups not persisted in sandbox: {r.output[:200]}")
                pytest.fail(f"adgroups update failed (CLI regression?): {r.output[:500]}")
            assert_success(r, "adgroups update")
        finally:
            _invoke("adgroups", "delete", "--id", str(gid))


# ── ads ──────────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
@pytest.mark.sandbox_limitation(
    reason="Sandbox does not persist adgroups; ads add always returns 'Ad group not found'"
)
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
@pytest.mark.sandbox_limitation(
    reason="Sandbox does not persist adgroups; keywords add always returns 'Ad group not found'"
)
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
    def test_set_bid(self, sandbox_keyword):
        r = _invoke(
            "bids", "set",
            "--keyword-id", str(sandbox_keyword),
            "--bid", "15",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"bids set not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"bids set failed (CLI regression?): {r.output[:500]}")

        # Even with exit_code 0, the API can return embedded errors.
        if _has_result_errors(r.output, "SetResults"):
            if _is_sandbox_error(r.output):
                pytest.skip(f"bids set rejected (sandbox): {r.output[:200]}")
            pytest.fail(f"bids set returned errors (CLI regression?): {r.output[:500]}")


# ── keywordbids ──────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
@pytest.mark.sandbox_limitation(
    reason="Sandbox does not persist adgroups/keywords; no keywords to bid on"
)
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
class TestWriteBidModifiersAdd:
    """Lifecycle for the new ``bidmodifiers add`` subcommand.

    Creates a mobile bid adjustment on the sandbox campaign via the
    nested-object payload (``MobileAdjustment: {BidModifier: 120}``),
    parses the resulting modifier ID from ``AddResults``, and deletes
    it — a full add → delete round-trip against the live sandbox.
    """

    def test_add_delete_mobile(self, sandbox_campaign):
        r = _invoke(
            "bidmodifiers", "add",
            "--campaign-id", str(sandbox_campaign),
            "--type", "MOBILE_ADJUSTMENT",
            "--value", "120",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"bidmodifiers add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"bidmodifiers add failed (CLI regression?): {r.output[:500]}")

        # ``bidmodifiers/add`` returns ``{"Ids": [<long>]}`` rather than
        # the usual ``{"AddResults": [{"Id": <long>}]}`` wrapper.  Handle
        # both shapes because tapi-yandex-direct may unwrap differently.
        data = json.loads(r.output)
        if isinstance(data, dict) and "Ids" in data:
            ids = data["Ids"]
        elif isinstance(data, list) and data and isinstance(data[0], dict) and "Ids" in data[0]:
            ids = data[0]["Ids"]
        else:
            ids = None
        assert ids, f"bidmodifiers add returned no Ids: {r.output[:500]}"
        mid = ids[0]

        r = _invoke("bidmodifiers", "delete", "--id", str(mid))
        assert_success(r, "bidmodifiers delete")


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteBidModifiersSet:
    """Regression guard: ``bidmodifiers set`` without ``--id`` is rejected.

    The API's ``set`` method updates EXISTING modifiers only — it
    requires the ``Id`` field.  The CLI's ``set`` subcommand builds a
    payload without ``Id``, so the call is by-design rejected.  New
    modifiers go through the ``bidmodifiers add`` subcommand instead
    (covered by ``TestWriteBidModifiersAdd``).

    This test freezes the broken-by-design behaviour: if the CLI ever
    starts including ``Id`` automatically, or the API stops returning
    this specific error, the cassette miss will flag it.
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
        """Add a modifier, then toggle it off and back on."""
        cid = sandbox_campaign

        # Step 1: Create a modifier so we have something to toggle
        r = _invoke(
            "bidmodifiers", "add",
            "--campaign-id", str(cid),
            "--type", "MOBILE_ADJUSTMENT",
            "--value", "120",
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"bidmodifiers add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"bidmodifiers add failed (CLI regression?): {r.output[:500]}")

        # Parse modifier ID from add result
        data = json.loads(r.output)
        ids = None
        if isinstance(data, dict) and "Ids" in data:
            ids = data["Ids"]
        elif isinstance(data, list) and data and isinstance(data[0], dict) and "Ids" in data[0]:
            ids = data[0]["Ids"]

        if not ids:
            pytest.fail(f"bidmodifiers add returned no Ids (CLI regression?): {r.output[:200]}")
        mid = ids[0]

        try:
            # Step 2: Toggle off
            r = _invoke(
                "bidmodifiers", "toggle",
                "--id", str(mid),
                "--disabled",
            )
            if r.exit_code != 0:
                if _is_sandbox_error(r.output):
                    pytest.skip(f"bidmodifiers toggle not supported (sandbox): {r.output[:200]}")
                pytest.fail(f"bidmodifiers toggle --disabled failed (CLI regression?): {r.output[:500]}")

            # Even with exit_code 0, the API can return embedded errors.
            if _has_result_errors(r.output, "SetResults"):
                if _is_sandbox_error(r.output):
                    pytest.skip(f"bidmodifiers toggle not supported (sandbox): {r.output[:200]}")
                pytest.fail(f"bidmodifiers toggle returned errors (CLI regression?): {r.output[:500]}")

            # Step 3: Toggle back on
            r = _invoke(
                "bidmodifiers", "toggle",
                "--id", str(mid),
                "--enabled",
            )
            if r.exit_code != 0:
                if _is_sandbox_error(r.output):
                    pytest.skip(f"bidmodifiers toggle on not supported (sandbox): {r.output[:200]}")
                pytest.fail(f"bidmodifiers toggle on failed (CLI regression?): {r.output[:500]}")

            # Even with exit_code 0, the API can return embedded errors.
            if _has_result_errors(r.output, "SetResults"):
                if _is_sandbox_error(r.output):
                    pytest.skip(f"bidmodifiers toggle not supported (sandbox): {r.output[:200]}")
                pytest.fail(f"bidmodifiers toggle returned errors (CLI regression?): {r.output[:500]}")
        finally:
            _invoke("bidmodifiers", "delete", "--id", str(mid))


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
            if _is_sandbox_error(r.output):
                pytest.skip(f"feeds add not supported in sandbox: {r.output[:200]}")
            pytest.fail(f"feeds add failed (CLI regression?): {r.output[:500]}")

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
            "--type", "RETARGETING",
            "--json", json.dumps({
                "Rules": [{
                    "Operator": "ANY",
                    "Arguments": [{"ExternalId": 1234567890}],
                }]
            }),
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"retargeting add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"retargeting add failed (CLI regression?): {r.output[:500]}")

        rid = parse_add_result(r)
        r = _invoke("retargeting", "delete", "--id", str(rid))
        assert_success(r, "retargeting delete")


# ── audiencetargets ──────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
@pytest.mark.sandbox_limitation(
    reason="Sandbox lacks valid Yandex.Metrica goal ExternalIds for retargeting rules"
)
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
@pytest.mark.sandbox_limitation(
    reason="Sandbox sitelinks service permanently unavailable (error 1000)"
)
class TestWriteSitelinks:
    def test_add_delete(self):
        links = json.dumps([
            {"Title": "About", "Href": "https://example.com/about"},
            {"Title": "Contact", "Href": "https://example.com/contact"},
        ])
        r = _invoke("sitelinks", "add", "--links", links)
        if r.exit_code != 0:
            if _is_sandbox_error(r.output, extra_patterns=_SITELINK_PATTERNS):
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
    """Live lifecycle for a Callout ad extension.

    Exercises the fix that stopped the CLI from sending the extra
    top-level ``Type`` field (the API derives the extension kind from
    the nested object name).  The regenerated cassette freezes the
    correct payload as a regression guard.
    """

    def test_add_delete(self):
        ext_json = json.dumps({"Callout": {"CalloutText": "Free shipping"}})
        r = _invoke(
            "adextensions", "add",
            "--type", "CALLOUT",
            "--json", ext_json,
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"adextensions add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"adextensions add failed (CLI regression?): {r.output[:500]}")

        first = parse_first_result(r)
        eid = first["Id"]
        r = _invoke("adextensions", "delete", "--id", str(eid))
        assert_success(r, "adextensions delete")


# ── adimages ─────────────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
@pytest.mark.sandbox_limitation(
    reason="Sandbox rejects valid base64-encoded PNG image uploads (error 5004)"
)
class TestWriteAdImages:
    def test_add_delete(self):
        # 450x450 solid red PNG — meets Yandex Direct minimum image dimension
        # requirements. The previous 1x1px image was rejected by the API (error 5004).
        png_b64 = (
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
            "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7"
            "AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQ"
            "th8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0H"
            "AGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDa"
            "fgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8A"
            "pO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGn7AUDafgCQth8ApO0HAGk/"
            "KWgbKQyncKAAAAAASUVORK5CYII="
        )
        image = json.dumps({"Name": "test-image.png", "ImageData": png_b64})
        r = _invoke("adimages", "add", "--json", image)
        if r.exit_code != 0:
            if _is_sandbox_error(r.output, extra_patterns=_IMAGE_PATTERNS):
                pytest.skip(f"adimages add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"adimages add failed (CLI regression?): {r.output[:500]}")

        data = json.loads(r.output)
        assert isinstance(data, list) and data, (
            f"adimages add returned empty result: {r.output[:200]}"
        )
        first = data[0]
        if "Errors" in first and first["Errors"]:
            err_text = str(first["Errors"])
            if _is_sandbox_error(err_text, extra_patterns=_IMAGE_PATTERNS):
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
    def test_add_update_delete(self, sandbox_dynamic_adgroup):
        target = {
            "Name": "Test Webpage",
            "Conditions": [
                {"Operand": "URL", "Operator": "CONTAINS_ANY", "Arguments": ["test"]},
            ],
        }
        r = _invoke(
            "dynamicads", "add",
            "--adgroup-id", str(sandbox_dynamic_adgroup),
            "--json", json.dumps(target),
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output):
                pytest.skip(f"dynamicads add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"dynamicads add failed (CLI regression?): {r.output[:500]}")

        data = json.loads(r.output)
        first = data[0] if isinstance(data, list) else data.get("AddResults", [{}])[0]
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


# ── smartadtargets ───────────────────────────────────────────────────────


@pytest.mark.integration_write
@pytest.mark.vcr
class TestWriteSmartAdTargets:
    """Live-API regression guard for the Type-field fix from PR #12.

    The CLI ``smartadtargets add`` used to send a spurious top-level
    ``Type`` field.  PR #12 removed it.  This test both exercises the
    fixed code path and captures the API's successful response into a
    cassette — so any regression that reintroduces ``Type`` will cause
    the cassette body matcher to fail in replay mode.
    """

    def test_add_update_delete(self, sandbox_smart_adgroup):
        payload = json.dumps({
            "Name": "regression-smart-target",
            "Audience": "ALL_SEGMENTS",
        })
        r = _invoke(
            "smartadtargets", "add",
            "--adgroup-id", str(sandbox_smart_adgroup),
            "--type", "VIEWED_PRODUCT",
            "--json", payload,
        )
        if r.exit_code != 0:
            if _is_sandbox_error(r.output, extra_patterns=_SMART_AD_PATTERNS):
                pytest.skip(f"smartadtargets add not supported (sandbox): {r.output[:200]}")
            pytest.fail(f"smartadtargets add failed (CLI regression?): {r.output[:500]}")

        data = json.loads(r.output)
        first = data[0] if isinstance(data, list) else data.get("AddResults", [{}])[0]
        if "Errors" in first and first["Errors"]:
            err_text = str(first["Errors"])
            if _is_sandbox_error(err_text, extra_patterns=_SMART_AD_PATTERNS):
                pytest.skip(f"smartadtargets add rejected (sandbox): {first['Errors']}")
            pytest.fail(
                f"API rejected smartadtargets add (potential Type-field "
                f"regression from PR #12): {first['Errors']}"
            )

        tid = first["Id"]
        try:
            r = _invoke(
                "smartadtargets", "update",
                "--id", str(tid),
                "--json", json.dumps({"Priority": "HIGH"}),
            )
            assert_success(r, "smartadtargets update")
        finally:
            _invoke("smartadtargets", "delete", "--id", str(tid))


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

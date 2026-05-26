"""
Integration tests for Direct CLI — read-only commands.

Requires a real Yandex Direct API token.  Tests are automatically skipped
if ``YANDEX_DIRECT_TOKEN`` is not set in the environment or ``.env`` file.
Unlike the write test suite, these tests do NOT use recorded cassettes —
each run hits the real API in read-only mode.

Run with:
    pytest -m integration -v

Write operations (add/update/delete/set) are tested separately in
``test_integration_write.py`` against the Yandex Direct sandbox, with
VCR cassettes so CI can replay them offline.  See that file for coverage
details.

Read-only commands that remain uncovered here:

    sitelinks get  — requires explicit ``--ids``, no list endpoint
    feeds get      — requires explicit ``--ids``, no list endpoint
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli._smoke_probes import advideo_probe_id

sys.path.insert(0, os.path.dirname(__file__))
from conftest import skip_if_no_token  # noqa: E402


def make_runner():
    return CliRunner()


def invoke_get(*args):
    """Invoke a read-only CLI command and return the result."""
    return make_runner().invoke(cli, list(args))


def assert_success(result, cmd_label: str):
    """Assert command exited successfully with valid JSON output."""
    assert result.exit_code == 0, (
        f"[{cmd_label}] exit_code={result.exit_code}\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    try:
        json.loads(result.output)
    except json.JSONDecodeError:
        pytest.fail(f"[{cmd_label}] output is not valid JSON:\n{result.output[:500]}")


def parse_json_output(result):
    """Return decoded JSON output, or None if the command did not return JSON."""
    if result.exit_code != 0:
        return None
    try:
        return json.loads(result.output)
    except json.JSONDecodeError:
        return None


def get_first_campaign_id() -> int | None:
    """Return the first available campaign ID, or None if no campaigns exist."""
    result = invoke_get("campaigns", "get", "--limit", "1", "--format", "json")
    data = parse_json_output(result)
    if isinstance(data, list) and data:
        return data[0].get("Id")
    return None


def get_first_turbopage_id() -> int | None:
    """Return the first available turbo page ID, or None if none exist."""
    result = invoke_get("turbopages", "get", "--limit", "1", "--format", "json")
    data = parse_json_output(result)
    if isinstance(data, list) and data:
        return data[0].get("Id")
    return None


def get_first_leads_turbopage_id() -> int | None:
    """
    Return a turbo page ID that can be used for leads.get, or None if no
    read-only probe is accepted by the API.
    """
    turbo_page_id = get_first_turbopage_id()
    if turbo_page_id:
        return turbo_page_id

    result = invoke_get(
        "leads",
        "get",
        "--turbo-page-ids",
        "1",
        "--limit",
        "1",
        "--format",
        "json",
    )
    if result.exit_code == 0 and isinstance(parse_json_output(result), list):
        return 1
    return None


def get_first_business_id() -> int | None:
    """Return a validated business ID, or None if discovery is unavailable."""
    env_id = os.getenv("YANDEX_DIRECT_TEST_BUSINESS_ID")
    if env_id:
        env_result = invoke_get(
            "businesses",
            "get",
            "--ids",
            env_id,
            "--limit",
            "1",
            "--format",
            "json",
        )
        env_data = parse_json_output(env_result)
        if isinstance(env_data, list) and env_data:
            return env_data[0].get("Id")

    probe_result = invoke_get(
        "businesses",
        "get",
        "--ids",
        "0",
        "--limit",
        "1",
        "--format",
        "json",
    )
    data = parse_json_output(probe_result)
    if isinstance(data, list) and data:
        return data[0].get("Id")
    return None


def get_first_advideo_probe_id() -> str | None:
    """Return a creative/video ID accepted by advideos.get, or None."""
    return advideo_probe_id()


def is_agency_access_denied(result) -> bool:
    """Return True if agencyclients is unavailable for the current account."""
    return result.exit_code != 0 and (
        "403" in result.output
        or "Access denied" in result.output
        or "error_code=54" in result.output
        or "No rights to access the agency service" in result.output
    )


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyCampaigns(unittest.TestCase):
    def test_get_campaigns(self):
        result = invoke_get("campaigns", "get", "--limit", "1", "--format", "json")
        assert_success(result, "campaigns get")

    def test_get_campaigns_table(self):
        result = invoke_get("campaigns", "get", "--limit", "1", "--format", "table")
        self.assertEqual(result.exit_code, 0, result.output)


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAdGroups(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign_id = get_first_campaign_id()

    def test_get_adgroups(self):
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "adgroups",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "adgroups get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign_id = get_first_campaign_id()

    def test_get_ads(self):
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "ads",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "ads get")

    def test_get_ads_returns_textad(self):
        """TEXT_AD ads must include TextAd with Title and Text."""
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "ads",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
            "--limit",
            "50",
            "--format",
            "json",
        )
        assert_success(result, "ads get (TextAd check)")
        data = json.loads(result.output)
        text_ads = [ad for ad in data if ad.get("Type") == "TEXT_AD"]
        if not text_ads:
            self.skipTest("No TEXT_AD ads found in first 50 results")
        for ad in text_ads:
            self.assertIn(
                "TextAd",
                ad,
                f"TEXT_AD {ad['Id']} missing TextAd — TextAdFieldNames may not be sent",
            )
            self.assertIn("Title", ad["TextAd"])
            self.assertIn("Text", ad["TextAd"])


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyKeywords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign_id = get_first_campaign_id()

    def test_get_keywords(self):
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "keywords",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "keywords get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyClients(unittest.TestCase):
    def test_get_clients(self):
        result = invoke_get(
            "clients",
            "get",
            "--fields",
            "ClientId,Login,Currency,CountryId",
            "--format",
            "json",
        )
        assert_success(result, "clients get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAdExtensions(unittest.TestCase):
    def test_get_adextensions(self):
        result = invoke_get("adextensions", "get", "--limit", "1", "--format", "json")
        assert_success(result, "adextensions get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAdImages(unittest.TestCase):
    def test_get_adimages(self):
        result = invoke_get(
            "adimages",
            "get",
            "--fields",
            "AdImageHash,Name",
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "adimages get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyCreatives(unittest.TestCase):
    def test_get_creatives(self):
        result = invoke_get(
            "creatives",
            "get",
            "--fields",
            "Id,Name,Type",
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "creatives get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyRetargeting(unittest.TestCase):
    def test_get_retargeting(self):
        result = invoke_get("retargeting", "get", "--limit", "1", "--format", "json")
        assert_success(result, "retargeting get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyDictionaries(unittest.TestCase):
    def test_get_currencies(self):
        result = invoke_get(
            "dictionaries", "get", "--names", "Currencies", "--format", "json"
        )
        assert_success(result, "dictionaries get --names Currencies")

    def test_get_geo_regions(self):
        result = invoke_get(
            "dictionaries", "get", "--names", "GeoRegions", "--format", "json"
        )
        assert_success(result, "dictionaries get --names GeoRegions")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyReports(unittest.TestCase):
    def test_get_campaign_performance_report(self):
        result = invoke_get(
            "reports",
            "get",
            "--type",
            "campaign_performance_report",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "Integration Test Report",
            "--fields",
            "Date,CampaignId,Clicks,Impressions",
            "--format",
            "json",
        )
        assert_success(result, "reports get campaign_performance_report")

    def test_get_report_with_filter(self):
        result = invoke_get(
            "reports",
            "get",
            "--type",
            "campaign_performance_report",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "Filtered Report",
            "--fields",
            "Date,CampaignId,Clicks",
            "--filter",
            "Clicks:GREATER_THAN:0",
            "--format",
            "json",
        )
        assert_success(result, "reports get with --filter")

    def test_get_report_with_order_by(self):
        result = invoke_get(
            "reports",
            "get",
            "--type",
            "campaign_performance_report",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-31",
            "--name",
            "Ordered Report",
            "--fields",
            "Date,CampaignId,Clicks",
            "--order-by",
            "Clicks",
            "--format",
            "json",
        )
        assert_success(result, "reports get with --order-by Clicks")

    def test_get_report_formats(self):
        for output_format in ["json", "table", "csv", "tsv"]:
            result = invoke_get(
                "reports",
                "get",
                "--type",
                "campaign_performance_report",
                "--from",
                "2026-01-01",
                "--to",
                "2026-01-31",
                "--name",
                f"Format Test {output_format}",
                "--fields",
                "Date,CampaignId",
                "--format",
                output_format,
            )
            assert result.exit_code == 0, (
                f"[reports get --format {output_format}] exit_code={result.exit_code}\n"
                f"output: {result.output}\n"
                f"exception: {result.exception}"
            )


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyStrategies(unittest.TestCase):
    def test_get_strategies(self):
        result = invoke_get("strategies", "get", "--limit", "1", "--format", "json")
        assert_success(result, "strategies get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyDynamicFeedAdTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.campaign_id = get_first_campaign_id()

    def test_get_dynamic_feed_ad_targets(self):
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "dynamicfeedadtargets",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "dynamicfeedadtargets get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyLeads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.turbo_page_id = get_first_leads_turbopage_id()

    def test_get_leads(self):
        if self.turbo_page_id is None:
            self.skipTest("No turbo page ID or accepted leads probe available")
        result = invoke_get(
            "leads",
            "get",
            "--turbo-page-ids",
            str(self.turbo_page_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "leads get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyTurbopages(unittest.TestCase):
    def test_get_turbopages(self):
        result = invoke_get("turbopages", "get", "--limit", "1", "--format", "json")
        assert_success(result, "turbopages get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyBusinesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.business_id = get_first_business_id()

    def test_get_businesses(self):
        if self.business_id is None:
            self.skipTest("No business ID or accepted businesses probe available")
        result = invoke_get(
            "businesses",
            "get",
            "--ids",
            str(self.business_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "businesses get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAdVideos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.advideo_id = get_first_advideo_probe_id()

    def test_get_advideos(self):
        if self.advideo_id is None:
            self.skipTest("No video creative ID accepted by advideos get")
        result = invoke_get(
            "advideos",
            "get",
            "--ids",
            str(self.advideo_id),
            "--limit",
            "1",
            "--format",
            "json",
        )
        assert_success(result, "advideos get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAgencyClients(unittest.TestCase):
    def test_get_agencyclients(self):
        sandbox_result = invoke_get(
            "--sandbox",
            "agencyclients",
            "get",
            "--limit",
            "1",
            "--format",
            "json",
        )
        if sandbox_result.exit_code == 0:
            assert_success(sandbox_result, "agencyclients get --sandbox")
            return

        live_result = invoke_get(
            "agencyclients",
            "get",
            "--limit",
            "1",
            "--format",
            "json",
        )
        if is_agency_access_denied(live_result):
            self.skipTest(
                "agencyclients is unavailable in sandbox and current live "
                "account is not an agency account"
            )
        assert_success(live_result, "agencyclients get")


def _recent_timestamp() -> str:
    """Return an ISO timestamp 1 hour in the past for changes.check* probes."""
    ts = datetime.now(timezone.utc) - timedelta(hours=1)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyChanges(unittest.TestCase):
    def test_changes_check_dictionaries(self):
        result = invoke_get("changes", "check-dictionaries", "--format", "json")
        assert_success(result, "changes check-dictionaries")

    def test_changes_check_campaigns(self):
        result = invoke_get(
            "changes",
            "check-campaigns",
            "--timestamp",
            _recent_timestamp(),
            "--format",
            "json",
        )
        assert_success(result, "changes check-campaigns")

    def test_changes_check(self):
        campaign_id = get_first_campaign_id()
        if campaign_id is None:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "changes",
            "check",
            "--campaign-ids",
            str(campaign_id),
            "--timestamp",
            _recent_timestamp(),
            "--format",
            "json",
        )
        assert_success(result, "changes check")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyKeywordsResearch(unittest.TestCase):
    def test_has_search_volume(self):
        result = invoke_get(
            "keywordsresearch",
            "has-search-volume",
            "--keywords",
            "купить квартиру",
            "--region-ids",
            "213",
            "--format",
            "json",
        )
        assert_success(result, "keywordsresearch has-search-volume")

    def test_deduplicate(self):
        result = invoke_get(
            "keywordsresearch",
            "deduplicate",
            "--keywords",
            "купить квартиру,купить дом",
            "--format",
            "json",
        )
        assert_success(result, "keywordsresearch deduplicate")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyBalance(unittest.TestCase):
    def test_balance_get(self):
        # ``invoke_get`` calls the live API (read-only mode), same as the
        # other TestReadOnly* classes in this file. The v4
        # AccountManagement.Get endpoint exists in production; the sandbox
        # 3500 limitation does not apply to this invocation path.
        result = invoke_get("balance", "--format", "json")
        assert_success(result, "balance")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAuth(unittest.TestCase):
    """Read-only coverage of ``direct auth status`` / ``direct auth list``.

    These commands do not hit the Yandex Direct API — they read local
    profile state — but they require an active profile (i.e. the same
    credentials the rest of the integration suite needs), so we gate them
    behind ``skip_if_no_token``.

    ``auth login`` and ``auth use`` are DANGEROUS (they mutate
    ``~/.direct-cli/auth.json``) and are intentionally NOT covered here.
    """

    def test_auth_status_json(self):
        result = invoke_get("auth", "status", "--format", "json")
        self.assertEqual(result.exit_code, 0, result.output)
        # If credentials come from env vars without a saved OAuth profile,
        # `auth status --format json` prints "No active profile." in plain
        # text and exits 0 — skip rather than blow up on json.loads.
        try:
            payload = json.loads(result.output)
        except json.JSONDecodeError:
            self.skipTest(
                f"auth status returned non-JSON output (no active profile?): "
                f"{result.output[:200]}"
            )
        for key in ("profile", "source", "has_token"):
            self.assertIn(key, payload, f"auth status JSON missing {key}: {payload}")
        self.assertTrue(payload["has_token"], payload)

    def test_auth_list(self):
        result = invoke_get("auth", "list")
        self.assertEqual(result.exit_code, 0, result.output)


if __name__ == "__main__":
    unittest.main()

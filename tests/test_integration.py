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

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli

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


def get_first_campaign_id() -> int | None:
    """Return the first available campaign ID, or None if no campaigns exist."""
    result = invoke_get("campaigns", "get", "--limit", "1", "--format", "json")
    if result.exit_code != 0:
        return None
    data = json.loads(result.output)
    if isinstance(data, list) and data:
        return data[0].get("Id")
    return None


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
                f"TEXT_AD {ad['Id']} missing TextAd — "
                "TextAdFieldNames may not be sent",
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
        cls.campaign_id = get_first_campaign_id()

    def test_get_leads(self):
        if not self.campaign_id:
            self.skipTest("No campaigns found in account")
        result = invoke_get(
            "leads",
            "get",
            "--campaign-ids",
            str(self.campaign_id),
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
    def test_get_businesses(self):
        result = invoke_get("businesses", "get", "--limit", "1", "--format", "json")
        assert_success(result, "businesses get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAdVideos(unittest.TestCase):
    def test_get_advideos(self):
        result = invoke_get("advideos", "get", "--limit", "1", "--format", "json")
        assert_success(result, "advideos get")


@pytest.mark.integration
@skip_if_no_token
class TestReadOnlyAgencyClients(unittest.TestCase):
    def test_get_agencyclients(self):
        result = invoke_get("agencyclients", "get", "--limit", "1", "--format", "json")
        if result.exit_code != 0 and (
            "403" in result.output or "Access denied" in result.output
        ):
            self.skipTest("agencyclients returned 403 — not an agency account")
        assert_success(result, "agencyclients get")


if __name__ == "__main__":
    unittest.main()

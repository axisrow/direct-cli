"""
Integration tests for Direct CLI — read-only commands.

Requires a real Yandex Direct API token. Tests are automatically skipped
if YANDEX_DIRECT_TOKEN is not set in the environment or .env file.

Run with:
    pytest -m integration -v

Write operations (add/update/delete/set) are tested separately in
``test_integration_write.py`` against the sandbox API.  See that file
for coverage details.

The commands below remain excluded from *both* test files (with rationale):

    ads moderate      — submits ad for review, side effect on moderation queue
    agencyclients *   — requires agency account permissions
    clients update    — account-wide mutation
    sitelinks get     — requires explicit --ids, no list endpoint
    feeds get         — requires explicit --ids, no list endpoint
"""

import json
import os
import unittest

import pytest
from click.testing import CliRunner
from dotenv import load_dotenv

from direct_cli.cli import cli

load_dotenv()

TOKEN = os.getenv("YANDEX_DIRECT_TOKEN")

skip_if_no_token = pytest.mark.skipif(
    not TOKEN,
    reason="YANDEX_DIRECT_TOKEN is not set — skipping integration tests",
)


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


if __name__ == "__main__":
    unittest.main()

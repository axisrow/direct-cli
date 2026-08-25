"""
Tests for Direct CLI
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from direct_cli._deprecated import DEPRECATED_ENTRYPOINT_MESSAGE, deprecated_main
from direct_cli.cli import cli
from direct_cli.utils import get_docs_url


class _FakeAdGroupsResponse:
    def __call__(self) -> "_FakeAdGroupsResponse":
        return self

    def extract(self) -> list[dict[str, int]]:
        return [{"Id": 1}]


class _FakeAdGroupsEndpoint:
    def __init__(self, client: "_FakeAdGroupsClient", resource_name: str) -> None:
        self.client = client
        self.resource_name = resource_name

    def post(self, data: dict[str, Any]) -> _FakeAdGroupsResponse:
        self.client.calls.append((self.resource_name, data))
        return _FakeAdGroupsResponse()


class _FakeAdGroupsClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def adgroups(self) -> _FakeAdGroupsEndpoint:
        return _FakeAdGroupsEndpoint(self, "adgroups")

    def adgroups_v501(self) -> _FakeAdGroupsEndpoint:
        return _FakeAdGroupsEndpoint(self, "adgroups_v501")


class _FakeAdsResponse:
    """Fake ``ads()`` response supporting both ``iter_items`` (get) and
    ``extract`` (suspend/resume), keyed by the request method in the body."""

    def __init__(self, ad_ids: list[int], result_key: str) -> None:
        self._ad_ids = ad_ids
        self._result_key = result_key

    def __call__(self) -> "_FakeAdsResponse":
        return self

    def iter_items(self):
        return iter({"Id": ad_id} for ad_id in self._ad_ids)

    def extract(self) -> dict[str, Any]:
        return {
            self._result_key: [{"Id": ad_id, "Errors": []} for ad_id in self._ad_ids]
        }


class _FakeAdsEndpoint:
    def __init__(self, client: "_FakeAdsClient") -> None:
        self.client = client

    def post(self, data: dict[str, Any]) -> _FakeAdsResponse:
        self.client.calls.append(("ads", data))
        method = data["method"]
        if method == "get":
            return _FakeAdsResponse(self.client.ad_ids, "unused")
        result_key = f"{method.capitalize()}Results"
        return _FakeAdsResponse(self.client.ad_ids, result_key)


class _FakeAdsClient:
    """Fake client for ``adgroups suspend``/``adgroups resume`` (issue #573):
    ``ads().post`` with ``method="get"`` returns ``ad_ids`` via
    ``iter_items``; any other method returns them via ``extract`` under
    ``<Method>Results``."""

    def __init__(self, ad_ids: list[int]) -> None:
        self.ad_ids = ad_ids
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def ads(self) -> _FakeAdsEndpoint:
        return _FakeAdsEndpoint(self)


class TestCLI(unittest.TestCase):
    """Test CLI commands"""

    def setUp(self):
        self.runner = CliRunner()

    def test_cli_help(self):
        """Test CLI help command (English opt-in via --locale en)."""
        result = self.runner.invoke(cli, ["--locale", "en", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Command-line interface for Yandex Direct API", result.output)
        self.assertIn("Usage: direct", result.output)
        self.assertIn("Credential context:", result.output)
        self.assertIn(
            "YANDEX_DIRECT_LOGIN selects the Yandex Direct Client-Login", result.output
        )
        self.assertIn("direct auth status", result.output)
        self.assertIn("Item-level Yandex Direct Errors", result.output)
        self.assertIn("Error 8800", result.output)

    def test_cli_help_russian_by_default(self):
        """Root help and epilog default to Russian."""
        # Clear the suite-wide en pin so the genuine Russian default renders.
        result = self.runner.invoke(
            cli, ["--help"], env={"YANDEX_DIRECT_CLI_LOCALE": ""}
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Контекст учётных данных", result.output)
        self.assertIn("Ошибка 8800", result.output)

    def test_cli_version(self):
        """Test CLI version command"""
        result = self.runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)
        expected = f"direct, version {version('direct-cli')}"
        self.assertEqual(result.output.strip(), expected)

    def test_campaigns_help(self):
        """Test campaigns help"""
        result = self.runner.invoke(cli, ["--locale", "en", "campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage campaigns", result.output)
        self.assertIn("Usage: direct campaigns", result.output)
        self.assertIn(f"Documentation: {get_docs_url('campaigns')}", result.output)

    def test_adgroups_help(self):
        """Test adgroups help"""
        result = self.runner.invoke(cli, ["--locale", "en", "adgroups", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage ad groups", result.output)

    def test_keywords_help(self):
        """Test keywords help"""
        result = self.runner.invoke(cli, ["--locale", "en", "keywords", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage keywords", result.output)

    def test_reports_help(self):
        """Test reports help"""
        result = self.runner.invoke(cli, ["--locale", "en", "reports", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Generate and manage reports", result.output)
        self.assertIn(f"Documentation: {get_docs_url('reports')}", result.output)

    def test_registered_mapped_groups_show_docs_url(self):
        """Registered groups from resource mapping show their documentation URL."""
        mapped_groups = sorted(set(cli.commands) & set(RESOURCE_MAPPING_V5))
        self.assertTrue(mapped_groups)
        for group in mapped_groups:
            with self.subTest(group=group):
                result = self.runner.invoke(cli, [group, "--help"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn(
                    f"Documentation: {get_docs_url(group)}",
                    result.output,
                )

    def test_group_help_does_not_resolve_client_login_over_network(self):
        """``<group> --help`` must never make the #480 client-login API call.

        Regression: a cold OAuth profile with an email login + no
        ``login_migration_checked`` flag made every CLI invocation — including
        ``--help`` — fire a network ``clients.get`` with no timeout, which
        could hang the CLI (and the whole test suite). Help/version passes run
        no command, so they must skip the resolver entirely.
        """
        import direct_cli.auth as auth_module

        cold_profile = {
            "source": "oauth",
            "token": "cold-token",
            "refresh_token": "cold-refresh",
            "login": "someone@yandex.ru",
            "expires_at": float(2**31),
        }
        calls = {"n": 0}

        def _counting_resolver(*_args, **_kwargs):
            calls["n"] += 1
            return None

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(auth_module, "load_env_file", return_value=None),
            patch.object(auth_module, "get_active_profile", return_value="default"),
            patch.object(auth_module, "get_oauth_profile", return_value=cold_profile),
            patch.object(
                auth_module, "_resolve_client_login_via_api", _counting_resolver
            ),
            patch.object(sys, "argv", ["direct", "bids", "--help"]),
        ):
            result = self.runner.invoke(cli, ["bids", "--help"])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(
            calls["n"], 0, "client-login resolver must not run on a --help pass"
        )

    def test_get_credentials_skips_login_resolve_when_disallowed(self):
        """``allow_login_resolve=False`` suppresses the #480 network migration."""
        import direct_cli.auth as auth_module

        cold_profile = {
            "source": "oauth",
            "token": "cold-token",
            "refresh_token": "cold-refresh",
            "login": "someone@yandex.ru",
            "expires_at": float(2**31),
        }
        calls = {"n": 0}

        def _counting_resolver(*_args, **_kwargs):
            calls["n"] += 1
            return None

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(auth_module, "load_env_file", return_value=None),
            patch.object(auth_module, "get_active_profile", return_value="default"),
            patch.object(auth_module, "get_oauth_profile", return_value=cold_profile),
            patch.object(
                auth_module, "_resolve_client_login_via_api", _counting_resolver
            ),
        ):
            token, login = auth_module.get_credentials(allow_login_resolve=False)

        self.assertEqual(token, "cold-token")
        self.assertEqual(calls["n"], 0)

    def test_adgroups_v501_resource_mapping_exists_for_unified_groups(self):
        """Unified ad groups must be sent to the documented v501 endpoint."""
        self.assertEqual(
            RESOURCE_MAPPING_V5["adgroups_v501"]["resource"],
            "json/v501/adgroups",
        )
        self.assertEqual(
            RESOURCE_MAPPING_V5["adgroups_v501"]["methods"],
            ["add", "update"],
        )

    def test_adgroups_add_unified_uses_v501_endpoint(self):
        """UNIFIED_AD_GROUP add payloads must not use the default v5 resource."""
        fake_client = _FakeAdGroupsClient()
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                [
                    "adgroups",
                    "add",
                    "--name",
                    "Unified Group",
                    "--campaign-id",
                    "12345",
                    "--type",
                    "UNIFIED_AD_GROUP",
                    "--region-ids",
                    "1,225",
                    "--offer-retargeting",
                    "YES",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(fake_client.calls[0][0], "adgroups_v501")
        adgroup = fake_client.calls[0][1]["params"]["AdGroups"][0]
        self.assertEqual(adgroup["UnifiedAdGroup"]["OfferRetargeting"], "YES")

    def test_adgroups_update_unified_uses_v501_endpoint(self):
        """UnifiedAdGroup update blocks must use the documented v501 resource."""
        fake_client = _FakeAdGroupsClient()
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                [
                    "adgroups",
                    "update",
                    "--id",
                    "67890",
                    "--name",
                    "Updated Unified",
                    "--offer-retargeting",
                    "NO",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(fake_client.calls[0][0], "adgroups_v501")
        adgroup = fake_client.calls[0][1]["params"]["AdGroups"][0]
        self.assertEqual(adgroup["Name"], "Updated Unified")
        self.assertEqual(adgroup["UnifiedAdGroup"]["OfferRetargeting"], "NO")

    def test_adgroups_add_smart_keeps_v5_endpoint(self):
        """Non-unified ad group payloads keep the regular v5 resource."""
        fake_client = _FakeAdGroupsClient()
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                [
                    "adgroups",
                    "add",
                    "--name",
                    "Smart Group",
                    "--campaign-id",
                    "12345",
                    "--type",
                    "SMART_AD_GROUP",
                    "--region-ids",
                    "1,225",
                    "--feed-id",
                    "42",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(fake_client.calls[0][0], "adgroups")

    def test_adgroups_update_smart_keeps_v5_endpoint(self):
        """Smart-only update payloads keep the regular v5 resource."""
        fake_client = _FakeAdGroupsClient()
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                [
                    "adgroups",
                    "update",
                    "--id",
                    "67890",
                    "--ad-title-source",
                    "FEED_NAME",
                    "--ad-body-source",
                    "FEED_DESCRIPTION",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(fake_client.calls[0][0], "adgroups")
        adgroup = fake_client.calls[0][1]["params"]["AdGroups"][0]
        self.assertEqual(adgroup["SmartAdGroup"]["AdTitleSource"], "FEED_NAME")
        self.assertEqual(
            adgroup["SmartAdGroup"]["AdBodySource"],
            "FEED_DESCRIPTION",
        )

    def test_adgroups_suspend_batches_group_ads(self):
        """issue #573: suspend resolves the group's ads via ads.get then
        suspends them via ads.suspend, in the same client session."""
        fake_client = _FakeAdsClient(ad_ids=[10, 20, 30])
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                ["adgroups", "suspend", "--id", "555"],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(fake_client.calls), 2)
        get_call, suspend_call = fake_client.calls
        self.assertEqual(get_call[1]["method"], "get")
        self.assertEqual(
            get_call[1]["params"]["SelectionCriteria"], {"AdGroupIds": [555]}
        )
        self.assertEqual(suspend_call[1]["method"], "suspend")
        self.assertEqual(
            suspend_call[1]["params"]["SelectionCriteria"], {"Ids": [10, 20, 30]}
        )
        payload = json.loads(result.output)
        self.assertEqual(
            payload["SuspendResults"],
            [
                {"Id": 10, "Errors": []},
                {"Id": 20, "Errors": []},
                {"Id": 30, "Errors": []},
            ],
        )

    def test_adgroups_resume_batches_group_ads(self):
        fake_client = _FakeAdsClient(ad_ids=[7])
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                ["adgroups", "resume", "--id", "555"],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        suspend_call = fake_client.calls[1]
        self.assertEqual(suspend_call[1]["method"], "resume")
        payload = json.loads(result.output)
        self.assertEqual(payload["ResumeResults"], [{"Id": 7, "Errors": []}])

    def test_adgroups_suspend_empty_group_sends_no_ads_request(self):
        """An empty group must not send ads.suspend with an empty Ids array."""
        fake_client = _FakeAdsClient(ad_ids=[])
        adgroups_module = import_module("direct_cli.commands.adgroups")

        with patch.object(adgroups_module, "create_client", return_value=fake_client):
            result = self.runner.invoke(
                cli,
                ["adgroups", "suspend", "--id", "555"],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(fake_client.calls[0][1]["method"], "get")
        payload = json.loads(result.output)
        self.assertEqual(payload, {"SuspendResults": []})

    def test_auth_help_has_no_docs_url(self):
        """Auth is not a Yandex Direct API resource and has no docs epilog."""
        result = self.runner.invoke(cli, ["auth", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Documentation:", result.output)

    def test_ads_add_help_documents_text_ad_optional_extensions(self):
        result = self.runner.invoke(cli, ["--locale", "en", "ads", "add", "--help"])
        self.assertEqual(result.exit_code, 0)
        collapsed = " ".join(result.output.split())
        self.assertIn(
            "Ad type: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | DYNAMIC_TEXT_AD | "
            "MOBILE_APP_IMAGE_AD | RESPONSIVE_AD | SHOPPING_AD | LISTING_AD | "
            "SMART_AD_BUILDER_AD | TEXT_AD_BUILDER_AD",
            collapsed,
        )
        self.assertIn("Ad text (TEXT_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)", collapsed)
        self.assertIn(
            "Ad image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
            "DYNAMIC_TEXT_AD / MOBILE_APP_IMAGE_AD)",
            collapsed,
        )
        self.assertIn(
            "Repeatable MobileAppAd.Features item as FEATURE=YES|NO", collapsed
        )
        self.assertIn("Comma-separated ResponsiveAd.Titles values", collapsed)
        self.assertIn("Comma-separated ResponsiveAd.Texts values", collapsed)
        self.assertIn("Comma-separated ResponsiveAd.AdImageHashes values", collapsed)
        self.assertIn(
            "Comma-separated ResponsiveAd.VideoExtensionIds values", collapsed
        )
        self.assertIn(
            "FinalUrl (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD)", collapsed
        )
        self.assertIn(
            "TextAd/MobileAppAd.VideoExtension.CreativeId (TEXT_AD / MOBILE_APP_AD)",
            collapsed,
        )
        self.assertIn(
            "TextAd/ResponsiveAd.PriceExtension.Price in micro-rubles",
            collapsed,
        )
        self.assertIn(
            "Optional; if supplied, PriceExtension add also requires", collapsed
        )
        self.assertIn(
            "BusinessId (TEXT_AD / RESPONSIVE_AD / SHOPPING_AD / LISTING_AD)",
            collapsed,
        )
        self.assertIn("TextAd.PreferVCardOverBusiness value: YES or NO", collapsed)
        self.assertIn(
            "ErirAdDescription (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
            "MOBILE_APP_IMAGE_AD / RESPONSIVE_AD / non-SMART AdBuilder add subtypes)",
            collapsed,
        )
        self.assertIn(
            "SmartAdBuilderAd.LogoExtensionHash (SMART_AD_BUILDER_AD)", collapsed
        )
        self.assertIn(
            "AdBuilder Creative.CreativeId for non-SMART AdBuilder add subtypes",
            collapsed,
        )
        self.assertIn(
            "Comma-separated AdBuilder TrackingPixels.Items values",
            collapsed,
        )
        self.assertIn(
            "ShoppingAd/ListingAd.FeedId (SHOPPING_AD / LISTING_AD)",
            collapsed,
        )
        self.assertIn(
            "Repeatable ShoppingAd/ListingAd.FeedFilterConditions item as "
            "OPERAND:OPERATOR:ARG1|ARG2",
            collapsed,
        )
        self.assertIn(
            "ShoppingAd/ListingAd.DefaultTexts value "
            "(required for SHOPPING_AD/LISTING_AD)",
            collapsed,
        )

    def test_ads_update_help_documents_text_ad_image_hash(self):
        result = self.runner.invoke(cli, ["--locale", "en", "ads", "update", "--help"])
        self.assertEqual(result.exit_code, 0)
        # Click may wrap the help text across lines, so collapse whitespace
        # before searching for the canonical phrase.
        collapsed = " ".join(result.output.split())
        self.assertIn(
            "Image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / "
            "DYNAMIC_TEXT_AD / MOBILE_APP_IMAGE_AD)",
            collapsed,
        )
        self.assertIn(
            "Tracking URL (MOBILE_APP_AD / MOBILE_APP_AD_BUILDER_AD / "
            "MOBILE_APP_CPC_VIDEO_AD_BUILDER_AD / MOBILE_APP_IMAGE_AD)",
            collapsed,
        )
        self.assertIn(
            "TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | DYNAMIC_TEXT_AD | "
            "MOBILE_APP_IMAGE_AD | RESPONSIVE_AD | SHOPPING_AD | LISTING_AD | "
            "SMART_AD_BUILDER_AD | TEXT_AD_BUILDER_AD",
            collapsed,
        )
        self.assertIn("Comma-separated ResponsiveAd.Titles values", collapsed)
        self.assertIn("Comma-separated ResponsiveAd.Texts values", collapsed)
        self.assertIn(
            "Comma-separated ResponsiveAd.AdImageHashes.Items values", collapsed
        )
        self.assertIn(
            "Repeatable ShoppingAd/ListingAd FeedFilterConditions item", collapsed
        )
        self.assertIn(
            "FinalUrl (TEXT_AD / TEXT_IMAGE_AD / TEXT_AD_BUILDER_AD)", collapsed
        )
        self.assertIn("TextAd.PreferVCardOverBusiness value: YES or NO", collapsed)
        self.assertIn(
            "Repeatable MobileAppAd.Features item as FEATURE=YES|NO", collapsed
        )
        self.assertIn(
            "Comma-separated ShoppingAd/ListingAd.TitleSources.Items values",
            collapsed,
        )
        self.assertIn("AdBuilder Creative.CreativeId", collapsed)
        self.assertIn("SmartAdBuilderAd.LogoExtensionHash", collapsed)
        self.assertIn(
            "Comma-separated AdBuilder TrackingPixels.Items values", collapsed
        )

    def test_clients_update_help_documents_erir_organization_flags(self):
        result = self.runner.invoke(cli, ["clients", "update", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--erir-organization-name", result.output)
        self.assertIn("--erir-organization-kpp", result.output)
        self.assertIn("--erir-organization-epay-number", result.output)
        self.assertIn("--erir-organization-reg-number", result.output)
        self.assertIn("--erir-organization-oksm-number", result.output)
        self.assertIn("--erir-organization-okved-code", result.output)

    def test_clients_update_help_documents_erir_contract_flags(self):
        result = self.runner.invoke(cli, ["clients", "update", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--erir-contract-number", result.output)
        self.assertIn("--erir-contract-date", result.output)
        self.assertIn("--erir-contract-type", result.output)
        self.assertIn("--erir-contract-action-type", result.output)
        self.assertIn("--erir-contract-subject-type", result.output)
        self.assertIn("--erir-contract-is-agency-payment", result.output)
        self.assertIn("--erir-contract-price-amount", result.output)
        self.assertIn("--erir-contract-price-including-vat", result.output)

    def test_clients_update_help_documents_erir_contragent_flags(self):
        result = self.runner.invoke(cli, ["clients", "update", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--erir-contragent-name", result.output)
        self.assertIn("--erir-contragent-kpp", result.output)
        self.assertIn("--erir-contragent-phone", result.output)
        self.assertIn("--erir-contragent-epay-number", result.output)
        self.assertIn("--erir-contragent-reg-number", result.output)
        self.assertIn("--erir-contragent-oksm-number", result.output)
        self.assertIn("--erir-contragent-tin-type", result.output)
        self.assertIn("--erir-contragent-tin", result.output)

    def test_bids_set_help_documents_optional_bid_flags(self):
        result = self.runner.invoke(cli, ["bids", "set", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--campaign-id", result.output)
        self.assertIn("--adgroup-id", result.output)
        self.assertIn("--keyword-id", result.output)
        self.assertIn("--context-bid", result.output)
        self.assertIn("--autotargeting-search-bid-is-auto", result.output)
        self.assertIn("--priority", result.output)

    def test_keywordbids_set_help_documents_optional_bid_flags(self):
        result = self.runner.invoke(cli, ["keywordbids", "set", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--campaign-id", result.output)
        self.assertIn("--adgroup-id", result.output)
        self.assertIn("--keyword-id", result.output)
        self.assertIn("--autotargeting-search-bid-is-auto", result.output)
        self.assertIn("--priority", result.output)

    def test_keywords_add_help_documents_scalar_autotargeting_flags(self):
        result = self.runner.invoke(cli, ["keywords", "add", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--autotargeting-search-bid-is-auto", result.output)
        self.assertIn("--priority", result.output)

    def test_keywords_help_documents_autotargeting_category_flags(self):
        add_result = self.runner.invoke(cli, ["keywords", "add", "--help"])
        update_result = self.runner.invoke(cli, ["keywords", "update", "--help"])
        self.assertEqual(add_result.exit_code, 0)
        self.assertEqual(update_result.exit_code, 0)
        self.assertIn("--autotargeting-category", add_result.output)
        self.assertIn("--autotargeting-category", update_result.output)

    def test_keywords_help_documents_autotargeting_brand_option_flags(self):
        add_result = self.runner.invoke(cli, ["keywords", "add", "--help"])
        update_result = self.runner.invoke(cli, ["keywords", "update", "--help"])
        self.assertEqual(add_result.exit_code, 0)
        self.assertEqual(update_result.exit_code, 0)
        self.assertIn("--autotargeting-brand-option", add_result.output)
        self.assertIn("--autotargeting-brand-option", update_result.output)

    def test_keywords_help_documents_autotargeting_settings_flags(self):
        add_result = self.runner.invoke(cli, ["keywords", "add", "--help"])
        update_result = self.runner.invoke(cli, ["keywords", "update", "--help"])
        self.assertEqual(add_result.exit_code, 0)
        self.assertEqual(update_result.exit_code, 0)
        for option in (
            "--autotargeting-settings-exact",
            "--autotargeting-settings-narrow",
            "--autotargeting-settings-alternative",
            "--autotargeting-settings-accessory",
            "--autotargeting-settings-broader",
            "--autotargeting-settings-without-brands",
            "--autotargeting-settings-with-advertiser-brand",
            "--autotargeting-settings-with-competitors-brand",
        ):
            self.assertIn(option, add_result.output)
            self.assertIn(option, update_result.output)

    def test_canonical_groups_in_help(self):
        """Test canonical transport groups"""
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("dynamicads", result.output)
        self.assertIn("smartadtargets", result.output)
        self.assertIn("negativekeywordsharedsets", result.output)

    def test_legacy_group_aliases_are_removed(self):
        """Test legacy group aliases are not registered"""
        for command in ["dynamictargets", "smarttargets", "negativekeywords"]:
            result = self.runner.invoke(cli, [command, "--help"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("No such command", result.output)

    def test_auth_login_alias_is_not_registered(self):
        """Test underscore auth alias is intentionally not registered."""
        result = self.runner.invoke(cli, ["auth_login", "--help"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_embedded_api_errors_are_reported_as_cli_errors(self):
        """Direct item-level Errors should be visible as command failures."""

        class FakeResponse:
            def __call__(self):
                return self

            def extract(self):
                return [
                    {
                        "Errors": [
                            {
                                "Code": 8800,
                                "Message": "Object not found",
                                "Details": "Ad not found",
                            }
                        ]
                    }
                ]

        class FakeClient:
            def ads(self):
                return self

            def post(self, data):
                return FakeResponse()

        ads_module = import_module("direct_cli.commands.ads._cli")
        with patch.object(ads_module, "create_client", return_value=FakeClient()):
            result = self.runner.invoke(
                cli,
                [
                    "ads",
                    "update",
                    "--id",
                    "17722952450",
                    "--type",
                    "TEXT_AD",
                    "--image-hash",
                    "h5ojHelMOAjyHko5bq6QFw",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Yandex Direct API returned errors", result.output)
        self.assertIn("Error 8800: Object not found", result.output)
        self.assertIn("Details: Ad not found", result.output)
        self.assertIn("current Client-Login/account", result.output)
        self.assertIn("YANDEX_DIRECT_LOGIN", result.output)

    def test_ads_add_surfaces_combinatorial_banner_warning(self):
        """Warning 10251 (silent TEXT_AD-to-combinatorial substitution, #850)
        must be surfaced on stderr, not only visible in the JSON body."""

        class FakeResponse:
            def __call__(self):
                return self

            def extract(self):
                return {
                    "AddResults": [
                        {
                            "Id": 1918459304756685779,
                            "Warnings": [
                                {
                                    "Code": 10165,
                                    "Message": "Parameter will not be applied",
                                },
                                {
                                    "Code": 10251,
                                    "Message": (
                                        "Создание " "текстовых " "баннеров " "закрыто"
                                    ),
                                },
                            ],
                            "Errors": [],
                        }
                    ]
                }

        class FakeClient:
            def ads(self):
                return self

            def post(self, data):
                return FakeResponse()

        ads_module = import_module("direct_cli.commands.ads._cli")
        with patch.object(ads_module, "create_client", return_value=FakeClient()):
            result = self.runner.invoke(
                cli,
                [
                    "ads",
                    "add",
                    "--adgroup-id",
                    "5786702368",
                    "--title",
                    "Test",
                    "--text",
                    "Test text",
                    "--href",
                    "https://example.com",
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertEqual(result.exit_code, 0, result.output)
        # The JSON result body (stdout) is unaffected — still parses cleanly
        # once the stderr-only warning banner is excluded.
        json_body = "\n".join(
            line
            for line in result.output.splitlines()
            if not line.startswith("\x1b[33m")
        )
        parsed = json.loads(json_body)
        self.assertEqual(parsed["AddResults"][0]["Warnings"][1]["Code"], 10251)
        # A human-readable explanation is printed via the stderr-only helper.
        self.assertIn("10251", result.stderr)
        self.assertIn("combinatorial banner", result.stderr)
        # The unexplained code (10165) still gets a raw pass-through line.
        self.assertIn("10165", result.stderr)

    def test_keywords_bulk_add_surfaces_item_errors(self):
        """Bulk-add path must not bypass the item-level error renderer. See #211."""

        class FakeResponse:
            def __call__(self):
                return self

            def extract(self):
                return [
                    {
                        "Errors": [
                            {
                                "Code": 8800,
                                "Message": "Object not found",
                                "Details": "Ad group not found",
                            }
                        ]
                    }
                ]

        class FakeClient:
            def keywords(self):
                return self

            def post(self, data):
                return FakeResponse()

        keywords_module = import_module("direct_cli.commands.keywords")
        with patch.object(keywords_module, "create_client", return_value=FakeClient()):
            result = self.runner.invoke(
                cli,
                [
                    "keywords",
                    "add",
                    "--keywords-json",
                    '[{"AdGroupId": 1, "Keyword": "shoes"}]',
                ],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Yandex Direct API returned errors", result.output)
        self.assertIn("Error 8800: Object not found", result.output)
        self.assertIn("Details: Ad group not found", result.output)
        self.assertIn("current Client-Login/account", result.output)

    def test_keywords_bulk_add_multi_chunk_partial_success(self):
        """Earlier chunk OK, later chunk fails: diagnostic shows both. See #211."""

        good_chunk_result = [
            {"Id": idx} for idx in range(1, 11)  # KEYWORDS_ADD_MAX_BATCH = 10
        ]
        # Mixed chunk: one item succeeds, one fails. The success item must
        # land in partial-success diagnostic; the failure item must not.
        bad_chunk_result = [
            {"Id": 999},
            {
                "Errors": [
                    {
                        "Code": 8800,
                        "Message": "Object not found",
                        "Details": "Ad group not found",
                    }
                ]
            },
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __call__(self):
                return self

            def extract(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def keywords(self):
                return self

            def post(self, data):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(good_chunk_result)
                return FakeResponse(bad_chunk_result)

        keywords_json = json.dumps(
            [{"AdGroupId": 1, "Keyword": f"kw-{i}"} for i in range(12)]
        )

        keywords_module = import_module("direct_cli.commands.keywords")
        with patch.object(keywords_module, "create_client", return_value=FakeClient()):
            result = self.runner.invoke(
                cli,
                ["keywords", "add", "--keywords-json", keywords_json],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Yandex Direct API returned errors", result.output)
        self.assertIn("Error 8800: Object not found", result.output)
        self.assertIn("Partial success before failure", result.output)
        # Successful items (chunk 1 ids 1..10 + mixed chunk id 999) must
        # appear in the partial-success diagnostic.
        self.assertIn('"Id": 1', result.output)
        self.assertIn('"Id": 10', result.output)
        self.assertIn('"Id": 999', result.output)
        # The failed item must NOT be claimed as "already created".
        diagnostic = result.output.split("Partial success before failure")[1]
        self.assertNotIn('"Errors"', diagnostic)

    def test_keywords_bulk_add_all_failure_second_chunk(self):
        """Chunk 1 OK, chunk 2 all-failure: diagnostic shows chunk 1 only. See #211."""

        good_chunk_result = [{"Id": idx} for idx in range(1, 11)]
        all_failure_chunk_result = [
            {
                "Errors": [
                    {
                        "Code": 8800,
                        "Message": "Object not found",
                        "Details": "Ad group not found",
                    }
                ]
            }
        ]

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __call__(self):
                return self

            def extract(self):
                return self.payload

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def keywords(self):
                return self

            def post(self, data):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse(good_chunk_result)
                return FakeResponse(all_failure_chunk_result)

        keywords_json = json.dumps(
            [{"AdGroupId": 1, "Keyword": f"kw-{i}"} for i in range(11)]
        )

        keywords_module = import_module("direct_cli.commands.keywords")
        with patch.object(keywords_module, "create_client", return_value=FakeClient()):
            result = self.runner.invoke(
                cli,
                ["keywords", "add", "--keywords-json", keywords_json],
                env={
                    "YANDEX_DIRECT_TOKEN": "test-token",
                    "YANDEX_DIRECT_LOGIN": "axisrow",
                },
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Error 8800: Object not found", result.output)
        self.assertIn("Partial success before failure", result.output)
        # Only chunk-1 ids must appear in the diagnostic.
        diagnostic = result.output.split("Partial success before failure")[1]
        self.assertIn('"Id": 1', diagnostic)
        self.assertIn('"Id": 10', diagnostic)
        # The failed chunk's Errors item must NOT be in the diagnostic.
        self.assertNotIn('"Errors"', diagnostic)

    def test_changes_help_uses_canonical_names(self):
        """Test changes help only exposes canonical command names"""
        result = self.runner.invoke(cli, ["changes", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("check-campaigns", result.output)
        self.assertIn("check-dictionaries", result.output)
        self.assertNotIn("checkcamp", result.output)
        self.assertNotIn("checkdict", result.output)

    def test_changes_help_uses_canonical_datetime_format(self):
        result = self.runner.invoke(
            cli, ["--locale", "en", "changes", "check-campaigns", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("YYYY-MM-DDTHH:MM:SSZ", result.output)
        self.assertNotIn("ISO format", result.output)

    def test_keywordsresearch_help_uses_canonical_names(self):
        """Test keywords research help only exposes canonical command names"""
        result = self.runner.invoke(cli, ["keywordsresearch", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("has-search-volume", result.output)
        self.assertIn("deduplicate", result.output)
        self.assertNotIn("has-volume", result.output)

    def test_list_alias_is_removed(self):
        """Test legacy list alias is not registered"""
        result = self.runner.invoke(cli, ["adgroups", "list", "--help"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_write_command_help_hides_blob_flags(self):
        for command in [
            ["campaigns", "add"],
            ["campaigns", "update"],
            ["adgroups", "add"],
            ["ads", "add"],
            ["dynamicads", "add"],
            ["smartadtargets", "add"],
            ["sitelinks", "add"],
            ["vcards", "add"],
            ["adimages", "add"],
            ["agencyclients", "add"],
        ]:
            result = self.runner.invoke(cli, [*command, "--help"])
            self.assertEqual(result.exit_code, 0)
            self.assertNotIn("--json", result.output)
            self.assertNotIn("--links", result.output)
            self.assertNotIn("--notification-json", result.output)
            self.assertNotIn("--send-invite-to-json", result.output)

    def test_deprecated_direct_cli_entrypoint_exits_with_hint(self):
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as context:
            with redirect_stderr(stderr):
                deprecated_main()
        self.assertEqual(context.exception.code, 2)
        self.assertIn(DEPRECATED_ENTRYPOINT_MESSAGE, stderr.getvalue())


class TestAuth(unittest.TestCase):
    """Test authentication"""

    def test_missing_token(self):
        """Test error when token is missing"""
        from direct_cli.auth import get_credentials

        with patch.dict(os.environ, {}, clear=True):
            with patch("direct_cli.auth.load_env_file"):
                with patch("direct_cli.auth.get_active_profile", return_value=None):
                    with self.assertRaises(ValueError) as context:
                        get_credentials(token=None, login=None)

        self.assertIn("API token required", str(context.exception))


class TestReadmeContract(unittest.TestCase):
    """Test README documents the canonical CLI contract."""

    def setUp(self):
        self.readme = Path(__file__).resolve().parent.parent / "README.md"
        self.content = self.readme.read_text(encoding="utf-8")

    def test_readme_describes_canonical_only_policy(self):
        """README must describe the canonical-only policy and alias exceptions."""
        self.assertIn("canonical-only", self.content)
        self.assertIn("explicit exception", self.content)
        self.assertNotIn("canonical MCP-facing names", self.content)

    def test_readme_contains_canonical_naming_rules(self):
        """README must define the canonical group/command naming contract."""
        self.assertIn("direct <group> <command> [flags]", self.content)
        self.assertIn("Naming rules:", self.content)
        self.assertIn("multiword groups are concatenated", self.content)
        self.assertIn("multiword commands use kebab-case", self.content)
        self.assertIn(
            "The `direct` executable defines the public naming contract",
            self.content,
        )
        self.assertIn("use direct instead of direct-cli", self.content)

    def test_readme_contains_canonical_command_examples(self):
        """README must include canonical examples for renamed commands."""
        self.assertIn("direct changes check-campaigns", self.content)
        self.assertIn("direct changes check-dictionaries", self.content)
        self.assertIn("direct keywordsresearch has-search-volume", self.content)
        self.assertIn("direct negativekeywordsharedsets update", self.content)
        self.assertIn("direct smartadtargets update", self.content)
        self.assertIn("direct dynamicads set-bids", self.content)

    def test_readme_tracks_dynamicads_update_api_status(self):
        """README must document that dynamicads update is unsupported by the API."""
        self.assertIn("dynamicads update", self.content)
        self.assertIn("unsupported by API", self.content)
        self.assertNotIn("dynamicads update` is still a transport gap", self.content)

    def test_readme_documents_auth_profile_contract(self):
        """README must document profile auth flow and profile env variables."""
        self.assertIn("direct auth login", self.content)
        self.assertIn("direct auth list", self.content)
        self.assertIn("direct auth use --profile agency1", self.content)
        self.assertIn("direct --profile agency1", self.content)
        self.assertIn("YANDEX_DIRECT_TOKEN_AGENCY1", self.content)
        self.assertIn("YANDEX_DIRECT_LOGIN_AGENCY1", self.content)
        self.assertNotIn("YANDEX_DIRECT_PROFILE", self.content)

    def test_readme_documents_text_ad_image_update_contract(self):
        """README must show WSDL-valid TEXT_AD image update syntax."""
        self.assertIn(
            "direct ads update --id 99999 --type TEXT_AD --image-hash",
            self.content,
        )
        self.assertNotIn("direct ads update --id 99999 --status", self.content)

    def test_readme_documents_api_item_errors(self):
        """README must explain item-level API Errors and 8800 account context."""
        self.assertIn("item-level `Errors`", self.content)
        self.assertIn("Code `8800`", self.content)
        self.assertIn("Client-Login", self.content)
        self.assertIn("YANDEX_DIRECT_LOGIN", self.content)

    def test_readme_documents_removed_legacy_names(self):
        """README must include a table of removed legacy group/command names."""
        for legacy in [
            "dynamictargets",
            "smarttargets",
            "negativekeywords",
        ]:
            self.assertIn(legacy, self.content)


if __name__ == "__main__":
    unittest.main()

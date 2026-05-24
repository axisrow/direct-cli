"""
Tests for Direct CLI
"""

import io
import json
import os
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


class TestCLI(unittest.TestCase):
    """Test CLI commands"""

    def setUp(self):
        self.runner = CliRunner()

    def test_cli_help(self):
        """Test CLI help command"""
        result = self.runner.invoke(cli, ["--help"])
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

    def test_cli_version(self):
        """Test CLI version command"""
        result = self.runner.invoke(cli, ["--version"])
        self.assertEqual(result.exit_code, 0)
        expected = f"direct, version {version('direct-cli')}"
        self.assertEqual(result.output.strip(), expected)

    def test_campaigns_help(self):
        """Test campaigns help"""
        result = self.runner.invoke(cli, ["campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage campaigns", result.output)
        self.assertIn("Usage: direct campaigns", result.output)
        self.assertIn(f"Documentation: {get_docs_url('campaigns')}", result.output)

    def test_adgroups_help(self):
        """Test adgroups help"""
        result = self.runner.invoke(cli, ["adgroups", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage ad groups", result.output)

    def test_keywords_help(self):
        """Test keywords help"""
        result = self.runner.invoke(cli, ["keywords", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage keywords", result.output)

    def test_reports_help(self):
        """Test reports help"""
        result = self.runner.invoke(cli, ["reports", "--help"])
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

    def test_auth_help_has_no_docs_url(self):
        """Auth is not a Yandex Direct API resource and has no docs epilog."""
        result = self.runner.invoke(cli, ["auth", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Documentation:", result.output)

    def test_ads_update_help_documents_text_ad_image_hash(self):
        result = self.runner.invoke(cli, ["ads", "update", "--help"])
        self.assertEqual(result.exit_code, 0)
        # Click may wrap the help text across lines, so collapse whitespace
        # before searching for the canonical phrase.
        collapsed = " ".join(result.output.split())
        self.assertIn(
            "Image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)",
            collapsed,
        )
        self.assertIn(
            "TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | DYNAMIC_TEXT_AD | "
            "RESPONSIVE_AD",
            collapsed,
        )
        self.assertIn("Comma-separated ResponsiveAd.Titles values", collapsed)
        self.assertIn("Comma-separated ResponsiveAd.Texts values", collapsed)
        self.assertIn(
            "Comma-separated ResponsiveAd.AdImageHashes.Items values", collapsed
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

        ads_module = import_module("direct_cli.commands.ads")
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
        result = self.runner.invoke(cli, ["changes", "check-campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("YYYY-MM-DDTHH:MM:SS", result.output)
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
        self.assertIn("Group naming rules", self.content)
        self.assertIn("Command naming rules", self.content)
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

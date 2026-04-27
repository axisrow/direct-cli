"""
Tests for Direct CLI
"""

import io
import os
import unittest
from contextlib import redirect_stderr
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli._vendor.tapi_yandex_direct.resource_mapping import RESOURCE_MAPPING_V5
from direct_cli._deprecated import DEPRECATED_ENTRYPOINT_MESSAGE, deprecated_main
from direct_cli.cli import cli
from direct_cli.utils import get_docs_url


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

    def test_auth_help_has_no_docs_url(self):
        """Auth is not a Yandex Direct API resource and has no docs epilog."""
        result = self.runner.invoke(cli, ["auth", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Documentation:", result.output)

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

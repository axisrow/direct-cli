"""
Tests for Direct CLI
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch
from click.testing import CliRunner
from direct_cli.cli import cli


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

    def test_campaigns_help(self):
        """Test campaigns help"""
        result = self.runner.invoke(cli, ["campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage campaigns", result.output)
        self.assertIn("Usage: direct campaigns", result.output)

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

    def test_changes_help_uses_canonical_names(self):
        """Test changes help only exposes canonical command names"""
        result = self.runner.invoke(cli, ["changes", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("check-campaigns", result.output)
        self.assertIn("check-dictionaries", result.output)
        self.assertNotIn("checkcamp", result.output)
        self.assertNotIn("checkdict", result.output)

    def test_keywordsresearch_help_uses_canonical_names(self):
        """Test keywords research help only exposes canonical command names"""
        result = self.runner.invoke(cli, ["keywordsresearch", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("has-search-volume", result.output)
        self.assertIn("deduplicate", result.output)
        self.assertNotIn("has-volume", result.output)

    def test_list_alias_help(self):
        """Test legacy list alias is not registered"""
        result = self.runner.invoke(cli, ["adgroups", "list", "--help"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)


class TestAuth(unittest.TestCase):
    """Test authentication"""

    def test_missing_token(self):
        """Test error when token is missing"""
        from direct_cli.auth import get_credentials

        with patch.dict(os.environ, {}, clear=True):
            with patch("direct_cli.auth.load_env_file"):
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
        self.assertIn("direct-cli owns the public naming contract", self.content)

    def test_readme_contains_canonical_command_examples(self):
        """README must include canonical examples for renamed commands."""
        self.assertIn("direct changes check-campaigns", self.content)
        self.assertIn("direct changes check-dictionaries", self.content)
        self.assertIn("direct keywordsresearch has-search-volume", self.content)
        self.assertIn("direct negativekeywordsharedsets update", self.content)
        self.assertIn("direct smartadtargets update", self.content)
        self.assertIn("direct dynamicads set-bids", self.content)

    def test_readme_tracks_dynamicads_update_gap(self):
        """README must document the missing dynamicads update transport gap."""
        self.assertIn("dynamicads update", self.content)
        self.assertIn("transport gap", self.content)


if __name__ == "__main__":
    unittest.main()

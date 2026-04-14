"""
Tests for Direct CLI
"""

import os
import unittest
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

    def test_list_alias_is_removed(self):
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


if __name__ == "__main__":
    unittest.main()

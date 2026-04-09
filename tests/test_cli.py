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

    def test_canonical_alias_groups_in_help(self):
        """Test canonical plugin-compatible group aliases"""
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("dynamictargets", result.output)
        self.assertIn("smarttargets", result.output)
        self.assertIn("negativekeywords", result.output)

    def test_dynamic_targets_alias_help(self):
        """Test dynamic targets alias help"""
        result = self.runner.invoke(cli, ["dynamictargets", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage dynamic ad targets", result.output)
        self.assertIn("list", result.output)

    def test_smart_targets_alias_help(self):
        """Test smart targets alias help"""
        result = self.runner.invoke(cli, ["smarttargets", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage smart ad targets", result.output)
        self.assertIn("list", result.output)

    def test_negative_keywords_alias_help(self):
        """Test negative keywords alias help"""
        result = self.runner.invoke(cli, ["negativekeywords", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage negative keyword shared sets", result.output)
        self.assertIn("list", result.output)

    def test_changes_short_aliases_help(self):
        """Test changes short aliases"""
        result = self.runner.invoke(cli, ["changes", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("checkcamp", result.output)
        self.assertIn("checkdict", result.output)

    def test_keywordsresearch_aliases_help(self):
        """Test keywords research aliases"""
        result = self.runner.invoke(cli, ["keywordsresearch", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("has-volume", result.output)
        self.assertIn("deduplicate", result.output)

    def test_list_alias_help(self):
        """Test list alias on a resource command"""
        result = self.runner.invoke(cli, ["adgroups", "list", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Usage: direct adgroups list", result.output)


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

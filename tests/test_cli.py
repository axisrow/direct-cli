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

    def test_campaigns_help(self):
        """Test campaigns help"""
        result = self.runner.invoke(cli, ["campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage campaigns", result.output)

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


class TestAuth(unittest.TestCase):
    """Test authentication"""

    def test_missing_token(self):
        """Test error when token is missing"""
        from direct_cli.auth import get_credentials

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("direct_cli.auth.load_env_file"),
            self.assertRaises(ValueError) as context,
        ):
            get_credentials(token=None, login=None)

        self.assertIn("API token required", str(context.exception))


if __name__ == "__main__":
    unittest.main()

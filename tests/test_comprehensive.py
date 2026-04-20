"""
Comprehensive tests for Direct CLI
"""

import os
import unittest
from unittest.mock import patch
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli import auth, utils, output


class TestCLIHelp(unittest.TestCase):
    """Test CLI help output"""

    def setUp(self):
        self.runner = CliRunner()

    def test_cli_help(self):
        result = self.runner.invoke(cli, ["--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Command-line interface for Yandex Direct API", result.output)

    def test_campaigns_help(self):
        result = self.runner.invoke(cli, ["campaigns", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Manage campaigns", result.output)
        self.assertIn("get", result.output)
        self.assertIn("add", result.output)


class TestCommandsRegistered(unittest.TestCase):
    """Test that all commands are registered"""

    EXPECTED_COMMANDS = [
        "campaigns",
        "adgroups",
        "ads",
        "keywords",
        "keywordbids",
        "bids",
        "bidmodifiers",
        "audiencetargets",
        "retargeting",
        "creatives",
        "adimages",
        "advideos",
        "adextensions",
        "sitelinks",
        "vcards",
        "leads",
        "clients",
        "agencyclients",
        "dictionaries",
        "changes",
        "reports",
        "turbopages",
        "negativekeywordsharedsets",
        "feeds",
        "smartadtargets",
        "businesses",
        "keywordsresearch",
        "dynamicads",
        "dynamicfeedadtargets",
        "strategies",
    ]

    def test_all_expected_commands_registered(self):
        """Every expected command must be present"""
        missing = [cmd for cmd in self.EXPECTED_COMMANDS if cmd not in cli.commands]
        self.assertEqual(missing, [], f"Missing commands: {missing}")

    def test_no_unexpected_commands(self):
        """No command should exist that is not in the expected list"""
        extra = [cmd for cmd in cli.commands if cmd not in self.EXPECTED_COMMANDS]
        self.assertEqual(
            extra, [], f"Unexpected commands (add them to EXPECTED_COMMANDS): {extra}"
        )


class TestUtils(unittest.TestCase):
    """Test utility functions"""

    def test_parse_ids_valid(self):
        self.assertEqual(utils.parse_ids("1,2,3"), [1, 2, 3])

    def test_parse_ids_with_spaces(self):
        self.assertEqual(utils.parse_ids("1, 2 , 3"), [1, 2, 3])

    def test_parse_ids_none(self):
        self.assertIsNone(utils.parse_ids(None))

    def test_parse_ids_empty_string(self):
        self.assertIsNone(utils.parse_ids(""))

    def test_parse_ids_invalid(self):
        with self.assertRaises(ValueError) as ctx:
            utils.parse_ids("1,abc,3")
        self.assertIn("Invalid ID", str(ctx.exception))
        self.assertIn("abc", str(ctx.exception))

    def test_parse_json_valid(self):
        self.assertEqual(utils.parse_json('{"key": "value"}'), {"key": "value"})

    def test_parse_json_invalid(self):
        with self.assertRaises(ValueError):
            utils.parse_json("{bad json}")

    def test_parse_json_none(self):
        self.assertIsNone(utils.parse_json(None))

    def test_get_default_fields_campaigns(self):
        fields = utils.get_default_fields("campaigns")
        self.assertIn("Id", fields)
        self.assertIn("Name", fields)

    def test_get_default_fields_unknown(self):
        fields = utils.get_default_fields("unknown_resource")
        self.assertEqual(fields, ["Id", "Name"])


class TestOutputFormatters(unittest.TestCase):
    """Test output formatters"""

    def setUp(self):
        self.data = [{"id": 1, "name": "Test"}, {"id": 2, "name": "Test2"}]

    def test_format_json(self):
        result = output.format_json(self.data)
        self.assertIn('"id": 1', result)
        self.assertIn('"name": "Test"', result)

    def test_format_table(self):
        result = output.format_table(self.data)
        self.assertIn("Test", result)

    def test_format_csv(self):
        result = output.format_csv(self.data)
        self.assertIn("id,name", result)
        self.assertIn("Test", result)

    def test_format_tsv(self):
        result = output.format_tsv(self.data)
        self.assertIn("id\tname", result)


class TestAuth(unittest.TestCase):
    """Test authentication module"""

    def test_missing_token_raises(self):
        """Raises ValueError when no token is available anywhere"""
        with patch.dict(os.environ, {}, clear=True):
            with patch("direct_cli.auth.load_env_file"):
                with self.assertRaises(ValueError) as ctx:
                    auth.get_credentials(token=None, login=None)
        self.assertIn("API token required", str(ctx.exception))

    def test_token_from_argument(self):
        token, login = auth.get_credentials(token="test_token", login="test_login")
        self.assertEqual(token, "test_token")
        self.assertEqual(login, "test_login")

    def test_token_from_env(self):
        with patch.dict(os.environ, {"YANDEX_DIRECT_TOKEN": "env_token"}, clear=True):
            with patch("direct_cli.auth.load_env_file"):
                token, login = auth.get_credentials(token=None, login=None)
        self.assertEqual(token, "env_token")

    def test_argument_takes_priority_over_env(self):
        with patch.dict(os.environ, {"YANDEX_DIRECT_TOKEN": "env_token"}, clear=True):
            token, _ = auth.get_credentials(token="arg_token", login=None)
        self.assertEqual(token, "arg_token")


class TestErrorHandling(unittest.TestCase):
    """Test CLI error handling"""

    def test_campaigns_get_without_token_fails(self):
        """Command must fail when no token is provided"""
        runner = CliRunner(env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""})
        with patch("direct_cli.auth.load_env_file"):
            result = runner.invoke(cli, ["campaigns", "get"])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()

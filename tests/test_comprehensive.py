"""
Tests for Direct CLI utility surface — command-registry inventory,
utils parsers, output formatters, and auth credential chain.

Surfaces here are NOT duplicated by ``test_cli.py`` (which focuses on
help-text and behavior contracts). The previous ``TestCLIHelp`` and
``test_campaigns_help`` were redundant with ``test_cli.py`` and have
been removed. See issue #396 for context.
"""

import os
import unittest
from unittest.mock import patch
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli import auth, utils, output


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
        "trackingparams",
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
        "balance",
        "api",
        "v4finance",
        "v4account",
        "v4goals",
        "v4events",
        "v4wordstat",
        "v4tags",
        "v4keywords",
        "v4adimage",
        "v4forecast",
        "v4meta",
        "auth",
        "masters",
        "history",
        "support",
        "adrestrictions",
        "playwright",
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

    def test_format_csv_extra_field_in_later_record(self):
        """#900: optional fields appearing only in later records export fine."""
        data = [
            {"Id": 1, "Type": "MOBILE_APP_AD"},
            {"Id": 2, "Type": "TEXT_AD", "TextAd": {"Title": "Example"}},
        ]
        result = output.format_csv(data)
        self.assertEqual(result.splitlines()[0], "Id,Type,TextAd")
        self.assertIn("1,MOBILE_APP_AD,", result)
        self.assertIn("2,TEXT_AD,", result)
        self.assertIn("Title", result)

    def test_format_tsv_extra_field_in_later_record(self):
        data = [
            {"Id": 1, "Type": "MOBILE_APP_AD"},
            {"Id": 2, "Type": "TEXT_AD", "TextAd": {"Title": "Example"}},
        ]
        result = output.format_tsv(data)
        self.assertEqual(result.splitlines()[0], "Id\tType\tTextAd")
        self.assertIn("1\tMOBILE_APP_AD\t", result)

    def test_format_csv_missing_field_in_later_record(self):
        """#900 inverse: later records with fewer keys get empty cells."""
        data = [
            {"Id": 1, "Name": "A", "Extra": "x"},
            {"Id": 2, "Name": "B"},
        ]
        result = output.format_csv(data)
        self.assertEqual(result.splitlines()[0], "Id,Name,Extra")
        self.assertIn("1,A,x", result)
        self.assertIn("2,B,", result)

    def test_format_csv_column_set_independent_of_row_order(self):
        first, second = (
            {"Id": 1, "Type": "MOBILE_APP_AD"},
            {"Id": 2, "Type": "TEXT_AD", "TextAd": {"Title": "Example"}},
        )
        cols = [
            output.format_csv([a, b]).splitlines()[0].split(",")
            for a, b in ((first, second), (second, first))
        ]
        self.assertEqual(set(cols[0]), set(cols[1]))
        self.assertEqual(set(cols[0]), {"Id", "Type", "TextAd"})

    def test_format_csv_explicit_headers_preserved(self):
        result = output.format_csv(self.data, headers=["name", "id"])
        self.assertEqual(result.splitlines()[0], "name,id")
        self.assertEqual(result.splitlines()[1], "Test,1")


class TestAuth(unittest.TestCase):
    """Test authentication module"""

    def test_missing_token_raises(self):
        """Raises ValueError when no token is available anywhere"""
        with patch.dict(os.environ, {}, clear=True):
            with patch("direct_cli.auth.load_env_file"):
                with patch("direct_cli.auth.get_active_profile", return_value=None):
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
                with patch("direct_cli.auth.get_active_profile", return_value=None):
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
            with patch("direct_cli.auth.get_active_profile", return_value=None):
                result = runner.invoke(cli, ["campaigns", "get"])
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()

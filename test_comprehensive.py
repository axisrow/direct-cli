#!/usr/bin/env python
"""
Comprehensive tests for Direct CLI
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from click.testing import CliRunner
from direct_cli.cli import cli
from direct_cli import auth, utils, output


def test_cli_help():
    """Test main CLI help"""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    print("=" * 60)
    print("TEST 1: Main CLI --help")
    print("=" * 60)
    print("Exit code:", result.exit_code)
    print(result.output)

    assert result.exit_code == 0
    assert "Command-line interface for Yandex Direct API" in result.output
    print("✓ Test passed\n")


def test_campaigns_help():
    """Test campaigns help"""
    runner = CliRunner()
    result = runner.invoke(cli, ["campaigns", "--help"])

    print("=" * 60)
    print("TEST 2: campaigns --help")
    print("=" * 60)
    print("Exit code:", result.exit_code)
    print(result.output)

    assert result.exit_code == 0
    assert "Manage campaigns" in result.output
    assert "get" in result.output
    assert "add" in result.output
    print("✓ Test passed\n")


def test_all_commands_registered():
    """Test all commands are registered"""
    print("=" * 60)
    print("TEST 3: All commands registered")
    print("=" * 60)

    expected_commands = [
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
    ]

    print(f"Expected commands: {len(expected_commands)}")
    print(f"Registered commands: {len(cli.commands)}")

    for cmd in expected_commands:
        if cmd in cli.commands:
            print(f"  ✓ {cmd}")
        else:
            print(f"  ✗ {cmd} - MISSING")
            assert False, f"Command {cmd} not registered"

    assert len(cli.commands) == len(expected_commands)
    print("✓ Test passed\n")


def test_utils():
    """Test utility functions"""
    print("=" * 60)
    print("TEST 4: Utility functions")
    print("=" * 60)

    # Test parse_ids
    result = utils.parse_ids("1,2,3")
    assert result == [1, 2, 3], f"parse_ids failed: {result}"
    print('  ✓ parse_ids("1,2,3") = [1, 2, 3]')

    # Test parse_json
    result = utils.parse_json('{"key": "value"}')
    assert result == {"key": "value"}, f"parse_json failed: {result}"
    print('  ✓ parse_json(\'{"key": "value"}\') = {"key": "value"}')

    # Test get_default_fields
    fields = utils.get_default_fields("campaigns")
    assert "Id" in fields, f"get_default_fields failed: {fields}"
    print(f'  ✓ get_default_fields("campaigns") contains "Id"')

    print("✓ Test passed\n")


def test_output_formatters():
    """Test output formatters"""
    print("=" * 60)
    print("TEST 5: Output formatters")
    print("=" * 60)

    data = [{"id": 1, "name": "Test"}, {"id": 2, "name": "Test2"}]

    # Test JSON
    json_output = output.format_json(data)
    assert '"id": 1' in json_output
    print("  ✓ format_json works")

    # Test table
    table_output = output.format_table(data)
    assert "Test" in table_output
    print("  ✓ format_table works")

    # Test CSV
    csv_output = output.format_csv(data)
    assert "id,name" in csv_output
    print("  ✓ format_csv works")

    print("✓ Test passed\n")


def test_auth():
    """Test authentication module"""
    print("=" * 60)
    print("TEST 6: Authentication module")
    print("=" * 60)

    # Test missing token error
    try:
        auth.get_credentials(token=None, login=None)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "Token required" in str(e)
        print("  ✓ Raises ValueError when token is missing")

    # Test with token provided
    token, login = auth.get_credentials(token="test_token", login="test_login")
    assert token == "test_token"
    assert login == "test_login"
    print("  ✓ get_credentials returns correct values")

    print("✓ Test passed\n")


def test_error_handling():
    """Test error handling"""
    print("=" * 60)
    print("TEST 7: Error handling (no token)")
    print("=" * 60)

    runner = CliRunner()

    # Try to get campaigns without token - should fail
    result = runner.invoke(cli, ["campaigns", "get"])
    print(f"Exit code: {result.exit_code}")
    print(f"Output (first 200 chars): {result.output[:200]}")

    # Should fail because no token provided
    assert result.exit_code != 0
    print("  ✓ Command fails without token (as expected)")

    print("✓ Test passed\n")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("DIRECT CLI - COMPREHENSIVE TEST SUITE")
    print("=" * 60 + "\n")

    tests = [
        test_cli_help,
        test_campaigns_help,
        test_all_commands_registered,
        test_utils,
        test_output_formatters,
        test_auth,
        test_error_handling,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ Test failed: {e}\n")
            failed += 1
        except Exception as e:
            print(f"✗ Test error: {e}\n")
            import traceback

            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"✓ Passed: {passed}/{len(tests)}")
    print(f"✗ Failed: {failed}/{len(tests)}")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)

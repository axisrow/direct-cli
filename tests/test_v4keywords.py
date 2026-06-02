import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


def test_get_suggestion_dry_run_builds_keywords_array():
    result = _invoke(
        "v4keywords",
        "get-suggestion",
        "--keyword",
        "холодильник",
        "--keyword",
        "камера",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetKeywordsSuggestion",
        "param": {"Keywords": ["холодильник", "камера"]},
    }


def test_get_suggestion_strips_and_drops_blank_keywords():
    result = _invoke(
        "v4keywords",
        "get-suggestion",
        "--keyword",
        "  телефон  ",
        "--keyword",
        "   ",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetKeywordsSuggestion",
        "param": {"Keywords": ["телефон"]},
    }


def test_get_suggestion_missing_keyword_fails():
    result = _invoke("v4keywords", "get-suggestion", "--dry-run")

    assert result.exit_code != 0
    assert "Missing option '--keyword'" in result.output


def test_get_suggestion_all_blank_keywords_fails():
    result = _invoke(
        "v4keywords",
        "get-suggestion",
        "--keyword",
        "   ",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--keyword must not be empty" in result.output


def test_get_suggestion_formats_mocked_response():
    with patch("direct_cli.v4.emit.create_v4_client") as create_client:
        with patch(
            "direct_cli.v4.emit.call_v4",
            return_value=["холодильник купить", "холодильник цена"],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "v4keywords",
                "get-suggestion",
                "--keyword",
                "холодильник",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        "холодильник купить",
        "холодильник цена",
    ]
    call.assert_called_once_with(
        create_client.return_value,
        "GetKeywordsSuggestion",
        {"Keywords": ["холодильник"]},
    )


def test_v4keywords_help_has_no_json_input_flag():
    for args in [
        ("v4keywords", "--help"),
        ("v4keywords", "get-suggestion", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4keywords_command_declares_contract():
    commands = cli.commands["v4keywords"].commands
    assert commands["get-suggestion"].v4_method == "GetKeywordsSuggestion"
    assert commands["get-suggestion"].v4_contract == get_v4_contract(
        "GetKeywordsSuggestion"
    )

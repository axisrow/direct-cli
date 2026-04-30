import json
from unittest.mock import patch

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import (
    PARAM_OBJECT,
    PARAM_OPTIONAL_OBJECT,
    PARAM_SCALAR,
    SOURCE_DOCS,
    get_v4_contract,
)


def _invoke(*args: str):
    env = {"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=env).invoke(cli, list(args))


def test_create_report_dry_run_uses_phrases_only_body():
    result = _invoke(
        "v4wordstat",
        "create-report",
        "--phrases",
        "buy laptop",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "CreateNewWordstatReport",
        "param": {"Phrases": ["buy laptop"]},
    }


def test_create_report_dry_run_adds_geo_ids():
    result = _invoke(
        "v4wordstat",
        "create-report",
        "--phrases",
        "buy laptop,buy desktop",
        "--geo-ids",
        "213,225",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "CreateNewWordstatReport",
        "param": {
            "Phrases": ["buy laptop", "buy desktop"],
            "GeoID": [213, 225],
        },
    }


def test_create_report_parses_three_phrase_entries():
    result = _invoke(
        "v4wordstat",
        "create-report",
        "--phrases",
        "a,b,c",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["param"]["Phrases"] == ["a", "b", "c"]


def test_create_report_empty_phrases_fail_before_api_call():
    with patch("direct_cli.commands.v4wordstat.create_v4_client") as create_client:
        result = _invoke(
            "v4wordstat",
            "create-report",
            "--phrases",
            ",",
        )

    assert result.exit_code != 0
    assert "--phrases must not be empty" in result.output
    create_client.assert_not_called()


def test_create_report_more_than_10_phrases_fail_before_api_call():
    phrases = ",".join(str(index) for index in range(11))
    with patch("direct_cli.commands.v4wordstat.create_v4_client") as create_client:
        result = _invoke(
            "v4wordstat",
            "create-report",
            "--phrases",
            phrases,
        )

    assert result.exit_code != 0
    assert "--phrases accepts at most 10 phrases" in result.output
    create_client.assert_not_called()


def test_create_report_invalid_geo_ids_fail_before_api_call():
    with patch("direct_cli.commands.v4wordstat.create_v4_client") as create_client:
        result = _invoke(
            "v4wordstat",
            "create-report",
            "--phrases",
            "buy laptop",
            "--geo-ids",
            "213,abc",
        )

    assert result.exit_code != 0
    assert "Invalid ID: 'abc'" in result.output
    create_client.assert_not_called()


def test_list_reports_dry_run_has_no_param():
    result = _invoke("v4wordstat", "list-reports", "--dry-run")

    assert result.exit_code == 0
    assert json.loads(result.output) == {"method": "GetWordstatReportList"}


def test_get_report_dry_run_uses_scalar_report_id():
    result = _invoke(
        "v4wordstat",
        "get-report",
        "--report-id",
        "123",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetWordstatReport",
        "param": 123,
    }


def test_delete_report_dry_run_uses_scalar_report_id():
    result = _invoke(
        "v4wordstat",
        "delete-report",
        "--report-id",
        "123",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "DeleteWordstatReport",
        "param": 123,
    }


def test_list_reports_formats_mocked_response_as_json():
    response = [{"ReportID": 123, "StatusReport": "Done"}]
    with patch("direct_cli.commands.v4wordstat.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4wordstat.call_v4",
            return_value=response,
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4wordstat",
                "list-reports",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == response
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=False,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "GetWordstatReportList",
        None,
    )


def test_get_report_formats_mocked_response_as_table():
    with patch("direct_cli.commands.v4wordstat.create_v4_client"):
        with patch(
            "direct_cli.commands.v4wordstat.call_v4",
            return_value=[{"Phrase": "buy laptop", "Shows": 42}],
        ):
            result = _invoke(
                "--token",
                "token",
                "v4wordstat",
                "get-report",
                "--report-id",
                "123",
                "--format",
                "table",
            )

    assert result.exit_code == 0
    assert "buy laptop" in result.output
    assert "Shows" in result.output


def test_v4wordstat_help_contains_no_json_input_flag():
    for args in [
        ("v4wordstat", "--help"),
        ("v4wordstat", "create-report", "--help"),
        ("v4wordstat", "list-reports", "--help"),
        ("v4wordstat", "get-report", "--help"),
        ("v4wordstat", "delete-report", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4wordstat_commands_declare_v4_contracts():
    commands = cli.commands["v4wordstat"].commands

    expected = {
        "create-report": "CreateNewWordstatReport",
        "list-reports": "GetWordstatReportList",
        "get-report": "GetWordstatReport",
        "delete-report": "DeleteWordstatReport",
    }
    for command_name, method in expected.items():
        assert commands[command_name].v4_method == method
        assert commands[command_name].v4_contract == get_v4_contract(method)


def test_v4wordstat_contracts_are_docs_backed():
    create = get_v4_contract("CreateNewWordstatReport")
    list_reports = get_v4_contract("GetWordstatReportList")
    get = get_v4_contract("GetWordstatReport")
    delete = get_v4_contract("DeleteWordstatReport")

    assert create.param_shape == PARAM_OBJECT
    assert create.source_status == SOURCE_DOCS
    assert create.example_param == {"Phrases": ["buy laptop"], "GeoID": [213]}
    assert list_reports.param_shape == PARAM_OPTIONAL_OBJECT
    assert list_reports.source_status == SOURCE_DOCS
    assert get.param_shape == PARAM_SCALAR
    assert get.source_status == SOURCE_DOCS
    assert delete.param_shape == PARAM_SCALAR
    assert delete.source_status == SOURCE_DOCS

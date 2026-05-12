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


def test_create_dry_run_uses_required_currency_body():
    result = _invoke(
        "v4forecast",
        "create",
        "--phrases",
        "buy laptop",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "CreateNewForecast",
        "param": {
            "Phrases": ["buy laptop"],
            "Currency": "RUB",
        },
    }


def test_create_dry_run_adds_geo_ids():
    result = _invoke(
        "v4forecast",
        "create",
        "--phrases",
        "buy laptop,buy desktop",
        "--geo-ids",
        "213,225",
        "--currency",
        "USD",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "CreateNewForecast",
        "param": {
            "Phrases": ["buy laptop", "buy desktop"],
            "Currency": "USD",
            "GeoID": [213, 225],
        },
    }


def test_create_parses_three_phrase_entries():
    result = _invoke(
        "v4forecast",
        "create",
        "--phrases",
        "a,b,c",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["param"]["Phrases"] == ["a", "b", "c"]


def test_create_empty_phrases_fail_before_api_call():
    with patch("direct_cli.commands.v4forecast.create_v4_client") as create_client:
        result = _invoke(
            "v4forecast",
            "create",
            "--phrases",
            ",",
        )

    assert result.exit_code != 0
    assert "--phrases must not be empty" in result.output
    create_client.assert_not_called()


def test_create_more_than_100_phrases_fail_before_api_call():
    phrases = ",".join(str(index) for index in range(101))
    with patch("direct_cli.commands.v4forecast.create_v4_client") as create_client:
        result = _invoke(
            "v4forecast",
            "create",
            "--phrases",
            phrases,
        )

    assert result.exit_code != 0
    assert "--phrases accepts at most 100 phrases" in result.output
    create_client.assert_not_called()


def test_create_invalid_geo_ids_fail_before_api_call():
    with patch("direct_cli.commands.v4forecast.create_v4_client") as create_client:
        result = _invoke(
            "v4forecast",
            "create",
            "--phrases",
            "buy laptop",
            "--geo-ids",
            "213,abc",
        )

    assert result.exit_code != 0
    assert "Invalid ID: 'abc'" in result.output
    create_client.assert_not_called()


def test_list_dry_run_has_no_param():
    result = _invoke("v4forecast", "list", "--dry-run")

    assert result.exit_code == 0
    assert json.loads(result.output) == {"method": "GetForecastList"}


def test_get_dry_run_uses_scalar_forecast_id():
    result = _invoke(
        "v4forecast",
        "get",
        "--forecast-id",
        "123",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetForecast",
        "param": 123,
    }


def test_delete_dry_run_uses_scalar_forecast_id():
    result = _invoke(
        "v4forecast",
        "delete",
        "--forecast-id",
        "123",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "DeleteForecastReport",
        "param": 123,
    }


def test_list_formats_mocked_response_as_json():
    response = [{"ForecastID": 123, "StatusForecast": "Done"}]
    with patch("direct_cli.commands.v4forecast.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4forecast.call_v4",
            return_value=response,
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4forecast",
                "list",
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
        "GetForecastList",
        None,
    )


def test_v4forecast_help_contains_no_json_input_flag():
    for args in [
        ("v4forecast", "--help"),
        ("v4forecast", "create", "--help"),
        ("v4forecast", "list", "--help"),
        ("v4forecast", "get", "--help"),
        ("v4forecast", "delete", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4forecast_commands_declare_v4_contracts():
    commands = cli.commands["v4forecast"].commands

    expected = {
        "create": "CreateNewForecast",
        "list": "GetForecastList",
        "get": "GetForecast",
        "delete": "DeleteForecastReport",
    }
    for command_name, method in expected.items():
        assert commands[command_name].v4_method == method
        assert commands[command_name].v4_contract == get_v4_contract(method)


def test_v4forecast_contracts_are_docs_backed():
    create = get_v4_contract("CreateNewForecast")
    list_forecasts = get_v4_contract("GetForecastList")
    get = get_v4_contract("GetForecast")
    delete = get_v4_contract("DeleteForecastReport")

    assert create.param_shape == PARAM_OBJECT
    assert create.source_status == SOURCE_DOCS
    assert create.example_param == {
        "Phrases": ["buy laptop"],
        "Currency": "RUB",
        "GeoID": [213],
    }
    assert list_forecasts.param_shape == PARAM_OPTIONAL_OBJECT
    assert list_forecasts.source_status == SOURCE_DOCS
    assert get.param_shape == PARAM_SCALAR
    assert get.source_status == SOURCE_DOCS
    assert delete.param_shape == PARAM_SCALAR
    assert delete.source_status == SOURCE_DOCS

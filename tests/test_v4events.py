import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.v4_contracts import get_v4_contract


def _invoke(*args: str):
    env = {"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""}
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=env).invoke(cli, list(args))


def test_get_events_log_dry_run_uses_canonical_body_with_default_currency():
    result = _invoke(
        "v4events",
        "get-events-log",
        "--from",
        "2026-04-14T00:00:00",
        "--to",
        "2026-04-14T01:00:00",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetEventsLog",
        "param": {
            "TimestampFrom": "2026-04-14T00:00:00",
            "TimestampTo": "2026-04-14T01:00:00",
            "Currency": "RUB",
        },
    }


def test_get_events_log_dry_run_adds_optional_pagination_when_passed():
    result = _invoke(
        "v4events",
        "get-events-log",
        "--from",
        "2026-04-14T00:00:00",
        "--to",
        "2026-04-14T01:00:00",
        "--currency",
        "USD",
        "--limit",
        "100",
        "--offset",
        "20",
        "--dry-run",
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "method": "GetEventsLog",
        "param": {
            "TimestampFrom": "2026-04-14T00:00:00",
            "TimestampTo": "2026-04-14T01:00:00",
            "Currency": "USD",
            "Limit": 100,
            "Offset": 20,
        },
    }


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-04-14T00:00:00Z",
        "2026-04-14 00:00:00",
        "2026-04-14",
    ],
)
def test_get_events_log_rejects_noncanonical_from_datetime(timestamp):
    result = _invoke(
        "v4events",
        "get-events-log",
        "--from",
        timestamp,
        "--to",
        "2026-04-14T01:00:00",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Expected YYYY-MM-DDTHH:MM:SS" in result.output


def test_get_events_log_rejects_from_after_to_before_api_call():
    with patch("direct_cli.commands.v4events.create_v4_client") as create_client:
        result = _invoke(
            "v4events",
            "get-events-log",
            "--from",
            "2026-04-14T02:00:00",
            "--to",
            "2026-04-14T01:00:00",
        )

    assert result.exit_code != 0
    assert "--from must be earlier than or equal to --to" in result.output
    create_client.assert_not_called()


def test_get_events_log_formats_mocked_response_as_json():
    with patch("direct_cli.commands.v4events.create_v4_client") as create_client:
        with patch(
            "direct_cli.commands.v4events.call_v4",
            return_value=[{"Timestamp": "2026-04-14T00:01:00", "EventType": "ADD"}],
        ) as call:
            result = _invoke(
                "--token",
                "token",
                "--login",
                "client-login",
                "v4events",
                "get-events-log",
                "--from",
                "2026-04-14T00:00:00",
                "--to",
                "2026-04-14T01:00:00",
            )

    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {"Timestamp": "2026-04-14T00:01:00", "EventType": "ADD"}
    ]
    create_client.assert_called_once_with(
        token="token",
        login="client-login",
        profile=None,
        sandbox=False,
    )
    call.assert_called_once_with(
        create_client.return_value,
        "GetEventsLog",
        {
            "TimestampFrom": "2026-04-14T00:00:00",
            "TimestampTo": "2026-04-14T01:00:00",
            "Currency": "RUB",
        },
    )


def test_v4events_help_contains_no_json_input_flag():
    for args in [
        ("v4events", "--help"),
        ("v4events", "get-events-log", "--help"),
    ]:
        result = _invoke(*args)
        assert result.exit_code == 0
        assert "--json" not in result.output


def test_v4events_command_declares_v4_contract():
    command = cli.commands["v4events"].commands["get-events-log"]

    assert command.v4_method == "GetEventsLog"
    assert command.v4_contract == get_v4_contract("GetEventsLog")

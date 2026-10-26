"""Tests for ``direct api units`` — API units balance via the Units header (#919).

Yandex has no dedicated "get units" method: the balance arrives in the HTTP
``Units`` header of every response. The command performs the lightest v5 call
(``clients get``) and surfaces that header. The vendored client does not expose
response headers on success, so the command uses ``requests.post`` directly —
hosts come from the endpoint registry, the resource path from
``RESOURCE_MAPPING_V5``.
"""

import json
from unittest import mock

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.commands.api import api


class _FakeResponse:
    def __init__(self, payload=None, headers=None):
        self._payload = payload
        self.headers = headers or {}
        self.content = (
            json.dumps(payload).encode() if payload is not None else b""
        )

    def json(self):
        return self._payload


def _invoke(obj=None, args=("units",)):
    return CliRunner().invoke(
        api, list(args), obj=obj or {"token": "tok", "login": "login", "sandbox": False}
    )


def test_api_group_is_registered_in_cli():
    assert "api" in cli.commands


def test_units_prints_balance():
    fake = _FakeResponse(
        payload={"result": {"Clients": [{"Login": "login"}]}},
        headers={"Units": "27/239100/240000"},
    )
    with mock.patch("direct_cli.commands.api.requests.post", return_value=fake) as post:
        result = _invoke()
    assert result.exit_code == 0, result.output
    assert "239100" in result.output
    assert "240000" in result.output
    url = post.call_args.args[0]
    assert url.startswith("https://api.direct.yandex.com/")
    assert url.endswith("json/v5/clients")
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
    assert post.call_args.kwargs["headers"]["Client-Login"] == "login"


def test_units_sandbox_uses_sandbox_host():
    fake = _FakeResponse(
        payload={"result": {"Clients": []}}, headers={"Units": "1/2/3"}
    )
    with mock.patch("direct_cli.commands.api.requests.post", return_value=fake) as post:
        result = _invoke(obj={"token": "tok", "login": "login", "sandbox": True})
    assert result.exit_code == 0, result.output
    assert post.call_args.args[0].startswith("https://api-sandbox.direct.yandex.com/")


def test_units_without_login_omits_client_login_header():
    fake = _FakeResponse(
        payload={"result": {"Clients": []}}, headers={"Units": "1/2/3"}
    )
    with mock.patch("direct_cli.commands.api.requests.post", return_value=fake) as post:
        result = _invoke(obj={"token": "tok", "login": None, "sandbox": False})
    assert result.exit_code == 0, result.output
    assert "Client-Login" not in post.call_args.kwargs["headers"]


def test_units_api_error_still_reports_units():
    fake = _FakeResponse(
        payload={
            "error": {
                "error_code": 53,
                "error_string": "OAuth token is missing",
                "error_detail": "",
            }
        },
        headers={"Units": "27/239100/240000"},
    )
    with mock.patch("direct_cli.commands.api.requests.post", return_value=fake):
        result = _invoke()
    assert result.exit_code != 0
    assert "53" in result.output
    assert "27/239100/240000" in result.output


def test_units_missing_header_is_an_error():
    fake = _FakeResponse(payload={"result": {"Clients": []}}, headers={})
    with mock.patch("direct_cli.commands.api.requests.post", return_value=fake):
        result = _invoke()
    assert result.exit_code != 0
    assert "Units" in result.output


def test_units_dry_run_makes_no_request():
    with mock.patch("direct_cli.commands.api.requests.post") as post:
        result = _invoke(args=("units", "--dry-run"))
    assert result.exit_code == 0, result.output
    post.assert_not_called()
    assert "json/v5/clients" in result.output

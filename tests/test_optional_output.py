"""Offline tests for the DIRECT_SHOW_UNITS / DIRECT_QUIET optional-output
registry (issue #925): quiet by default, stdout untouched, vendor success
hook fires only on successful responses (#921's error path stays alone)."""

import pytest
from click.testing import CliRunner
from tapi2.exceptions import ResponseProcessException
from unittest.mock import patch

from direct_cli._vendor.tapi_yandex_direct import tapi_yandex_direct as vendored

# The vendored .pyi stubs cover only the public clients; adapters are internal.
from direct_cli._vendor.tapi_yandex_direct.tapi_yandex_direct import (
    YandexDirectClientAdapter,  # pyright: ignore[reportAttributeAccessIssue]
)
from direct_cli.cli import cli
from direct_cli.optional_output import (
    CHANNELS,
    channel_enabled,
    emit,
    install_vendor_hook,
    on_api_response,
    quiet_mode,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.delenv("DIRECT_QUIET", raising=False)
    monkeypatch.delenv("DIRECT_SHOW_UNITS", raising=False)


class FakeResponse:
    """Minimal successful-response stand-in for the vendored process_response."""

    def __init__(self, content=b'{"result": {"Campaigns": []}}', headers=None):
        self.status_code = 200
        self.content = content
        self.headers = headers or {}
        self.request = type("Request", (), {"path_url": "/json/v5/campaigns"})()


def _run_process_response(response, store=None):
    return YandexDirectClientAdapter().process_response(
        response,
        {"data": b'{"method": "get", "params": {}}'},
        store=store if store is not None else {},
    )


class TestRegistry:
    def test_units_channel_registered(self):
        channel = CHANNELS["units"]
        assert channel.env == "DIRECT_SHOW_UNITS"
        assert channel.legacy_default is False

    def test_every_channel_targets_stderr_with_show_env(self):
        for channel in CHANNELS.values():
            assert channel.env.startswith("DIRECT_SHOW_")
            assert channel.stream == "stderr"


class TestResolution:
    def test_quiet_is_the_default(self):
        assert quiet_mode() is True
        assert channel_enabled("units") is False

    def test_empty_quiet_value_keeps_default(self, monkeypatch):
        monkeypatch.setenv("DIRECT_QUIET", "")
        assert quiet_mode() is True

    def test_show_units_enables_even_under_quiet(self, monkeypatch):
        monkeypatch.setenv("DIRECT_QUIET", "1")
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        assert channel_enabled("units") is True

    def test_quiet_zero_without_show_keeps_units_hidden(self, monkeypatch):
        # The Units channel has no pre-#925 visible output, so the legacy
        # behaviour must not start printing it either.
        monkeypatch.setenv("DIRECT_QUIET", "0")
        assert channel_enabled("units") is False

    def test_explicit_show_zero_beats_quiet_zero(self, monkeypatch):
        monkeypatch.setenv("DIRECT_QUIET", "0")
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "0")
        assert channel_enabled("units") is False

    def test_quiet_zero_with_show_one_enables(self, monkeypatch):
        monkeypatch.setenv("DIRECT_QUIET", "0")
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        assert channel_enabled("units") is True

    def test_non_numeric_truthy_values(self, monkeypatch):
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "true")
        assert channel_enabled("units") is True
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "false")
        assert channel_enabled("units") is False


class TestEmit:
    def test_emits_to_stderr_only(self, capsys, monkeypatch):
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        emit("units", "API units: 10/20828/64000")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "API units: 10/20828/64000\n"

    def test_disabled_channel_prints_nothing(self, capsys):
        emit("units", "API units: 10/20828/64000")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""


class TestUnitsLine:
    HEADERS = {"Units": "10/20828/64000"}

    def test_format_matches_units_docs(self, capsys, monkeypatch):
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        on_api_response(FakeResponse(headers=self.HEADERS))
        assert capsys.readouterr().err == "API units: 10/20828/64000\n"

    def test_used_login_appended_when_present(self, capsys, monkeypatch):
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        headers = {"Units": "10/20828/64000", "Units-Used-Login": "agency-login"}
        on_api_response(FakeResponse(headers=headers))
        assert capsys.readouterr().err == (
            "API units: 10/20828/64000 (used-login: agency-login)\n"
        )

    def test_silent_without_units_header(self, capsys, monkeypatch):
        monkeypatch.setenv("DIRECT_SHOW_UNITS", "1")
        on_api_response(FakeResponse(headers={}))
        assert capsys.readouterr().err == ""

    def test_silent_when_channel_disabled(self, capsys):
        on_api_response(FakeResponse(headers=self.HEADERS))
        assert capsys.readouterr().err == ""


class TestVendorHook:
    def test_hook_fires_on_successful_response(self):
        captured = []
        with patch.object(vendored, "SUCCESS_RESPONSE_HOOK", captured.append):
            data = _run_process_response(FakeResponse(headers={"Units": "1/2/3"}))
        assert data == {"result": {"Campaigns": []}}
        assert [r.headers for r in captured] == [{"Units": "1/2/3"}]

    def test_hook_skipped_on_error_response(self):
        # Error responses must keep the #921 contract: no success-hook Units
        # line on top of the error reporting.
        captured = []
        error = FakeResponse(
            content=b'{"error": {"code": 56, "error_string": "limit"}}',
            headers={"Units": "1/2/3"},
        )
        with patch.object(vendored, "SUCCESS_RESPONSE_HOOK", captured.append):
            with pytest.raises(ResponseProcessException):
                _run_process_response(error)
        assert captured == []

    def test_no_hook_is_a_noop(self):
        with patch.object(vendored, "SUCCESS_RESPONSE_HOOK", None):
            data = _run_process_response(FakeResponse())
        assert data == {"result": {"Campaigns": []}}

    def test_install_wires_emitter_once(self):
        with patch.object(vendored, "SUCCESS_RESPONSE_HOOK", None):
            install_vendor_hook()
            assert vendored.SUCCESS_RESPONSE_HOOK is on_api_response
            install_vendor_hook()
            assert vendored.SUCCESS_RESPONSE_HOOK is on_api_response


class TestSafetyOutputNotGated:
    def test_auth_status_note_visible_under_quiet(self, monkeypatch, tmp_path):
        # #909's unbound-folder note is safety output: DIRECT_QUIET=1 must
        # not suppress it (it does not route through the optional registry).
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
        monkeypatch.delenv("YANDEX_DIRECT_INHERIT_GLOBAL", raising=False)
        monkeypatch.setenv("DIRECT_QUIET", "1")
        with patch(
            "direct_cli.commands.auth.get_active_profile", return_value="default"
        ):
            with patch("direct_cli.commands.auth.get_oauth_profile", return_value=None):
                result = CliRunner().invoke(cli, ["auth", "status"])
        assert result.exit_code == 0, result.output
        assert "No credentials bound to this folder." in result.output
        assert "Global profile 'default'" in result.output

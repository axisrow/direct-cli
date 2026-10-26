"""Unit tests for the @handle_api_errors decorator (dedup #491 A2, issue #493).

The decorator replaces the canonical command error-handling block:

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

It must re-raise click.ClickException (incl. click.UsageError) unchanged so
Click renders usage text / its own exit codes, and convert any other exception
into a printed error + click.Abort.
"""

import click
import pytest

from direct_cli.output import handle_api_errors


def test_passes_through_return_value():
    @handle_api_errors
    def ok():
        return 42

    assert ok() == 42


def test_forwards_args_and_kwargs():
    @handle_api_errors
    def echo(a, b, c=0):
        return (a, b, c)

    assert echo(1, 2, c=3) == (1, 2, 3)


def test_reraises_usage_error_unchanged():
    @handle_api_errors
    def boom():
        raise click.UsageError("bad flag")

    with pytest.raises(click.UsageError) as excinfo:
        boom()
    assert "bad flag" in str(excinfo.value)


def test_reraises_click_exception_unchanged():
    @handle_api_errors
    def boom():
        raise click.ClickException("click problem")

    with pytest.raises(click.ClickException) as excinfo:
        boom()
    assert "click problem" in str(excinfo.value)


def test_wraps_generic_exception_into_abort(capsys):
    @handle_api_errors
    def boom():
        raise RuntimeError("api exploded")

    with pytest.raises(click.Abort):
        boom()
    captured = capsys.readouterr()
    # print_error writes the message to stderr with the ✗ marker.
    assert "api exploded" in captured.err
    assert "✗" in captured.err


def test_value_error_is_wrapped_into_abort(capsys):
    @handle_api_errors
    def boom():
        raise ValueError("value problem")

    with pytest.raises(click.Abort):
        boom()
    assert "value problem" in capsys.readouterr().err


def test_abort_raised_inside_is_treated_as_generic_exception():
    """click.Abort is a RuntimeError, not a ClickException, so it falls into the
    generic ``except Exception`` branch and re-raises as a (new) Abort — exactly
    as the canonical block this decorator replaces would have behaved. In
    practice commands never raise Abort inside the body; they raise UsageError or
    let API exceptions propagate."""

    @handle_api_errors
    def boom():
        raise click.Abort()

    with pytest.raises(click.Abort):
        boom()


def test_preserves_function_metadata():
    @handle_api_errors
    def documented(ctx, value):
        """Original docstring."""
        return value

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Original docstring."


# --- Units balance in error output (#919) -----------------------------------
#
# Every vendored API exception carries the raw requests.Response in
# ``.response``; Yandex returns ``Units: spent/left/limit`` on every call.
# The decorator must append that balance so a limit error (56/152/506) is
# diagnosable: zero left = daily quota exhausted, units left = per-method
# throttling or a concurrent client on the same token.


class _FakeResponse:
    def __init__(self, headers):
        self.headers = headers


class _FakeLimitError(Exception):
    """Stand-in for the vendored YandexDirectRequestsLimitError."""

    def __init__(self, message, headers):
        super().__init__(message)
        self.response = _FakeResponse(headers)


def test_appends_units_balance_to_limit_error(capsys):
    @handle_api_errors
    def boom():
        raise _FakeLimitError(
            "request_id=1, error_code=56, "
            "error_string=Exceeded limit of method requests",
            {"Units": "15/239100/240000"},
        )

    with pytest.raises(click.Abort):
        boom()
    err = capsys.readouterr().err
    assert "15/239100/240000" in err
    assert "API units (spent/left/limit): 15/239100/240000" in err


def test_units_hint_zero_balance_says_daily_exhaustion(capsys):
    @handle_api_errors
    def boom():
        raise _FakeLimitError("error_code=152", {"Units": "15000/0/240000"})

    with pytest.raises(click.Abort):
        boom()
    err = capsys.readouterr().err
    assert (
        "daily balance exhausted; retries cannot succeed "
        "until Yandex replenishes units" in err
    )


def test_units_hint_with_balance_says_throttling(capsys):
    @handle_api_errors
    def boom():
        raise _FakeLimitError("error_code=56", {"Units": "15/239100/240000"})

    with pytest.raises(click.Abort):
        boom()
    err = capsys.readouterr().err
    assert (
        "units remain; the limit is per-method throttling "
        "or a concurrent client on the same token" in err
    )


def test_no_units_header_means_no_hint(capsys):
    @handle_api_errors
    def boom():
        raise _FakeLimitError("plain api error", {"Content-Type": "application/json"})

    with pytest.raises(click.Abort):
        boom()
    err = capsys.readouterr().err
    # Pin the exact error line: an empty hint must append nothing at all.
    assert "✗ plain api error\x1b[0m" in err
    assert "API units" not in err


def test_plain_exception_without_response_no_hint(capsys):
    @handle_api_errors
    def boom():
        raise RuntimeError("no response attribute at all")

    with pytest.raises(click.Abort):
        boom()
    assert "API units" not in capsys.readouterr().err

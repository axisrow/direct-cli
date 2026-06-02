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

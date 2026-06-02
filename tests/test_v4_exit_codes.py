"""Regression for issue #227.

v4 command wrappers must let `click.ClickException` (UsageError, BadParameter)
propagate so Click can format the message with a usage hint and exit with
status code 2. Generic runtime exceptions still fall through to
`print_error` + `click.Abort` (exit code 1).
"""

from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from direct_cli.cli import cli

# (module short name, argv invoked through the top-level `cli` group).
# Each argv hits a code path that calls `call_v4` inside the shared
# `emit_or_call_v4`/`emit_or_call_v4_finance` helpers (direct_cli.v4.emit).
# Since #494 every v4 command routes through those helpers, so the real
# `call_v4` / `create_v4_client` are invoked there — we patch the aliases on
# `direct_cli.v4.emit`, not per-command-module.
V4_COMMAND_PROBES = [
    (
        "v4account",
        # `--sandbox` is required at the top level because the command
        # rejects non-sandbox runs without `--dry-run` before reaching
        # the wrapped `call_v4`. We want the wrapper, not the guard.
        [
            "--sandbox",
            "v4account",
            "enable-shared-account",
            "--client-login",
            "agency-test",
        ],
    ),
    (
        "v4events",
        [
            "v4events",
            "get-events-log",
            "--from",
            "2026-05-01T00:00:00",
            "--to",
            "2026-05-02T00:00:00",
        ],
    ),
    (
        "v4finance",
        ["v4finance", "get-clients-units", "--logins", "client1"],
    ),
    (
        "v4forecast",
        ["v4forecast", "create", "--phrases", "buy laptop"],
    ),
    (
        "v4goals",
        ["v4goals", "get-stat-goals", "--campaign-ids", "1"],
    ),
    (
        "v4tags",
        ["v4tags", "get-campaigns", "--campaign-ids", "1"],
    ),
    (
        "v4wordstat",
        ["v4wordstat", "list-reports"],
    ),
]


def _invoke(*args: str):
    env = {"YANDEX_DIRECT_TOKEN": "fake-token", "YANDEX_DIRECT_LOGIN": "fake-login"}
    with patch("direct_cli.cli.get_active_profile", return_value=None):
        return CliRunner(env=env).invoke(cli, list(args))


@pytest.mark.parametrize(
    ("module_name", "argv"),
    V4_COMMAND_PROBES,
    ids=[probe[0] for probe in V4_COMMAND_PROBES],
)
def test_usage_error_from_call_v4_yields_exit_code_2(module_name, argv):
    """If call_v4 raises UsageError, Click must format it and exit with 2."""
    sentinel = "v4 shape validation failed: bogus"

    with (
        patch(
            "direct_cli.v4.emit.call_v4",
            side_effect=click.UsageError(sentinel),
        ),
        patch(
            "direct_cli.v4.emit.create_v4_client",
            return_value=object(),
        ),
    ):
        result = _invoke(*argv)

    assert result.exit_code == 2, (
        f"{module_name}: UsageError was swallowed by `except Exception` — "
        f"got exit_code={result.exit_code}. Output: {result.output!r}"
    )
    assert sentinel in result.output, (
        f"{module_name}: UsageError message was not propagated. "
        f"Output: {result.output!r}"
    )


@pytest.mark.parametrize(
    ("module_name", "argv"),
    V4_COMMAND_PROBES,
    ids=[probe[0] for probe in V4_COMMAND_PROBES],
)
def test_runtime_error_from_call_v4_still_exits_with_abort(module_name, argv):
    """Non-Click exceptions must still go through print_error + Abort (exit 1)."""
    with (
        patch(
            "direct_cli.v4.emit.call_v4",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "direct_cli.v4.emit.create_v4_client",
            return_value=object(),
        ),
    ):
        result = _invoke(*argv)

    assert result.exit_code == 1, (
        f"{module_name}: RuntimeError should map to Abort/exit 1, "
        f"got exit_code={result.exit_code}. Output: {result.output!r}"
    )
    assert "boom" in result.output

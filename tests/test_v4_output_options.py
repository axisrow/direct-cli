"""Surface guard for the v4_output_options decorator (issue #550).

The dedup that introduced ``v4_output_options`` must keep the CLI surface
byte-identical: every standard v4/balance command keeps the
``--format [json|table|csv|tsv]`` / ``--output`` / ``--dry-run`` stack in the
same order with the same help, and the five excluded commands keep their
divergent stacks. These tests are written to pass BOTH before and after the
refactor (golden-snapshot style), so they prove the surface did not move.

The autouse fixture in ``conftest.py`` pins ``YANDEX_DIRECT_CLI_LOCALE=en``,
so help strings render in English here.
"""

import click
import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.utils import v4_output_options

# (group, subcommand) for every command that carries the standard v4 output
# stack. ``("balance",)`` is a top-level command, not a group/sub pair.
_V4_OUTPUT_COMMANDS = [
    ("v4tags", "get-campaigns"),
    ("v4tags", "get-banners"),
    ("v4tags", "update-campaigns"),
    ("v4tags", "update-banners"),
    ("v4forecast", "create"),
    ("v4forecast", "list"),
    ("v4forecast", "get"),
    ("v4forecast", "delete"),
    ("v4wordstat", "create-report"),
    ("v4wordstat", "list-reports"),
    ("v4wordstat", "get-report"),
    ("v4wordstat", "delete-report"),
    ("v4goals", "get-stat-goals"),
    ("v4goals", "get-retargeting-goals"),
    ("v4adimage", "get"),
    ("v4adimage", "set"),
    ("v4events", "get-events-log"),
    ("v4keywords", "get-suggestion"),
    ("v4finance", "get-clients-units"),
    ("v4finance", "get-credit-limits"),
    ("v4finance", "check-payment"),
    ("v4finance", "create-invoice"),
    ("v4meta", "ping-api"),
    ("v4meta", "ping-api-x"),
    ("v4meta", "get-version"),
    ("v4meta", "get-available-versions"),
    ("balance",),
]

# Commands that MUST NOT receive the decorator (divergent surface).
_EXCLUDED_DRY_RUN_ONLY = [
    ("v4finance", "transfer-money"),
    ("v4finance", "pay-campaigns"),
    ("v4finance", "pay-campaigns-by-card"),
]
_EXCLUDED_CUSTOM_DRY_RUN_HELP = [
    ("v4account", "enable-shared-account"),
    ("v4account", "account-management"),
]


def _resolve(path):
    """Return the Click command for a (group, sub) or (command,) path."""
    cmd = cli.commands[path[0]]
    for name in path[1:]:
        cmd = cmd.commands[name]
    return cmd


@pytest.mark.parametrize("path", _V4_OUTPUT_COMMANDS)
def test_v4_output_stack_help_unchanged(path):
    result = CliRunner().invoke(cli, list(path) + ["--help"])
    assert result.exit_code == 0, result.output
    assert "--format [json|table|csv|tsv]" in result.output
    assert "Output format" in result.output
    assert "Output file" in result.output
    assert "Show request without sending" in result.output


@pytest.mark.parametrize("path", _V4_OUTPUT_COMMANDS)
def test_v4_output_stack_option_metadata(path):
    cmd = _resolve(path)
    params = {p.name: p for p in cmd.params if isinstance(p, click.Option)}

    fmt = params["output_format"]
    assert isinstance(fmt.type, click.Choice)
    assert list(fmt.type.choices) == ["json", "table", "csv", "tsv"]
    assert fmt.default == "json"
    assert fmt.help == "Output format"

    assert params["output"].help == "Output file"

    dry = params["dry_run"]
    assert dry.is_flag is True
    assert dry.help == "Show request without sending"


@pytest.mark.parametrize("path", _EXCLUDED_DRY_RUN_ONLY)
def test_excluded_dry_run_only_have_no_format(path):
    result = CliRunner().invoke(cli, list(path) + ["--help"])
    assert result.exit_code == 0, result.output
    assert "--format" not in result.output
    assert "--output" not in result.output


@pytest.mark.parametrize("path", _EXCLUDED_CUSTOM_DRY_RUN_HELP)
def test_excluded_custom_dry_run_help_unchanged(path):
    result = CliRunner().invoke(cli, list(path) + ["--help"])
    assert result.exit_code == 0, result.output
    assert "required outside" in result.output


def test_v4_output_options_decorator_applies_expected_stack():
    @click.command()
    @v4_output_options
    def _probe(output_format, output, dry_run):
        pass

    params = {p.name: p for p in _probe.params if isinstance(p, click.Option)}
    assert set(params) == {"output_format", "output", "dry_run"}
    # --help order must be format, output, dry-run (Click stores params in
    # the order they will be listed).
    ordered = [p.name for p in _probe.params if isinstance(p, click.Option)]
    assert ordered == ["output_format", "output", "dry_run"]
    assert isinstance(params["output_format"].type, click.Choice)
    assert list(params["output_format"].type.choices) == [
        "json",
        "table",
        "csv",
        "tsv",
    ]

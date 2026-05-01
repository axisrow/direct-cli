"""Global regression tests for the public CLI contract."""

import re
from pathlib import Path

from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.smoke_matrix import SMOKE_MATRIX

GROUP_NAME_RE = re.compile(r"^[a-z0-9]+$")
COMMAND_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DATETIME_WITH_Z_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
QUOTED_SPACE_DATETIME_RE = re.compile(r'"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"')

MUTATING_COMMANDS = {
    "add",
    "add-passport-organization",
    "add-passport-organization-member",
    "archive",
    "create-invoice",
    "delete",
    "enable-shared-account",
    "moderate",
    "pay-campaigns",
    "resume",
    "set",
    "set-auto",
    "set-bids",
    "suspend",
    "transfer-money",
    "unarchive",
    "update",
}

DRY_RUN_EXCEPTIONS = {
    # This command rejects locally because the API has no delete operation.
    "agencyclients.delete",
}

FORBIDDEN_HELP_TEXT = (
    "--json",
    "SelectionCriteria",
    " as JSON",
    "JSON object",
    "JSON list",
    "payload",
)


def _option_names(command):
    return {
        opt for parameter in command.params for opt in getattr(parameter, "opts", ())
    }


def _subcommands():
    for group_name, group in sorted(cli.commands.items()):
        for command_name, command in sorted(getattr(group, "commands", {}).items()):
            yield group_name, command_name, command


def _readme_direct_example_lines():
    readme = Path(__file__).resolve().parent.parent / "README.md"
    in_bash = False
    for raw_line in readme.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "```bash":
            in_bash = True
            continue
        if line == "```" and in_bash:
            in_bash = False
            continue
        if in_bash and line.startswith("direct "):
            yield line


def _readme_bash_lines():
    readme = Path(__file__).resolve().parent.parent / "README.md"
    in_bash = False
    for raw_line in readme.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "```bash":
            in_bash = True
            continue
        if line == "```" and in_bash:
            in_bash = False
            continue
        if in_bash:
            yield line


def test_registered_cli_names_are_canonical():
    for group_name in cli.commands:
        assert GROUP_NAME_RE.fullmatch(group_name), group_name

    for group_name, command_name, _command in _subcommands():
        key = f"{group_name}.{command_name}"
        assert COMMAND_NAME_RE.fullmatch(command_name), key


def test_public_commands_do_not_expose_json_blob_options():
    offenders = []
    for group_name, command_name, command in _subcommands():
        if "--json" in _option_names(command):
            offenders.append(f"{group_name}.{command_name}")

    assert offenders == []


def test_mutating_commands_have_dry_run_or_explicit_exception():
    missing = []
    for group_name, command_name, command in _subcommands():
        key = f"{group_name}.{command_name}"
        if command_name not in MUTATING_COMMANDS or key in DRY_RUN_EXCEPTIONS:
            continue
        if "--dry-run" not in _option_names(command):
            missing.append(key)

    assert missing == []


def test_help_output_does_not_advertise_raw_payload_inputs():
    runner = CliRunner()
    offenders = []

    for group_name, command_name, _command in _subcommands():
        result = runner.invoke(cli, [group_name, command_name, "--help"])
        assert result.exit_code == 0, f"direct {group_name} {command_name} --help"
        for forbidden in FORBIDDEN_HELP_TEXT:
            if forbidden in result.output:
                offenders.append(f"{group_name}.{command_name}: {forbidden}")

    assert offenders == []


def test_readme_direct_examples_are_single_line_canonical_commands():
    offenders = []
    for line in _readme_direct_example_lines():
        if "\\" in line:
            offenders.append(f"line continuation: {line}")
        if "--json" in line:
            offenders.append(f"json flag: {line}")
        if DATETIME_WITH_Z_RE.search(line):
            offenders.append(f"timezone datetime: {line}")
        if QUOTED_SPACE_DATETIME_RE.search(line):
            offenders.append(f"quoted space datetime: {line}")

    assert offenders == []


def test_strategies_help_does_not_expose_legacy_json_flags():
    runner = CliRunner()
    for command in ["add", "update"]:
        result = runner.invoke(cli, ["strategies", command, "--help"])
        assert result.exit_code == 0
        assert "--params" not in result.output
        assert "--priority-goals" not in result.output
        assert "--priority-goal" in result.output


def test_readme_bash_blocks_do_not_use_deprecated_direct_cli_executable():
    offenders = [
        line
        for line in _readme_bash_lines()
        if line.startswith("direct-cli ") or " direct-cli " in line
    ]

    assert offenders == []


def test_smoke_matrix_entries_are_registered_canonical_commands():
    registered = set()
    for group_name, group in cli.commands.items():
        for command_name in getattr(group, "commands", {}):
            registered.add(f"{group_name}.{command_name}")

    offenders = []
    for commands in SMOKE_MATRIX.values():
        for command in commands:
            if "." in command:
                group_name, command_name = command.split(".", 1)
                if not GROUP_NAME_RE.fullmatch(group_name):
                    offenders.append(f"{command}: noncanonical group")
                if not COMMAND_NAME_RE.fullmatch(command_name):
                    offenders.append(f"{command}: noncanonical command")
                if command not in registered:
                    offenders.append(f"{command}: not registered")
            elif command not in cli.commands:
                offenders.append(f"{command}: not registered")

    assert offenders == []

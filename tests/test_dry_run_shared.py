"""Shared dry-run helpers used by every ``test_dry_run_*`` module.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import json

from click.testing import CliRunner, Result

from direct_cli.cli import cli


def _dry_run(*args: str) -> dict:
    """Invoke a CLI command with ``--dry-run`` and return the parsed body."""
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _read_dry_run(*args: str) -> dict:
    """Invoke a read command dry-run with dummy credentials."""
    result = CliRunner().invoke(
        cli,
        list(args) + ["--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def _rejected(*args: str) -> Result:
    """Invoke a CLI command expecting Click-level rejection."""
    result = CliRunner().invoke(cli, list(args) + ["--dry-run"])
    assert result.exit_code != 0, (
        f"command unexpectedly succeeded: direct {' '.join(args)} --dry-run\n"
        f"output: {result.output}"
    )
    return result


def _write_jsonl(tmp_path, rows):
    path = tmp_path / "keywords.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return str(path)


def _ids_csv(n):
    return ",".join(str(i) for i in range(1, n + 1))


def _failing_run(*args: str) -> Result:
    """Invoke a CLI command expected to fail, returning the result."""
    return CliRunner().invoke(cli, list(args))

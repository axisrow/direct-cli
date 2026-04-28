import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from direct_cli.cli import cli
from direct_cli.smoke_matrix import (
    DANGEROUS,
    SAFE,
    WRITE_SANDBOX,
    SMOKE_MATRIX,
    command_category,
    command_entries,
    command_key,
    smoke_summary,
)
from direct_cli.wsdl_coverage import (
    CLI_TO_API_SERVICE,
    NON_WSDL_SERVICES,
    fetch_wsdl,
    parse_wsdl_operations,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_sandbox_runner_module():
    runner_path = ROOT_DIR / "scripts" / "sandbox_write_live.py"
    spec = importlib.util.spec_from_file_location("sandbox_write_live", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _registered_cli_commands() -> set[str]:
    registered = set()
    for group_name, group in cli.commands.items():
        if hasattr(group, "commands"):
            for command_name in group.commands:
                registered.add(command_key(group_name, command_name))
        else:
            registered.add(group_name)
    return registered


def test_smoke_matrix_covers_every_cli_subcommand_once():
    actual = _registered_cli_commands()
    seen = []
    for category, commands in SMOKE_MATRIX.items():
        assert category in {SAFE, WRITE_SANDBOX, DANGEROUS}
        seen.extend(commands)

    assert sorted(seen) == sorted(set(seen))
    assert set(seen) == actual


def test_smoke_matrix_counts_match_current_cli_surface():
    summary = smoke_summary()

    assert summary["total_cli_groups"] == 39
    assert summary["total_cli_subcommands"] == 123
    assert summary["api_cli_subcommands"] == 119
    assert summary["wsdl_services"] == 29
    assert summary["non_wsdl_services"] == sorted(NON_WSDL_SERVICES)
    assert summary["api_services_total"] == 30
    assert summary["wsdl_operations"] == 112


def test_wsdl_backed_cli_commands_are_classified():
    classified = {entry.command for entry in command_entries()}

    for cli_group, api_service in sorted(CLI_TO_API_SERVICE.items()):
        api_methods = set(parse_wsdl_operations(fetch_wsdl(api_service)))
        for command_name in cli.commands[cli_group].commands:
            key = command_key(cli_group, command_name)
            assert key in classified
            assert command_category(key) in {SAFE, WRITE_SANDBOX, DANGEROUS}

        assert api_methods, f"{api_service} WSDL exposes no operations"


def test_smoke_scripts_exist_and_are_shell_syntax_valid():
    for script_name in [
        "test_safe_commands.sh",
        "test_sandbox_write.sh",
        "test_dangerous_commands.sh",
    ]:
        script = ROOT_DIR / "scripts" / script_name
        assert script.exists(), f"Missing smoke script: scripts/{script_name}"
        subprocess.run(["bash", "-n", str(script)], check=True, cwd=ROOT_DIR)


def test_sandbox_write_script_is_live_runner_not_cassette_replay():
    script = ROOT_DIR / "scripts" / "test_sandbox_write.sh"
    contents = script.read_text()

    forbidden_terms = ["pytest", "record-mode", "RECORD_MODE", "VCR", "cassette"]
    for term in forbidden_terms:
        assert term not in contents

    assert "YANDEX_DIRECT_TOKEN" in contents
    assert "YANDEX_DIRECT_LOGIN" in contents
    assert "sandbox_write_live.py" in contents

    runner = ROOT_DIR / "scripts" / "sandbox_write_live.py"
    assert runner.exists(), "Missing live sandbox write runner"
    subprocess.run(
        ["python3", "-m", "py_compile", str(runner)], check=True, cwd=ROOT_DIR
    )


def test_safe_smoke_script_runs_agencyclients_sandbox_get():
    script = ROOT_DIR / "scripts" / "test_safe_commands.sh"
    contents = script.read_text()

    assert "agencyclients get" in contents
    assert "--sandbox" in contents
    assert "YANDEX_DIRECT_AGENCY_TOKEN" in contents
    assert "BUG #73" not in contents


def test_sandbox_write_live_runner_covers_write_sandbox_matrix():
    module = _load_sandbox_runner_module()

    runner = module.LiveSandboxRunner(
        commands=SMOKE_MATRIX[WRITE_SANDBOX],
        timeout=1,
        verbose=False,
        report_file=None,
    )
    try:
        assert set(runner.handlers()) == set(SMOKE_MATRIX[WRITE_SANDBOX])
        assert len(SMOKE_MATRIX[WRITE_SANDBOX]) == 75
    finally:
        runner.close()


def test_sandbox_write_live_runner_reports_subprocess_timeout(monkeypatch):
    module = _load_sandbox_runner_module()

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="partial")

    monkeypatch.setattr(module.subprocess, "run", raise_timeout)
    runner = module.LiveSandboxRunner(
        commands=["campaigns.add"],
        timeout=1,
        verbose=False,
        report_file=None,
    )
    try:
        run = runner.invoke("campaigns", "add", ["--name", "x"])
        status, detail = runner.classify(run)
        assert status == module.FAIL
        assert "timed out after 1 seconds" in detail
    finally:
        runner.close()


def test_sandbox_write_live_runner_classifies_adimage_delete_1002():
    module = _load_sandbox_runner_module()
    runner = module.LiveSandboxRunner(
        commands=["adimages.delete"],
        timeout=1,
        verbose=False,
        report_file=None,
    )
    try:
        run = module.CommandRun(
            args=["direct", "--sandbox", "adimages", "delete", "--hash", "hash"],
            returncode=1,
            stdout="",
            stderr="error_code=1002, error_string=Operation error",
        )
        status, detail = runner.classify(run, "adimages.delete")
        assert status == module.SANDBOX_LIMITATION
        assert "error_code=1002" in detail
    finally:
        runner.close()


def test_sandbox_write_live_runner_classifies_known_sandbox_codes():
    module = _load_sandbox_runner_module()
    runner = module.LiveSandboxRunner(
        commands=["campaigns.resume", "advideos.add"],
        timeout=1,
        verbose=False,
        report_file=None,
    )
    try:
        for code in [5005, 8300]:
            run = module.CommandRun(
                args=["direct", "--sandbox", "group", "command"],
                returncode=0,
                stdout=json_with_error_code(code),
                stderr="",
            )
            status, detail = runner.classify(run)
            assert status == module.SANDBOX_LIMITATION
            assert str(code) in detail
    finally:
        runner.close()


def json_with_error_code(code: int) -> str:
    return json.dumps(
        {
            "result": {
                "ActionResults": [
                    {
                        "Errors": [
                            {
                                "Code": code,
                                "Message": "sandbox limitation",
                                "Details": "test",
                            }
                        ]
                    }
                ]
            }
        }
    )


def test_dangerous_script_is_not_executable_smoke_runner():
    result = subprocess.run(
        ["bash", "scripts/test_dangerous_commands.sh"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "manual checklist" in result.stdout.lower()

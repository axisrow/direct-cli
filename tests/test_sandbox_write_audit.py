import json
import subprocess
from pathlib import Path

from direct_cli.smoke_matrix import WRITE_SANDBOX, commands_for_category

ROOT_DIR = Path(__file__).resolve().parent.parent
AUDIT_SCRIPT = ROOT_DIR / "scripts" / "sandbox_write_audit.py"
SANDBOX_SCRIPT = ROOT_DIR / "scripts" / "test_sandbox_write.sh"

EXPECTED_NOT_COVERED: set[str] = set()
ALLOWED_STATUSES = {"PASS", "SANDBOX_LIMITATION", "DANGEROUS", "NOT_COVERED"}


def test_sandbox_write_audit_outputs_markdown_and_json(tmp_path):
    json_output = tmp_path / "sandbox_audit.json"

    result = subprocess.run(
        ["python3", str(AUDIT_SCRIPT), "--json-output", str(json_output)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "| group | subcommand | status | evidence | follow_up |" in result.stdout
    assert json_output.exists()

    audit = json.loads(json_output.read_text())
    rows = audit["rows"]

    assert audit["summary"]["category"] == WRITE_SANDBOX
    assert audit["summary"]["total"] == len(commands_for_category(WRITE_SANDBOX))
    assert audit["summary"]["total"] == 83
    assert len(rows) == 83
    assert {row["status"] for row in rows} <= ALLOWED_STATUSES

    not_covered = {row["command"] for row in rows if row["status"] == "NOT_COVERED"}
    assert not_covered == EXPECTED_NOT_COVERED

    for row in rows:
        assert row["follow_up"] == ""


def test_sandbox_write_audit_mode_does_not_require_credentials(tmp_path):
    json_output = tmp_path / "sandbox_audit.json"

    result = subprocess.run(
        [
            "bash",
            str(SANDBOX_SCRIPT),
            "--audit",
            "--json-output",
            str(json_output),
        ],
        cwd=ROOT_DIR,
        env={},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ERROR: no credentials" not in result.stderr
    assert "| group | subcommand | status | evidence | follow_up |" in result.stdout
    assert json_output.exists()

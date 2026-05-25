"""Tests for Direct CLI .env loading rules."""

import ast
import os
import subprocess
import sys
from pathlib import Path

from direct_cli import auth


def test_load_env_file_uses_cwd_dotenv_by_default(monkeypatch, tmp_path):
    """Default .env loading is pinned to the command working directory."""
    calls = []

    def fake_load_dotenv(dotenv_path):
        calls.append(Path(dotenv_path))
        return True

    monkeypatch.setattr(auth, "load_dotenv", fake_load_dotenv)
    monkeypatch.chdir(tmp_path)

    auth.load_env_file()

    assert calls == [tmp_path / ".env"]


def test_load_env_file_uses_explicit_path(monkeypatch, tmp_path):
    """Explicit env paths are respected exactly."""
    calls = []

    def fake_load_dotenv(dotenv_path):
        calls.append(Path(dotenv_path))
        return True

    env_path = tmp_path / "custom.env"
    monkeypatch.setattr(auth, "load_dotenv", fake_load_dotenv)

    auth.load_env_file(str(env_path))

    assert calls == [env_path]


def test_load_env_file_loads_cwd_dotenv(tmp_path):
    """A .env in the command working directory is loaded."""
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / ".env").write_text(
        "YANDEX_DIRECT_TOKEN=cwd-token\n" "YANDEX_DIRECT_LOGIN=cwd-login\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.pop("YANDEX_DIRECT_TOKEN", None)
    env.pop("YANDEX_DIRECT_LOGIN", None)
    env["PYTHONPATH"] = str(repo_root)
    script = (
        "import os\n"
        "from direct_cli import auth\n"
        "auth.load_env_file()\n"
        "print(os.environ.get('YANDEX_DIRECT_TOKEN'))\n"
        "print(os.environ.get('YANDEX_DIRECT_LOGIN'))\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert result.stdout.splitlines() == ["cwd-token", "cwd-login"]


def test_load_env_file_does_not_search_from_source_location(monkeypatch, tmp_path):
    """A source-adjacent .env is ignored when the command runs elsewhere."""
    source_dir = tmp_path / "source"
    run_dir = tmp_path / "run"
    source_dir.mkdir()
    run_dir.mkdir()
    source_env = source_dir / ".env"
    source_env.write_text(
        "YANDEX_DIRECT_TOKEN=source-token\n" "YANDEX_DIRECT_LOGIN=source-login\n",
        encoding="utf-8",
    )
    calls = []

    def fake_load_dotenv(dotenv_path):
        path = Path(dotenv_path)
        calls.append(path)
        if path == source_env:
            monkeypatch.setenv("YANDEX_DIRECT_TOKEN", "source-token")
            monkeypatch.setenv("YANDEX_DIRECT_LOGIN", "source-login")
        return path.exists()

    monkeypatch.delenv("YANDEX_DIRECT_TOKEN", raising=False)
    monkeypatch.delenv("YANDEX_DIRECT_LOGIN", raising=False)
    monkeypatch.setattr(auth, "load_dotenv", fake_load_dotenv)
    monkeypatch.chdir(run_dir)

    auth.load_env_file()

    assert calls == [run_dir / ".env"]
    assert "YANDEX_DIRECT_TOKEN" not in os.environ
    assert "YANDEX_DIRECT_LOGIN" not in os.environ


def test_cli_routes_early_dotenv_loading_through_auth_helper():
    """cli.py must not call python-dotenv directly."""
    repo_root = Path(__file__).resolve().parents[1]
    cli_source = (repo_root / "direct_cli" / "cli.py").read_text(encoding="utf-8")
    cli_tree = ast.parse(cli_source)

    imports_dotenv_loader = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "dotenv"
        and any(alias.name == "load_dotenv" for alias in node.names)
        for node in ast.walk(cli_tree)
    )
    imports_auth_env_loader = any(
        isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "auth"
        and any(alias.name == "load_env_file" for alias in node.names)
        for node in ast.walk(cli_tree)
    )
    calls_auth_env_loader = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_env_file"
        for node in ast.walk(cli_tree)
    )

    assert not imports_dotenv_loader
    assert imports_auth_env_loader
    assert calls_auth_env_loader

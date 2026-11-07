"""The headless auth contract lock (issue #962).

Authorization is headless and non-interactive by default — terminals
included; TTY detection may only cause a refusal, never enable a dialog or
a browser window by itself. ``--interactive`` (api) and ``--source manual``
(browser) are the only explicit opt-ins. This module pins the defaults,
the behavior in a substituted and in a *real* pty, the AST guard that
keeps terminal detection refusal-only, the registry of the places allowed
to prompt or open a browser, the doc examples (parsed by live Click), and
the CI step that runs all of it.
"""

import ast
import json
import os
import pty
import select
import shlex
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

import direct_cli
from direct_cli.auth import load_auth_store
from direct_cli.browser import session
from direct_cli.cli import cli

REPO_ROOT = Path(direct_cli.__file__).resolve().parents[1]
AUTH_COMMANDS = Path(direct_cli.__file__).parent / "commands" / "auth.py"

# The only functions allowed to prompt or to open a browser (issue #962).
# Everything a user must answer or that opens a window lives here, behind
# the explicit --interactive / --source manual opt-ins.
PROMPT_SITES = {"login_api", "_prompt_authorize_code", "_ask_copy_token"}
PROMPT_CALL_NAMES = {"click.prompt", "click.confirm", "webbrowser.open"}


@pytest.fixture
def auth_env(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith("YANDEX_DIRECT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("YANDEX_DIRECT_CLI_LOCALE", "en")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    yield tmp_path
    for name in tuple(os.environ):
        if name.startswith("YANDEX_DIRECT_"):
            if name in os.environ:
                del os.environ[name]


def _login_command(domain: str) -> click.Command:
    ctx = click.Context(cli)
    auth = cli.get_command(ctx, "auth")
    assert isinstance(auth, click.Group)
    login = auth.get_command(ctx, "login")
    assert isinstance(login, click.Group)
    command = login.get_command(ctx, domain)
    assert command is not None
    return command


def _login_option(domain: str, name: str) -> click.Parameter:
    option = next(o for o in _login_command(domain).params if o.name == name)
    return option


# ---------------------------------------------------------------------------
# Defaults — the command surface itself is the contract.


class TestHeadlessDefaults:
    def test_api_interactive_is_an_explicit_visible_flag(self):
        option = _login_option("api", "interactive_login")
        assert isinstance(option, click.Option)
        assert option.is_flag
        assert option.opts == ["--interactive"]
        assert not option.get_default(click.Context(_login_command("api")))
        assert not option.hidden  # explicit opt-in: advertised in --help

    def test_api_headful_stays_a_removed_stub(self):
        option = _login_option("api", "headful")
        assert isinstance(option, click.Option)
        assert option.hidden

    def test_browser_source_defaults_to_chrome(self):
        option = _login_option("browser", "source")
        assert isinstance(option.type, click.Choice)
        assert option.default == "chrome"
        assert set(option.type.choices) == {"manual", "chrome"}

    def test_removed_stubs_name_the_exact_replacements(self):
        runner = CliRunner()
        replacements = {
            ("login", "--interactive"): "direct auth login api --interactive",
            ("login", "--headful"): "direct auth login browser --source manual",
            ("login", "browser", "--headful"): (
                "direct auth login browser --source manual"
            ),
            ("login", "browser", "--interactive"): (
                "direct auth login browser --source manual"
            ),
            ("login", "--method", "api"): "direct auth login api",
        }
        for argv, hint in replacements.items():
            result = runner.invoke(cli, ["auth", *argv])
            assert result.exit_code == 2, (argv, result.output)
            assert hint in result.output, (argv, result.output)


# ---------------------------------------------------------------------------
# Behavior outside a terminal (CliRunner) — the headless defaults.


class TestHeadlessBehavior:
    @pytest.mark.parametrize("argv", [["login"], ["login", "api"]])
    def test_no_flags_print_the_url_and_never_prompt_or_write_dotenv(
        self, auth_env, monkeypatch, argv
    ):
        monkeypatch.setattr(
            "direct_cli.commands.auth._stdin_is_interactive", lambda: True
        )  # even a terminal stays headless without --interactive
        prompt, browser = Mock(), Mock()
        monkeypatch.setattr("click.prompt", prompt)
        monkeypatch.setattr("direct_cli.commands.auth.webbrowser.open", browser)
        result = CliRunner().invoke(cli, ["auth", *argv])
        assert result.exit_code == 0, result.output
        assert "oauth.yandex.ru/authorize" in result.stdout
        assert not (auth_env / ".env").exists()
        store = load_auth_store()
        assert "default" in store["pending_pkce"]  # completion: --code / --code -
        assert store["profiles"] == {}
        prompt.assert_not_called()
        browser.assert_not_called()

    @pytest.mark.parametrize(
        "extra",
        [
            ["--format", "json"],
            ["--start-pkce"],
            ["--code", "-"],
            ["--code-stdin"],
        ],
    )
    def test_interactive_conflicts_refuse_before_any_write(
        self, auth_env, monkeypatch, extra
    ):
        prompt, browser = Mock(), Mock()
        monkeypatch.setattr("click.prompt", prompt)
        monkeypatch.setattr("direct_cli.commands.auth.webbrowser.open", browser)
        result = CliRunner().invoke(
            cli,
            ["auth", "login", "api", "--interactive", *extra],
            input="unused\n",
        )
        assert result.exit_code == 2, result.output
        assert "--interactive" in result.output
        assert not (auth_env / ".env").exists()
        store = load_auth_store()
        assert store["pending_pkce"] == {}
        assert store["profiles"] == {}
        prompt.assert_not_called()
        browser.assert_not_called()

    def test_interactive_without_a_terminal_refuses(self, auth_env, monkeypatch):
        monkeypatch.setattr(
            "direct_cli.commands.auth._stdin_is_interactive", lambda: False
        )
        prompt = Mock()
        monkeypatch.setattr("click.prompt", prompt)
        result = CliRunner().invoke(cli, ["auth", "login", "api", "--interactive"])
        assert result.exit_code == 2, result.output
        assert "interactive terminal" in result.output
        assert not (auth_env / ".env").exists()
        prompt.assert_not_called()

    def test_bare_browser_login_imports_chrome_headlessly(self, auth_env, monkeypatch):
        capture = Mock(
            return_value=({"cookies": [], "origins": []}, {"verified": False})
        )
        window = Mock()
        monkeypatch.setattr(session, "capture_storage_state", capture)
        monkeypatch.setattr(session, "login_manual_session", window)
        result = CliRunner().invoke(cli, ["auth", "login", "browser"])
        assert result.exit_code == 0, result.output
        capture.assert_called_once()
        window.assert_not_called()

    def test_manual_browser_login_needs_a_terminal_or_allow_no_tty(
        self, auth_env, monkeypatch
    ):
        monkeypatch.setattr(
            "direct_cli.commands.auth._stdin_is_interactive", lambda: False
        )
        window = Mock()
        monkeypatch.setattr(session, "login_manual_session", window)
        refused = CliRunner().invoke(
            cli, ["auth", "login", "browser", "--source", "manual"]
        )
        # A runtime refusal (ClickException), not a usage error: the
        # arguments themselves are valid.
        assert refused.exit_code == 1, refused.output
        assert "interactive terminal" in refused.output
        window.assert_not_called()
        # --allow-no-tty only overrides the terminal check; the window comes
        # from the explicit --source manual, which was now given.
        allowed = CliRunner().invoke(
            cli,
            ["auth", "login", "browser", "--source", "manual", "--allow-no-tty"],
        )
        assert allowed.exit_code == 0, allowed.output
        window.assert_called_once()


# ---------------------------------------------------------------------------
# AST guard: terminal detection may only cause a refusal.


def _dotted_name(node: ast.expr) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _is_tty_call(node: ast.Call) -> bool:
    name = _dotted_name(node.func)
    if name is None:
        return False
    return name == "_stdin_is_interactive" or name.split(".")[-1] == "isatty"


def _call_is_under_not(test: ast.expr, call: ast.Call) -> bool:
    for node in ast.walk(test):
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            if any(child is call for child in ast.walk(node.operand)):
                return True
    return False


def tty_contract_violations(tree: ast.Module) -> list[str]:
    """Report tty checks that enable behavior instead of refusing it.

    A tty check may appear only (a) inside ``_stdin_is_interactive`` itself,
    or (b) in an ``if`` test negated (``not <tty-check>``) whose body is
    nothing but ``raise`` statements — a terminal may only refuse.
    """
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "_stdin_is_interactive":
                exempt.update(id(child) for child in ast.walk(node))

    guarded: set[int] = set()
    refusals: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = [
            c
            for c in ast.walk(node.test)
            if isinstance(c, ast.Call) and _is_tty_call(c)
        ]
        if not calls:
            continue
        if node.body and all(isinstance(stmt, ast.Raise) for stmt in node.body):
            guarded.update(id(c) for c in calls)
            refusals.update(id(c) for c in calls if _call_is_under_not(node.test, c))

    violations = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and _is_tty_call(node)
            and id(node) not in exempt
            and (id(node) not in guarded or id(node) not in refusals)
        ):
            violations.append(
                f"line {node.lineno}: a terminal check may only guard a "
                f"refusal (raise), never enable a dialog or a window"
            )
    return violations


def prompt_site_violations(tree: ast.Module) -> list[str]:
    """Report prompt/browser calls outside the registered prompt sites."""
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and _dotted_name(inner.func) in (
                    PROMPT_CALL_NAMES
                ):
                    if scope not in PROMPT_SITES:
                        violations.append(
                            f"line {inner.lineno}: {scope}() prompts or opens a "
                            f"browser; add it to PROMPT_SITES only behind the "
                            f"explicit opt-ins"
                        )
    return violations


class TestTerminalOnlyRefusesAstGuard:
    def test_production_auth_module_is_clean(self):
        tree = ast.parse(AUTH_COMMANDS.read_text(encoding="utf-8"))
        assert tty_contract_violations(tree) == []
        assert prompt_site_violations(tree) == []

    def test_guard_flags_a_terminal_enabled_dialog(self):
        source = (
            "import click\n"
            "def cmd() -> None:\n"
            "    if _stdin_is_interactive():\n"
            "        click.prompt('code')\n"
        )
        violations = tty_contract_violations(ast.parse(source))
        assert len(violations) == 1
        assert "may only guard a refusal" in violations[0]

    def test_guard_accepts_a_terminal_enabled_refusal(self):
        source = (
            "import click\n"
            "def cmd() -> None:\n"
            "    if not _stdin_is_interactive():\n"
            "        raise click.UsageError('needs a terminal')\n"
            "def _stdin_is_interactive() -> bool:\n"
            "    import sys\n"
            "    return sys.stdin.isatty() and sys.stdout.isatty()\n"
        )
        assert tty_contract_violations(ast.parse(source)) == []

    def test_guard_flags_an_unnegated_check_with_a_raise(self):
        source = (
            "def cmd() -> None:\n"
            "    if _stdin_is_interactive():\n"
            "        raise ValueError('no dialogs here')\n"
        )
        assert len(tty_contract_violations(ast.parse(source))) == 1

    def test_guard_flags_a_prompt_outside_the_registry(self):
        source = (
            "import click\n"
            "def rogue() -> None:\n"
            "    click.prompt('code')\n"
        )
        assert len(prompt_site_violations(ast.parse(source))) == 1

    def test_guard_accepts_a_registered_prompt_site(self):
        source = (
            "import click\n"
            "def _ask_copy_token(profile: str) -> bool:\n"
            "    return click.prompt('mode') == 'copy'\n"
        )
        assert prompt_site_violations(ast.parse(source)) == []


# ---------------------------------------------------------------------------
# A real pty: even when both streams are terminals, no flags means headless.


def _run_in_real_pty(argv, cwd, env, timeout=30):
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdin=slave,
        stdout=slave,
        stderr=subprocess.PIPE,
    )
    os.close(slave)
    chunks = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait(timeout=10)
                raise AssertionError(
                    "auth login never finished in a real pty — it is "
                    f"prompting or hanging again: {''.join(chunks)!r}"
                )
            ready, _, _ = select.select([master], [], [], min(0.2, remaining))
            if not ready:
                continue
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break  # EIO: the child closed the pty (exited)
            if not chunk:
                break
            chunks.append(chunk.decode("utf-8", "replace"))
    finally:
        os.close(master)
    assert proc.stderr is not None
    stderr = proc.stderr.read().decode("utf-8", "replace")
    returncode = proc.wait(timeout=10)
    return returncode, "".join(chunks), stderr


def _pty_env(tmp_path):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("YANDEX_DIRECT_")
    }
    env["HOME"] = str(tmp_path)  # the auth store must not leave the sandbox
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["YANDEX_DIRECT_CLI_LOCALE"] = "en"
    # Belt and braces: even a regression that calls webbrowser.open must not
    # pop a real browser on the developer's machine.
    env["BROWSER"] = "true"
    return env


class TestRealPty:
    @pytest.mark.parametrize("argv", [["auth", "login"], ["auth", "login", "api"]])
    def test_no_flags_in_a_real_terminal_stay_headless(self, tmp_path, argv):
        returncode, out, err = _run_in_real_pty(
            [sys.executable, "-m", "direct_cli.cli", *argv],
            cwd=str(tmp_path),
            env=_pty_env(tmp_path),
        )
        assert returncode == 0, f"stdout={out!r} stderr={err!r}"
        assert "oauth.yandex.ru/authorize" in out
        # Nothing was asked: no profile menu, no code prompt.
        assert "Enter OAuth code" not in out
        assert "Choose a profile" not in out
        assert not (tmp_path / ".env").exists()
        store = json.loads((tmp_path / ".direct-cli" / "auth.json").read_text())
        assert "default" in store["pending_pkce"]
        assert store["profiles"] == {}


# ---------------------------------------------------------------------------
# The docs must describe this contract: every `direct auth ...` example in
# the fenced code blocks parses through the live Click tree.


def _doc_paths():
    return [
        REPO_ROOT / name
        for name in ("AGENTS.md", "README.md", "README_ru.md", "CLAUDE.md")
    ]


def _direct_auth_examples(path: Path):
    examples = []
    in_fence = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        line = raw.strip()
        if "|" in line:  # shell pipeline: the example is the command after it
            line = line.rsplit("|", 1)[1].strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line, comments=True)
        except ValueError:
            continue
        if len(tokens) >= 2 and tokens[0] == "direct" and tokens[1] == "auth":
            examples.append((" ".join(tokens), tokens))
    return examples


DOC_EXAMPLES = [
    example
    for path in _doc_paths()
    for example in _direct_auth_examples(path)
]


class TestDocsMatchTheContract:
    def test_docs_were_found(self):
        assert len(DOC_EXAMPLES) >= 10

    @pytest.mark.parametrize(
        "source,argv",
        DOC_EXAMPLES,
        ids=[source for source, _ in DOC_EXAMPLES],
    )
    def test_every_direct_auth_example_parses_with_live_click(self, source, argv):
        # --help makes the invocation side-effect-free while still parsing
        # every flag against the real command tree.
        result = CliRunner().invoke(cli, argv[1:] + ["--help"])
        assert result.exit_code == 0, f"{source!r}: {result.output}"
        assert "Usage:" in result.output


# ---------------------------------------------------------------------------
# Meta: CI must run this file, or the lock silently stops guarding.


class TestQualityGateWiring:
    def test_quality_yml_has_the_headless_auth_contract_step(self):
        text = (REPO_ROOT / ".github" / "workflows" / "quality.yml").read_text(
            encoding="utf-8"
        )
        assert "Headless auth contract" in text
        assert "pytest tests/test_headless_auth_contract.py" in text

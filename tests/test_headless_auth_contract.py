"""The headless authorization contract, pinned so it cannot quietly come back.

AGENTS.md ("Authorization Execution Mode"): authorization is headless and
non-interactive by default, *including when stdin and stdout are terminals*.
Nothing prompts and nothing opens a window unless the caller asks with an
explicit flag — ``auth login api --interactive`` for terminal dialogs,
``auth login browser --source manual`` for the visible login window.

The contract regressed once: 0.5.5 (#932) made ``auth login api`` prompt, open
a browser and write ``.env`` whenever a terminal was attached, and made
``auth login browser`` always open a window, while AGENTS.md kept promising
the opposite. Every section below catches that from a different side, so that
undoing the contract takes a visible edit of this file *and* of AGENTS.md —
not a quiet default flip:

1. defaults, read off the Click command tree;
2. behaviour under a faked terminal, with tripwires on every dialog primitive;
3. behaviour under a REAL pseudo-terminal in a subprocess — independent of how
   the code detects a terminal;
4. the shape of the code: terminal detection may only refuse, and every
   prompt / browser-opening primitive lives in a registered function;
5. the documentation: AGENTS.md states the contract, every user doc names the
   two opt-ins, and every ``direct auth ...`` example is live syntax;
6. CI: the quality workflow runs this file by name.

If a check here fails, the change is probably re-introducing interactive login
by default. Fix the change; edit this file only when the contract itself is
deliberately changed (and change AGENTS.md in the same commit).
"""

import ast
import os
import re
import select
import shlex
import signal
import site
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, NamedTuple, Optional, Set, Tuple
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

import direct_cli
from direct_cli._auth_hints import (
    HINT_LOGIN_API,
    HINT_LOGIN_API_INTERACTIVE,
    HINT_LOGIN_BROWSER,
    HINT_LOGIN_BROWSER_CHROME,
    HINT_LOGIN_BROWSER_MANUAL,
)
from direct_cli.browser import session, store
from direct_cli.cli import cli

PACKAGE = Path(direct_cli.__file__).resolve().parent
REPO = PACKAGE.parent
THIS_FILE = "tests/test_headless_auth_contract.py"

# --- 1. defaults, read off the Click command tree ---------------------------


def _command(*path: str) -> click.Command:
    command: click.Command = cli
    for name in path:
        command = command.commands[name]  # type: ignore[attr-defined]
    return command


def _option(command: click.Command, flag: str) -> click.Option:
    for param in command.params:
        if isinstance(param, click.Option) and flag in param.opts:
            return param
    raise AssertionError(f"`{command.name}` has no {flag}")


def _find_option(command: click.Command, flag: str) -> Optional[click.Option]:
    candidates = [command]
    if command.name == "login" and isinstance(command, click.Group):
        candidates.append(command.commands["api"])  # bare `login ...` means `login api`
    for candidate in candidates:
        for param in candidate.params:
            if isinstance(param, click.Option) and flag in (
                *param.opts,
                *param.secondary_opts,
            ):
                return param
    return None


def _is_live(param: click.Option) -> bool:
    """An option a user can really use: not hidden, not a `Removed:` stub."""
    return not param.hidden and not (param.help or "").startswith("Removed")


def test_the_hint_constants_name_the_two_opt_ins():
    # The docs, the errors and these tests all derive from the constants.
    assert HINT_LOGIN_API_INTERACTIVE == f"{HINT_LOGIN_API} --interactive"
    assert HINT_LOGIN_BROWSER_MANUAL == f"{HINT_LOGIN_BROWSER} --source manual"
    assert HINT_LOGIN_BROWSER_CHROME == f"{HINT_LOGIN_BROWSER} --source chrome"


def test_api_dialogs_are_a_flag_that_is_off_by_default():
    command = _command("auth", "login", "api")
    interactive = _option(command, "--interactive")
    assert interactive.is_flag and not interactive.hidden
    assert not interactive.get_default(click.Context(command))


def test_browser_login_defaults_to_the_headless_chrome_import():
    command = _command("auth", "login", "browser")
    source = _option(command, "--source")
    assert source.get_default(click.Context(command)) == "chrome"
    assert isinstance(source.type, click.Choice)
    assert set(source.type.choices) == {"chrome", "manual"}


def test_the_login_group_does_not_swallow_the_interactive_flag():
    # `auth login --interactive` must be routed to `login api`; a group-level
    # option of that name would answer for the whole group, terminal or not.
    group = _command("auth", "login")
    assert not any("--interactive" in param.opts for param in group.params)


@pytest.mark.parametrize("flag", ["--interactive", "--headful"])
def test_browser_login_offers_no_flag_that_could_mean_the_window(flag):
    # The window is `--source manual`; these names survive only as hidden stubs
    # that refuse and name it.
    option = _find_option(_command("auth", "login", "browser"), flag)
    assert option is None or not _is_live(option)


# --- 2. behaviour under a faked terminal ------------------------------------

_SAVED_STATE = (
    {"cookies": [{"domain": ".yandex.ru", "value": "secret"}], "origins": []},
    {"verified": True},
)


@pytest.fixture
def terminal(monkeypatch, tmp_path):
    """A faked terminal, an empty folder, and tripwires on every dialog primitive."""
    for name in tuple(os.environ):
        if name.startswith("YANDEX_DIRECT_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("YANDEX_DIRECT_CLI_LOCALE", "en")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    monkeypatch.setattr(store, "PLAYWRIGHT_SESSION_PATH", tmp_path / "session.json")
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: True)
    tripwires = SimpleNamespace(
        prompt=Mock(),
        confirm=Mock(),
        browser=Mock(),
        window=Mock(),
        capture=Mock(return_value=_SAVED_STATE),
        folder=tmp_path,
    )
    monkeypatch.setattr("click.prompt", tripwires.prompt)
    monkeypatch.setattr("click.confirm", tripwires.confirm)
    monkeypatch.setattr("webbrowser.open", tripwires.browser)
    monkeypatch.setattr(session, "login_manual_session", tripwires.window)
    monkeypatch.setattr(session, "capture_storage_state", tripwires.capture)
    yield tripwires
    for name in tuple(os.environ):
        if name.startswith("YANDEX_DIRECT_"):
            del os.environ[name]


def _assert_nothing_interactive_happened(terminal):
    terminal.prompt.assert_not_called()
    terminal.confirm.assert_not_called()
    terminal.browser.assert_not_called()
    terminal.window.assert_not_called()
    assert not (terminal.folder / ".env").exists(), "login wrote the folder's .env"


@pytest.mark.parametrize(
    "argv",
    [
        ["auth", "login"],
        ["auth", "login", "api"],
        ["auth", "login", "--profile", "fresh"],
        ["auth", "login", "api", "--client-secret", "s"],
        ["auth", "login", "--format", "json"],
        ["auth", "login", "browser"],
        ["auth", "login", "browser", "--source", "chrome"],
    ],
)
def test_a_terminal_alone_never_starts_a_dialog_or_a_window(terminal, argv):
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code == 0, result.output
    _assert_nothing_interactive_happened(terminal)


def test_a_terminal_alone_never_starts_a_login_for_an_ordinary_command(terminal):
    result = CliRunner().invoke(cli, ["campaigns", "get"])
    assert result.exit_code == 2, result.output
    assert "No credentials bound to this folder" in result.output
    _assert_nothing_interactive_happened(terminal)


@pytest.mark.parametrize(
    "argv",
    [
        ["auth", "login", "api", "--interactive"],
        ["auth", "login", "--interactive"],
        ["auth", "login", "browser", "--source", "manual"],
    ],
)
def test_the_opt_ins_are_the_only_way_in(monkeypatch, tmp_path, argv):
    """Control: without a terminal even the opt-ins refuse, and do nothing."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("direct_cli.auth.AUTH_STORE_PATH", tmp_path / "auth.json")
    monkeypatch.setattr("direct_cli.commands.auth._stdin_is_interactive", lambda: False)
    prompt, window = Mock(), Mock()
    monkeypatch.setattr("click.prompt", prompt)
    monkeypatch.setattr(session, "login_manual_session", window)
    result = CliRunner().invoke(cli, argv)
    assert result.exit_code != 0, result.output
    prompt.assert_not_called()
    window.assert_not_called()
    assert not (tmp_path / ".env").exists()


# --- 3. behaviour under a REAL pseudo-terminal ------------------------------

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="needs a POSIX pseudo-terminal"
)


class TerminalRun(NamedTuple):
    returncode: Optional[int]  # None: still running, had to be killed
    reason: str  # "exited" | "stopped" (saw stop_at) | "timeout"
    output: str


def _run_in_terminal(
    argv: List[str],
    *,
    home: Path,
    cwd: Path,
    extra_env: Optional[Dict[str, str]] = None,
    stop_at: Optional[str] = None,
    timeout: float = 25.0,
) -> TerminalRun:
    """Run the CLI with a real tty on stdin, stdout and stderr.

    The environment is minimal on purpose (no inherited credentials), HOME and
    cwd are throwaway, and the code under test is the one this test module
    imported. A headless command exits by itself; one that is waiting for
    input is killed at ``timeout`` (or as soon as ``stop_at`` shows up).
    """
    import pty  # POSIX only: the callers are skipped on Windows

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "PYTHONPATH": str(REPO),
        # HOME is a throwaway, but packages installed with `pip --user` must
        # stay importable in the child.
        "PYTHONUSERBASE": site.getuserbase(),
        "PYTHONIOENCODING": "utf-8",
        "YANDEX_DIRECT_CLI_LOCALE": "en",
        **(extra_env or {}),
    }
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", "direct_cli.cli", *argv],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        cwd=str(cwd),
        env=env,
        close_fds=True,
        # A new session has no controlling terminal, so getpass cannot reach
        # /dev/tty and a prompt shows up in the pty instead of on the screen.
        start_new_session=True,
    )
    os.close(slave)
    chunks: List[bytes] = []
    reason = "exited"
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                reason = "timeout"
                break
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    data = os.read(master, 4096)
                except OSError:  # EIO: every slave end is closed
                    data = b""
                if not data:
                    break
                chunks.append(data)
                if stop_at and stop_at in b"".join(chunks).decode("utf-8", "replace"):
                    reason = "stopped"
                    break
            elif proc.poll() is not None:
                # What the child wrote just before it exited may still sit in
                # the pty buffer: drain it, or the output can come back short.
                while select.select([master], [], [], 0)[0]:
                    try:
                        data = os.read(master, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    chunks.append(data)
                break
        if reason == "exited":
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                reason = "timeout"
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        os.close(master)
    output = b"".join(chunks).decode("utf-8", "replace")
    return TerminalRun(proc.returncode if reason == "exited" else None, reason, output)


@pytest.fixture
def sandbox(tmp_path):
    """Throwaway HOME and cwd, plus a BROWSER opener that leaves a marker file."""
    home = tmp_path / "home"
    cwd = tmp_path / "cwd"
    home.mkdir()
    cwd.mkdir()
    marker = tmp_path / "browser-was-opened"
    opener = tmp_path / "opener.sh"
    opener.write_text(f'#!/bin/sh\necho "$@" >> "{marker}"\n', encoding="utf-8")
    opener.chmod(0o755)
    return SimpleNamespace(
        home=home, cwd=cwd, marker=marker, env={"BROWSER": str(opener)}
    )


def _wait_for(path: Path, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return path.exists()


@posix_only
@pytest.mark.parametrize("argv", [["auth", "login"], ["auth", "login", "api"]])
def test_login_in_a_real_terminal_prints_the_url_and_exits(sandbox, argv):
    run = _run_in_terminal(
        argv, home=sandbox.home, cwd=sandbox.cwd, extra_env=sandbox.env
    )
    assert (run.reason, run.returncode) == ("exited", 0), run.output
    assert "oauth.yandex.ru/authorize" in run.output
    assert "Enter OAuth code" not in run.output
    assert "Choose a profile" not in run.output
    assert not (sandbox.cwd / ".env").exists(), "login wrote the folder's .env"
    assert not sandbox.marker.exists(), "a browser was opened without being asked"


@posix_only
def test_the_interactive_flag_does_prompt_in_a_real_terminal(sandbox):
    """Control for the test above: the harness can see a prompt when there is one."""
    run = _run_in_terminal(
        ["auth", "login", "api", "--interactive"],
        home=sandbox.home,
        cwd=sandbox.cwd,
        extra_env=sandbox.env,
        stop_at="Enter OAuth code",
    )
    assert run.reason == "stopped", run.output
    assert _wait_for(sandbox.marker), "the BROWSER opener never ran: broken harness"


@posix_only
def test_an_ordinary_command_in_a_real_terminal_never_starts_a_login(sandbox):
    run = _run_in_terminal(
        ["campaigns", "get"],
        home=sandbox.home,
        cwd=sandbox.cwd,
        extra_env=sandbox.env,
    )
    assert (run.reason, run.returncode) == ("exited", 2), run.output
    assert "No credentials bound to this folder" in run.output
    assert "Enter OAuth code" not in run.output
    assert not sandbox.marker.exists()


@posix_only
def test_browser_login_in_a_real_terminal_imports_instead_of_opening_a_window(
    sandbox, tmp_path
):
    pytest.importorskip("playwright")
    # No Chrome under the throwaway HOME, and no Chromium to launch: the
    # headless import stops at "profile not found"; a regression that opens
    # the window would fail to launch and say something else.
    no_browsers = tmp_path / "no-browsers"
    no_browsers.mkdir()
    run = _run_in_terminal(
        ["auth", "login", "browser"],
        home=sandbox.home,
        cwd=sandbox.cwd,
        extra_env={**sandbox.env, "PLAYWRIGHT_BROWSERS_PATH": str(no_browsers)},
    )
    assert (run.reason, run.returncode) == ("exited", 1), run.output
    assert "Chrome profile directory not found" in run.output, run.output
    assert "Login confirmed" not in run.output
    assert not sandbox.marker.exists()


# --- 4. the shape of the code ------------------------------------------------

TERMINAL_PROBE = "_stdin_is_interactive"

# Every prompt / browser-opening primitive of the package, by (module, function).
# Each site must be reachable only behind an explicit opt-in (or be a refusal
# or a destructive-action confirmation); sections 2 and 3 prove the behaviour,
# this registry makes a *new* site a conscious decision. Add an entry only
# together with its flag in AGENTS.md.
DIALOG_SITES: Dict[Tuple[str, str], Set[str]] = {
    # auth login api --interactive: the dialogs behind the flag.
    ("commands/auth.py", "_prompt_authorize_code"): {"click.prompt", "webbrowser.open"},
    ("commands/auth.py", "_ask_copy_token"): {"click.prompt"},
    ("commands/auth.py", "login_api"): {"click.prompt"},  # the profile menu
    # auth login browser --source manual: the visible window.
    ("commands/auth.py", "browser_login"): {"login_manual_session"},
    ("browser/session.py", "login_manual_session"): {"headless=False"},
    # `masters delete` confirms a destructive, irreversible click (--yes skips).
    ("commands/masters.py", "delete"): {"click.confirm"},
}

_DIALOG_CALLS = {
    "input",
    "login_manual_session",
    "click.prompt",
    "click.confirm",
    "getpass.getpass",
    "webbrowser.open",
    "webbrowser.open_new",
    "webbrowser.open_new_tab",
}


def _parents(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> str:
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return "<module>"


def _call_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
        return func.attr
    return None


def terminal_probe_violations(source: str) -> List[Tuple[int, str]]:
    """Uses of terminal detection that could *enable* something.

    A terminal may only ever *refuse* (``if not _stdin_is_interactive(): raise
    ...``): every reference to the probe is the callee of a negated call, and
    ``isatty`` lives nowhere else. ``interactive = _stdin_is_interactive() and
    ...`` is exactly how 0.5.5 made a terminal mean "dialogs on"; an alias
    (``probe = _stdin_is_interactive``) or a callback would hide the same thing
    from a check that only looks at calls.
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    found = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "isatty"
            and _enclosing_function(node, parents) != TERMINAL_PROBE
        ):
            found.append((node.lineno, f"isatty outside {TERMINAL_PROBE}()"))
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name != TERMINAL_PROBE:
                continue
            call = parents.get(node)
            if not (isinstance(call, ast.Call) and call.func is node):
                found.append((node.lineno, f"{TERMINAL_PROBE} used other than called"))
                continue
            negation = parents.get(call)
            if not (
                isinstance(negation, ast.UnaryOp) and isinstance(negation.op, ast.Not)
            ):
                found.append(
                    (node.lineno, f"{TERMINAL_PROBE}() not negated: it may only refuse")
                )
    return found


def dialog_sites(source: str) -> Dict[str, Set[str]]:
    """Function name -> prompt / browser-opening primitives it calls."""
    tree = ast.parse(source)
    parents = _parents(tree)
    sites: Dict[str, Set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name in _DIALOG_CALLS:
            sites.setdefault(_enclosing_function(node, parents), set()).add(name)
        for keyword in node.keywords:
            if (
                keyword.arg == "headless"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
            ):
                sites.setdefault(_enclosing_function(node, parents), set()).add(
                    "headless=False"
                )
    return sites


def _package_sources() -> Dict[str, str]:
    return {
        path.relative_to(PACKAGE).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.rglob("*.py"))
        if "_vendor" not in path.parts  # fork-synced third-party code
    }


def test_a_terminal_can_only_refuse_never_enable():
    offenders = [
        f"{module}:{lineno}: {problem}"
        for module, source in _package_sources().items()
        for lineno, problem in terminal_probe_violations(source)
    ]
    assert offenders == [], (
        "Terminal detection must only refuse, never switch a dialog or a window "
        "on (AGENTS.md, Authorization Execution Mode):\n" + "\n".join(offenders)
    )


def test_prompts_and_browser_windows_live_only_in_registered_functions():
    actual = {
        (module, function): primitives
        for module, source in _package_sources().items()
        for function, primitives in dialog_sites(source).items()
    }
    unregistered = {
        site: sorted(p) for site, p in actual.items() if site not in DIALOG_SITES
    }
    assert unregistered == {}, (
        "New prompt / browser-opening call sites. Gate them behind an explicit "
        "flag, document the flag in AGENTS.md, then register them in "
        "DIALOG_SITES: " + repr(unregistered)
    )
    drift = {
        site: (sorted(actual.get(site, ())), sorted(expected))
        for site, expected in DIALOG_SITES.items()
        if actual.get(site, set()) != expected
    }
    assert drift == {}, "DIALOG_SITES is stale (site: (found, registered)): " + repr(
        drift
    )


# The detectors need their own coverage: both guards above pass when the
# package is clean and when the detector is blind.


@pytest.mark.parametrize(
    "source",
    [
        "interactive = _stdin_is_interactive() and fmt == 'text'\n",
        "if _stdin_is_interactive():\n    prompt()\n",
        "ok = auth._stdin_is_interactive()\n",
        "probe = _stdin_is_interactive\nif probe():\n    prompt()\n",
        "click.option('--x', default=_stdin_is_interactive)\n",
        "def elsewhere():\n    return sys.stdin.isatty()\n",
        "flag = os.isatty(0)\n",
    ],
)
def test_the_terminal_detector_flags_enabling_uses(source):
    assert terminal_probe_violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "if not _stdin_is_interactive():\n    raise click.UsageError('x')\n",
        "if not _stdin_is_interactive() and not allow_no_tty:\n    raise X\n",
        "def _stdin_is_interactive():\n    return sys.stdin.isatty()\n",
    ],
)
def test_the_terminal_detector_allows_refusals(source):
    assert terminal_probe_violations(source) == []


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def f():\n    click.prompt('x')\n", {"f": {"click.prompt"}}),
        ("def f():\n    webbrowser.open(url)\n", {"f": {"webbrowser.open"}}),
        ("def f():\n    return input()\n", {"f": {"input"}}),
        ("def f():\n    login_manual_session()\n", {"f": {"login_manual_session"}}),
        ("def f():\n    launch(headless=False)\n", {"f": {"headless=False"}}),
        ("def f(flag):\n    launch(headless=flag)\n", {}),
        ("def f():\n    click.echo('x')\n", {}),
    ],
)
def test_the_dialog_detector_finds_each_primitive(source, expected):
    assert dialog_sites(source) == expected


# --- 5. the documentation ----------------------------------------------------

USER_DOCS = ("README.md", "README_ru.md", "CLAUDE.md", "AGENTS.md")

# What the contract says in AGENTS.md; a deliberate rewording edits this list.
AGENTS_CONTRACT = (
    "Authorization is headless and non-interactive by default, including when "
    "stdin and stdout are terminals.",
    "TTY detection must never enable login dialogs or browser UI by itself.",
    f"`{HINT_LOGIN_API_INTERACTIVE}`",
    f"`{HINT_LOGIN_BROWSER_MANUAL}`",
    THIS_FILE,
)

# The phrasings the drifted 0.5.5 docs used for the behaviour this file forbids.
DRIFT_PHRASES = (
    r"(?<!non-)(?<!non )interactive by default",
    r"interactive in a terminal",
    r"opens a visible window once",
    r"visible by definition",
    r"opens the login window itself",
    r"(?<!не )(?<!без )интерактивн\w+ по умолчанию",
    r"интерактивн\w+ в терминале",
    r"окно входа открывается само",
)


def _doc(name: str) -> str:
    path = REPO / name
    if not path.exists():
        pytest.skip(f"{name} is not part of this install")
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("phrase", AGENTS_CONTRACT)
def test_agents_md_states_the_contract(phrase):
    assert phrase in _doc("AGENTS.md")


@pytest.mark.parametrize("name", USER_DOCS)
def test_every_user_doc_names_both_opt_ins(name):
    text = _doc(name)
    for hint in (HINT_LOGIN_API_INTERACTIVE, HINT_LOGIN_BROWSER_MANUAL):
        assert hint in text, f"{name} never mentions `{hint}`"


@pytest.mark.parametrize("name", USER_DOCS)
def test_no_user_doc_describes_interactive_login_as_the_default(name):
    text = _doc(name)
    offenders = [
        match.group(0)
        for pattern in DRIFT_PHRASES
        for match in re.finditer(pattern, text, flags=re.IGNORECASE)
    ]
    assert offenders == [], f"{name} describes the retired behaviour: {offenders}"


def _auth_examples(raw: str) -> List[str]:
    """``direct auth ...`` commands in code fences and inline code spans."""
    examples: List[str] = []
    prose: List[str] = []
    in_fence = False
    for line in raw.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            code = line.split(" #", 1)[0]
            examples += [m.group(0) for m in re.finditer(r"direct auth [^|]+", code)]
        else:
            prose.append(line)
    flat = re.sub(r"\s+", " ", " ".join(prose))
    return examples + re.findall(r"`(direct auth [^`]+)`", flat)


def _unknown_flags(example: str) -> List[str]:
    """Flags of a ``direct auth ...`` example that the real command does not offer."""
    command: click.Command = cli.commands["auth"]
    unknown: List[str] = []
    takes_value = False
    for token in shlex.split(example)[2:]:  # drop `direct auth`
        if takes_value:  # `--method browser`: `browser` is a value, not a subcommand
            takes_value = False
        elif token.startswith("--"):
            flag = token.split("=", 1)[0]
            option = _find_option(command, flag)
            if flag != "--help" and not (option and _is_live(option)):
                unknown.append(flag)
            takes_value = option is not None and not option.is_flag and "=" not in token
        elif not token.startswith("-") and isinstance(command, click.Group):
            command = command.commands.get(token, command)
    return unknown


@pytest.mark.parametrize("name", USER_DOCS)
def test_every_documented_auth_command_is_live_syntax(name):
    raw = (REPO / name).read_text(encoding="utf-8") if (REPO / name).exists() else None
    if raw is None:
        pytest.skip(f"{name} is not part of this install")
    stale = {
        example.strip(): unknown
        for example in _auth_examples(raw)
        if (unknown := _unknown_flags(example))
    }
    assert stale == {}, f"{name} shows flags the CLI no longer has: {stale}"


@pytest.mark.parametrize(
    "example,unknown",
    [
        ("direct auth login --method browser --interactive", ["--method"]),
        ("direct auth login browser --headful", ["--headful"]),
        ("direct auth login api --interactive", []),
        ("direct auth login --interactive", []),
        ("direct auth login browser --source manual --timeout 60", []),
        ("direct auth status --method all", ["--method"]),
        ("direct auth logout --method browser", ["--method"]),
        ("direct auth logout api --profile agency1", []),
    ],
)
def test_the_example_checker_catches_retired_syntax(example, unknown):
    assert _unknown_flags(example) == unknown


# --- 6. CI -------------------------------------------------------------------


def test_the_quality_workflow_runs_this_contract_by_name():
    workflow = REPO / ".github" / "workflows" / "quality.yml"
    if not workflow.exists():
        pytest.skip("not a source checkout")
    text = workflow.read_text(encoding="utf-8")
    # A dedicated step: a deleted, renamed or emptied contract file fails it
    # (pytest exits 5 when nothing is collected) instead of vanishing from the
    # big run.
    assert f"pytest {THIS_FILE}" in text

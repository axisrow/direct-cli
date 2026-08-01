"""
``direct playwright`` — manage the browser session ``direct masters`` uses.

Мастер кампаний (Campaign Wizard) has no API surface at all, so ``direct
masters`` (``direct_cli/commands/masters.py``) drives a real Playwright
browser with the user's decrypted Yandex cookies instead — see
``direct_cli/browser/session.py`` for why (macOS Keychain, #634) and
``direct_cli/browser/store.py`` for the on-disk session format.

Two commands, deliberately split:

- ``direct playwright login`` decrypts Chrome's Yandex cookies once and
  *persists* the result as a Playwright ``storage_state`` file, so
  subsequent ``direct masters`` calls skip the Keychain round-trip.
- ``direct playwright doctor`` is **read-only diagnostics**. It never logs
  in, never launches a browser session of its own, and never writes
  anything — see ``direct_cli/browser/diagnostics.py``'s module docstring
  for the invariant and the contract tests enforcing it. If something is
  broken, the fix is always ``direct playwright login``, never a flag on
  ``doctor``.

Module filename is deliberately ``browser_session.py``, not ``playwright.py``
— a same-named module inside a package can shadow the real ``playwright``
package if a script is ever run with this directory as ``sys.path[0]``. The
Click *group* is still named ``playwright`` (``cli.commands["playwright"]``
is unrelated to the Python module namespace).
"""

from pathlib import Path

import click

from ..browser import store
from ..browser.session import BrowserSessionError
from ..utils import reference_output_options
from ..output import print_success

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)


def _browser_options(func):
    """Shared ``--profile-dir`` / ``--chrome-profile`` option pair.

    Deliberately does NOT include ``--login`` (unlike
    ``direct_cli.commands.masters._masters_browser_options``): cookies are
    account-scoped by construction, and neither ``login`` nor ``doctor``
    builds a ``?ulogin=`` URL — that is ``direct masters``' concern alone.
    """
    func = click.option(
        "--chrome-profile",
        default="Default",
        help="Chrome profile subdirectory to read cookies from (e.g. 'Profile 1')",
    )(func)
    return click.option(
        "--profile-dir", help="Chrome user-data-dir to read cookies from"
    )(func)


@click.group(name="playwright")
def playwright_group():
    """Manage the browser session `direct masters` uses (no API token needed)"""


@playwright_group.command(name="login")
@_browser_options
@click.option("--headful", is_flag=True, help="Show the browser window (for debugging)")
@click.option(
    "--no-verify",
    is_flag=True,
    help="Skip navigating to Direct to confirm the session is authenticated",
)
@reference_output_options
def login(profile_dir, chrome_profile, headful, no_verify, output_format, output):
    """Decrypt Chrome's Yandex cookies once and save a reusable browser session"""
    try:
        from ..browser.session import capture_storage_state
    except ImportError as exc:
        raise click.UsageError(
            "playwright is required for `direct playwright login` but is "
            f"not installed. Run: {_BROWSER_INSTALL_HINT}"
        ) from exc

    # A plain try/except (not the whole-with-block wrapping
    # direct_cli/commands/masters.py:_open_session uses) is correct here:
    # capture_storage_state() returns a value rather than being a
    # contextmanager/generator itself, so there is no generator-body error
    # that could surface outside this except (the #634 pitfall that wrapping
    # style guards against does not apply to a plain function call).
    try:
        storage_state, source_meta = capture_storage_state(
            profile_dir=Path(profile_dir) if profile_dir else None,
            chrome_profile=chrome_profile,
            headless=not headful,
            verify=not no_verify,
        )
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc

    saved_path = store.save_session(storage_state, source=source_meta)
    status = store.session_status(saved_path)
    cookies = storage_state.get("cookies") or []
    domains = sorted({c["domain"] for c in cookies if c.get("domain")})

    payload = {
        "saved": str(saved_path),
        "cookies": len(cookies),
        "domains": domains,
        "verified": not no_verify,
        "mode": status["mode"],
    }

    if output_format == "json":
        import json

        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if output_format == "text":
        print_success(f"Saved browser session to {saved_path}")
        click.echo(f"saved={payload['saved']}")
        click.echo(f"cookies={payload['cookies']}")
        click.echo(f"domains={', '.join(domains)}")
        click.echo(f"verified={'yes' if payload['verified'] else 'no'}")
        click.echo(f"mode={payload['mode']}")
        return

    from ..output import format_output

    format_output(payload, output_format, output)


@playwright_group.command(name="doctor")
@_browser_options
@reference_output_options
def doctor(profile_dir, chrome_profile, output_format, output):
    """Diagnose the browser-session pipeline — read-only, never logs in"""
    from ..browser.diagnostics import run_diagnostics

    checks = run_diagnostics(
        profile_dir=Path(profile_dir) if profile_dir else None,
        chrome_profile=chrome_profile,
    )
    overall_ok = all(c.ok is not False for c in checks)

    if output_format == "json":
        import json

        payload = {
            "ok": overall_ok,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint}
                for c in checks
            ],
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if output_format == "text":
        for c in checks:
            status = {True: "ok", False: "fail", None: "unknown"}[c.ok]
            click.echo(f"{c.name}={status}\t{c.detail}")
            if c.ok is False and c.hint:
                click.echo(f"  hint: {c.hint}")
        return

    from ..output import format_output

    format_output(
        [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint}
            for c in checks
        ],
        output_format,
        output,
    )

"""
Мастер кампаний (Campaign Wizard) commands.

Мастер кампаний has no Yandex Direct API surface at all — it exists only in
the web interface, and must not be confused with ``UNIFIED_CAMPAIGN``, an
unrelated v5 API campaign type already supported by ``campaigns add/get
--type unified_campaign`` (see ``direct_cli/commands/_campaigns_unified.py``).
This group reads Мастер кампаний by driving a real Chrome session (via
Playwright) with the user's own Yandex cookies decrypted and injected — see
``direct_cli/browser/`` for the browser layer this group is a thin Click
wrapper around.

Read-only in this first version: ``list`` and ``get``. No mutations.
"""

import contextlib
from pathlib import Path
from typing import Optional

import click

from ..output import format_output, handle_api_errors
from ..utils import parse_ids

_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)


def _require_login(ctx: click.Context, login: Optional[str]) -> str:
    resolved = login or (ctx.obj or {}).get("login")
    if not resolved:
        raise click.UsageError(
            "A Yandex Direct login is required to open Мастер кампаний "
            "(used as ?ulogin=... in the Direct web UI). Pass --login, set "
            "YANDEX_DIRECT_LOGIN, or select an active `direct auth` profile."
        )
    return resolved


@contextlib.contextmanager
def _open_session(headful: bool, profile_dir: Optional[str], chrome_profile: str):
    """Open a browser session, converting session errors to ClickException.

    Wrapping the *whole* ``with open_chrome_session(...)`` block (rather than
    only the call that constructs it) matters because ``open_chrome_session``
    is itself a contextmanager: an error raised inside its generator body
    (Keychain/decryption failures, and BrowserAuthError/BrowserCaptchaError
    raised by callers using this session) only surfaces on ``__enter__``,
    which is outside a try/except placed around the bare function call (see
    the regression test for #634 in tests/test_masters.py).
    """
    try:
        from ..browser.session import BrowserSessionError, open_chrome_session
    except ImportError as exc:
        raise click.UsageError(
            "playwright is required for `direct masters` but is not "
            f"installed. Run: {_BROWSER_INSTALL_HINT}"
        ) from exc

    try:
        with open_chrome_session(
            profile_dir=Path(profile_dir) if profile_dir else None,
            chrome_profile=chrome_profile,
            headless=not headful,
        ) as page:
            yield page
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc


def _masters_browser_options(func):
    """Apply the option stack shared by every ``masters`` subcommand.

    Equivalent to, top-to-bottom::

        @click.option("--login", help="...")
        @click.option("--headful", is_flag=True, help="...")
        @click.option("--profile-dir", help="...")
        @click.option("--chrome-profile", default="Default", help="...")
        @click.option("--format", "output_format", default="json", help="...")
        @click.option("--output", help="...")

    Mirrors the shared-decorator convention in ``direct_cli.utils``
    (``v4_output_options`` / ``reference_output_options``) instead of
    repeating this six-option stack on both ``list`` and ``get``.
    """
    func = click.option("--output", help="Output file")(func)
    func = click.option(
        "--format", "output_format", default="json", help="Output format"
    )(func)
    func = click.option(
        "--chrome-profile",
        default="Default",
        help="Chrome profile subdirectory to read cookies from (e.g. 'Profile 1')",
    )(func)
    func = click.option(
        "--profile-dir", help="Chrome user-data-dir to read cookies from"
    )(func)
    func = click.option(
        "--headful", is_flag=True, help="Show the browser window (for debugging)"
    )(func)
    return click.option(
        "--login", help="Yandex Direct login (defaults to resolved --login/profile)"
    )(func)


@click.group()
def masters():
    """Read Мастер кампаний (Campaign Wizard) — browser-only, no API"""


@masters.command(name="list")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def list_masters(
    ctx, login, headful, profile_dir, chrome_profile, output_format, output
):
    """List every Мастер кампаний in the account"""
    from ..browser.masters import fetch_masters_list

    resolved_login = _require_login(ctx, login)

    with _open_session(headful, profile_dir, chrome_profile) as page:
        result = fetch_masters_list(page, resolved_login)

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    campaign_ids,
    login,
    headful,
    profile_dir,
    chrome_profile,
    output_format,
    output,
):
    """Get one or more Мастер кампаний by ID (comma-separated)"""
    from ..browser.masters import fetch_master

    resolved_login = _require_login(ctx, login)
    ids = parse_ids(campaign_ids) or []

    results = []
    with _open_session(headful, profile_dir, chrome_profile) as page:
        for campaign_id in ids:
            results.append(fetch_master(page, campaign_id, resolved_login))

    format_output(results if len(results) != 1 else results[0], output_format, output)

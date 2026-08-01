"""
Мастер кампаний (Campaign Wizard) commands.

Мастер кампаний has no Yandex Direct API surface at all — it exists only in
the web interface, and must not be confused with ``UNIFIED_CAMPAIGN``, an
unrelated v5 API campaign type already supported by ``campaigns add/get
--type unified_campaign`` (see ``direct_cli/commands/_campaigns_unified.py``).
This group reads Мастер кампаний by driving a real Chrome session (via
Playwright) on a throwaway copy of the user's own Chrome cookies — see
``direct_cli/browser/`` for the browser layer this group is a thin Click
wrapper around.

Read-only in this first version: ``list`` and ``get``. No mutations.
"""

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


def _open_session(headful: bool, profile_dir: Optional[str]):
    try:
        from ..browser.session import BrowserSessionError, open_chrome_session
    except ImportError as exc:
        raise click.UsageError(
            "playwright is required for `direct masters` but is not "
            f"installed. Run: {_BROWSER_INSTALL_HINT}"
        ) from exc

    try:
        return open_chrome_session(
            profile_dir=Path(profile_dir) if profile_dir else None,
            headless=not headful,
        )
    except BrowserSessionError as exc:
        raise click.ClickException(str(exc)) from exc


def _masters_browser_options(func):
    """Apply the option stack shared by every ``masters`` subcommand.

    Equivalent to, top-to-bottom::

        @click.option("--login", help="...")
        @click.option("--headful", is_flag=True, help="...")
        @click.option("--profile-dir", help="...")
        @click.option("--format", "output_format", default="json", help="...")
        @click.option("--output", help="...")

    Mirrors the shared-decorator convention in ``direct_cli.utils``
    (``v4_output_options`` / ``reference_output_options``) instead of
    repeating this five-option stack on both ``list`` and ``get``.
    """
    func = click.option("--output", help="Output file")(func)
    func = click.option(
        "--format", "output_format", default="json", help="Output format"
    )(func)
    func = click.option(
        "--profile-dir", help="Chrome user-data-dir to copy cookies from"
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
def list_masters(ctx, login, headful, profile_dir, output_format, output):
    """List every Мастер кампаний in the account"""
    from ..browser.masters import fetch_masters_list
    from ..browser.session import BrowserCaptchaError

    resolved_login = _require_login(ctx, login)

    with _open_session(headful, profile_dir) as page:
        try:
            result = fetch_masters_list(page, resolved_login)
        except BrowserCaptchaError as exc:
            raise click.ClickException(str(exc)) from exc

    format_output(result, output_format, output)


@masters.command()
@click.argument("campaign_ids")
@_masters_browser_options
@click.pass_context
@handle_api_errors
def get(ctx, campaign_ids, login, headful, profile_dir, output_format, output):
    """Get one or more Мастер кампаний by ID (comma-separated)"""
    from ..browser.masters import fetch_master
    from ..browser.session import BrowserCaptchaError

    resolved_login = _require_login(ctx, login)
    ids = parse_ids(campaign_ids) or []

    results = []
    with _open_session(headful, profile_dir) as page:
        for campaign_id in ids:
            try:
                results.append(fetch_master(page, campaign_id, resolved_login))
            except BrowserCaptchaError as exc:
                raise click.ClickException(str(exc)) from exc

    format_output(results if len(results) != 1 else results[0], output_format, output)

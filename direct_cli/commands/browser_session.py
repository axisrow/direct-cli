"""Deprecated browser-auth command paths; canonical commands live under auth."""

import click

from .._auth_hints import HINT_LOGIN_BROWSER_CHROME
from ..utils import reference_output_options
from .auth import (
    _browser_options,
    doctor_browser,
    import_browser_session,
    legacy_auth_warning,
)


@click.group(name="playwright", hidden=True)
def playwright_group():
    """Deprecated browser authorization commands; use direct auth."""


@playwright_group.command(name="login", hidden=True)
@_browser_options
@click.option("--headful", is_flag=True, help="Show the browser window (for debugging)")
@click.option("--no-verify", is_flag=True, help="Skip session verification")
@reference_output_options
def login(
    profile_dir: str,
    chrome_profile: str,
    headful: bool,
    no_verify: bool,
    output_format: str,
    output: str,
) -> None:
    """Import Chrome cookies (deprecated); the printed warning names the replacement."""
    legacy_auth_warning(HINT_LOGIN_BROWSER_CHROME)
    import_browser_session(
        profile_dir, chrome_profile, headful, no_verify, output_format, output
    )


@playwright_group.command(name="doctor", hidden=True)
@_browser_options
@reference_output_options
def doctor(
    profile_dir: str, chrome_profile: str, output_format: str, output: str
) -> None:
    """Diagnose browser authorization; use direct auth doctor."""
    legacy_auth_warning("direct auth doctor")
    doctor_browser(profile_dir, chrome_profile, output_format, output)

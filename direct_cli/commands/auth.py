"""Authentication commands for OAuth profile management."""

import json
import sys
import time
from typing import Optional, Tuple

import click

from ..auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    build_oauth_authorize_url,
    build_pkce_pair,
    exchange_oauth_code,
    get_active_profile,
    get_env_profile,
    get_oauth_profile,
    get_pending_pkce,
    list_profiles,
    remove_pending_pkce,
    resolve_login,
    save_oauth_profile,
    save_pending_confidential_auth,
    save_pending_pkce,
    set_active_profile,
    validate_oauth_profile,
)
from ..output import print_info, print_success


@click.group()
def auth():
    """Manage authentication profiles."""


@auth.command()
@click.option("--profile", default="default", show_default=True, help="Profile name")
@click.option("--code", help="OAuth authorization code")
@click.option(
    "--code-stdin",
    is_flag=True,
    help="Read OAuth authorization code from stdin",
)
@click.option("--oauth-token", help="Ready OAuth access token")
@click.option("--client-id", help="Custom OAuth app client_id")
@click.option("--client-secret", help="Custom OAuth app client_secret")
@click.option("--login", help="Direct client login for this profile")
@click.option(
    "--start-pkce",
    is_flag=True,
    help="Start a non-interactive PKCE login and print the authorize URL",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format for non-interactive auth start",
)
def login(
    profile,
    code,
    code_stdin,
    oauth_token,
    client_id,
    client_secret,
    login,
    start_pkce,
    output_format,
):
    """Authorize and save OAuth credentials under a profile."""
    chosen_client_id = client_id or DEFAULT_OAUTH_CLIENT_ID

    if code_stdin:
        if code or oauth_token or start_pkce:
            raise click.ClickException(
                "--code-stdin cannot be combined with --code, "
                "--oauth-token, or --start-pkce."
            )
        code = sys.stdin.read().strip()
        if not code:
            raise click.ClickException("--code-stdin requires a code on stdin.")

    if start_pkce:
        if code or oauth_token or client_secret:
            raise click.ClickException(
                "--start-pkce cannot be combined with --code, "
                "--oauth-token, or --client-secret."
            )
        _start_noninteractive_pkce(
            profile=profile,
            client_id=chosen_client_id,
            login=login,
            output_format=output_format,
        )
        return

    token = oauth_token
    if token:
        if not login:
            login = resolve_login(token)
        save_oauth_profile(
            profile=profile,
            token=token,
            login=login,
            source="manual",
        )
        print_success(f"Profile '{profile}' is saved and active.")
        return

    code_verifier = None
    auth_code = code
    effective_client_id = chosen_client_id
    effective_client_secret = client_secret

    if not auth_code:
        if not _stdin_is_interactive():
            _start_noninteractive_auth(
                profile=profile,
                client_id=chosen_client_id,
                client_secret=client_secret,
                login=login,
                output_format=output_format,
            )
            return

        auth_url, code_verifier = _build_interactive_authorize_url(
            client_id=chosen_client_id,
            client_secret=client_secret,
        )
        print_info("Open this URL and grant access:")
        click.echo(auth_url)
        auth_code = click.prompt("Enter OAuth code", type=str).strip()
    elif not client_secret:
        pending_pkce = get_pending_pkce(profile)
        if pending_pkce:
            if float(pending_pkce["expires_at"]) <= time.time():
                remove_pending_pkce(profile)
                pending_pkce = None
            else:
                if client_id and client_id != pending_pkce["client_id"]:
                    raise click.ClickException(
                        f"--client-id {client_id} does not match pending client_id "
                        f"for profile '{profile}'."
                    )
                effective_client_id = pending_pkce["client_id"]
                if pending_pkce["type"] == "confidential":
                    effective_client_secret = pending_pkce["client_secret"]
                else:
                    code_verifier = pending_pkce["code_verifier"]
                if not login:
                    login = pending_pkce.get("login")
        if not pending_pkce:
            remembered_profile = get_oauth_profile(profile)
            remembered_secret = None
            remembered_client_id = None
            if remembered_profile:
                remembered_secret = remembered_profile.get("client_secret")
                remembered_client_id = remembered_profile.get("client_id")
            if (
                isinstance(remembered_secret, str)
                and remembered_secret
                and isinstance(remembered_client_id, str)
                and remembered_client_id
            ):
                if client_id and client_id != remembered_client_id:
                    raise click.ClickException(
                        f"--client-id {client_id} does not match saved client_id "
                        f"for profile '{profile}'."
                    )
                effective_client_id = remembered_client_id
                effective_client_secret = remembered_secret
                if not login:
                    login = remembered_profile.get("login")
            else:
                raise click.ClickException(_start_pkce_required_message(profile))

    try:
        token_response = exchange_oauth_code(
            code=auth_code,
            client_id=effective_client_id,
            client_secret=effective_client_secret,
            code_verifier=code_verifier,
        )
    except RuntimeError as error:
        raise click.ClickException(str(error))

    access_token = token_response["access_token"]
    if not login:
        login = resolve_login(access_token)
    save_oauth_profile(
        profile=profile,
        token=access_token,
        login=login,
        refresh_token=token_response["refresh_token"],
        expires_at=time.time() + token_response["expires_in"],
        client_id=effective_client_id,
        client_secret=effective_client_secret,
    )
    remove_pending_pkce(profile)
    print_success(f"Profile '{profile}' is saved and active.")


@auth.command(name="list")
def list_command():
    """List available auth profiles without exposing secrets."""
    profiles = list_profiles()
    if not profiles:
        print_info("No profiles configured.")
        return

    for item in profiles:
        marker = "*" if item["active"] else " "
        login_display = item.get("login") or "(not set)"
        profile = item["profile"]
        source = item["source"]
        click.echo(f"{marker} {profile}  source={source}  login={login_display}")


@auth.command()
@click.option("--profile", required=True, help="Profile name")
def use(profile):
    """Set active profile for future commands."""
    token, _ = get_env_profile(profile)
    oauth_profile = get_oauth_profile(profile)
    if not token and not oauth_profile:
        raise click.ClickException(
            f"Profile '{profile}' not found in OAuth storage or env variables."
        )
    set_active_profile(profile)
    print_success(f"Active profile is '{profile}'.")


@auth.command()
@click.option("--profile", help="Profile name (defaults to active profile)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format",
)
def status(profile, output_format):
    """Show auth status for one profile."""
    selected = profile or get_active_profile()
    if not selected:
        print_info("No active profile.")
        return

    oauth_profile = get_oauth_profile(selected)
    env_token, env_login = get_env_profile(selected)

    if oauth_profile:
        source = oauth_profile.get("source") or "oauth"
        if source == "oauth":
            try:
                validate_oauth_profile(selected, oauth_profile)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        login_value = oauth_profile.get("login")
        if not login_value and env_login:
            login_value = env_login
            source = "oauth+env"
    elif env_token:
        source = "env"
        login_value = env_login
    else:
        raise click.ClickException(f"Profile '{selected}' is not configured.")

    expires_at = None
    expires_in_seconds = None
    if oauth_profile and isinstance(oauth_profile.get("expires_at"), (int, float)):
        expires_at = float(oauth_profile["expires_at"])
        expires_in_seconds = max(0, int(expires_at - time.time()))

    if output_format == "json":
        payload = {
            "profile": selected,
            "source": source,
            "has_token": True,
            "login": login_value,
        }
        if expires_at is not None:
            payload["expires_at"] = expires_at
            payload["expires_in_seconds"] = expires_in_seconds
        click.echo(json.dumps(payload, ensure_ascii=False))
        return

    click.echo(f"profile={selected}")
    click.echo(f"source={source}")
    click.echo("has_token=yes")
    if login_value:
        click.echo(f"login={login_value}")
    else:
        click.echo("login=(not set)")
    if expires_in_seconds is not None:
        click.echo(f"expires_in={_format_duration(expires_in_seconds)}")


def _format_duration(seconds: int) -> str:
    """Format a duration for auth status text output."""
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def _stdin_is_interactive() -> bool:
    """Return whether stdin can be used for an OAuth code prompt."""
    return sys.stdin.isatty()


def _build_interactive_authorize_url(
    client_id: str, client_secret: Optional[str] = None
) -> Tuple[str, Optional[str]]:
    """Build an authorize URL for same-process interactive login."""
    if client_secret:
        return build_oauth_authorize_url(client_id=client_id), None
    code_verifier, code_challenge = build_pkce_pair()
    auth_url = build_oauth_authorize_url(
        client_id=client_id, code_challenge=code_challenge
    )
    return auth_url, code_verifier


def _start_noninteractive_auth(
    profile: str,
    client_id: str,
    client_secret: Optional[str],
    login: Optional[str],
    output_format: str,
) -> None:
    """Persist pending state and print the authorize URL without prompting."""
    if client_secret:
        pending = save_pending_confidential_auth(
            profile=profile,
            client_id=client_id,
            client_secret=client_secret,
            login=login,
            created_at=time.time(),
        )
        auth_url = build_oauth_authorize_url(client_id=client_id)
    else:
        _start_noninteractive_pkce(
            profile=profile,
            client_id=client_id,
            login=login,
            output_format=output_format,
        )
        return

    _print_start_auth_output(
        profile=profile,
        auth_url=auth_url,
        expires_at=pending["expires_at"],
        output_format=output_format,
    )


def _start_noninteractive_pkce(
    profile: str,
    client_id: str,
    login: Optional[str],
    output_format: str,
) -> None:
    """Persist pending PKCE state and print the authorize URL."""
    code_verifier, code_challenge = build_pkce_pair()
    pending = save_pending_pkce(
        profile=profile,
        client_id=client_id,
        code_verifier=code_verifier,
        login=login,
        created_at=time.time(),
    )
    auth_url = build_oauth_authorize_url(
        client_id=client_id, code_challenge=code_challenge
    )
    _print_start_auth_output(
        profile=profile,
        auth_url=auth_url,
        expires_at=pending["expires_at"],
        output_format=output_format,
    )


def _print_start_auth_output(
    profile: str,
    auth_url: str,
    expires_at: float,
    output_format: str,
) -> None:
    """Print the non-interactive auth start response without secrets."""
    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "profile": profile,
                    "authorize_url": auth_url,
                    "expires_at": expires_at,
                },
                ensure_ascii=False,
            )
        )
        return
    print_info("Open this URL and grant access:")
    click.echo(auth_url)


def _start_pkce_required_message(profile: str) -> str:
    return (
        "Missing or expired pending PKCE state. "
        f"Run direct auth login --profile {profile} first."
    )

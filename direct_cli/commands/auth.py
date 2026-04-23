"""Authentication commands for OAuth profile management."""

import click

from ..auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    build_oauth_authorize_url,
    build_pkce_pair,
    exchange_oauth_code,
    get_active_profile,
    get_env_profile,
    get_oauth_profile,
    list_profiles,
    save_oauth_profile,
    set_active_profile,
)
from ..output import print_info, print_success


@click.group()
def auth():
    """Manage authentication profiles."""


@auth.command()
@click.option("--profile", default="default", show_default=True, help="Profile name")
@click.option("--code", help="OAuth authorization code")
@click.option("--oauth-token", help="Ready OAuth access token")
@click.option("--client-id", help="Custom OAuth app client_id")
@click.option("--client-secret", help="Custom OAuth app client_secret")
@click.option("--login", help="Direct client login for this profile")
def login(profile, code, oauth_token, client_id, client_secret, login):
    """Authorize and save OAuth credentials under a profile."""
    chosen_client_id = client_id or DEFAULT_OAUTH_CLIENT_ID

    token = oauth_token
    if token:
        save_oauth_profile(profile=profile, token=token, login=login)
        print_success(f"Profile '{profile}' is saved and active.")
        return

    code_verifier = None
    auth_code = code

    if not auth_code:
        if client_secret:
            auth_url = build_oauth_authorize_url(client_id=chosen_client_id)
        else:
            code_verifier, code_challenge = build_pkce_pair()
            auth_url = build_oauth_authorize_url(
                client_id=chosen_client_id, code_challenge=code_challenge
            )
        print_info("Open this URL and grant access:")
        click.echo(auth_url)
        auth_code = click.prompt("Enter OAuth code", type=str).strip()

    try:
        token = exchange_oauth_code(
            code=auth_code,
            client_id=chosen_client_id,
            client_secret=client_secret,
            code_verifier=code_verifier,
        )
    except RuntimeError as error:
        raise click.ClickException(str(error))

    save_oauth_profile(profile=profile, token=token, login=login)
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
        login_state = "yes" if item["has_login"] else "no"
        click.echo(
            f"{marker} {item['profile']}  source={item['source']}  login={login_state}"
        )


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
def status(profile):
    """Show auth status for one profile."""
    selected = profile or get_active_profile()
    if not selected:
        print_info("No active profile.")
        return

    oauth_profile = get_oauth_profile(selected)
    env_token, env_login = get_env_profile(selected)

    if oauth_profile:
        source = "oauth"
        has_login = bool(oauth_profile.get("login"))
    elif env_token:
        source = "env"
        has_login = bool(env_login)
    else:
        raise click.ClickException(f"Profile '{selected}' is not configured.")

    click.echo(f"profile={selected}")
    click.echo(f"source={source}")
    click.echo("has_token=yes")
    click.echo(f"has_login={'yes' if has_login else 'no'}")

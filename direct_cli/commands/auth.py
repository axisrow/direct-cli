"""Authentication commands for OAuth profile management."""

import json
import os
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import click
from click.core import ParameterSource

from ..auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    FOLDER_CREDENTIAL_KEYS,
    INHERIT_GLOBAL_ENV,
    bw_read,
    build_oauth_authorize_url,
    build_pkce_pair,
    exchange_oauth_code,
    get_active_profile,
    get_env_profile,
    get_credentials_with_source,
    get_oauth_profile,
    get_pending_pkce,
    inherit_globally_enabled,
    load_env_file,
    list_profiles,
    load_auth_store,
    op_read,
    remove_pending_pkce,
    resolve_account_login,
    save_env_credentials,
    save_auth_store,
    save_oauth_profile,
    save_pending_confidential_auth,
    save_pending_pkce,
    set_active_profile,
    validate_oauth_profile,
)
from ..i18n import t
from ..output import (
    format_output,
    handle_api_errors,
    print_info,
    print_success,
    print_warning,
)
from ..utils import reference_output_options


def _prompt_authorize_code(
    client_id: str, client_secret: Optional[str], open_browser: bool = False
) -> Tuple[str, Optional[str]]:
    """Interactive browser-paste prompt: print the authorize URL, read the code.

    Returns ``(auth_code, code_verifier)``; the caller performs the token
    exchange so pending/remembered-PKCE paths can substitute their own
    client settings. Shared by `auth login` and the bind menu.
    """
    auth_url, code_verifier = _build_interactive_authorize_url(
        client_id=client_id,
        client_secret=client_secret,
    )
    print_info(t("Open this URL and grant access:"))
    click.echo(auth_url)
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except (webbrowser.Error, OSError):
            pass  # The printed URL remains usable on hosts without a browser.
    auth_code = click.prompt(t("Enter OAuth code"), type=str, hide_input=True).strip()
    return auth_code, code_verifier


def bind_credentials_to_dotenv(
    profile: str, token: str, login_value: Optional[str]
) -> None:
    """Persist an in-hand credential pair as this folder's cwd `.env` binding.

    Re-exports the pair into ``os.environ`` so the running process resolves
    the freshly bound credentials even when the shell already exported a
    stale ``YANDEX_DIRECT_LOGIN`` — ``load_dotenv`` never overrides set
    variables.
    """
    try:
        save_env_credentials(token=token, login=login_value)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    os.environ["YANDEX_DIRECT_TOKEN"] = token
    if login_value:
        os.environ["YANDEX_DIRECT_LOGIN"] = login_value
    else:
        os.environ.pop("YANDEX_DIRECT_LOGIN", None)
    print_success(
        t("Bound credentials to .env (profile {profile}).").format(profile=profile)
    )


def bind_profile_to_dotenv(profile: str) -> Tuple[str, Optional[str]]:
    """Resolve *profile* and bind it to this folder's cwd `.env` (merge, 0600).

    Shared by `auth write` and the interactive bind menu.
    """
    try:
        token, login_value = get_credentials_with_source(
            profile=profile,
            allow_login_resolve=True,
        )[:2]
    except (RuntimeError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    bind_credentials_to_dotenv(profile, token, login_value)
    return token, login_value


@click.group()
def auth():
    """Manage API and browser authorization."""


@auth.command()
@click.option(
    "--method", type=click.Choice(["api", "browser"]), help="Authorization method"
)
@click.option(
    "--source",
    type=click.Choice(["manual", "chrome"]),
    default="manual",
    help="Browser login source",
)
@click.option(
    "--profile-dir", type=click.Path(file_okay=False), help="Browser profile directory"
)
@click.option(
    "--chrome-profile", default="Default", help="Chrome profile subdirectory to import"
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=click.IntRange(min=1),
    default=300,
    help="Seconds to wait for browser login",
)
@click.option(
    "--allow-no-tty",
    is_flag=True,
    help="Open the login window even without an interactive terminal",
)
@click.option(
    "--headful", is_flag=True, help="Show the browser window during Chrome import"
)
@click.option(
    "--no-verify", is_flag=True, help="Skip session verification during Chrome import"
)
@click.option("--profile", default="default", show_default=True, help="Profile name")
@click.option(
    "--code",
    help="OAuth authorization code; use '-' to read from stdin for automation",
)
@click.option(
    "--code-stdin",
    is_flag=True,
    hidden=True,
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
@click.pass_context
@handle_api_errors
def login(
    ctx: click.Context,
    method: Optional[str],
    source: str,
    profile_dir: Optional[str],
    chrome_profile: str,
    timeout_seconds: int,
    allow_no_tty: bool,
    headful: bool,
    no_verify: bool,
    profile: str,
    code: Optional[str],
    code_stdin: bool,
    oauth_token: Optional[str],
    client_id: Optional[str],
    client_secret: Optional[str],
    login: Optional[str],
    start_pkce: bool,
    output_format: str,
) -> None:
    """Log in to the API or save a browser session."""
    api_options = (
        "profile",
        "code",
        "code_stdin",
        "oauth_token",
        "client_id",
        "client_secret",
        "login",
        "start_pkce",
    )
    browser_options = (
        "source",
        "profile_dir",
        "chrome_profile",
        "timeout_seconds",
        "allow_no_tty",
        "headful",
        "no_verify",
    )
    explicit_api = any(
        ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE
        for name in api_options
    )
    explicit_browser = any(
        ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE
        for name in browser_options
    )
    interactive = (
        output_format == "text"
        and code != "-"
        and not code_stdin
        and _should_prompt_save_env()
    )
    if explicit_browser and method != "browser":
        raise click.UsageError(t("Browser options require --method browser."))
    if method == "browser" and explicit_api:
        raise click.UsageError(
            t("API options cannot be combined with --method browser.")
        )
    canonical = method is not None
    if method is None and not explicit_api and interactive:
        click.echo(t("1) API — campaigns, ads, reports"))
        click.echo(t("2) Browser — Campaign Wizard, change history"))
        choice = click.prompt(t("Choose login method"), type=click.Choice(["1", "2"]))
        method = "api" if choice == "1" else "browser"
        canonical = True
    if method == "browser":
        if source == "chrome":
            if (
                allow_no_tty
                or ctx.get_parameter_source("timeout_seconds")
                is ParameterSource.COMMANDLINE
            ):
                raise click.UsageError(
                    t("--timeout and --allow-no-tty require --source manual.")
                )
            import_browser_session(
                profile_dir, chrome_profile, headful, no_verify, output_format, None
            )
        else:
            if (
                headful
                or no_verify
                or ctx.get_parameter_source("chrome_profile")
                is ParameterSource.COMMANDLINE
            ):
                raise click.UsageError(
                    t("Chrome import options require --source chrome.")
                )
            browser_login(profile_dir, timeout_seconds, allow_no_tty, output_format)
        return
    auto_profile = canonical and not explicit_api and interactive
    if auto_profile:
        profiles = list_profiles()
        if profiles:
            for index, item in enumerate(profiles, start=1):
                account = f" (login={item['login']})" if item.get("login") else ""
                click.echo(f"{index}) {item['profile']}{account}")
            click.echo(t("0) Log in to a new API account"))
            profile_choice = click.prompt(
                t("Choose a profile"), type=click.IntRange(0, len(profiles))
            )
            if profile_choice:
                bind_profile_to_dotenv(profiles[profile_choice - 1]["profile"])
                return
    chosen_client_id = client_id or DEFAULT_OAUTH_CLIENT_ID
    code_from_stdin = False

    if code_stdin:
        if code or oauth_token or start_pkce:
            raise click.ClickException(
                "--code-stdin cannot be combined with --code, "
                "--oauth-token, or --start-pkce."
            )
        code = "-"

    if code == "-":
        if oauth_token or start_pkce:
            raise click.ClickException(
                "--code - cannot be combined with --oauth-token or --start-pkce."
            )
        code = sys.stdin.read().strip()
        if not code:
            raise click.ClickException("--code - requires a code on stdin.")
        code_from_stdin = True

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
            login = resolve_account_login(token)
        save_oauth_profile(
            profile=profile,
            token=token,
            login=login,
            source="manual",
        )
        if canonical and interactive:
            bind_credentials_to_dotenv(profile, token, login)
        else:
            _offer_save_token_to_env(token, login)
        print_success(
            t("Profile '{profile}' is saved and active.").format(profile=profile)
        )
        return

    code_verifier = None
    auth_code = code
    effective_client_id = chosen_client_id
    effective_client_secret = client_secret

    if not auth_code:
        if not _stdin_is_interactive() or output_format == "json":
            _start_noninteractive_auth(
                profile=profile,
                client_id=chosen_client_id,
                client_secret=client_secret,
                login=login,
                output_format=output_format,
            )
            return

        auth_code, code_verifier = _prompt_authorize_code(
            client_id=chosen_client_id,
            client_secret=client_secret,
            open_browser=canonical,
        )
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
            remembered_profile = get_oauth_profile(profile) or {}
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
        login = resolve_account_login(access_token)
    if auto_profile:
        names = {item["profile"] for item in list_profiles()}
        base = login or "default"
        profile = base
        index = 2
        while profile in names:
            profile = f"{base}-{index}"
            index += 1
    save_oauth_profile(
        profile=profile,
        token=access_token,
        login=login,
        refresh_token=token_response["refresh_token"],
        expires_at=time.time() + token_response["expires_in"],
        client_id=effective_client_id,
        client_secret=effective_client_secret,
        make_active=not auto_profile,
    )
    remove_pending_pkce(profile)
    if canonical and interactive and not code_from_stdin:
        bind_credentials_to_dotenv(profile, access_token, login)
    else:
        _offer_save_token_to_env(access_token, login, allow_prompt=not code_from_stdin)
    if auto_profile:
        print_success(t("Profile '{profile}' is saved.").format(profile=profile))
    else:
        print_success(
            t("Profile '{profile}' is saved and active.").format(profile=profile)
        )


@auth.command(name="list")
def list_command():
    """List available auth profiles without exposing secrets."""
    profiles = list_profiles()
    if not profiles:
        print_info(t("No profiles configured."))
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
    print_success(t("Active profile is '{profile}'.").format(profile=profile))


@auth.command()
@click.option("--profile", required=True, help="Profile name to bind this folder to")
def write(profile):
    """Bind this folder to a profile by writing the cwd .env file."""
    bind_profile_to_dotenv(profile)


@auth.command()
@click.option(
    "--method",
    type=click.Choice(["api", "browser", "all"]),
    default="api",
    show_default=True,
    help="Authorization method",
)
@click.option("--profile", help="Profile name (otherwise show effective credentials)")
@click.option(
    "--profile-dir",
    type=click.Path(file_okay=False),
    help="Saved browser profile directory",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    show_default=True,
    help="Output format",
)
@click.pass_context
def status(
    ctx: click.Context,
    method: str,
    profile: Optional[str],
    profile_dir: Optional[str],
    output_format: str,
) -> None:
    """Show API authorization, browser authorization, or both."""
    if method == "api" and profile_dir:
        raise click.UsageError(t("--profile-dir requires --method browser or all."))
    if method == "browser" and profile:
        raise click.UsageError(
            t("--profile selects an API profile, not a browser session.")
        )
    if method == "api":
        payload = api_status(ctx, profile)
    else:
        from ..browser.auth import session_status

        browser = session_status(Path(profile_dir) if profile_dir else None)
        if method == "browser":
            payload = browser
        else:
            payload = {"api": api_status(ctx, profile), "browser": browser}
    if output_format == "json":
        click.echo(json.dumps(payload, ensure_ascii=False))
    elif method == "api":
        _print_api_status(payload)
    elif method == "browser":
        _print_browser_status(payload)
    else:
        click.echo("API:")
        _print_api_status(payload["api"])
        click.echo(t("Browser:"))
        _print_browser_status(payload["browser"])


def api_status(ctx: click.Context, profile: Optional[str]) -> Dict[str, Any]:
    """Return the legacy API status shape without printing secrets."""
    load_env_file()
    root_obj = ctx.find_root().obj or ctx.obj or {}
    selected = profile or root_obj.get("profile")
    # True when the profile was reached via the global active-profile
    # fallback — only possible under the #904 opt-in env; then the
    # credentials are inherited, not bound to this folder.
    inherited_profile = False
    if not selected:
        root_token = root_obj.get("token")
        if root_token:
            return _api_status_payload(
                profile_name=None,
                source="args",
                login_value=root_obj.get("login"),
                expires_at=None,
            )
        env_token = os.getenv("YANDEX_DIRECT_TOKEN")
        env_login = os.getenv("YANDEX_DIRECT_LOGIN")
        if env_token:
            return _api_status_payload(
                profile_name=None,
                source="env",
                login_value=env_login,
                expires_at=None,
            )
        active = get_active_profile()
        if active and not inherit_globally_enabled():
            # #904: the global active profile is not a credential source
            # without the opt-in — report no binding plus a note.
            return {
                "profile": None,
                "source": None,
                "has_token": False,
                "login": None,
                "global_profile": active,
                "global_login": (get_oauth_profile(active) or {}).get("login"),
            }
        selected = active
        inherited_profile = True
    if not selected:
        op_token_ref = root_obj.get("op_token_ref") or os.getenv(
            "YANDEX_DIRECT_OP_TOKEN_REF"
        )
        if op_token_ref:
            try:
                token_value = op_read(op_token_ref)
                op_login_ref = root_obj.get("op_login_ref") or os.getenv(
                    "YANDEX_DIRECT_OP_LOGIN_REF"
                )
                login_value = op_read(op_login_ref) if op_login_ref else None
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc
            if token_value:
                return _api_status_payload(
                    profile_name=None,
                    source="op",
                    login_value=login_value,
                    expires_at=None,
                )

        bw_token_ref = root_obj.get("bw_token_ref") or os.getenv(
            "YANDEX_DIRECT_BW_TOKEN_REF"
        )
        if bw_token_ref:
            try:
                token_value = bw_read(bw_token_ref, "password")
                bw_login_ref = root_obj.get("bw_login_ref") or os.getenv(
                    "YANDEX_DIRECT_BW_LOGIN_REF"
                )
                login_value = (
                    bw_read(bw_login_ref, "username") if bw_login_ref else None
                )
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc
            if token_value:
                return _api_status_payload(
                    profile_name=None,
                    source="bw",
                    login_value=login_value,
                    expires_at=None,
                )

        return {"profile": None, "source": None, "has_token": False, "login": None}

    oauth_profile = get_oauth_profile(selected)
    env_token, env_login = get_env_profile(selected)

    if oauth_profile:
        stored_source = oauth_profile.get("source") or "oauth"
        if stored_source == "oauth":
            try:
                validate_oauth_profile(selected, oauth_profile)
            except ValueError as exc:
                raise click.ClickException(str(exc)) from exc
        login_value = oauth_profile.get("login")
        source = "global-profile-inherited" if inherited_profile else stored_source
        if not login_value and env_login:
            login_value = env_login
            if not inherited_profile:
                source = "oauth+env"
    elif env_token:
        source = "global-profile-inherited" if inherited_profile else "env"
        login_value = env_login
    else:
        raise click.ClickException(f"Profile '{selected}' is not configured.")

    expires_at = None
    if oauth_profile and isinstance(oauth_profile.get("expires_at"), (int, float)):
        expires_at = float(oauth_profile["expires_at"])

    return _api_status_payload(
        profile_name=selected,
        source=source,
        login_value=login_value,
        expires_at=expires_at,
    )


def _api_status_payload(
    profile_name: Optional[str],
    source: str,
    login_value: Optional[str],
    expires_at: Optional[float],
) -> Dict[str, Any]:
    """Build the compatible API status payload."""
    payload: Dict[str, Any] = {
        "profile": profile_name,
        "source": source,
        "has_token": True,
        "login": login_value,
    }
    if expires_at is not None:
        payload["expires_at"] = expires_at
        payload["expires_in_seconds"] = max(0, int(expires_at - time.time()))
    return payload


def _print_api_status(payload: Dict[str, Any]) -> None:
    """Render the legacy text status, including the unbound-folder note."""
    if not payload["has_token"]:
        if "global_profile" not in payload:
            print_info(t("No active profile."))
            return
        print_info(t("No credentials bound to this folder."))
        click.echo(
            t(
                "Global profile '{name}' (login={login}) exists but is not bound here."
            ).format(
                name=payload["global_profile"],
                login=payload["global_login"] or "(not set)",
            )
        )
        print_info(
            t(
                "Bind this folder via a .env file (YANDEX_DIRECT_TOKEN) or --profile, or set {env}=1 to use the global profile."
            ).format(env=INHERIT_GLOBAL_ENV)
        )
        return
    click.echo(f"profile={payload['profile'] or '(none)'}")
    click.echo(f"source={payload['source']}")
    click.echo("has_token=yes")
    click.echo(f"login={payload['login'] or '(not set)'}")
    if "expires_in_seconds" in payload:
        click.echo(f"expires_in={_format_duration(payload['expires_in_seconds'])}")


def _offer_save_token_to_env(
    token: str, login: Optional[str], allow_prompt: bool = True
) -> None:
    """Ask interactive users whether to store the access token in cwd .env."""
    if not allow_prompt:
        return
    if not _should_prompt_save_env():
        return
    if not click.confirm(t("Save token to .env?"), default=False):
        return
    save_env_credentials(token=token, login=login)
    print_success(t("Saved token to .env."))


def _should_prompt_save_env() -> bool:
    """Return whether it is safe to ask an extra interactive question."""
    return sys.stdin.isatty() and sys.stdout.isatty()


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
    """Return whether both streams belong to the terminal for a login dialog."""
    return sys.stdin.isatty() and sys.stdout.isatty()


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
    print_info(t("Open this URL and grant access:"))
    click.echo(auth_url)


def _start_pkce_required_message(profile: str) -> str:
    return (
        "Missing or expired pending PKCE state. "
        f"Run direct auth login --profile {profile} first."
    )


_BROWSER_INSTALL_HINT = (
    'pip install "direct-cli[browser]" && playwright install chromium'
)


def legacy_auth_warning(replacement: str) -> None:
    """Keep compatibility notices out of machine-readable stdout."""
    click.echo(
        t("Deprecated auth command; use {command}.").format(command=replacement),
        err=True,
    )


def browser_login(
    profile_dir: Optional[str],
    timeout_seconds: int,
    allow_no_tty: bool,
    output_format: str = "text",
) -> None:
    """Run the existing persistent-browser login with a shared terminal guard."""
    if not _stdin_is_interactive() and not allow_no_tty:
        raise click.ClickException(
            t(
                "Browser login needs an interactive terminal. Run "
                "`direct auth login --method browser` in a terminal "
                "(override: --allow-no-tty)."
            )
        )
    try:
        from ..browser.session import BrowserSessionError, login_persistent_session
    except ImportError as exc:
        raise click.UsageError(
            t("playwright is required for browser login. Run: {install}").format(
                install=_BROWSER_INSTALL_HINT
            )
        ) from exc
    try:
        login_persistent_session(
            profile_dir=Path(profile_dir) if profile_dir else None,
            timeout_ms=timeout_seconds * 1000,
        )
    except (BrowserSessionError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if output_format == "json":
        click.echo(json.dumps({"saved": True, "source": "manual"}))
    else:
        print_info(t("Login confirmed. Browser commands will now reuse this session."))


def browser_logout_persistent(profile_dir: Optional[str]) -> None:
    """Compatibility exit: forget only the persistent Chromium profile."""
    from ..browser.auth import logout_persistent_profile
    from ..browser.session import BrowserSessionError, configured_persistent_profile_dir

    target = Path(profile_dir) if profile_dir else configured_persistent_profile_dir()
    try:
        removed = logout_persistent_profile(target)
    except (BrowserSessionError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    if removed:
        print_info(
            t("Deleted persistent browser profile at {path}").format(path=target)
        )
    else:
        print_warning(
            t("No persistent browser profile found at {path}").format(path=target)
        )


def _print_browser_status(payload: Dict[str, Any]) -> None:
    """Keep the existing browser status text format."""
    persistent = payload["persistent_profile"]
    saved = payload["saved_session"]
    click.echo(f"active_tier={payload['active_tier']} ({payload['active_source']})")
    click.echo(
        f"persistent_profile: path={persistent['path']} usable={persistent['usable']}"
    )
    click.echo(
        f"saved_session: exists={saved['exists']} expired={saved['expired']} cookie_count={saved['cookie_count']} path={saved['path']}"
    )
    if saved["error"]:
        click.echo(f"  error: {saved['error']}")


def browser_status(
    profile_dir: Optional[str], output_format: str, output: Optional[str]
) -> None:
    """Render a saved browser status for legacy and canonical auth commands."""
    from ..browser.auth import session_status

    payload = session_status(Path(profile_dir) if profile_dir else None)
    if output_format == "text":
        _print_browser_status(payload)
    else:
        format_output(payload, output_format, output)


def _browser_options(func: Callable[..., Any]) -> Callable[..., Any]:
    """Chrome import source options shared with compatibility commands."""
    func = click.option(
        "--chrome-profile",
        default="Default",
        help="Chrome profile subdirectory to read cookies from (e.g. 'Profile 1')",
    )(func)
    return click.option(
        "--profile-dir", help="Chrome user-data-dir to read cookies from"
    )(func)


def import_browser_session(
    profile_dir: Optional[str],
    chrome_profile: str,
    headful: bool,
    no_verify: bool,
    output_format: str,
    output: Optional[str],
) -> None:
    """Explicitly import Chrome cookies and persist the existing session format."""
    from ..browser import store
    from ..browser.session import BrowserSessionError

    try:
        from ..browser.session import capture_storage_state
    except ImportError as exc:
        raise click.UsageError(
            t("playwright is required for browser login. Run: {install}").format(
                install=_BROWSER_INSTALL_HINT
            )
        ) from exc

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
        # Did the live check actually PASS (issue #870): False also for
        # --no-verify runs and for the save-without-verification path the
        # render-timeout fallback takes, so scripts can tell a verified
        # session from a merely saved one. Default False, never True: an
        # unknown verification state must not read as verified (#692).
        "verified": bool(source_meta.get("verified", False)),
        "mode": status["mode"],
    }

    if output_format == "json":
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if output_format == "text":
        print_success(t("Saved browser session to {path}").format(path=saved_path))
        click.echo(f"saved={payload['saved']}")
        click.echo(f"cookies={payload['cookies']}")
        click.echo(f"domains={', '.join(domains)}")
        click.echo(f"verified={'yes' if payload['verified'] else 'no'}")
        click.echo(f"mode={payload['mode']}")
        return

    format_output(payload, output_format, output)


def doctor_browser(
    profile_dir: Optional[str],
    chrome_profile: str,
    output_format: str,
    output: Optional[str],
) -> None:
    """Inspect browser dependencies and saved authorization without Keychain."""
    from ..browser.diagnostics import run_diagnostics

    checks = run_diagnostics(
        profile_dir=Path(profile_dir) if profile_dir else None,
        chrome_profile=chrome_profile,
    )
    overall_ok = all(c.ok is not False for c in checks)

    if output_format == "json":
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

    format_output(
        [
            {"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint}
            for c in checks
        ],
        output_format,
        output,
    )


@auth.command()
@_browser_options
@reference_output_options
def doctor(
    profile_dir: Optional[str],
    chrome_profile: str,
    output_format: str,
    output: Optional[str],
) -> None:
    """Diagnose browser authorization without logging in or reading Keychain."""
    doctor_browser(profile_dir, chrome_profile, output_format, output)


@auth.command()
@click.option(
    "--method",
    type=click.Choice(["api", "browser"]),
    required=True,
    help="Authorization method",
)
@click.option("--profile", help="Local API profile to remove")
def logout(method: str, profile: Optional[str]) -> None:
    """Forget local API credentials or both saved browser sessions."""
    try:
        if method == "browser":
            if profile:
                raise click.UsageError(
                    t("--profile selects an API profile, not a browser session.")
                )
            from ..browser.auth import logout as logout_browser
            from ..browser.session import BrowserSessionError

            try:
                logout_browser()
            except BrowserSessionError as exc:
                raise click.ClickException(str(exc)) from exc
            print_success(t("Saved browser authorization removed."))
            return
        if not profile:
            raise click.UsageError(
                t("API logout requires --profile to select the profile to remove.")
            )
        store = load_auth_store()
        if profile not in store["profiles"]:
            raise click.ClickException(
                t("No local API profile named '{profile}'.").format(profile=profile)
            )
        save_env_credentials(token=None)
        del store["profiles"][profile]
        store["pending_pkce"].pop(profile, None)
        if store["active_profile"] == profile:
            store["active_profile"] = None
        save_auth_store(store)
        for name in FOLDER_CREDENTIAL_KEYS:
            os.environ.pop(name, None)
        print_success(
            t("API profile '{profile}' and this folder's binding removed.").format(
                profile=profile
            )
        )
        print_info(
            t("Token copies in other folders or external environments are not revoked.")
        )
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

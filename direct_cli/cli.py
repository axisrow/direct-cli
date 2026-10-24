#!/usr/bin/env python
"""
Direct CLI - Command-line interface for Yandex Direct API
"""

import os
import sys
import time
from typing import TYPE_CHECKING, Optional, Tuple

import click
from click.core import ParameterSource

from . import __version__
from .auth import (
    DEFAULT_OAUTH_CLIENT_ID,
    INHERIT_GLOBAL_ENV,
    exchange_oauth_code,
    get_active_profile,
    get_credentials_with_source,
    inherit_globally_enabled,
    list_profiles,
    load_env_file,
    resolve_account_login,
    save_env_credentials,
    save_oauth_profile,
)
from .i18n import (
    LOCALE_ENV_VAR,
    LocalizedOption,
    resolve_locale,
    set_active_locale,
    t,
)
from .output import print_info
from .utils import get_docs_url

from .commands.campaigns import campaigns
from .commands.adgroups import adgroups
from .commands.ads import ads
from .commands.keywords import keywords
from .commands.keywordbids import keywordbids
from .commands.bids import bids
from .commands.bidmodifiers import bidmodifiers
from .commands.audiencetargets import audiencetargets
from .commands.retargeting import retargeting
from .commands.creatives import creatives
from .commands.adimages import adimages
from .commands.adextensions import adextensions
from .commands.sitelinks import sitelinks
from .commands.vcards import vcards
from .commands.leads import leads
from .commands.clients import clients
from .commands.agencyclients import agencyclients
from .commands.dictionaries import dictionaries
from .commands.trackingparams import tracking_params
from .commands.changes import changes
from .commands.reports import reports
from .commands.turbopages import turbopages
from .commands.negativekeywordsharedsets import negativekeywordsharedsets
from .commands.feeds import feeds
from .commands.smartadtargets import smartadtargets
from .commands.businesses import businesses
from .commands.keywordsresearch import keywordsresearch
from .commands.dynamicads import dynamicads
from .commands.advideos import advideos
from .commands.dynamicfeedadtargets import dynamicfeedadtargets
from .commands.strategies import strategies
from .commands.auth import auth
from .commands.balance import balance
from .commands.v4events import v4events
from .commands.v4forecast import v4forecast
from .commands.v4finance import v4finance
from .commands.v4account import v4account
from .commands.v4shells import v4meta
from .commands.v4goals import v4goals
from .commands.v4tags import v4tags
from .commands.v4wordstat import v4wordstat
from .commands.v4keywords import v4keywords
from .commands.v4adimage import v4adimage
from .commands.masters import masters
from .commands.history import history
from .commands.ad_elements import ad_elements
from .commands.browser_session import playwright_group

# Load .env file
load_env_file()


# Groups that need no Yandex Direct credentials at all: `auth` manages
# credentials themselves, `playwright` manages a separate browser-cookie
# session (see direct_cli/commands/browser_session.py), and `masters` reads
# Мастер кампаний for the logged-in browser session's own account only (no
# agency/managed-client support, see direct_cli/browser/masters.py module
# docstring -- issue #639 found that passing a login as `?ulogin=` there
# actually broke access with HTTP 401). `history` is browser-backed the same
# way (issue #837): «История изменений» has no API surface, and its data call
# authorizes off the browser session, not off a token. So is `adrestrictions`
# (issue #892): the banners grid's own data calls authorize off the browser
# session too. None of these read ctx.obj["token"] or ctx.obj["login"].
_NO_CREDENTIALS_GROUPS = ("auth", "playwright", "masters", "history", "adrestrictions")


CLI_EPILOG = """\b
Credential context:
  --login / YANDEX_DIRECT_LOGIN selects the Yandex Direct Client-Login.
  Use direct auth status to inspect the selected credentials.

\b
API errors:
  Item-level Yandex Direct Errors are reported as command failures.
  Error 8800 usually means the object is not available under the current
  Client-Login/account.
"""


def _command_line_option_value(ctx, name, value):
    """Return only values explicitly supplied on the command line."""
    if ctx.get_parameter_source(name) is ParameterSource.COMMANDLINE:
        return value
    return None


def _command_has_option(cmd: click.Command, option_name: str) -> bool:
    """Whether *cmd* declares *option_name* among its Click options.

    Searches both ``opts`` (e.g. ``--send-warnings``) and ``secondary_opts``
    (e.g. ``--no-send-warnings`` for ``--foo/--no-foo`` style switches), and
    includes hidden options — so `keywords update`'s hidden deprecated traps
    still count as "having" `--bid` and won't be advertised as siblings.
    """
    return any(
        isinstance(param, click.Option)
        and (option_name in param.opts or option_name in param.secondary_opts)
        for param in cmd.params
    )


def _interactive_streams() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _bind_hints() -> str:
    """Shared hint text for refusals in folders with no bound credentials."""
    return t(
        "No credentials bound to this folder. Run `direct auth login`, bind "
        "this folder via a .env file (YANDEX_DIRECT_TOKEN), pass --profile, "
        f"or set {INHERIT_GLOBAL_ENV}=1 to use the global active profile."
    )


def _authorize_new_profile(profile_name: str) -> Tuple[str, Optional[str]]:
    """Run the interactive OAuth flow and store it as *profile_name*.

    Mirrors `direct auth login`'s interactive path (authorize URL + code
    prompt + exchange) without its non-interactive branches — this helper is
    only ever called from the TTY bind menu.
    """
    from .commands.auth import _build_interactive_authorize_url

    auth_url, code_verifier = _build_interactive_authorize_url(
        client_id=DEFAULT_OAUTH_CLIENT_ID,
        client_secret=None,
    )
    print_info(t("Open this URL and grant access:"))
    click.echo(auth_url)
    auth_code = click.prompt(t("Enter OAuth code"), type=str).strip()
    token_response = exchange_oauth_code(
        code=auth_code,
        client_id=DEFAULT_OAUTH_CLIENT_ID,
        code_verifier=code_verifier,
    )
    access_token = token_response["access_token"]
    login_value = resolve_account_login(access_token)
    save_oauth_profile(
        profile=profile_name,
        token=access_token,
        login=login_value,
        refresh_token=token_response.get("refresh_token"),
        expires_at=time.time() + token_response["expires_in"],
        client_id=DEFAULT_OAUTH_CLIENT_ID,
    )
    return access_token, login_value


def _bind_folder_interactively(ctx: click.Context) -> None:
    """Bind this folder to credentials chosen by the user (#904).

    Offers the existing profiles, or a fresh interactive OAuth login, and
    persists the choice to the cwd `.env` so the question never comes back
    for this folder. A cancellation exits with binding hints.
    """
    profiles = list_profiles()
    if profiles:
        click.echo(t("No credentials bound to this folder. Available profiles:"))
        for index, item in enumerate(profiles, start=1):
            login_display = item.get("login") or "(not set)"
            active_mark = " [active]" if item.get("active") else ""
            click.echo(
                t("  {index}) {profile} (login={login}){mark}").format(
                    index=index,
                    profile=item["profile"],
                    login=login_display,
                    mark=active_mark,
                )
            )
        choice_hint = t(
            "Select a profile number to bind this folder to it via .env, "
            "'login' to authorize a new profile, or 'cancel':"
        )
    else:
        click.echo(
            t(
                "No credentials bound to this folder and no profiles are "
                "configured yet."
            )
        )
        choice_hint = t("Type 'login' to authorize a new profile, or 'cancel':")

    while True:
        choice = click.prompt(choice_hint, type=str).strip().lower()
        if choice in ("c", "cancel"):
            raise click.UsageError(_bind_hints())
        if choice in ("l", "login"):
            profile_name = click.prompt(
                t("New profile name"), default="default", type=str
            ).strip()
            try:
                token, login_value = _authorize_new_profile(profile_name)
            except RuntimeError as error:
                raise click.ClickException(str(error)) from error
            break
        if profiles and choice.isdigit() and 1 <= int(choice) <= len(profiles):
            profile_name = profiles[int(choice) - 1]["profile"]
            try:
                token, login_value = get_credentials_with_source(
                    profile=profile_name,
                    allow_login_resolve=False,
                )[:2]
            except (RuntimeError, ValueError) as error:
                raise click.ClickException(str(error)) from error
            break
        click.echo(t("Enter a profile number, 'login', or 'cancel'."))

    if not click.confirm(
        t(
            "Save these credentials to the .env file in the current folder? "
            f"(or set {INHERIT_GLOBAL_ENV}=1 globally instead)"
        ),
        default=True,
    ):
        raise click.UsageError(_bind_hints())
    save_env_credentials(token=token, login=login_value)
    load_env_file()
    click.echo(t("Bound credentials to .env."))


def _ensure_credentials_bound(ctx: click.Context) -> None:
    """Refuse to run with no bound credentials unless the user binds now (#904).

    A folder with no explicit binding (cwd `.env`, `--profile`, base env) has
    no credentials of its own — the global active profile is no longer
    inherited silently. Interactive sessions get a bind menu (pick a profile
    or authorize a new one, saved to the cwd `.env`); non-interactive
    sessions fail closed with binding hints. `--dry-run` never touches the
    API and needs no credentials, so it stays silent. Opt back into the old
    inheritance with `YANDEX_DIRECT_INHERIT_GLOBAL=1`.
    """
    if inherit_globally_enabled():
        return
    if ctx.params.get("dry_run"):
        return
    obj = ctx.obj or {}
    if obj.get("credential_gate") is False or obj.get("token"):
        return
    if not _interactive_streams():
        raise click.UsageError(_bind_hints())
    _bind_folder_interactively(ctx)
    token, login_value, credential_source = get_credentials_with_source(
        allow_login_resolve=False
    )
    obj["token"] = token
    obj["login"] = login_value
    obj["credential_source"] = credential_source
    obj["credential_profile"] = None


def _augment_no_such_option(
    exc: click.exceptions.NoSuchOption, ctx: click.Context
) -> Optional[click.exceptions.NoSuchOption]:
    """Return a NoSuchOption error with a cross-command hint appended.

    For `direct <group> <cmd> --bad-flag`, finds sibling subcommands of
    `<group>` that declare `--bad-flag` and tells the user where to use
    it instead. When no sibling matches, points at `--help`. Returns None
    when Click's default error should be kept.
    """
    parent = ctx.parent
    if parent is None or parent.command is None:
        return None  # Unknown option on the root group — leave Click's default.

    group = parent.command
    if not isinstance(group, click.Group):
        return None

    bad = exc.option_name
    siblings = sorted(
        name
        for name, sibling in group.commands.items()
        if name != ctx.info_name and _command_has_option(sibling, bad)
    )
    group_path = parent.command_path  # e.g. "direct ads" (leaf) or "direct" (group)
    current_path = ctx.command_path  # e.g. "direct ads update" or "direct ads"

    if siblings:
        sibling_paths = " or ".join(f"`{group_path} {name}`" for name in siblings)
        hint = (
            f"Hint: {bad} is accepted by {sibling_paths}, not by `{current_path}`. "
            f"This usually means the Yandex Direct API does not expose that "
            f"field on the selected operation. Run `{current_path} --help` to "
            f"see available flags."
        )
    else:
        hint = f"Run `{current_path} --help` to see available flags."

    # Fold the "Did you mean..." suggestion into the message now and leave
    # `possibilities` empty so Click's NoSuchOption.format_message() does not
    # re-append it after the Hint on print.
    return click.exceptions.NoSuchOption(
        bad, message=f"{exc.format_message()}\n\n{hint}", ctx=exc.ctx
    )


if TYPE_CHECKING:
    # The mixins below are only ever combined with click.Command/Group;
    # tell the type checker what ``super()``/``self`` resolve to.
    _CommandBase = click.Command
else:
    _CommandBase = object


class _NoSuchOptionHintMixin(_CommandBase):
    """Mixin that augments NoSuchOption errors raised by ``parse_args``."""

    def parse_args(self, ctx, args):
        try:
            return super().parse_args(ctx, args)
        except click.exceptions.NoSuchOption as exc:
            augmented = _augment_no_such_option(exc, ctx)
            if augmented is None:
                raise
            raise augmented from exc


class _LocalizedHelpMixin(_CommandBase):
    """Mixin that localizes a command/group docstring at render time.

    The English docstring (``self.help``) is the catalog key; the resolved-locale
    text is substituted while Click formats help and restored afterwards so the
    source key stays stable. ``format_help_text`` also primes the process-wide
    active locale so the short-help lines that Click renders next (via
    context-free ``get_short_help_str``) use the same locale.
    """

    def format_help_text(self, ctx, formatter):
        set_active_locale(resolve_locale(ctx))
        if self.help:
            original = self.help
            self.help = t(self.help, resolve_locale(ctx))
            try:
                super().format_help_text(ctx, formatter)
            finally:
                self.help = original
            return
        super().format_help_text(ctx, formatter)

    def get_short_help_str(self, limit=45):
        if self.help:
            original = self.help
            self.help = t(self.help)
            try:
                return super().get_short_help_str(limit)
            finally:
                self.help = original
        return super().get_short_help_str(limit)


class DirectCliCommand(_LocalizedHelpMixin, _NoSuchOptionHintMixin, click.Command):
    """Click Command that localizes help and augments NoSuchOption errors."""

    def invoke(self, ctx):
        # Every leaf command funnels through here, after parsing (params are
        # final) and before any command body runs — the one tree-wide point
        # for the credential-binding gate (#904).
        _ensure_credentials_bound(ctx)
        return super().invoke(ctx)


class DirectCliGroup(_LocalizedHelpMixin, _NoSuchOptionHintMixin, click.Group):
    """Click Group that retypes descendants, localizes help, and augments
    NoSuchOption on the group itself (e.g. `direct ads --bogus get`)."""

    command_class = DirectCliCommand

    def format_epilog(self, ctx, formatter):
        """Render a locale-aware epilog.

        A group may set ``i18n_epilog_text`` (an English source string in the
        catalog) and, optionally, ``i18n_epilog_suffix`` (an already-built tail
        appended verbatim so single-sourced text such as ``V4_EPILOG`` — which
        carries a registry-owned docs URL — is not copied into translations).
        Otherwise any plain ``self.epilog`` is translated by source string,
        a no-op when it has no catalog entry (e.g. ``Documentation: <url>``).
        """
        original = self.epilog
        text_source = getattr(self, "i18n_epilog_text", None)
        if text_source is not None:
            translated = t(text_source, resolve_locale(ctx))
            suffix = getattr(self, "i18n_epilog_suffix", None)
            self.epilog = f"{translated}\n\n{suffix}" if suffix else translated
        elif self.epilog:
            self.epilog = t(self.epilog, resolve_locale(ctx))
        try:
            super().format_epilog(ctx, formatter)
        finally:
            # Restore the English source so repeated renders (and a later
            # render in another locale) translate from the original, not from
            # an already-translated string.
            self.epilog = original


def _localize_options(command: click.Command) -> None:
    """Retype every plain ``click.Option`` on *command* to ``LocalizedOption``.

    This is the i18n counterpart to the command retyping below: modules declare
    options with plain ``@click.option(..., help="English")`` and the English
    help is localized at render time without any ``cls=``/``help_key`` edits.
    The exact-type check leaves custom option subclasses untouched, mirroring
    the command retyping rationale.
    """
    for param in command.params:
        if type(param) is click.Option:  # noqa: PIE789 — see docstring
            param.__class__ = LocalizedOption


def _apply_directcli_classes(command: click.Command) -> None:
    """Recursively retype *command* (and subcommands) so every node in the
    tree intercepts NoSuchOption and localizes help/options.

    Subcommand modules use plain ``@click.group()`` / ``@click.command()``
    without ``cls=`` and plain ``@click.option(...)`` without ``cls=``. Rather
    than touch 41 command files, we mutate ``__class__`` after registration. The
    identity check (``type(...) is`` rather than ``isinstance``) is deliberate:
    a contributor who registers a command/option with a custom subclass is
    opting out of the hint, not into silent retyping that would discard their
    behaviour.
    """
    _localize_options(command)
    if isinstance(command, click.Group):
        if type(command) is click.Group:  # noqa: PIE789 — see docstring
            command.__class__ = DirectCliGroup
        for subcommand in command.commands.values():
            _apply_directcli_classes(subcommand)
    elif type(command) is click.Command:  # noqa: PIE789 — see docstring
        command.__class__ = DirectCliCommand


def _set_locale_eager(ctx, param, value):
    """Stash and prime the locale during parsing, before any eager ``--help``.

    ``--help``/``--version`` are eager and can render (and short-circuit) before
    the group callback runs, so without this the root ``--help`` epilog would
    ignore an inline ``--locale``. Making ``--locale`` eager and storing it on
    the context lets ``resolve_locale`` find it during help rendering. The value
    is returned unchanged so the group callback still receives it.
    """
    if value:
        ctx.ensure_object(dict)
        ctx.obj["locale"] = value
        set_active_locale(resolve_locale(ctx))
    return value


@click.group(name="direct", cls=DirectCliGroup, epilog=CLI_EPILOG)
@click.version_option(__version__, prog_name="direct")
@click.option("--token", envvar="YANDEX_DIRECT_TOKEN", help="API access token")
@click.option("--login", envvar="YANDEX_DIRECT_LOGIN", help="Client login")
@click.option("--profile", help="Credential profile name")
@click.option("--sandbox", is_flag=True, help="Use sandbox API")
@click.option(
    "--locale",
    envvar=LOCALE_ENV_VAR,
    default=None,
    is_eager=True,
    callback=_set_locale_eager,
    help="Language for help and messages (ru or en; default: ru)",
)
@click.option(
    "--op-token-ref",
    envvar="YANDEX_DIRECT_OP_TOKEN_REF",
    help="1Password secret reference for token (e.g. op://vault/item/token)",
)
@click.option(
    "--op-login-ref",
    envvar="YANDEX_DIRECT_OP_LOGIN_REF",
    help="1Password secret reference for login",
)
@click.option(
    "--bw-token-ref",
    envvar="YANDEX_DIRECT_BW_TOKEN_REF",
    help="Bitwarden item name/ID for token (reads password field)",
)
@click.option(
    "--bw-login-ref",
    envvar="YANDEX_DIRECT_BW_LOGIN_REF",
    help="Bitwarden item name/ID for login (reads username field)",
)
@click.pass_context
def cli(
    ctx,
    token,
    login,
    profile,
    sandbox,
    locale,
    op_token_ref,
    op_login_ref,
    bw_token_ref,
    bw_login_ref,
):
    """Command-line interface for Yandex Direct API"""
    ctx.ensure_object(dict)
    ctx.obj["sandbox"] = sandbox
    ctx.obj["profile"] = profile
    ctx.obj["locale"] = locale
    # Prime the process-wide locale so print_* runtime messages localize even
    # where no Click context is threaded through. Help rendering re-primes from
    # its own context (see _LocalizedHelpMixin.format_help_text).
    set_active_locale(resolve_locale(ctx))
    active_profile = None
    if (
        ctx.invoked_subcommand not in _NO_CREDENTIALS_GROUPS
        and inherit_globally_enabled()
    ):
        # The global active profile is a credential source only under the
        # #904 opt-in; otherwise a folder with no explicit binding has no
        # credentials at all (the bind gate runs per leaf command).
        active_profile = get_active_profile()

    explicit_token = _command_line_option_value(ctx, "token", token)
    explicit_login = _command_line_option_value(ctx, "login", login)
    if (
        explicit_login is None
        and active_profile is None
        and not profile
        and ctx.get_parameter_source("login") is ParameterSource.ENVIRONMENT
    ):
        explicit_login = login
    explicit_op_token_ref = _command_line_option_value(
        ctx, "op_token_ref", op_token_ref
    )
    explicit_op_login_ref = _command_line_option_value(
        ctx, "op_login_ref", op_login_ref
    )
    explicit_bw_token_ref = _command_line_option_value(
        ctx, "bw_token_ref", bw_token_ref
    )
    explicit_bw_login_ref = _command_line_option_value(
        ctx, "bw_login_ref", bw_login_ref
    )
    if ctx.invoked_subcommand in _NO_CREDENTIALS_GROUPS:
        # These groups manage or consume their own non-API credentials; the
        # leaf bind gate must not fire for them (#904).
        ctx.obj["credential_gate"] = False
        ctx.obj["token"] = explicit_token
        ctx.obj["login"] = explicit_login
        ctx.obj["op_token_ref"] = op_token_ref
        ctx.obj["op_login_ref"] = op_login_ref
        ctx.obj["bw_token_ref"] = bw_token_ref
        ctx.obj["bw_login_ref"] = bw_login_ref
        return

    # Resolve credentials early so all subcommands get the final values
    # The cwd .env may not be loaded yet: the import-time load ran in the
    # process' original directory. Load it before the has_refs check —
    # otherwise a folder whose only binding is a cwd .env would look
    # credential-less (#904 removed the active profile that used to force
    # the resolve path).
    load_env_file()
    has_refs = (
        token
        or login
        or profile
        or active_profile
        or op_token_ref
        or op_login_ref
        or bw_token_ref
        or bw_login_ref
        or os.getenv("YANDEX_DIRECT_TOKEN")
    )
    # When the user is only asking for help/version, no command will run, so
    # skip the best-effort network client-login resolution (#480 migration).
    # Otherwise ``<group> --help`` would block on a network round-trip — and on
    # a slow link or a SmartCaptcha gateway it could hang the CLI. ``ctx`` can't
    # tell a help pass from a real subcommand in the group callback, so detect
    # the eager flags in argv directly.
    help_or_version = any(arg in ("--help", "-h", "--version") for arg in sys.argv[1:])
    if has_refs:
        try:
            (
                resolved_token,
                resolved_login,
                credential_source,
            ) = get_credentials_with_source(
                token=explicit_token,
                login=explicit_login,
                profile=profile,
                op_token_ref=explicit_op_token_ref,
                op_login_ref=explicit_op_login_ref,
                bw_token_ref=explicit_bw_token_ref,
                bw_login_ref=explicit_bw_login_ref,
                allow_login_resolve=not help_or_version,
            )
            if credential_source == "explicit-profile":
                credential_profile = profile
            elif credential_source == "active-profile":
                credential_profile = active_profile
            else:
                credential_profile = None
            ctx.obj["token"] = resolved_token
            ctx.obj["login"] = resolved_login
            ctx.obj["credential_source"] = credential_source
            ctx.obj["credential_profile"] = credential_profile
        except RuntimeError as e:
            raise click.ClickException(str(e))
        except ValueError as e:
            if profile or active_profile:
                # Explicit profile selected but not found — surface the error
                raise click.ClickException(str(e))
            # No credential source at all — let subcommands fail naturally
            ctx.obj["token"] = explicit_token
            ctx.obj["login"] = explicit_login
    else:
        ctx.obj["token"] = explicit_token
        ctx.obj["login"] = explicit_login


def _register_command(command: click.Command) -> None:
    """Register a command and append mapped documentation URL to group help."""
    docs_url = get_docs_url(command.name or "")
    if docs_url:
        docs_line = f"\b\nDocumentation: {docs_url}"
        command.epilog = (
            f"{command.epilog}\n\n{docs_line}" if command.epilog else docs_line
        )
    _apply_directcli_classes(command)
    cli.add_command(command)


# Register all commands
for command in (
    campaigns,
    adgroups,
    ads,
    keywords,
    keywordbids,
    bids,
    bidmodifiers,
    audiencetargets,
    retargeting,
    creatives,
    adimages,
    adextensions,
    sitelinks,
    vcards,
    leads,
    clients,
    agencyclients,
    dictionaries,
    tracking_params,
    changes,
    reports,
    turbopages,
    negativekeywordsharedsets,
    feeds,
    smartadtargets,
    businesses,
    keywordsresearch,
    dynamicads,
    advideos,
    dynamicfeedadtargets,
    strategies,
    balance,
    v4finance,
    v4account,
    v4goals,
    v4events,
    v4wordstat,
    v4tags,
    v4keywords,
    v4adimage,
    v4forecast,
    v4meta,
    auth,
    masters,
    history,
    ad_elements,
    playwright_group,
):
    _register_command(command)

# Localize the root group's own options (--token, --locale, ...); these do not
# pass through _register_command, which only walks registered subcommands.
_localize_options(cli)


if __name__ == "__main__":
    cli()

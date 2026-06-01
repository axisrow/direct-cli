#!/usr/bin/env python
"""
Direct CLI - Command-line interface for Yandex Direct API
"""

import sys

import click
from click.core import ParameterSource

from . import __version__
from .auth import get_active_profile, get_credentials, load_env_file
from .i18n import (
    LOCALE_ENV_VAR,
    LocalizedOption,
    resolve_locale,
    set_active_locale,
    t,
)
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

# Load .env file
load_env_file()


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


def _augment_no_such_option(
    exc: click.exceptions.NoSuchOption, ctx: click.Context
) -> None:
    """Append a cross-command hint to a NoSuchOption error.

    For `direct <group> <cmd> --bad-flag`, finds sibling subcommands of
    `<group>` that declare `--bad-flag` and tells the user where to use
    it instead. When no sibling matches, points at `--help`.
    """
    parent = ctx.parent
    if parent is None or parent.command is None:
        return  # Unknown option on the root group — leave Click's default.

    group = parent.command
    if not isinstance(group, click.Group):
        return

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

    # Fold the "Did you mean..." suggestion into self.message now and clear
    # `possibilities` so Click's NoSuchOption.format_message() does not
    # re-append it after the Hint on print.
    exc.message = f"{exc.format_message()}\n\n{hint}"
    exc.possibilities = None


class _NoSuchOptionHintMixin:
    """Mixin that augments NoSuchOption errors raised by ``parse_args``."""

    def parse_args(self, ctx, args):
        try:
            return super().parse_args(ctx, args)
        except click.exceptions.NoSuchOption as exc:
            _augment_no_such_option(exc, ctx)
            raise


class _LocalizedHelpMixin:
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
    if ctx.invoked_subcommand != "auth":
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

    # Resolve credentials early so all subcommands get the final values
    has_refs = (
        token
        or login
        or profile
        or active_profile
        or op_token_ref
        or op_login_ref
        or bw_token_ref
        or bw_login_ref
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
            resolved_token, resolved_login = get_credentials(
                token=explicit_token,
                login=explicit_login,
                profile=profile,
                op_token_ref=explicit_op_token_ref,
                op_login_ref=explicit_op_login_ref,
                bw_token_ref=explicit_bw_token_ref,
                bw_login_ref=explicit_bw_login_ref,
                allow_login_resolve=not help_or_version,
            )
            ctx.obj["token"] = resolved_token
            ctx.obj["login"] = resolved_login
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
):
    _register_command(command)

# Localize the root group's own options (--token, --locale, ...); these do not
# pass through _register_command, which only walks registered subcommands.
_localize_options(cli)


if __name__ == "__main__":
    cli()

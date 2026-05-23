#!/usr/bin/env python
"""
Direct CLI - Command-line interface for Yandex Direct API
"""

import click
from dotenv import load_dotenv

from . import __version__
from .auth import get_active_profile, get_credentials
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

# Load .env file
load_dotenv()


CLI_EPILOG = """\b
Credential context:
  --login / YANDEX_DIRECT_LOGIN selects the Yandex Direct Client-Login.
  Use direct auth status to inspect the selected OAuth profile.

\b
API errors:
  Item-level Yandex Direct Errors are reported as command failures.
  Error 8800 usually means the object is not available under the current
  Client-Login/account.
"""


def _command_has_option(cmd: click.Command, option_name: str) -> bool:
    """Whether *cmd* declares *option_name* among its Click options.

    Searches all option names (including hidden ones), so `keywords update`
    with its hidden deprecated traps still counts as "having" `--bid` and
    won't be advertised as a sibling that accepts the flag.
    """
    return any(
        isinstance(param, click.Option) and option_name in param.opts
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


class DirectCliCommand(_NoSuchOptionHintMixin, click.Command):
    """Click Command that augments NoSuchOption errors with sibling hints."""


class DirectCliGroup(_NoSuchOptionHintMixin, click.Group):
    """Click Group that retypes descendants and augments NoSuchOption on
    the group itself (e.g. `direct ads --bogus get`)."""

    command_class = DirectCliCommand


def _apply_directcli_classes(command: click.Command) -> None:
    """Recursively retype *command* (and subcommands) so every node in the
    tree intercepts NoSuchOption.

    Subcommand modules use plain ``@click.group()`` / ``@click.command()``
    without ``cls=``. Rather than touch 39 command files, we mutate
    ``__class__`` after registration. The identity check (``type(...) is``
    rather than ``isinstance``) is deliberate: a contributor who registers
    a command with a custom subclass is opting out of the hint, not into
    silent retyping that would discard their behaviour.
    """
    if isinstance(command, click.Group):
        if type(command) is click.Group:  # noqa: PIE789 — see docstring
            command.__class__ = DirectCliGroup
        for subcommand in command.commands.values():
            _apply_directcli_classes(subcommand)
    elif type(command) is click.Command:  # noqa: PIE789 — see docstring
        command.__class__ = DirectCliCommand


@click.group(name="direct", cls=DirectCliGroup, epilog=CLI_EPILOG)
@click.version_option(__version__, prog_name="direct")
@click.option("--token", envvar="YANDEX_DIRECT_TOKEN", help="API access token")
@click.option("--login", envvar="YANDEX_DIRECT_LOGIN", help="Client login")
@click.option("--profile", help="Credential profile name")
@click.option("--sandbox", is_flag=True, help="Use sandbox API")
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
    op_token_ref,
    op_login_ref,
    bw_token_ref,
    bw_login_ref,
):
    """Command-line interface for Yandex Direct API"""
    ctx.ensure_object(dict)
    ctx.obj["sandbox"] = sandbox
    ctx.obj["profile"] = profile
    active_profile = None
    if ctx.invoked_subcommand != "auth":
        active_profile = get_active_profile()

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
    if has_refs:
        try:
            resolved_token, resolved_login = get_credentials(
                token=token,
                login=login,
                profile=profile,
                op_token_ref=op_token_ref,
                op_login_ref=op_login_ref,
                bw_token_ref=bw_token_ref,
                bw_login_ref=bw_login_ref,
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
            ctx.obj["token"] = token
            ctx.obj["login"] = login
    else:
        ctx.obj["token"] = token
        ctx.obj["login"] = login


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
    v4forecast,
    v4meta,
    auth,
):
    _register_command(command)


if __name__ == "__main__":
    cli()

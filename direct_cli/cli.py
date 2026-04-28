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
from .commands.v4shells import (
    v4account,
    v4events,
    v4finance,
    v4forecast,
    v4goals,
    v4meta,
    v4wordstat,
)

# Load .env file
load_dotenv()


@click.group(name="direct")
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
    v4forecast,
    v4meta,
    auth,
):
    _register_command(command)


if __name__ == "__main__":
    cli()

#!/usr/bin/env python
"""
Direct CLI - Command-line interface for Yandex Direct API
"""

import click
from dotenv import load_dotenv

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

# Load .env file
load_dotenv()


@click.group()
@click.option("--token", envvar="YANDEX_DIRECT_TOKEN", help="API access token")
@click.option("--login", envvar="YANDEX_DIRECT_LOGIN", help="Client login")
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
@click.pass_context
def cli(ctx, token, login, sandbox, op_token_ref, op_login_ref):
    """Command-line interface for Yandex Direct API"""
    ctx.ensure_object(dict)
    ctx.obj["token"] = token
    ctx.obj["login"] = login
    ctx.obj["sandbox"] = sandbox
    ctx.obj["op_token_ref"] = op_token_ref
    ctx.obj["op_login_ref"] = op_login_ref


# Register all commands
cli.add_command(campaigns)
cli.add_command(adgroups)
cli.add_command(ads)
cli.add_command(keywords)
cli.add_command(keywordbids)
cli.add_command(bids)
cli.add_command(bidmodifiers)
cli.add_command(audiencetargets)
cli.add_command(retargeting)
cli.add_command(creatives)
cli.add_command(adimages)
cli.add_command(adextensions)
cli.add_command(sitelinks)
cli.add_command(vcards)
cli.add_command(leads)
cli.add_command(clients)
cli.add_command(agencyclients)
cli.add_command(dictionaries)
cli.add_command(changes)
cli.add_command(reports)
cli.add_command(turbopages)
cli.add_command(negativekeywordsharedsets)
cli.add_command(feeds)
cli.add_command(smartadtargets)
cli.add_command(businesses)
cli.add_command(keywordsresearch)
cli.add_command(dynamicads)


if __name__ == "__main__":
    cli()

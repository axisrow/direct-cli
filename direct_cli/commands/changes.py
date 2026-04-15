"""
Changes commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_datetime, parse_ids


@click.group()
def changes():
    """Check for changes"""


@changes.command()
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@click.option(
    "--timestamp", help="Timestamp for changes check (YYYY-MM-DDTHH:MM:SS)"
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check(ctx, campaign_ids, timestamp, output_format, output):
    """Check changes for campaigns"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        params = {"CampaignIds": parse_ids(campaign_ids)}

        if timestamp:
            params["Timestamp"] = parse_datetime(timestamp)

        body = {"method": "check", "params": params}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@changes.command()
@click.option(
    "--timestamp", help="Timestamp for changes check (YYYY-MM-DDTHH:MM:SS)"
)
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check_campaigns(ctx, timestamp, output_format, output):
    """Check campaigns changes"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        params = {}

        if timestamp:
            params["Timestamp"] = parse_datetime(timestamp)

        body = {"method": "checkCampaigns", "params": params}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@changes.command()
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def check_dictionaries(ctx, output_format, output):
    """Check dictionaries changes"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "checkDictionaries", "params": {}}

        result = client.changes().post(data=body)
        format_output(result.data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

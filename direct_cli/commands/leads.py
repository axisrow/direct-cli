"""
Leads commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def leads():
    """Manage leads"""


@leads.command()
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--turbo-page-ids", help="Comma-separated turbo page IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(
    ctx, campaign_ids, turbo_page_ids, limit, fetch_all, output_format, output, fields
):
    """Get leads"""
    try:
        if not campaign_ids and not turbo_page_ids:
            raise click.UsageError(
                "Provide at least one of --campaign-ids or --turbo-page-ids"
            )

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",")
            if fields
            else ["Date", "LeadId", "CampaignId", "AdGroupId", "AdId"]
        )

        criteria = {}
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if turbo_page_ids:
            criteria["TurboPageIds"] = parse_ids(turbo_page_ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.leads().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()

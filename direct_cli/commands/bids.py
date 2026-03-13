"""
Bids commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def bids():
    """Manage bids"""


@bids.command()
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--keyword-ids", help="Comma-separated keyword IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(
    ctx, campaign_ids, adgroup_ids, keyword_ids, limit, fetch_all, output_format, output
):
    """Get bids"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if keyword_ids:
            criteria["KeywordIds"] = parse_ids(keyword_ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": ["CampaignId", "AdGroupId", "KeywordId", "Bid"],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.bids().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bids.command()
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option("--bid", type=float, help="Bid amount")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, campaign_id, bid, extra_json, dry_run):
    """Set bids"""
    try:
        bid_data = {"CampaignId": campaign_id}

        if bid:
            bid_data["Bid"] = int(bid * 1000000)

        if extra_json:
            extra = json.loads(extra_json)
            bid_data.update(extra)

        body = {"method": "set", "params": {"Bids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bids().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

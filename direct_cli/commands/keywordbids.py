"""
KeywordBids commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def keywordbids():
    """Manage keyword bids"""


@keywordbids.command()
@click.option("--keyword-ids", help="Comma-separated keyword IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(
    ctx, keyword_ids, adgroup_ids, campaign_ids, limit, fetch_all, output_format, output
):
    """Get keyword bids"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if keyword_ids:
            criteria["KeywordIds"] = parse_ids(keyword_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": ["KeywordId", "AdGroupId", "CampaignId", "Bid", "ContextBid"],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.keywordbids().post(data=body)

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


@keywordbids.command()
@click.option("--keyword-id", required=True, type=int, help="Keyword ID")
@click.option("--search-bid", type=float, help="Search bid")
@click.option("--network-bid", type=float, help="Network bid")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, keyword_id, search_bid, network_bid, extra_json, dry_run):
    """Set keyword bids"""
    try:
        bid_data = {"KeywordId": keyword_id}

        if search_bid:
            bid_data["SearchBid"] = int(search_bid * 1000000)
        if network_bid:
            bid_data["NetworkBid"] = int(network_bid * 1000000)

        if extra_json:
            extra = json.loads(extra_json)
            bid_data.update(extra)

        body = {"method": "set", "params": {"KeywordBids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywordbids().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

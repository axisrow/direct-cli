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
def get(ctx, campaign_ids, adgroup_ids, keyword_ids, limit, fetch_all, output_format, output):
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
@click.option("--keyword-id", required=True, type=int, help="Keyword ID")
@click.option("--bid", type=float, help="Bid amount")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, keyword_id, bid, extra_json, dry_run):
    """Set bids"""
    try:
        bid_data = {"KeywordId": keyword_id}

        if bid is not None:
            bid_data["Bid"] = int(bid * 1000000)

        if extra_json:
            bid_data.update(json.loads(extra_json))

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


@bids.command(name="set-auto")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--keyword-id", type=int, help="Keyword ID")
@click.option("--max-bid", type=float, help="Maximum bid")
@click.option("--position", help="Desired position")
@click.option("--increase-percent", type=int, help="Increase percent")
@click.option("--calculate-by", help="Calculate-by mode")
@click.option("--context-coverage", type=int, help="Context coverage")
@click.option("--scope", multiple=True, help="One or more scope values")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_auto(
    ctx,
    campaign_id,
    adgroup_id,
    keyword_id,
    max_bid,
    position,
    increase_percent,
    calculate_by,
    context_coverage,
    scope,
    extra_json,
    dry_run,
):
    """Configure automatic bidding"""
    try:
        bid_data = {}
        if campaign_id is not None:
            bid_data["CampaignId"] = campaign_id
        if adgroup_id is not None:
            bid_data["AdGroupId"] = adgroup_id
        if keyword_id is not None:
            bid_data["KeywordId"] = keyword_id
        if max_bid is not None:
            bid_data["MaxBid"] = int(max_bid * 1000000)
        if position:
            bid_data["Position"] = position
        if increase_percent is not None:
            bid_data["IncreasePercent"] = increase_percent
        if calculate_by:
            bid_data["CalculateBy"] = calculate_by
        if context_coverage is not None:
            bid_data["ContextCoverage"] = context_coverage
        if scope:
            bid_data["Scope"] = list(scope)
        if extra_json:
            bid_data.update(json.loads(extra_json))
        if "Scope" not in bid_data:
            raise click.UsageError(
                "Provide at least one --scope or include Scope in --json"
            )

        body = {"method": "setAuto", "params": {"Bids": [bid_data]}}

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

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


bids.add_command(get, name="list")

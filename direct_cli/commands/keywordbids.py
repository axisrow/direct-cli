"""
KeywordBids commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, to_micros


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
            "FieldNames": [
                "KeywordId",
                "AdGroupId",
                "CampaignId",
                "ServingStatus",
                "StrategyPriority",
            ],
            "SearchFieldNames": ["Bid"],
            "NetworkFieldNames": ["Bid"],
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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, keyword_id, search_bid, network_bid, dry_run):
    """Set keyword bids"""
    try:
        bid_data = {"KeywordId": keyword_id}

        if search_bid is not None:
            bid_data["SearchBid"] = to_micros(search_bid)
        if network_bid is not None:
            bid_data["NetworkBid"] = to_micros(network_bid)

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


@keywordbids.command(name="set-auto")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--keyword-id", type=int, help="Keyword ID")
@click.option(
    "--target-traffic-volume",
    type=int,
    help="SearchByTrafficVolume.TargetTrafficVolume value",
)
@click.option(
    "--target-coverage",
    type=int,
    help="NetworkByCoverage.TargetCoverage value",
)
@click.option("--increase-percent", type=int, help="Bidding rule IncreasePercent")
@click.option("--bid-ceiling", type=float, help="Bidding rule bid ceiling")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_auto(
    ctx,
    campaign_id,
    adgroup_id,
    keyword_id,
    target_traffic_volume,
    target_coverage,
    increase_percent,
    bid_ceiling,
    dry_run,
):
    """Configure automatic keyword bidding"""
    try:
        if (target_traffic_volume is None) == (target_coverage is None):
            raise click.UsageError(
                "Provide exactly one of --target-traffic-volume or --target-coverage"
            )

        bidding_rule = {}
        if target_traffic_volume is not None:
            bidding_rule["SearchByTrafficVolume"] = {
                "TargetTrafficVolume": target_traffic_volume
            }
            if increase_percent is not None:
                bidding_rule["SearchByTrafficVolume"][
                    "IncreasePercent"
                ] = increase_percent
            if bid_ceiling is not None:
                bidding_rule["SearchByTrafficVolume"]["BidCeiling"] = to_micros(
                    bid_ceiling
                )
        if target_coverage is not None:
            bidding_rule["NetworkByCoverage"] = {"TargetCoverage": target_coverage}
            if increase_percent is not None:
                bidding_rule["NetworkByCoverage"]["IncreasePercent"] = increase_percent
            if bid_ceiling is not None:
                bidding_rule["NetworkByCoverage"]["BidCeiling"] = to_micros(bid_ceiling)

        bid_data = {"BiddingRule": bidding_rule}
        if campaign_id is not None:
            bid_data["CampaignId"] = campaign_id
        if adgroup_id is not None:
            bid_data["AdGroupId"] = adgroup_id
        if keyword_id is not None:
            bid_data["KeywordId"] = keyword_id

        body = {"method": "setAuto", "params": {"KeywordBids": [bid_data]}}

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

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()

"""
KeywordBids commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, print_error
from ..utils import (
    add_criteria_csv,
    add_single_id_selector,
    get_default_fields,
    parse_csv_strings,
    parse_ids,
    MICRO_RUBLES,
)


@click.group()
def keywordbids():
    """Manage keyword bids"""


@keywordbids.command()
@click.option("--keyword-ids", help="Comma-separated keyword IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option(
    "--fields",
    help=(
        "Comma-separated top-level KeywordBidFieldEnum "
        "(KeywordId, AdGroupId, CampaignId, ServingStatus, "
        "StrategyPriority). Defaults to all five."
    ),
)
@click.option(
    "--search-field-names",
    help=(
        "Comma-separated KeywordBidSearchFieldEnum "
        "(Bid, AutotargetingSearchBidIsAuto, AuctionBids). "
        "Sent as separate top-level request parameter "
        "SearchFieldNames per the KeywordBidsGetRequest WSDL. "
        "Defaults to ['Bid']."
    ),
)
@click.option(
    "--network-field-names",
    help=(
        "Comma-separated KeywordBidNetworkFieldEnum "
        "(Bid, Coverage). Sent as separate top-level request "
        "parameter NetworkFieldNames per the KeywordBidsGetRequest "
        "WSDL. Defaults to ['Bid']."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    keyword_ids,
    adgroup_ids,
    campaign_ids,
    serving_statuses,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    search_field_names,
    network_field_names,
    dry_run,
):
    """Get keyword bids"""
    try:
        client = client_from_ctx(ctx, create_client)

        parsed_fields = parse_csv_strings(fields)
        if fields is not None and not parsed_fields:
            raise click.UsageError(
                t("Provide a non-empty comma-separated FieldNames list.")
            )
        parsed_search_field_names = parse_csv_strings(search_field_names)
        if search_field_names is not None and not parsed_search_field_names:
            raise click.UsageError(
                t("Provide a non-empty comma-separated SearchFieldNames list.")
            )
        parsed_network_field_names = parse_csv_strings(network_field_names)
        if network_field_names is not None and not parsed_network_field_names:
            raise click.UsageError(
                t("Provide a non-empty comma-separated NetworkFieldNames list.")
            )

        criteria = {}
        if keyword_ids:
            criteria["KeywordIds"] = parse_ids(keyword_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)

        if not criteria:
            raise click.UsageError(
                t(
                    "keywordbids get requires at least one filter: "
                    "--keyword-ids, --adgroup-ids, --campaign-ids, "
                    "or --serving-statuses."
                )
            )

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": (
                parsed_fields or get_default_fields("keywordbids", "FieldNames")
            ),
            "SearchFieldNames": (
                parsed_search_field_names
                or get_default_fields("keywordbids", "SearchFieldNames")
            ),
            "NetworkFieldNames": (
                parsed_network_field_names
                or get_default_fields("keywordbids", "NetworkFieldNames")
            ),
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.keywordbids().post(data=body)

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


@keywordbids.command()
@click.option("--campaign-id", type=int, help="Campaign ID selector")
@click.option("--adgroup-id", type=int, help="Ad group ID selector")
@click.option("--keyword-id", type=int, help="Keyword ID selector")
@click.option("--search-bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--network-bid", type=MICRO_RUBLES, help="Network bid in micro-rubles")
@click.option(
    "--autotargeting-search-bid-is-auto",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSearchBidIsAuto value: YES or NO",
)
@click.option(
    "--priority",
    type=click.Choice(["LOW", "NORMAL", "HIGH"], case_sensitive=False),
    help="StrategyPriority value: LOW, NORMAL, or HIGH",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(
    ctx,
    campaign_id,
    adgroup_id,
    keyword_id,
    search_bid,
    network_bid,
    autotargeting_search_bid_is_auto,
    priority,
    dry_run,
):
    """Set keyword bids"""
    # Reject empty-payload no-op (issue #198 H9).
    if (
        search_bid is None
        and network_bid is None
        and autotargeting_search_bid_is_auto is None
        and priority is None
    ):
        raise click.UsageError(
            t(
                "keywordbids set requires at least one bid field "
                "(--search-bid, --network-bid, --priority, "
                "or --autotargeting-search-bid-is-auto)."
            )
        )

    try:
        bid_data = {}
        add_single_id_selector(
            bid_data,
            campaign_id=campaign_id,
            adgroup_id=adgroup_id,
            keyword_id=keyword_id,
            command_name="keywordbids set",
        )

        if search_bid is not None:
            bid_data["SearchBid"] = search_bid
        if network_bid is not None:
            bid_data["NetworkBid"] = network_bid
        if autotargeting_search_bid_is_auto is not None:
            bid_data["AutotargetingSearchBidIsAuto"] = (
                autotargeting_search_bid_is_auto.upper()
            )
        if priority is not None:
            bid_data["StrategyPriority"] = priority.upper()

        body = {"method": "set", "params": {"KeywordBids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = client_from_ctx(ctx, create_client)
        result = client.keywordbids().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
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
@click.option(
    "--bid-ceiling", type=MICRO_RUBLES, help="Bidding rule bid ceiling in micro-rubles"
)
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
                t("Provide exactly one of --target-traffic-volume or --target-coverage")
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
                bidding_rule["SearchByTrafficVolume"]["BidCeiling"] = bid_ceiling
        if target_coverage is not None:
            bidding_rule["NetworkByCoverage"] = {"TargetCoverage": target_coverage}
            if increase_percent is not None:
                bidding_rule["NetworkByCoverage"]["IncreasePercent"] = increase_percent
            if bid_ceiling is not None:
                bidding_rule["NetworkByCoverage"]["BidCeiling"] = bid_ceiling

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

        client = client_from_ctx(ctx, create_client)
        result = client.keywordbids().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()

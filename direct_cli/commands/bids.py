"""
Bids commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    MICRO_RUBLES,
    add_criteria_csv,
    add_single_id_selector,
    build_common_params,
    get_default_fields,
    get_options,
    parse_csv_strings,
    parse_ids,
)


@click.group()
def bids():
    """Manage bids"""


@bids.command()
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--keyword-ids", help="Comma-separated keyword IDs")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@get_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    campaign_ids,
    adgroup_ids,
    keyword_ids,
    serving_statuses,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get bids"""
    client = client_from_ctx(ctx, create_client)

    criteria = {}
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if keyword_ids:
        criteria["KeywordIds"] = parse_ids(keyword_ids)
    add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)

    if not criteria:
        raise click.UsageError(
            t(
                "bids get requires at least one filter: "
                "--campaign-ids, --adgroup-ids, --keyword-ids, "
                "or --serving-statuses."
            )
        )

    field_names = parse_csv_strings(fields) or get_default_fields("bids")
    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.bids().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@bids.command()
@click.option("--campaign-id", type=click.IntRange(min=1), help="Campaign ID selector")
@click.option("--adgroup-id", type=click.IntRange(min=1), help="Ad group ID selector")
@click.option("--keyword-id", type=click.IntRange(min=1), help="Keyword ID selector")
@click.option("--bid", type=MICRO_RUBLES, help="Bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="ContextBid in micro-rubles")
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
@handle_api_errors
def set(
    ctx,
    campaign_id,
    adgroup_id,
    keyword_id,
    bid,
    context_bid,
    autotargeting_search_bid_is_auto,
    priority,
    dry_run,
):
    """Set bids"""
    # Reject empty-payload no-op (issue #198 H8).
    if (
        bid is None
        and context_bid is None
        and autotargeting_search_bid_is_auto is None
        and priority is None
    ):
        raise click.UsageError(
            t(
                "bids set requires at least one bid field "
                "(--bid, --context-bid, --priority, "
                "or --autotargeting-search-bid-is-auto)."
            )
        )

    bid_data = {}
    add_single_id_selector(
        bid_data,
        campaign_id=campaign_id,
        adgroup_id=adgroup_id,
        keyword_id=keyword_id,
        command_name="bids set",
    )
    if bid is not None:
        bid_data["Bid"] = bid
    if context_bid is not None:
        bid_data["ContextBid"] = context_bid
    if autotargeting_search_bid_is_auto is not None:
        bid_data["AutotargetingSearchBidIsAuto"] = (
            autotargeting_search_bid_is_auto.upper()
        )
    if priority is not None:
        bid_data["StrategyPriority"] = priority.upper()

    body = {"method": "set", "params": {"Bids": [bid_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.bids().post(data=body)
    format_output(result().extract(), "json", None)


@bids.command(name="set-auto")
@click.option("--campaign-id", type=click.IntRange(min=1), help="Campaign ID")
@click.option("--adgroup-id", type=click.IntRange(min=1), help="Ad group ID")
@click.option("--keyword-id", type=click.IntRange(min=1), help="Keyword ID")
@click.option("--max-bid", type=MICRO_RUBLES, help="Maximum bid in micro-rubles")
@click.option("--position", help="Desired position")
@click.option("--increase-percent", type=int, help="Increase percent")
@click.option("--calculate-by", help="Calculate-by mode")
@click.option("--context-coverage", type=int, help="Context coverage")
@click.option("--scope", multiple=True, help="One or more scope values")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
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
    dry_run,
):
    """Configure automatic bidding"""
    bid_data = {}
    add_single_id_selector(
        bid_data,
        campaign_id=campaign_id,
        adgroup_id=adgroup_id,
        keyword_id=keyword_id,
        command_name="bids set-auto",
    )
    if max_bid is not None:
        bid_data["MaxBid"] = max_bid
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
    if "Scope" not in bid_data:
        raise click.UsageError(t("Provide at least one --scope"))

    body = {"method": "setAuto", "params": {"Bids": [bid_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.bids().post(data=body)
    format_output(result().extract(), "json", None)

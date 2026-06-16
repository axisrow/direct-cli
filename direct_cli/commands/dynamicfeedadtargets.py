"""
DynamicFeedAdTargets commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ._lifecycle import make_lifecycle_command
from ..utils import (
    MICRO_RUBLES,
    build_common_params,
    get_default_fields,
    get_options,
    parse_condition_specs,
    parse_csv_strings,
    parse_csv_upper,
    parse_ids,
)


@click.group()
def dynamicfeedadtargets():
    """Manage dynamic feed ad targets"""


@dynamicfeedadtargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--states", help="Comma-separated states")
@get_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    adgroup_ids,
    campaign_ids,
    states,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get dynamic feed ad targets"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields(
        "dynamicfeedadtargets"
    )

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if states:
        criteria["States"] = parse_csv_upper(states) or []

    if not criteria:
        raise click.UsageError(t("Provide at least one typed filter"))

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.dynamicfeedadtargets().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@dynamicfeedadtargets.command()
@click.option(
    "--adgroup-id", required=True, type=click.IntRange(min=1), help="Ad group ID"
)
@click.option("--name", required=True, help="Target name")
@click.option(
    "--condition",
    "conditions",
    multiple=True,
    help="Condition spec: OPERAND:OPERATOR:ARG1|ARG2",
)
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option(
    "--available-items-only",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="Restrict to currently available feed items",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx, adgroup_id, name, conditions, bid, context_bid, available_items_only, dry_run
):
    """Add dynamic feed ad target"""
    target_data = {
        "AdGroupId": adgroup_id,
        "Name": name,
    }
    parsed_conditions = parse_condition_specs(list(conditions)) if conditions else None
    if parsed_conditions:
        target_data["Conditions"] = {"Items": parsed_conditions}
    if bid is not None:
        target_data["Bid"] = bid
    if context_bid is not None:
        target_data["ContextBid"] = context_bid
    if available_items_only:
        target_data["AvailableItemsOnly"] = available_items_only.upper()

    body = {"method": "add", "params": {"DynamicFeedAdTargets": [target_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicfeedadtargets().post(data=body)
    format_output(result().extract(), "json", None)


def _dynamicfeedadtarget_lifecycle(method, help_text):
    return make_lifecycle_command(
        dynamicfeedadtargets, method, help_text, "target_id", "Target ID", create_client
    )


delete = _dynamicfeedadtarget_lifecycle("delete", "Delete dynamic feed ad target")
suspend = _dynamicfeedadtarget_lifecycle("suspend", "Suspend dynamic feed ad target")
resume = _dynamicfeedadtarget_lifecycle("resume", "Resume dynamic feed ad target")


@dynamicfeedadtargets.command(name="set-bids")
@click.option("--id", "target_id", type=click.IntRange(min=1), help="Target ID")
@click.option("--adgroup-id", type=click.IntRange(min=1), help="Ad group ID")
@click.option("--campaign-id", type=click.IntRange(min=1), help="Campaign ID")
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def set_bids(ctx, target_id, adgroup_id, campaign_id, bid, context_bid, dry_run):
    """Set dynamic feed ad target bids"""
    bid_data = {}
    if target_id is not None:
        bid_data["Id"] = target_id
    if adgroup_id is not None:
        bid_data["AdGroupId"] = adgroup_id
    if campaign_id is not None:
        bid_data["CampaignId"] = campaign_id
    if bid is not None:
        bid_data["Bid"] = bid
    if context_bid is not None:
        bid_data["ContextBid"] = context_bid

    has_selector = any(k in bid_data for k in ("Id", "AdGroupId", "CampaignId"))
    has_bid = any(k in bid_data for k in ("Bid", "ContextBid"))
    if not has_selector:
        raise click.UsageError(
            t("Provide a target selector (--id, --adgroup-id, or --campaign-id)")
        )
    if not has_bid:
        raise click.UsageError(t("Provide at least one bid (--bid or --context-bid)"))

    body = {"method": "setBids", "params": {"Bids": [bid_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicfeedadtargets().post(data=body)
    format_output(result().extract(), "json", None)

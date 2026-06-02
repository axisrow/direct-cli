"""
DynamicAds (Webpages) commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    MICRO_RUBLES,
    get_default_fields,
    get_options,
    parse_condition_specs,
    parse_csv_strings,
    parse_csv_upper,
    parse_ids,
)


@click.group()
def dynamicads():
    """Manage dynamic ad targets"""


@dynamicads.command()
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
    """Get dynamic ad targets"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("dynamicads")

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if states:
        criteria["States"] = parse_csv_upper(states) or []

    params = {"SelectionCriteria": criteria, "FieldNames": field_names}

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.dynamicads().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@dynamicads.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--name", required=True, help="Target name")
@click.option(
    "--condition",
    "conditions",
    multiple=True,
    help="Condition spec: OPERAND:OPERATOR:ARG1|ARG2",
)
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, adgroup_id, name, conditions, bid, context_bid, priority, dry_run):
    """Add dynamic ad target"""
    # WSDL DynamicTextAdTargetAddItem.Conditions is minOccurs=0;
    # the CLI used to require it (over-constraint, issue #198 H7).
    target_data = {
        "AdGroupId": adgroup_id,
        "Name": name,
    }
    if conditions:
        target_data["Conditions"] = parse_condition_specs(list(conditions))
    if bid is not None:
        target_data["Bid"] = bid
    if context_bid is not None:
        target_data["ContextBid"] = context_bid
    if priority:
        target_data["StrategyPriority"] = priority

    body = {"method": "add", "params": {"Webpages": [target_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicads().post(data=body)
    format_output(result().extract(), "json", None)


@dynamicads.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, target_id, dry_run):
    """Delete dynamic ad target"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.dynamicads().post(data=body)
    format_output(result().extract(), "json", None)


@dynamicads.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def suspend(ctx, target_id, dry_run):
    """Suspend dynamic ad target"""
    body = {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicads().post(data=body)
    format_output(result().extract(), "json", None)


@dynamicads.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def resume(ctx, target_id, dry_run):
    """Resume dynamic ad target"""
    body = {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicads().post(data=body)
    format_output(result().extract(), "json", None)


@dynamicads.command(name="set-bids")
@click.option("--id", "target_id", type=int, help="Target ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def set_bids(
    ctx, target_id, adgroup_id, campaign_id, bid, context_bid, priority, dry_run
):
    """Set dynamic ad target bids"""
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
    if priority:
        bid_data["StrategyPriority"] = priority
    bid_fields = {k for k in ("Bid", "ContextBid", "StrategyPriority") if k in bid_data}
    selector_fields = {k for k in ("Id", "AdGroupId", "CampaignId") if k in bid_data}
    if not selector_fields:
        raise click.UsageError(
            t("Provide a target selector (--id, --adgroup-id, or --campaign-id)")
        )
    if not bid_fields:
        raise click.UsageError(
            t("Provide at least one bid field " "(--bid, --context-bid, or --priority)")
        )

    body = {"method": "setBids", "params": {"Bids": [bid_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.dynamicads().post(data=body)
    format_output(result().extract(), "json", None)

"""
AudienceTargets commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ..utils import (
    MICRO_RUBLES,
    add_criteria_csv,
    build_common_params,
    get_default_fields,
    get_options,
    parse_csv_strings,
    parse_ids,
)


@click.group()
def audiencetargets():
    """Manage audience targets"""


@audiencetargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--retargeting-list-ids", help="Comma-separated retargeting list IDs")
@click.option("--interest-ids", help="Comma-separated interest IDs")
@click.option("--states", help="Comma-separated states")
@get_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    adgroup_ids,
    campaign_ids,
    retargeting_list_ids,
    interest_ids,
    states,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get audience targets"""
    client = client_from_ctx(ctx, create_client)

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    add_criteria_csv(
        criteria, "RetargetingListIds", retargeting_list_ids, integers=True
    )
    add_criteria_csv(criteria, "InterestIds", interest_ids, integers=True)
    add_criteria_csv(criteria, "States", states, upper=True)

    if not criteria:
        raise click.UsageError(t("Provide at least one typed filter"))

    field_names = parse_csv_strings(fields) or get_default_fields("audiencetargets")
    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.audiencetargets().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@audiencetargets.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--retargeting-list-id", type=int, help="Retargeting list ID")
@click.option("--interest-id", type=int, help="Interest ID")
@click.option("--bid", type=MICRO_RUBLES, help="ContextBid value in micro-rubles")
@click.option(
    "--priority",
    type=click.Choice(["LOW", "NORMAL", "HIGH"], case_sensitive=False),
    help="StrategyPriority value for automatic strategies",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    adgroup_id,
    retargeting_list_id,
    interest_id,
    bid,
    priority,
    dry_run,
):
    """Add audience target"""
    if retargeting_list_id is None and interest_id is None:
        raise click.UsageError(
            t("Provide at least one of --retargeting-list-id or --interest-id")
        )

    target_data = {
        "AdGroupId": adgroup_id,
    }
    if retargeting_list_id is not None:
        target_data["RetargetingListId"] = retargeting_list_id
    if interest_id is not None:
        target_data["InterestId"] = interest_id

    if bid is not None:
        target_data["ContextBid"] = bid
    if priority:
        target_data["StrategyPriority"] = priority.upper()

    body = {"method": "add", "params": {"AudienceTargets": [target_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.audiencetargets().post(data=body)
    format_output(result().extract(), "json", None)


@audiencetargets.command(name="set-bids")
@click.option("--id", "target_id", type=int, help="Target ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def set_bids(ctx, target_id, adgroup_id, campaign_id, context_bid, priority, dry_run):
    """Set audience target bids"""
    bid_data = {}
    if target_id is not None:
        bid_data["Id"] = target_id
    if adgroup_id is not None:
        bid_data["AdGroupId"] = adgroup_id
    if campaign_id is not None:
        bid_data["CampaignId"] = campaign_id
    if context_bid is not None:
        bid_data["ContextBid"] = context_bid
    if priority:
        bid_data["StrategyPriority"] = priority
    bid_fields = {k for k in ("ContextBid", "StrategyPriority") if k in bid_data}
    selector_fields = {k for k in ("Id", "AdGroupId", "CampaignId") if k in bid_data}
    if not selector_fields:
        raise click.UsageError(
            t("Provide a target selector (--id, --adgroup-id, or --campaign-id)")
        )
    if not bid_fields:
        raise click.UsageError(
            t("Provide at least one bid field (--context-bid or --priority)")
        )

    body = {"method": "setBids", "params": {"Bids": [bid_data]}}

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.audiencetargets().post(data=body)
    format_output(result().extract(), "json", None)


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, target_id, dry_run):
    """Delete audience target"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.audiencetargets().post(data=body)
    format_output(result().extract(), "json", None)


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def suspend(ctx, target_id, dry_run):
    """Suspend audience target"""
    body = {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.audiencetargets().post(data=body)
    format_output(result().extract(), "json", None)


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def resume(ctx, target_id, dry_run):
    """Resume audience target"""
    body = {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [target_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.audiencetargets().post(data=body)
    format_output(result().extract(), "json", None)

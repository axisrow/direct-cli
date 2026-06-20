"""
DynamicFeedAdTargets commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import ids_adgroup_campaign_states_criteria, make_get_command
from ._lifecycle import register_lifecycle_commands
from ..utils import (
    MICRO_RUBLES,
    parse_condition_specs,
)

# Yandex Direct dynamicfeedadtargets.get caps SelectionCriteria arrays at
# runtime (the WSDL declares them maxOccurs="unbounded"). Live measurement
# 2026-06-17 via sandbox: --campaign-ids ×3 → 4001 "Exceed the maximum number
# of IDs per array SelectionCriteria.CampaignIds" (N=2 accepted, matches
# dynamicads/smartadtargets); --adgroup-ids ×10001 → 4001 ".AdGroupIds"
# (N=1000 accepted). Ids accepted at N=10000.
DYNAMICFEEDADTARGETS_GET_CRITERIA_LIMITS = {"CampaignIds": 2, "AdGroupIds": 1000}


@click.group()
def dynamicfeedadtargets():
    """Manage dynamic feed ad targets"""


get = make_get_command(
    dynamicfeedadtargets,
    create_client,
    default_fields_key="dynamicfeedadtargets",
    help_text="Get dynamic feed ad targets",
    ids_help="Comma-separated target IDs",
    extra_options=(
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--states", help="Comma-separated states"),
    ),
    criteria_builder=ids_adgroup_campaign_states_criteria,
    criteria_limits=DYNAMICFEEDADTARGETS_GET_CRITERIA_LIMITS,
    require_criteria_message="Provide at least one typed filter",
)


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

    execute_request(ctx, "dynamicfeedadtargets", body, dry_run, create_client)


register_lifecycle_commands(
    dynamicfeedadtargets,
    "target_id",
    "Target ID",
    create_client,
    [
        ("delete", "Delete dynamic feed ad target"),
        ("suspend", "Suspend dynamic feed ad target"),
        ("resume", "Resume dynamic feed ad target"),
    ],
)


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

    execute_request(ctx, "dynamicfeedadtargets", body, dry_run, create_client)

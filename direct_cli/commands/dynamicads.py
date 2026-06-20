"""
DynamicAds (Webpages) commands
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

# dynamicads.get (DynamicTextAdTargets) caps SelectionCriteria.CampaignIds at 2
# (the WSDL declares it maxOccurs="unbounded"; the doc page is not web-reachable).
# Confirmed live 2026-06-16: --campaign-ids ×3 → 4001 "Array
# SelectionCriteria.CampaignIds cannot contain more than 2 elements".
# AdGroupIds/Ids ×50 are accepted — only CampaignIds is capped.
DYNAMICADS_GET_CRITERIA_LIMITS = {"CampaignIds": 2}


@click.group()
def dynamicads():
    """Manage dynamic ad targets"""


get = make_get_command(
    dynamicads,
    create_client,
    default_fields_key="dynamicads",
    help_text="Get dynamic ad targets",
    ids_help="Comma-separated target IDs",
    extra_options=(
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--states", help="Comma-separated states"),
    ),
    criteria_builder=ids_adgroup_campaign_states_criteria,
    criteria_limits=DYNAMICADS_GET_CRITERIA_LIMITS,
    require_criteria_message="Provide at least one typed filter",
)


@dynamicads.command()
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

    execute_request(ctx, "dynamicads", body, dry_run, create_client)


register_lifecycle_commands(
    dynamicads,
    "target_id",
    "Target ID",
    create_client,
    [
        ("delete", "Delete dynamic ad target"),
        ("suspend", "Suspend dynamic ad target"),
        ("resume", "Resume dynamic ad target"),
    ],
)


@dynamicads.command(name="set-bids")
@click.option("--id", "target_id", type=click.IntRange(min=1), help="Target ID")
@click.option("--adgroup-id", type=click.IntRange(min=1), help="Ad group ID")
@click.option("--campaign-id", type=click.IntRange(min=1), help="Campaign ID")
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

    execute_request(ctx, "dynamicads", body, dry_run, create_client)

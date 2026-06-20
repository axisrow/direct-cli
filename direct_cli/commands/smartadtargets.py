"""
SmartAdTargets commands
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

# smartadtargets.get caps SelectionCriteria.CampaignIds at 2 (the WSDL declares
# it maxOccurs="unbounded"; the doc page is not web-reachable). Confirmed live
# 2026-06-16: --campaign-ids ×3 → 4001 "Array SelectionCriteria.CampaignIds ...
# не более 2 элементов". AdGroupIds ×50 are accepted — only CampaignIds is capped.
SMARTADTARGETS_GET_CRITERIA_LIMITS = {"CampaignIds": 2}


@click.group()
def smartadtargets():
    """Manage smart ad targets"""


get = make_get_command(
    smartadtargets,
    create_client,
    default_fields_key="smartadtargets",
    help_text="Get smart ad targets",
    ids_help="Comma-separated target IDs",
    extra_options=(
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--states", help="Comma-separated states"),
    ),
    criteria_builder=ids_adgroup_campaign_states_criteria,
    criteria_limits=SMARTADTARGETS_GET_CRITERIA_LIMITS,
    require_criteria_message="Provide at least one typed filter",
)


@smartadtargets.command()
@click.option(
    "--adgroup-id", required=True, type=click.IntRange(min=1), help="Ad group ID"
)
@click.option("--name", required=True, help="Target name")
@click.option("--audience", required=True, help="Audience value")
@click.option(
    "--condition",
    "conditions",
    multiple=True,
    help="Condition spec: OPERAND:OPERATOR:ARG1|ARG2",
)
@click.option("--average-cpc", type=MICRO_RUBLES, help="Average CPC in micro-rubles")
@click.option("--average-cpa", type=MICRO_RUBLES, help="Average CPA in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option(
    "--available-items-only",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="Whether only available items are targeted",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    adgroup_id,
    name,
    audience,
    conditions,
    average_cpc,
    average_cpa,
    priority,
    available_items_only,
    dry_run,
):
    """Add smart ad target"""
    target_data = {
        "AdGroupId": adgroup_id,
        "Name": name,
        "Audience": audience,
    }
    if conditions:
        target_data["Conditions"] = {"Items": parse_condition_specs(list(conditions))}
    if average_cpc is not None:
        target_data["AverageCpc"] = average_cpc
    if average_cpa is not None:
        target_data["AverageCpa"] = average_cpa
    if priority:
        target_data["StrategyPriority"] = priority
    if available_items_only:
        target_data["AvailableItemsOnly"] = available_items_only.upper()

    body = {"method": "add", "params": {"SmartAdTargets": [target_data]}}

    execute_request(ctx, "smartadtargets", body, dry_run, create_client)


@smartadtargets.command()
@click.option(
    "--id", "target_id", required=True, type=click.IntRange(min=1), help="Target ID"
)
@click.option("--name", help="Target name")
@click.option("--audience", help="Audience value")
@click.option(
    "--condition",
    "conditions",
    multiple=True,
    help="Condition spec: OPERAND:OPERATOR:ARG1|ARG2",
)
@click.option("--average-cpc", type=MICRO_RUBLES, help="Average CPC in micro-rubles")
@click.option("--average-cpa", type=MICRO_RUBLES, help="Average CPA in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option(
    "--available-items-only",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="Whether only available items are targeted",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    target_id,
    name,
    audience,
    conditions,
    average_cpc,
    average_cpa,
    priority,
    available_items_only,
    dry_run,
):
    """Update smart ad target"""
    target_data = {"Id": target_id}
    if name:
        target_data["Name"] = name
    if audience:
        target_data["Audience"] = audience
    if conditions:
        target_data["Conditions"] = {"Items": parse_condition_specs(list(conditions))}
    if average_cpc is not None:
        target_data["AverageCpc"] = average_cpc
    if average_cpa is not None:
        target_data["AverageCpa"] = average_cpa
    if priority:
        target_data["StrategyPriority"] = priority
    if available_items_only:
        target_data["AvailableItemsOnly"] = available_items_only.upper()
    if len(target_data) == 1:
        raise click.UsageError(t("Provide at least one field to update"))

    body = {"method": "update", "params": {"SmartAdTargets": [target_data]}}

    execute_request(ctx, "smartadtargets", body, dry_run, create_client)


register_lifecycle_commands(
    smartadtargets,
    "target_id",
    "Target ID",
    create_client,
    [
        ("delete", "Delete smart ad target"),
        ("suspend", "Suspend smart ad target"),
        ("resume", "Resume smart ad target"),
    ],
)


@smartadtargets.command(name="set-bids")
@click.option("--id", "target_id", type=click.IntRange(min=1), help="Target ID")
@click.option("--adgroup-id", type=click.IntRange(min=1), help="Ad group ID")
@click.option("--campaign-id", type=click.IntRange(min=1), help="Campaign ID")
@click.option("--average-cpc", type=MICRO_RUBLES, help="Average CPC in micro-rubles")
@click.option("--average-cpa", type=MICRO_RUBLES, help="Average CPA in micro-rubles")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def set_bids(
    ctx,
    target_id,
    adgroup_id,
    campaign_id,
    average_cpc,
    average_cpa,
    priority,
    dry_run,
):
    """Set smart ad target bids"""
    bid_data = {}
    if target_id is not None:
        bid_data["Id"] = target_id
    if adgroup_id is not None:
        bid_data["AdGroupId"] = adgroup_id
    if campaign_id is not None:
        bid_data["CampaignId"] = campaign_id
    if average_cpc is not None:
        bid_data["AverageCpc"] = average_cpc
    if average_cpa is not None:
        bid_data["AverageCpa"] = average_cpa
    if priority:
        bid_data["StrategyPriority"] = priority
    bid_fields = {
        k for k in ("AverageCpc", "AverageCpa", "StrategyPriority") if k in bid_data
    }
    if not bid_data:
        raise click.UsageError(
            t("Provide target selection and bid fields for set-bids")
        )
    if not bid_fields:
        raise click.UsageError(
            t(
                "Provide at least one bid field"
                " (--average-cpc, --average-cpa, or --priority)"
            )
        )

    body = {"method": "setBids", "params": {"Bids": [bid_data]}}

    execute_request(ctx, "smartadtargets", body, dry_run, create_client)

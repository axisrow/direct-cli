"""
AudienceTargets commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import make_get_command
from ._lifecycle import register_lifecycle_commands
from ._set_bids import make_set_bids_command
from ..utils import (
    MICRO_RUBLES,
    add_criteria_csv,
    parse_ids,
)

# Yandex Direct audiencetargets.get caps SelectionCriteria arrays at runtime
# (the WSDL declares them maxOccurs="unbounded"). Live measurement 2026-06-17
# via sandbox: --campaign-ids ×1001 → 4001 "Exceed the maximum number of IDs
# per array SelectionCriteria.CampaignIds" (N=100 accepted — unique among
# *.get); --adgroup-ids/--retargeting-list-ids/--interest-ids ×10001 → 4001
# (N=1000 accepted). Ids accepted at N=10000.
AUDIENCETARGETS_GET_CRITERIA_LIMITS = {
    "CampaignIds": 100,
    "AdGroupIds": 1000,
    "RetargetingListIds": 1000,
    "InterestIds": 1000,
}


@click.group()
def audiencetargets():
    """Manage audience targets"""


def _audiencetargets_get_criteria(
    ids=None,
    adgroup_ids=None,
    campaign_ids=None,
    retargeting_list_ids=None,
    interest_ids=None,
    states=None,
    **_,
):
    """SelectionCriteria for ``audiencetargets get``: optional Ids/AdGroupIds/
    CampaignIds, integer RetargetingListIds/InterestIds and upper-cased States."""
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
    return criteria


get = make_get_command(
    audiencetargets,
    create_client,
    default_fields_key="audiencetargets",
    help_text="Get audience targets",
    ids_help="Comma-separated target IDs",
    extra_options=(
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option(
            "--retargeting-list-ids", help="Comma-separated retargeting list IDs"
        ),
        click.option("--interest-ids", help="Comma-separated interest IDs"),
        click.option("--states", help="Comma-separated states"),
    ),
    criteria_builder=_audiencetargets_get_criteria,
    criteria_limits=AUDIENCETARGETS_GET_CRITERIA_LIMITS,
    require_criteria_message=(
        "audiencetargets get requires at least one filter "
        "(--ids, --adgroup-ids, --campaign-ids, --retargeting-list-ids, "
        "--interest-ids, or --states). The Yandex Direct API rejects an "
        "empty SelectionCriteria (error 8000/4001), so whole-account "
        "paging is not available. To sweep the account, first run "
        "`campaigns get`, then page `audiencetargets get` in batches of "
        "campaign ids."
    ),
)


@audiencetargets.command()
@click.option(
    "--adgroup-id", required=True, type=click.IntRange(min=1), help="Ad group ID"
)
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

    execute_request(ctx, "audiencetargets", body, dry_run, create_client)


set_bids = make_set_bids_command(
    audiencetargets,
    "audiencetargets",
    "Set audience target bids",
    (
        (
            "--context-bid",
            "context_bid",
            "ContextBid",
            MICRO_RUBLES,
            "Context bid in micro-rubles",
        ),
        (
            "--priority",
            "priority",
            "StrategyPriority",
            None,
            "Strategy priority",
            True,
        ),
    ),
    create_client,
    selector_error="Provide a target selector (--id, --adgroup-id, or --campaign-id)",
    bid_error="Provide at least one bid field (--context-bid or --priority)",
)


register_lifecycle_commands(
    audiencetargets,
    "target_id",
    "Target ID",
    create_client,
    [
        ("delete", "Delete audience target"),
        ("suspend", "Suspend audience target"),
        ("resume", "Resume audience target"),
    ],
)

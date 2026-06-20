"""Yandex Direct v4 Live goals commands."""

import click

from ..utils import v4_output_options
from ..v4.emit import emit_or_call_v4
from ..v4.parse import parse_positive_ids
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _campaign_ids_param(campaign_ids: str) -> dict:
    """Build the v4 Live CampaignIDInfo parameter."""
    return {
        "CampaignIDS": parse_positive_ids(
            campaign_ids, "--campaign-ids", require_positive=False
        )
    }


@click.group(epilog=V4_EPILOG)
def v4goals():
    """Yandex Direct v4 Live goals commands."""


@v4_method_contract("GetStatGoals")
@v4goals.command(name="get-stat-goals")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@v4_output_options
@click.pass_context
def get_stat_goals(ctx, campaign_ids, output_format, output, dry_run):
    """Get Yandex Metrica goals available for campaigns."""
    param = _campaign_ids_param(campaign_ids)
    emit_or_call_v4(ctx, "GetStatGoals", param, dry_run, output_format, output)


@v4_method_contract("GetRetargetingGoals")
@v4goals.command(name="get-retargeting-goals")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@v4_output_options
@click.pass_context
def get_retargeting_goals(ctx, campaign_ids, output_format, output, dry_run):
    """Get retargeting goals for campaigns."""
    param = _campaign_ids_param(campaign_ids)
    emit_or_call_v4(ctx, "GetRetargetingGoals", param, dry_run, output_format, output)

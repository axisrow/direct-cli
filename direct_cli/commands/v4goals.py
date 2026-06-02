"""Yandex Direct v4 Live goals commands."""

import click

from ..i18n import t
from ..utils import parse_ids
from ..v4.emit import emit_or_call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _campaign_ids_param(campaign_ids: str) -> dict:
    """Build the v4 Live CampaignIDInfo parameter."""
    try:
        ids = parse_ids(campaign_ids)
    except ValueError as exc:
        raise click.UsageError(str(exc))
    if not ids:
        raise click.UsageError(t("--campaign-ids must not be empty"))
    return {"CampaignIDS": ids}


@click.group(epilog=V4_EPILOG)
def v4goals():
    """Yandex Direct v4 Live goals commands."""


@v4_method_contract("GetStatGoals")
@v4goals.command(name="get-stat-goals")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get_stat_goals(ctx, campaign_ids, output_format, output, dry_run):
    """Get Yandex Metrica goals available for campaigns."""
    param = _campaign_ids_param(campaign_ids)
    emit_or_call_v4(ctx, "GetStatGoals", param, dry_run, output_format, output)


@v4_method_contract("GetRetargetingGoals")
@v4goals.command(name="get-retargeting-goals")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get_retargeting_goals(ctx, campaign_ids, output_format, output, dry_run):
    """Get retargeting goals for campaigns."""
    param = _campaign_ids_param(campaign_ids)
    emit_or_call_v4(ctx, "GetRetargetingGoals", param, dry_run, output_format, output)

"""Yandex Direct v4 Live goals commands."""

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _campaign_ids_param(campaign_ids: str) -> dict:
    """Build the v4 Live CampaignIDInfo parameter."""
    try:
        ids = parse_ids(campaign_ids)
    except ValueError as exc:
        raise click.UsageError(str(exc))
    if not ids:
        raise click.UsageError("--campaign-ids must not be empty")
    return {"CampaignIDS": ids}


def _run_goals_command(
    ctx,
    method: str,
    campaign_ids: str,
    output_format: str,
    output: str,
    dry_run: bool,
) -> None:
    param = _campaign_ids_param(campaign_ids)
    if dry_run:
        format_output(build_v4_body(method, param), "json", None)
        return

    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, method, param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


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
    _run_goals_command(
        ctx,
        "GetStatGoals",
        campaign_ids,
        output_format,
        output,
        dry_run,
    )


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
    _run_goals_command(
        ctx,
        "GetRetargetingGoals",
        campaign_ids,
        output_format,
        output,
        dry_run,
    )

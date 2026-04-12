"""
Campaigns commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import (
    parse_ids,
    build_selection_criteria,
    build_common_params,
    get_default_fields,
)


@click.group()
def campaigns():
    """Manage campaigns"""


@campaigns.command()
@click.option("--ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status (ACTIVE, SUSPENDED, etc.)")
@click.option("--types", help="Filter by types (TEXT_CAMPAIGN, etc.)")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (json/table/csv/tsv)",
)
@click.option("--output", help="Output file")
@click.option(
    "--fields", help="Comma-separated field names (default: all common fields)"
)
@click.pass_context
def get(ctx, ids, status, types, limit, fetch_all, output_format, output, fields):
    """Get campaigns"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        # Parse field names
        field_names = fields.split(",") if fields else get_default_fields("campaigns")

        # Build selection criteria
        criteria = build_selection_criteria(
            ids=parse_ids(ids), status=status, types=types
        )

        # Build params
        params = build_common_params(
            criteria=criteria, field_names=field_names, limit=limit
        )

        body = {"method": "get", "params": params}

        result = client.campaigns().post(data=body)

        if fetch_all:
            # Get all pages
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--name", required=True, help="Campaign name")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option(
    "--type",
    "campaign_type",
    default="TEXT_CAMPAIGN",
    help=(
        "Campaign type (case-insensitive). Convenience flags only build "
        "a TEXT_CAMPAIGN payload; for other types "
        "(MOBILE_APP_CAMPAIGN, DYNAMIC_TEXT_CAMPAIGN, ...) pass the "
        "matching nested object via --json."
    ),
)
@click.option("--budget", type=int, help="Daily budget in currency units")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, start_date, campaign_type, budget, end_date, extra_json, dry_run):
    """Add new campaign"""
    try:
        # Normalize --type so ``text_campaign`` / ``text-campaign`` /
        # ``TEXT-CAMPAIGN`` all map to ``TEXT_CAMPAIGN``.  Previously any
        # non-default value was silently dropped and the CLI hard-coded
        # ``TextCampaign`` regardless — see axisrow/direct-cli#23.
        campaign_type_norm = (
            (campaign_type or "TEXT_CAMPAIGN").upper().replace("-", "_")
        )

        campaign_data = {"Name": name, "StartDate": start_date}

        if campaign_type_norm == "TEXT_CAMPAIGN":
            campaign_data["TextCampaign"] = {
                "BiddingStrategy": {
                    "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
                    "Network": {"BiddingStrategyType": "SERVING_OFF"},
                },
                "Settings": [],
            }
        elif not extra_json:
            raise click.UsageError(
                f"--type {campaign_type} requires --json with the "
                f"campaign-type-specific nested object "
                f"(e.g. DynamicTextCampaign, SmartCampaign, MobileAppCampaign)."
            )

        if budget:
            campaign_data["DailyBudget"] = {
                "Amount": budget * 1000000,
                "Mode": "STANDARD",
            }

        if end_date:
            campaign_data["EndDate"] = end_date

        if extra_json:
            extra = json.loads(extra_json)
            campaign_data.update(extra)

        body = {"method": "add", "params": {"Campaigns": [campaign_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--name", help="New campaign name")
@click.option("--status", help="New status")
@click.option("--budget", type=int, help="New daily budget")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, campaign_id, name, status, budget, extra_json, dry_run):
    """Update campaign"""
    try:
        campaign_data = {"Id": campaign_id}

        if name:
            campaign_data["Name"] = name

        if status:
            campaign_data["Status"] = status

        if budget:
            campaign_data["DailyBudget"] = {
                "Amount": budget * 1000000,
                "Mode": "STANDARD",
            }

        if extra_json:
            extra = json.loads(extra_json)
            campaign_data.update(extra)

        body = {"method": "update", "params": {"Campaigns": [campaign_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.pass_context
def delete(ctx, campaign_id):
    """Delete campaign"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.pass_context
def archive(ctx, campaign_id):
    """Archive campaign"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "archive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.pass_context
def unarchive(ctx, campaign_id):
    """Unarchive campaign"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


campaigns.add_command(get, name="list")


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.pass_context
def suspend(ctx, campaign_id):
    """Suspend campaign"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.pass_context
def resume(ctx, campaign_id):
    """Resume campaign"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

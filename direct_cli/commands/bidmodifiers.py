"""
BidModifiers commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def bidmodifiers():
    """Manage bid modifiers"""


@bidmodifiers.command()
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(ctx, campaign_ids, adgroup_ids, limit, fetch_all, output_format, output):
    """Get bid modifiers"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type", "ModifierValue"],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.bidmodifiers().post(data=body)

        if fetch_all:
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


@bidmodifiers.command()
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option(
    "--type",
    "modifier_type",
    required=True,
    help="Modifier type (DEMOGRAPHICS, MOBILE, etc.)",
)
@click.option("--value", type=float, required=True, help="Modifier value")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, campaign_id, modifier_type, value, extra_json, dry_run):
    """Set bid modifier"""
    try:
        modifier_data = {
            "CampaignId": campaign_id,
            "Type": modifier_type,
            "BidModifier": value,
        }

        if extra_json:
            extra = json.loads(extra_json)
            modifier_data.update(extra)

        body = {"method": "set", "params": {"BidModifiers": [modifier_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bidmodifiers.command()
@click.option("--id", "modifier_id", required=True, type=int, help="Modifier ID")
@click.option("--enabled/--disabled", "enabled", default=True, help="Enable or disable")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def toggle(ctx, modifier_id, enabled, dry_run):
    """Toggle bid modifier state"""
    try:
        body = {
            "method": "set",
            "params": {
                "BidModifiers": [
                    {
                        "Id": modifier_id,
                        "Enabled": enabled,
                    }
                ]
            },
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bidmodifiers.command()
@click.option("--id", "modifier_id", required=True, type=int, help="Modifier ID")
@click.pass_context
def delete(ctx, modifier_id):
    """Delete bid modifier"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [modifier_id]}},
        }

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


bidmodifiers.add_command(get, name="list")

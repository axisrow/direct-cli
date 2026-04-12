"""
Ad Groups commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, get_default_fields


@click.group()
def adgroups():
    """Manage ad groups"""


@adgroups.command()
@click.option("--ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--types", help="Filter by types")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(
    ctx,
    ids,
    campaign_ids,
    status,
    types,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
):
    """Get ad groups"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("adgroups")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if status:
            criteria["Statuses"] = [status]
        if types:
            criteria["Types"] = types.split(",")

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.adgroups().post(data=body)

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


@adgroups.command()
@click.option("--name", required=True, help="Ad group name")
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option(
    "--type",
    "group_type",
    default="TEXT_AD_GROUP",
    help=(
        "Ad group type (case-insensitive). The Yandex Direct API derives "
        "the group type from nested objects (MobileAppAdGroup / "
        "DynamicTextAdGroup / SmartAdGroup / ...), not from a top-level "
        "Type discriminator. Convenience flags only build a TEXT_AD_GROUP; "
        "for other types pass the matching nested object via --json."
    ),
)
@click.option("--region-ids", help="Comma-separated region IDs")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, campaign_id, group_type, region_ids, extra_json, dry_run):
    """Add new ad group"""
    try:
        # Yandex Direct API rejects an explicit top-level "Type" field on
        # AdGroupAddItem — the group type is inferred from the presence of
        # MobileAppAdGroup / DynamicTextAdGroup / SmartAdGroup / etc.
        # sub-objects, exactly like Ads (see fix in commands/ads.py).
        # Previously --type was accepted but silently discarded — users
        # passing --type MOBILE_APP_AD_GROUP got a TEXT_AD_GROUP with no
        # warning.  Now we normalize case and fail loudly if the caller
        # asks for anything except TEXT_AD_GROUP.  See axisrow/direct-cli#23.
        # Refs: https://yandex.ru/dev/direct/doc/ref-v5/adgroups/add.html
        group_type_norm = (group_type or "TEXT_AD_GROUP").upper().replace("-", "_")

        if group_type_norm != "TEXT_AD_GROUP" and not extra_json:
            raise click.UsageError(
                f"--type {group_type} requires --json with the "
                f"ad-group-type-specific nested object "
                f"(e.g. DynamicTextAdGroup, SmartAdGroup, MobileAppAdGroup)."
            )

        adgroup_data = {"Name": name, "CampaignId": campaign_id}

        if region_ids:
            adgroup_data["RegionIds"] = parse_ids(region_ids)

        if extra_json:
            extra = json.loads(extra_json)
            adgroup_data.update(extra)

        body = {"method": "add", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--name", help="New ad group name")
@click.option("--status", help="New status")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, adgroup_id, name, status, extra_json, dry_run):
    """Update ad group"""
    try:
        adgroup_data = {"Id": adgroup_id}

        if name:
            adgroup_data["Name"] = name

        if status:
            adgroup_data["Status"] = status

        if extra_json:
            extra = json.loads(extra_json)
            adgroup_data.update(extra)

        body = {"method": "update", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.pass_context
def delete(ctx, adgroup_id):
    """Delete ad group"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [adgroup_id]}},
        }

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


adgroups.add_command(get, name="list")

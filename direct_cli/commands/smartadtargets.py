"""
SmartAdTargets commands
"""

import json

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def smartadtargets():
    """Manage smart ad targets"""


@smartadtargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, adgroup_ids, limit, fetch_all, output_format, output, fields):
    """Get smart ad targets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else ["Id", "CampaignId", "AdGroupId", "Status", "ServingStatus"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.smartadtargets().post(data=body)

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


@smartadtargets.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option(
    "--type",
    "target_type",
    help=(
        "Legacy UX hint; NOT forwarded to the API. SmartAdTargetAddItem "
        "has no top-level Type field — pass real fields like "
        "``Name``, ``Audience``, ``Conditions`` and bids via --json."
    ),
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, adgroup_id, target_type, extra_json, dry_run):
    """Add smart ad target"""
    try:
        target_data = {"AdGroupId": adgroup_id}
        _ = target_type

        if extra_json:
            target_data.update(json.loads(extra_json))

        if len(target_data) == 1:
            raise click.UsageError(
                "Provide --json with SmartAdTargetAddItem fields "
                '(e.g. {"Name":"Audience A","Audience":"ALL_SEGMENTS"}).'
            )

        body = {"method": "add", "params": {"SmartAdTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option(
    "--type",
    "target_type",
    help=(
        "Legacy UX hint; NOT forwarded to the API. SmartAdTargetAddItem "
        "has no top-level Type field — pass real fields via --json."
    ),
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, target_id, target_type, extra_json, dry_run):
    """Update smart ad target"""
    try:
        target_data = {"Id": target_id}
        _ = target_type
        if extra_json:
            target_data.update(json.loads(extra_json))
        if len(target_data) == 1:
            raise click.UsageError("Provide --json with fields to update")

        body = {"method": "update", "params": {"SmartAdTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, target_id, dry_run):
    """Delete smart ad target"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, target_id, dry_run):
    """Suspend smart ad target"""
    try:
        body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, target_id, dry_run):
    """Resume smart ad target"""
    try:
        body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@smartadtargets.command(name="set-bids")
@click.option("--id", "target_id", type=int, help="Target ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--average-cpc", type=float, help="Average CPC")
@click.option("--average-cpa", type=float, help="Average CPA")
@click.option("--priority", help="Strategy priority")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_bids(
    ctx,
    target_id,
    adgroup_id,
    campaign_id,
    average_cpc,
    average_cpa,
    priority,
    extra_json,
    dry_run,
):
    """Set smart ad target bids"""
    try:
        bid_data = {}
        if target_id is not None:
            bid_data["Id"] = target_id
        if adgroup_id is not None:
            bid_data["AdGroupId"] = adgroup_id
        if campaign_id is not None:
            bid_data["CampaignId"] = campaign_id
        if average_cpc is not None:
            bid_data["AverageCpc"] = int(average_cpc * 1000000)
        if average_cpa is not None:
            bid_data["AverageCpa"] = int(average_cpa * 1000000)
        if priority:
            bid_data["StrategyPriority"] = priority
        if extra_json:
            bid_data.update(json.loads(extra_json))
        if not bid_data:
            raise click.UsageError("Provide target selection and bid fields for set-bids")

        body = {"method": "setBids", "params": {"Bids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.smartadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


smartadtargets.add_command(get, name="list")

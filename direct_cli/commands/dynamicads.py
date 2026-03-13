"""
DynamicAds (Webpages) commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def dynamicads():
    """Manage dynamic ad targets"""


@dynamicads.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, adgroup_ids, limit, fetch_all, output_format, output, fields):
    """Get dynamic ad targets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else ["Id", "AdGroupId", "Condition", "Bid"]
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

        result = client.dynamicads().post(data=body)

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


@dynamicads.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option(
    "--condition", required=True, help='Target condition (e.g., "contains:product")'
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, adgroup_id, condition, extra_json, dry_run):
    """Add dynamic ad target"""
    try:
        target_data = {"AdGroupId": adgroup_id, "Condition": condition}

        if extra_json:
            extra = json.loads(extra_json)
            target_data.update(extra)

        body = {"method": "add", "params": {"Webpages": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.dynamicads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

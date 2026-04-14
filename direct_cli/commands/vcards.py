"""
VCards commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def vcards():
    """Manage vCards"""


@vcards.command()
@click.option("--ids", help="Comma-separated vCard IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get vCards"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",")
            if fields
            else ["Id", "CampaignId", "Country", "City", "CompanyName"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.vcards().post(data=body)

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


@vcards.command()
@click.option("--json", "vcard_json", required=True, help="vCard data in JSON")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, vcard_json, dry_run):
    """Add vCard"""
    try:
        body = {"method": "add", "params": {"VCards": [json.loads(vcard_json)]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.vcards().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@vcards.command()
@click.option("--id", "vcard_id", required=True, type=int, help="vCard ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, vcard_id, dry_run):
    """Delete vCard"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [vcard_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.vcards().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

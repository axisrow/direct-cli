"""
AdImages commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, get_default_fields


@click.group()
def adimages():
    """Manage ad images"""


@adimages.command()
@click.option("--ids", help="Comma-separated image IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get ad images"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else get_default_fields("adimages")
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.adimages().post(data=body)

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


@adimages.command()
@click.option("--json", "image_json", required=True, help="Ad image data in JSON")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, image_json, dry_run):
    """Add ad image"""
    try:
        body = {"method": "add", "params": {"AdImages": [json.loads(image_json)]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adimages().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adimages.command()
@click.option("--hash", "image_hash", required=True, help="Ad image hash")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, image_hash, dry_run):
    """Delete ad image"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"AdImageHashes": [image_hash]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adimages().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

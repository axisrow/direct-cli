"""
AdImages commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, load_base64_file, parse_ids


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
@click.option("--name", required=True, help="Image name")
@click.option("--image-data", help="Base64-encoded image data")
@click.option("--image-file", help="Path to an image file to base64-encode")
@click.option("--type", "image_type", help="Ad image type")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, image_data, image_file, image_type, dry_run):
    """Add ad image"""
    try:
        if bool(image_data) == bool(image_file):
            raise click.UsageError(
                "Provide exactly one of --image-data or --image-file"
            )

        payload = {
            "Name": name,
            "ImageData": image_data if image_data else load_base64_file(image_file),
        }
        if image_type:
            payload["Type"] = image_type

        body = {"method": "add", "params": {"AdImages": [payload]}}

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

    except click.UsageError:
        raise
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

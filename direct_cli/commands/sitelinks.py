"""
Sitelinks commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids, parse_sitelink_specs


@click.group()
def sitelinks():
    """Manage sitelinks"""


@sitelinks.command()
@click.option("--ids", help="Comma-separated sitelink IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get sitelinks"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("sitelinks")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.sitelinks().post(data=body)

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


@sitelinks.command()
@click.option(
    "--sitelink",
    "sitelinks_specs",
    multiple=True,
    required=True,
    help="Sitelink spec: TITLE|HREF[|DESCRIPTION]",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, sitelinks_specs, dry_run):
    """Add sitelinks set"""
    try:
        body = {
            "method": "add",
            "params": {
                "SitelinksSets": [
                    {"Sitelinks": parse_sitelink_specs(list(sitelinks_specs))}
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

        result = client.sitelinks().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@sitelinks.command()
@click.option("--id", "set_id", required=True, type=int, help="Sitelinks set ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, set_id, dry_run):
    """Delete sitelinks set"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [set_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.sitelinks().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

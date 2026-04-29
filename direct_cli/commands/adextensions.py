"""
AdExtensions commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import add_criteria_csv, get_default_fields, parse_ids


@click.group()
def adextensions():
    """Manage ad extensions"""


@adextensions.command()
@click.option("--ids", help="Comma-separated extension IDs")
@click.option("--types", help="Filter by types")
@click.option("--states", help="Comma-separated states")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--modified-since", help="ModifiedSince datetime")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    types,
    states,
    statuses,
    modified_since,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get ad extensions"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else get_default_fields("adextensions")
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if types:
            criteria["Types"] = types.split(",")
        add_criteria_csv(criteria, "States", states, upper=True)
        add_criteria_csv(criteria, "Statuses", statuses, upper=True)
        if modified_since:
            criteria["ModifiedSince"] = modified_since

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.adextensions().post(data=body)

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


@adextensions.command()
@click.option("--callout-text", required=True, help="Callout text")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, callout_text, dry_run):
    """Add ad extension (callout)"""
    try:
        ext_data = {"Callout": {"CalloutText": callout_text}}

        body = {"method": "add", "params": {"AdExtensions": [ext_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adextensions().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adextensions.command()
@click.option("--id", "extension_id", required=True, type=int, help="Extension ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, extension_id, dry_run):
    """Delete ad extension"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [extension_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adextensions().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

"""
NegativeKeywordSharedSets commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def negativekeywordsharedsets():
    """Manage negative keyword shared sets"""


@negativekeywordsharedsets.command()
@click.option("--ids", help="Comma-separated set IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get negative keyword shared sets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",") if fields else ["Id", "Name", "NegativeKeywords"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.negativekeywordsharedsets().post(data=body)

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


@negativekeywordsharedsets.command()
@click.option("--name", required=True, help="Set name")
@click.option("--keywords", required=True, help="Comma-separated negative keywords")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, keywords, dry_run):
    """Add negative keyword shared set"""
    try:
        set_data = {
            "Name": name,
            "NegativeKeywords": [{"Keyword": k.strip()} for k in keywords.split(",")],
        }

        body = {"method": "add", "params": {"NegativeKeywordSharedSets": [set_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.negativekeywordsharedsets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

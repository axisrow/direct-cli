"""
RetargetingLists commands
"""

import json

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def retargeting():
    """Manage retargeting lists"""


@retargeting.command()
@click.option("--ids", help="Comma-separated list IDs")
@click.option("--types", help="Filter by types")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, types, limit, fetch_all, output_format, output, fields):
    """Get retargeting lists"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("retargetinglists")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if types:
            criteria["Types"] = types.split(",")

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.retargeting().post(data=body)

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


_RETARGETING_LIST_TYPES = ["RETARGETING", "AUDIENCE"]


@retargeting.command()
@click.option("--name", required=True, help="List name")
@click.option(
    "--type",
    "list_type",
    default="RETARGETING",
    type=click.Choice(_RETARGETING_LIST_TYPES, case_sensitive=False),
    help=(
        "Retargeting list type (case-insensitive). Yandex Direct accepts "
        "only RETARGETING (default — Metrica goals/segments + Audience "
        "segments, usable in text & image / mobile-app campaigns) or "
        "AUDIENCE (any goals/segments, usable in display campaigns). "
        "See axisrow/direct-cli#25."
    ),
)
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, list_type, extra_json, dry_run):
    """Add new retargeting list"""
    try:
        list_data = {"Name": name, "Type": list_type}

        if extra_json:
            list_data.update(json.loads(extra_json))

        body = {"method": "add", "params": {"RetargetingLists": [list_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@retargeting.command()
@click.option("--id", "list_id", required=True, type=int, help="Retargeting list ID")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, list_id, extra_json, dry_run):
    """Update retargeting list"""
    try:
        list_data = {"Id": list_id}
        if extra_json:
            list_data.update(json.loads(extra_json))
        if len(list_data) == 1:
            raise click.UsageError("Provide --json with fields to update")

        body = {"method": "update", "params": {"RetargetingLists": [list_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@retargeting.command()
@click.option("--id", "list_id", required=True, type=int, help="Retargeting list ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, list_id, dry_run):
    """Delete retargeting list"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [list_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.retargeting().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


retargeting.add_command(get, name="list")

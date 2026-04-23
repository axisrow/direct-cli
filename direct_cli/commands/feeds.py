"""
Feeds commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def feeds():
    """Manage feeds"""


@feeds.command()
@click.option("--ids", help="Comma-separated feed IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields):
    """Get feeds"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("feeds")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.feeds().post(data=body)

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


@feeds.command()
@click.option("--name", required=True, help="Feed name")
@click.option("--url", required=True, help="Feed URL")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, url, dry_run):
    """Add feed"""
    try:
        feed_data = {
            "Name": name,
            "SourceType": "URL",
            "UrlFeed": {"Url": url},
        }

        body = {"method": "add", "params": {"Feeds": [feed_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.feeds().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@feeds.command()
@click.option("--id", "feed_id", required=True, type=int, help="Feed ID")
@click.option("--name", help="Feed name")
@click.option("--url", help="Feed URL")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, feed_id, name, url, dry_run):
    """Update feed"""
    try:
        feed_data = {"Id": feed_id}

        if name:
            feed_data["Name"] = name
        if url:
            feed_data["UrlFeed"] = {"Url": url}
        if len(feed_data) == 1:
            raise click.UsageError("Provide at least one of --name or --url")

        body = {"method": "update", "params": {"Feeds": [feed_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.feeds().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@feeds.command()
@click.option("--id", "feed_id", required=True, type=int, help="Feed ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, feed_id, dry_run):
    """Delete feed"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [feed_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.feeds().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

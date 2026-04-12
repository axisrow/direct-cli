"""
Feeds commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


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

        field_names = (
            fields.split(",") if fields else ["Id", "Name", "Source", "Status"]
        )

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
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, name, url, extra_json, dry_run):
    """Add feed

    Creates a URL feed by default.  The Yandex Direct API requires both
    the ``SourceType`` discriminator **and** the nested object matching
    that type (``UrlFeed`` / ``FileFeed`` / ``BusinessType``).  The old
    top-level ``Source`` field was invalid (the nested object holds the
    URL).  Pass ``--json`` to override for file feeds or business feeds.
    """
    try:
        # Detect the --url / --json UrlFeed collision up front.  Without
        # this check, ``feed_data.update(extra)`` below would silently
        # replace the ``UrlFeed`` object built from --url with whatever
        # the caller passed in --json, and the --url value would vanish
        # from the request — see axisrow/direct-cli#23.
        extra = json.loads(extra_json) if extra_json else {}
        if "UrlFeed" in extra:
            raise click.UsageError(
                "Pass the feed URL via exactly one of --url or "
                "--json '{\"UrlFeed\":{...}}', not both."
            )

        feed_data = {
            "Name": name,
            "SourceType": "URL",
            "UrlFeed": {"Url": url},
        }

        if extra:
            feed_data.update(extra)

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

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@feeds.command()
@click.option("--id", "feed_id", required=True, type=int, help="Feed ID")
@click.option("--name", help="Feed name")
@click.option("--url", help="Feed URL")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, feed_id, name, url, extra_json, dry_run):
    """Update feed"""
    try:
        # Mirror of the --url / --json UrlFeed collision check in
        # ``add`` — see axisrow/direct-cli#23.  Without it, --url would
        # be silently replaced by a UrlFeed object in --json.
        extra = json.loads(extra_json) if extra_json else {}
        if url and "UrlFeed" in extra:
            raise click.UsageError(
                "Pass the feed URL via exactly one of --url or "
                "--json '{\"UrlFeed\":{...}}', not both."
            )

        feed_data = {"Id": feed_id}

        if name:
            feed_data["Name"] = name
        if url:
            feed_data["UrlFeed"] = {"Url": url}
        if extra:
            feed_data.update(extra)
        if len(feed_data) == 1:
            raise click.UsageError(
                "Provide at least one of --name, --url, or --json for update"
            )

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
@click.pass_context
def delete(ctx, feed_id):
    """Delete feed"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [feed_id]}}}

        result = client.feeds().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


feeds.add_command(get, name="list")

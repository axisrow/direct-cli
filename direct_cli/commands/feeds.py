"""
Feeds commands
"""

from typing import Dict, Optional

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids

_YES_NO = ["YES", "NO"]


def _url_feed_payload(
    url: Optional[str] = None,
    remove_utm_tags: Optional[str] = None,
    login: Optional[str] = None,
    password: Optional[str] = None,
    clear_login: bool = False,
    clear_password: bool = False,
) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    if url:
        payload["Url"] = url
    if remove_utm_tags:
        payload["RemoveUtmTags"] = remove_utm_tags.upper()
    if clear_login:
        payload["Login"] = None
    elif login:
        payload["Login"] = login
    if clear_password:
        payload["Password"] = None
    elif password:
        payload["Password"] = password
    return payload


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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(ctx, ids, limit, fetch_all, output_format, output, fields, dry_run):
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

        params = {"FieldNames": field_names}
        if criteria:
            params["SelectionCriteria"] = criteria

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

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
@click.option(
    "--remove-utm-tags",
    type=click.Choice(_YES_NO, case_sensitive=False),
    help="UrlFeed.RemoveUtmTags: delete UTM tags from feed links, YES or NO.",
)
@click.option("--feed-login", help="UrlFeed.Login for protected feed URL")
@click.option("--feed-password", help="UrlFeed.Password for protected feed URL")
@click.option(
    "--business-type",
    required=True,
    type=click.Choice(
        ["RETAIL", "HOTELS", "REALTY", "AUTOMOBILES", "FLIGHTS", "OTHER"],
        case_sensitive=False,
    ),
    help="Business type (BusinessTypeEnum)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx, name, url, remove_utm_tags, feed_login, feed_password, business_type, dry_run
):
    """Add feed"""
    try:
        feed_data = {
            "Name": name,
            "BusinessType": business_type.upper(),
            "SourceType": "URL",
            "UrlFeed": _url_feed_payload(
                url, remove_utm_tags, feed_login, feed_password
            ),
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
@click.option(
    "--remove-utm-tags",
    type=click.Choice(_YES_NO, case_sensitive=False),
    help="UrlFeed.RemoveUtmTags: delete UTM tags from feed links, YES or NO.",
)
@click.option("--feed-login", help="UrlFeed.Login for protected feed URL")
@click.option("--feed-password", help="UrlFeed.Password for protected feed URL")
@click.option("--clear-feed-login", is_flag=True, help="Set UrlFeed.Login to null")
@click.option(
    "--clear-feed-password", is_flag=True, help="Set UrlFeed.Password to null"
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    feed_id,
    name,
    url,
    remove_utm_tags,
    feed_login,
    feed_password,
    clear_feed_login,
    clear_feed_password,
    dry_run,
):
    """Update feed"""
    try:
        if feed_login is not None and clear_feed_login:
            raise click.UsageError(
                "Use either --feed-login or --clear-feed-login, not both"
            )
        if feed_password is not None and clear_feed_password:
            raise click.UsageError(
                "Use either --feed-password or --clear-feed-password, not both"
            )

        feed_data = {"Id": feed_id}

        if name:
            feed_data["Name"] = name
        url_feed = _url_feed_payload(
            url,
            remove_utm_tags,
            feed_login,
            feed_password,
            clear_feed_login,
            clear_feed_password,
        )
        if url_feed:
            feed_data["UrlFeed"] = url_feed
        if len(feed_data) == 1:
            raise click.UsageError(
                "Provide at least one of --name, --url, --remove-utm-tags, "
                "--feed-login, --feed-password, --clear-feed-login, or "
                "--clear-feed-password"
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

"""
Keywords commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, get_default_fields


@click.group()
def keywords():
    """Manage keywords"""


@keywords.command()
@click.option("--ids", help="Comma-separated keyword IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(
    ctx,
    ids,
    adgroup_ids,
    campaign_ids,
    status,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
):
    """Get keywords"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("keywords")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if status:
            criteria["Statuses"] = [status]

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.keywords().post(data=body)

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


@keywords.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--keyword", required=True, help="Keyword text")
@click.option("--bid", type=float, help="Search bid")
@click.option("--context-bid", type=float, help="Context bid")
@click.option("--user-param-1", help="User parameter 1")
@click.option("--user-param-2", help="User parameter 2")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    adgroup_id,
    keyword,
    bid,
    context_bid,
    user_param_1,
    user_param_2,
    extra_json,
    dry_run,
):
    """Add new keyword"""
    try:
        keyword_data = {"AdGroupId": adgroup_id, "Keyword": keyword}

        if bid:
            keyword_data["Bid"] = int(bid * 1000000)
        if context_bid:
            keyword_data["ContextBid"] = int(context_bid * 1000000)
        if user_param_1:
            keyword_data["UserParam1"] = user_param_1
        if user_param_2:
            keyword_data["UserParam2"] = user_param_2

        if extra_json:
            extra = json.loads(extra_json)
            keyword_data.update(extra)

        body = {"method": "add", "params": {"Keywords": [keyword_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--bid", type=float, help="Search bid")
@click.option("--context-bid", type=float, help="Context bid")
@click.option("--status", help="New status")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, keyword_id, bid, context_bid, status, extra_json, dry_run):
    """Update keyword"""
    try:
        keyword_data = {"Id": keyword_id}

        if bid:
            keyword_data["Bid"] = int(bid * 1000000)
        if context_bid:
            keyword_data["ContextBid"] = int(context_bid * 1000000)
        if status:
            keyword_data["Status"] = status

        if extra_json:
            extra = json.loads(extra_json)
            keyword_data.update(extra)

        body = {"method": "update", "params": {"Keywords": [keyword_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.pass_context
def delete(ctx, keyword_id):
    """Delete keyword"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.pass_context
def archive(ctx, keyword_id):
    """Archive keyword"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "archive",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.pass_context
def unarchive(ctx, keyword_id):
    """Unarchive keyword"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.pass_context
def suspend(ctx, keyword_id):
    """Suspend keyword"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.pass_context
def resume(ctx, keyword_id):
    """Resume keyword"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
        }

        result = client.keywords().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

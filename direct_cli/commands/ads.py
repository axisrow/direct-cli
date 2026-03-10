"""
Ads commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def ads():
    """Manage ads"""
    pass


@ads.command()
@click.option("--ids", help="Comma-separated ad IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
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
    campaign_ids,
    adgroup_ids,
    status,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
):
    """Get ads"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",")
            if fields
            else ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if status:
            criteria["Statuses"] = [status]

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.ads().post(data=body)

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


@ads.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--type", "ad_type", default="TEXT_AD", help="Ad type")
@click.option("--title", help="Ad title")
@click.option("--text", help="Ad text")
@click.option("--href", help="Ad URL")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, adgroup_id, ad_type, title, text, href, extra_json, dry_run):
    """Add new ad"""
    try:
        ad_data = {"AdGroupId": adgroup_id, "Type": ad_type}

        if ad_type == "TEXT_AD":
            ad_data["TextAd"] = {}
            if title:
                ad_data["TextAd"]["Title"] = title
            if text:
                ad_data["TextAd"]["Text"] = text
            if href:
                ad_data["TextAd"]["Href"] = href

        if extra_json:
            extra = json.loads(extra_json)
            ad_data.update(extra)

        body = {"method": "add", "params": {"Ads": [ad_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--status", help="New status")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, ad_id, status, extra_json, dry_run):
    """Update ad"""
    try:
        ad_data = {"Id": ad_id}

        if status:
            ad_data["Status"] = status

        if extra_json:
            extra = json.loads(extra_json)
            ad_data.update(extra)

        body = {"method": "update", "params": {"Ads": [ad_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def delete(ctx, ad_id):
    """Delete ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def archive(ctx, ad_id):
    """Archive ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "archive", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def unarchive(ctx, ad_id):
    """Unarchive ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [ad_id]}},
        }

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def suspend(ctx, ad_id):
    """Suspend ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def resume(ctx, ad_id):
    """Resume ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.pass_context
def moderate(ctx, ad_id):
    """Moderate ad"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {"method": "moderate", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

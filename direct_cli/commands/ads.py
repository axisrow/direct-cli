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


@ads.command()
@click.option("--ids", help="Comma-separated ad IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--status", help="Filter by status")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated top-level field names")
@click.option(
    "--text-ad-fields", help="Comma-separated TextAd field names (e.g. Title,Text,Href)"
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
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
    text_ad_fields,
    dry_run,
):
    """Get ads"""
    try:
        field_names = (
            fields.split(",")
            if fields
            else ["Id", "CampaignId", "AdGroupId", "Status", "State", "Type"]
        )

        text_ad_field_names = (
            text_ad_fields.split(",")
            if text_ad_fields
            else ["Title", "Title2", "Text", "Href"]
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

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
            "TextAdFieldNames": text_ad_field_names,
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

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
@click.option(
    "--type",
    "ad_type",
    default="TEXT_AD",
    help=(
        "Ad type (case-insensitive). The convenience flags "
        "--title/--text/--href only build a payload for TEXT_AD. "
        "For other ad types (e.g. TEXT_IMAGE_AD, MOBILE_APP_AD) "
        "pass the nested object via --json."
    ),
)
@click.option("--title", help="Ad title (TEXT_AD only)")
@click.option("--text", help="Ad text (TEXT_AD only)")
@click.option("--href", help="Ad URL (TEXT_AD only)")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, adgroup_id, ad_type, title, text, href, extra_json, dry_run):
    """Add new ad"""
    try:
        # Normalize --type so case variants and hyphen forms (``text_ad``,
        # ``text-ad``) behave the same as ``TEXT_AD``.  Without this
        # normalization, the previous implementation silently dropped
        # --title/--text/--href for any value other than the exact
        # string ``"TEXT_AD"`` and the API responded with the very
        # misleading ``5008 None of the required fields were sent``
        # error — see axisrow/direct-cli#21.
        ad_type_norm = (ad_type or "TEXT_AD").upper().replace("-", "_")
        has_convenience_flags = any([title, text, href])

        if ad_type_norm != "TEXT_AD" and has_convenience_flags:
            raise click.UsageError(
                f"--type {ad_type} does not support --title/--text/--href "
                f"(these convenience flags only build a TEXT_AD payload). "
                f"Pass the nested ad object via --json, or use --type TEXT_AD."
            )

        ad_data = {"AdGroupId": adgroup_id}

        if ad_type_norm == "TEXT_AD" and has_convenience_flags:
            ad_data["TextAd"] = {"Mobile": "NO"}
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

    except click.UsageError:
        raise
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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, ad_id, dry_run):
    """Delete ad"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def archive(ctx, ad_id, dry_run):
    """Archive ad"""
    try:
        body = {"method": "archive", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def unarchive(ctx, ad_id, dry_run):
    """Unarchive ad"""
    try:
        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [ad_id]}},
        }

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, ad_id, dry_run):
    """Suspend ad"""
    try:
        body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, ad_id, dry_run):
    """Resume ad"""
    try:
        body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def moderate(ctx, ad_id, dry_run):
    """Moderate ad"""
    try:
        body = {"method": "moderate", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

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

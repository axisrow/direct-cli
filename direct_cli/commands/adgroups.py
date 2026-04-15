"""
Ad Groups commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_ids


@click.group()
def adgroups():
    """Manage ad groups"""


@adgroups.command()
@click.option("--ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--types", help="Filter by types")
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
    status,
    types,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
):
    """Get ad groups"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("adgroups")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if status:
            criteria["Statuses"] = [status]
        if types:
            criteria["Types"] = types.split(",")

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.adgroups().post(data=body)

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


@adgroups.command()
@click.option("--name", required=True, help="Ad group name")
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option(
    "--type",
    "group_type",
    default="TEXT_AD_GROUP",
    help="Ad group type",
)
@click.option("--region-ids", help="Comma-separated region IDs")
@click.option("--domain-url", help="Dynamic text ad group domain URL")
@click.option("--feed-id", type=int, help="Smart ad group feed ID")
@click.option("--ad-title-source", help="Smart ad group title source")
@click.option("--ad-body-source", help="Smart ad group body source")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    name,
    campaign_id,
    group_type,
    region_ids,
    domain_url,
    feed_id,
    ad_title_source,
    ad_body_source,
    dry_run,
):
    """Add new ad group"""
    try:
        group_type_norm = (group_type or "TEXT_AD_GROUP").upper().replace("-", "_")
        supported_types = {
            "TEXT_AD_GROUP",
            "DYNAMIC_TEXT_AD_GROUP",
            "SMART_AD_GROUP",
        }
        if group_type_norm not in supported_types:
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{group_type!r} is not one of "
                "'TEXT_AD_GROUP', 'DYNAMIC_TEXT_AD_GROUP', 'SMART_AD_GROUP'."
            )

        adgroup_data = {"Name": name, "CampaignId": campaign_id}

        if region_ids:
            adgroup_data["RegionIds"] = parse_ids(region_ids)
        if group_type_norm == "DYNAMIC_TEXT_AD_GROUP":
            if not domain_url:
                raise click.UsageError(
                    "--domain-url is required for DYNAMIC_TEXT_AD_GROUP"
                )
            adgroup_data["DynamicTextAdGroup"] = {"DomainUrl": domain_url}
        elif group_type_norm == "SMART_AD_GROUP":
            if feed_id is None:
                raise click.UsageError("--feed-id is required for SMART_AD_GROUP")
            smart_ad_group = {"FeedId": feed_id}
            if ad_title_source:
                smart_ad_group["AdTitleSource"] = ad_title_source
            if ad_body_source:
                smart_ad_group["AdBodySource"] = ad_body_source
            adgroup_data["SmartAdGroup"] = smart_ad_group

        body = {"method": "add", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--name", help="New ad group name")
@click.option("--status", help="New status")
@click.option("--region-ids", help="Comma-separated region IDs")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, adgroup_id, name, status, region_ids, dry_run):
    """Update ad group"""
    try:
        adgroup_data = {"Id": adgroup_id}

        if name:
            adgroup_data["Name"] = name

        if status:
            adgroup_data["Status"] = status
        if region_ids:
            adgroup_data["RegionIds"] = parse_ids(region_ids)

        body = {"method": "update", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, adgroup_id, dry_run):
    """Delete ad group"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [adgroup_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

"""
DynamicFeedAdTargets commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_condition_specs, parse_ids, to_micros


@click.group()
def dynamicfeedadtargets():
    """Manage dynamic feed ad targets"""


@dynamicfeedadtargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(
    ctx, ids, adgroup_ids, campaign_ids, limit, fetch_all, output_format, output, fields
):
    """Get dynamic feed ad targets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = (
            fields.split(",")
            if fields
            else ["Id", "AdGroupId", "CampaignId", "Name", "Bid", "ContextBid"]
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.dynamicfeedadtargets().post(data=body)

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


@dynamicfeedadtargets.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--name", required=True, help="Target name")
@click.option(
    "--condition",
    "conditions",
    multiple=True,
    help="Condition spec: OPERAND:OPERATOR:ARG1|ARG2",
)
@click.option("--bid", type=float, help="Search bid")
@click.option("--context-bid", type=float, help="Context bid")
@click.option(
    "--available-items-only",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="Restrict to currently available feed items",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx, adgroup_id, name, conditions, bid, context_bid, available_items_only, dry_run
):
    """Add dynamic feed ad target"""
    try:
        target_data = {
            "AdGroupId": adgroup_id,
            "Name": name,
        }
        parsed_conditions = (
            parse_condition_specs(list(conditions)) if conditions else None
        )
        if parsed_conditions:
            target_data["Conditions"] = parsed_conditions
        if bid is not None:
            target_data["Bid"] = to_micros(bid)
        if context_bid is not None:
            target_data["ContextBid"] = to_micros(context_bid)
        if available_items_only:
            target_data["AvailableItemsOnly"] = available_items_only.upper()

        body = {"method": "add", "params": {"DynamicFeedAdTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.dynamicfeedadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@dynamicfeedadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, target_id, dry_run):
    """Delete dynamic feed ad target"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [target_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.dynamicfeedadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@dynamicfeedadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, target_id, dry_run):
    """Suspend dynamic feed ad target"""
    try:
        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [target_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.dynamicfeedadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@dynamicfeedadtargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, target_id, dry_run):
    """Resume dynamic feed ad target"""
    try:
        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [target_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.dynamicfeedadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@dynamicfeedadtargets.command(name="set-bids")
@click.option("--id", "target_id", type=int, help="Target ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--bid", type=float, help="Search bid")
@click.option("--context-bid", type=float, help="Context bid")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_bids(ctx, target_id, adgroup_id, campaign_id, bid, context_bid, dry_run):
    """Set dynamic feed ad target bids"""
    try:
        bid_data = {}
        if target_id is not None:
            bid_data["Id"] = target_id
        if adgroup_id is not None:
            bid_data["AdGroupId"] = adgroup_id
        if campaign_id is not None:
            bid_data["CampaignId"] = campaign_id
        if bid is not None:
            bid_data["Bid"] = to_micros(bid)
        if context_bid is not None:
            bid_data["ContextBid"] = to_micros(context_bid)

        has_selector = any(k in bid_data for k in ("Id", "AdGroupId", "CampaignId"))
        has_bid = any(k in bid_data for k in ("Bid", "ContextBid"))
        if not has_selector:
            raise click.UsageError(
                "Provide a target selector (--id, --adgroup-id, or --campaign-id)"
            )
        if not has_bid:
            raise click.UsageError("Provide at least one bid (--bid or --context-bid)")

        body = {"method": "setBids", "params": {"Bids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.dynamicfeedadtargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()

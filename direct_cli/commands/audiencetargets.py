"""
AudienceTargets commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, to_micros


@click.group()
def audiencetargets():
    """Manage audience targets"""


@audiencetargets.command()
@click.option("--ids", help="Comma-separated target IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(ctx, ids, adgroup_ids, campaign_ids, limit, fetch_all, output_format, output):
    """Get audience targets"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": [
                "Id",
                "AdGroupId",
                "RetargetingListId",
                "State",
                "ContextBid",
            ],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.audiencetargets().post(data=body)

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


@audiencetargets.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option("--retargeting-list-id", type=int, help="Retargeting list ID")
@click.option("--interest-id", type=int, help="Interest ID")
@click.option("--bid", type=float, help="Context bid")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    adgroup_id,
    retargeting_list_id,
    interest_id,
    bid,
    priority,
    dry_run,
):
    """Add audience target"""
    try:
        if retargeting_list_id is None and interest_id is None:
            raise click.UsageError(
                "Provide at least one of --retargeting-list-id or --interest-id"
            )

        target_data = {
            "AdGroupId": adgroup_id,
        }
        if retargeting_list_id is not None:
            target_data["RetargetingListId"] = retargeting_list_id
        if interest_id is not None:
            target_data["InterestId"] = interest_id

        if bid is not None:
            target_data["ContextBid"] = to_micros(bid)
        if priority:
            target_data["StrategyPriority"] = priority

        body = {"method": "add", "params": {"AudienceTargets": [target_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.audiencetargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@audiencetargets.command(name="set-bids")
@click.option("--id", "target_id", type=int, help="Target ID")
@click.option("--adgroup-id", type=int, help="Ad group ID")
@click.option("--campaign-id", type=int, help="Campaign ID")
@click.option("--context-bid", type=float, help="Context bid")
@click.option("--priority", help="Strategy priority")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_bids(ctx, target_id, adgroup_id, campaign_id, context_bid, priority, dry_run):
    """Set audience target bids"""
    try:
        bid_data = {}
        if target_id is not None:
            bid_data["Id"] = target_id
        if adgroup_id is not None:
            bid_data["AdGroupId"] = adgroup_id
        if campaign_id is not None:
            bid_data["CampaignId"] = campaign_id
        if context_bid is not None:
            bid_data["ContextBid"] = to_micros(context_bid)
        if priority:
            bid_data["StrategyPriority"] = priority
        bid_fields = {
            k
            for k in ("ContextBid", "StrategyPriority")
            if k in bid_data
        }
        if not bid_data:
            raise click.UsageError(
                "Provide target selection and bid fields for set-bids"
            )
        if not bid_fields:
            raise click.UsageError(
                "Provide at least one bid field (--context-bid or --priority)"
            )

        body = {"method": "setBids", "params": {"Bids": [bid_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.audiencetargets().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, target_id, dry_run):
    """Delete audience target"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.audiencetargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, target_id, dry_run):
    """Suspend audience target"""
    try:
        body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.audiencetargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@audiencetargets.command()
@click.option("--id", "target_id", required=True, type=int, help="Target ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, target_id, dry_run):
    """Resume audience target"""
    try:
        body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [target_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.audiencetargets().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

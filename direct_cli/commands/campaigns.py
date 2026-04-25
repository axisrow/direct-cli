"""
Campaigns commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import (
    build_selection_criteria,
    build_common_params,
    get_default_fields,
    MICRO_RUBLES,
    parse_ids,
    parse_setting_specs,
)


@click.group()
def campaigns():
    """Manage campaigns"""


@campaigns.command()
@click.option("--ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status (ACTIVE, SUSPENDED, etc.)")
@click.option("--types", help="Filter by types (TEXT_CAMPAIGN, etc.)")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (json/table/csv/tsv)",
)
@click.option("--output", help="Output file")
@click.option(
    "--fields", help="Comma-separated field names (default: all common fields)"
)
@click.pass_context
def get(ctx, ids, status, types, limit, fetch_all, output_format, output, fields):
    """Get campaigns"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        # Parse field names
        field_names = fields.split(",") if fields else get_default_fields("campaigns")

        # Build selection criteria
        criteria = build_selection_criteria(
            ids=parse_ids(ids), status=status, types=types
        )

        # Build params
        params = build_common_params(
            criteria=criteria, field_names=field_names, limit=limit
        )

        body = {"method": "get", "params": params}

        result = client.campaigns().post(data=body)

        if fetch_all:
            # Get all pages
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


@campaigns.command()
@click.option("--name", required=True, help="Campaign name")
@click.option("--start-date", required=True, help="Start date (YYYY-MM-DD)")
@click.option(
    "--type",
    "campaign_type",
    default="TEXT_CAMPAIGN",
    help="Campaign type",
)
@click.option("--budget", type=MICRO_RUBLES, help="Daily budget in micro-rubles")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option(
    "--setting",
    "settings",
    multiple=True,
    help="Campaign setting spec: OPTION=VALUE",
)
@click.option("--search-strategy", help="Search bidding strategy type")
@click.option("--network-strategy", help="Network bidding strategy type")
@click.option(
    "--filter-average-cpc",
    type=MICRO_RUBLES,
    help="Smart campaign filter average CPC in micro-rubles",
)
@click.option("--counter-id", type=int, help="Smart campaign counter ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    name,
    start_date,
    campaign_type,
    budget,
    end_date,
    settings,
    search_strategy,
    network_strategy,
    filter_average_cpc,
    counter_id,
    dry_run,
):
    """Add new campaign"""
    try:
        campaign_type_norm = (
            (campaign_type or "TEXT_CAMPAIGN").upper().replace("-", "_")
        )
        supported_types = {
            "TEXT_CAMPAIGN",
            "DYNAMIC_TEXT_CAMPAIGN",
            "SMART_CAMPAIGN",
        }
        if campaign_type_norm not in supported_types:
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{campaign_type!r} is not one of "
                "'TEXT_CAMPAIGN', 'DYNAMIC_TEXT_CAMPAIGN', 'SMART_CAMPAIGN'."
            )

        campaign_data = {"Name": name, "StartDate": start_date}
        parsed_settings = parse_setting_specs(list(settings))
        if campaign_type_norm == "TEXT_CAMPAIGN":
            campaign_data["TextCampaign"] = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": (
                            search_strategy or "HIGHEST_POSITION"
                        )
                    },
                    "Network": {
                        "BiddingStrategyType": (
                            network_strategy or "SERVING_OFF"
                        )
                    },
                },
                "Settings": parsed_settings or [],
            }
        elif campaign_type_norm == "DYNAMIC_TEXT_CAMPAIGN":
            campaign_data["DynamicTextCampaign"] = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": (
                            search_strategy or "HIGHEST_POSITION"
                        )
                    },
                    "Network": {
                        "BiddingStrategyType": (
                            network_strategy or "SERVING_OFF"
                        )
                    },
                },
                "Settings": parsed_settings or [],
            }
        elif campaign_type_norm == "SMART_CAMPAIGN":
            network_strategy_type = network_strategy or "AVERAGE_CPC_PER_FILTER"
            smart_campaign = {
                "BiddingStrategy": {
                    "Search": {
                        "BiddingStrategyType": search_strategy or "SERVING_OFF"
                    },
                    "Network": {"BiddingStrategyType": network_strategy_type},
                }
            }
            if network_strategy_type == "AVERAGE_CPC_PER_FILTER":
                if filter_average_cpc is None:
                    raise click.UsageError(
                        "--filter-average-cpc is required for SMART_CAMPAIGN "
                        "with AVERAGE_CPC_PER_FILTER network strategy"
                    )
                smart_campaign["BiddingStrategy"]["Network"][
                    "AverageCpcPerFilter"
                ] = {"FilterAverageCpc": filter_average_cpc}
            if parsed_settings:
                smart_campaign["Settings"] = parsed_settings
            if counter_id is not None:
                smart_campaign["CounterId"] = counter_id
            campaign_data["SmartCampaign"] = smart_campaign

        if budget:
            campaign_data["DailyBudget"] = {
                "Amount": budget,
                "Mode": "STANDARD",
            }

        if end_date:
            campaign_data["EndDate"] = end_date

        body = {"method": "add", "params": {"Campaigns": [campaign_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--name", help="New campaign name")
@click.option("--status", help="New status")
@click.option("--budget", type=MICRO_RUBLES, help="New daily budget in micro-rubles")
@click.option("--start-date", help="New start date (YYYY-MM-DD)")
@click.option("--end-date", help="New end date (YYYY-MM-DD)")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(ctx, campaign_id, name, status, budget, start_date, end_date, dry_run):
    """Update campaign"""
    try:
        campaign_data = {"Id": campaign_id}

        if name:
            campaign_data["Name"] = name

        if status:
            campaign_data["Status"] = status

        if budget:
            campaign_data["DailyBudget"] = {
                "Amount": budget,
                "Mode": "STANDARD",
            }
        if start_date:
            campaign_data["StartDate"] = start_date
        if end_date:
            campaign_data["EndDate"] = end_date

        if len(campaign_data) == 1:
            raise click.UsageError("Provide at least one field to update")

        body = {"method": "update", "params": {"Campaigns": [campaign_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, campaign_id, dry_run):
    """Delete campaign"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def archive(ctx, campaign_id, dry_run):
    """Archive campaign"""
    try:
        body = {
            "method": "archive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def unarchive(ctx, campaign_id, dry_run):
    """Unarchive campaign"""
    try:
        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()



@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, campaign_id, dry_run):
    """Suspend campaign"""
    try:
        body = {
            "method": "suspend",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@campaigns.command()
@click.option("--id", "campaign_id", required=True, type=int, help="Campaign ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, campaign_id, dry_run):
    """Resume campaign"""
    try:
        body = {
            "method": "resume",
            "params": {"SelectionCriteria": {"Ids": [campaign_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.campaigns().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

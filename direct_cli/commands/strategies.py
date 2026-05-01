"""
Strategies commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import MICRO_RUBLES, get_default_fields, parse_ids

STRATEGY_TYPES = [
    "WbMaximumClicks",
    "WbMaximumClicksPerBid",
    "WbMaximumConversionRate",
    "WbMaximumConversionRatePerBid",
    "AverageCpc",
    "AverageCpa",
    "AverageCpaPerFilter",
    "AverageCpaPerCampaign",
    "AverageCrr",
    "AverageCrrPerCampaign",
    "MaxProfit",
    "MaxProfitPerFilter",
    "MaxProfitPerCampaign",
    "PayForConversion",
    "PayForConversionPerFilter",
    "PayForConversionPerCampaign",
]


def _parse_priority_goal(spec: str) -> dict:
    """Parse a priority goal spec in GOAL_ID:VALUE format."""
    goal_id, separator, value = spec.partition(":")
    if not separator:
        raise click.UsageError(
            "Invalid --priority-goal. Expected GOAL_ID:VALUE, for example 123:1000000"
        )
    try:
        return {"GoalId": int(goal_id.strip()), "Value": int(value.strip())}
    except ValueError:
        raise click.UsageError(
            "Invalid --priority-goal. GOAL_ID and VALUE must be integers"
        )


def _build_strategy_fields(
    average_cpc,
    average_cpa,
    average_crr,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
):
    """Build typed strategy-specific fields."""
    fields = {}
    if average_cpc is not None:
        fields["AverageCpc"] = average_cpc
    if average_cpa is not None:
        fields["AverageCpa"] = average_cpa
    if average_crr is not None:
        fields["AverageCrr"] = average_crr
    if spend_limit is not None:
        fields["SpendLimit"] = spend_limit
    if weekly_spend_limit is not None:
        fields["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        fields["BidCeiling"] = bid_ceiling
    return fields


@click.group()
def strategies():
    """Manage strategies"""


@strategies.command()
@click.option("--ids", help="Comma-separated strategy IDs")
@click.option(
    "--types",
    help="Comma-separated strategy types",
)
@click.option(
    "--is-archived",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="Filter by archived status",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.pass_context
def get(ctx, ids, types, is_archived, limit, fetch_all, output_format, output, fields):
    """Get strategies"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("strategies")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if types:
            criteria["Types"] = [t.strip() for t in types.split(",")]
        if is_archived:
            criteria["IsArchived"] = is_archived.upper()

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}
        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}
        result = client.strategies().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            format_output(result().extract(), output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@strategies.command()
@click.option("--name", required=True, help="Strategy name")
@click.option(
    "--type",
    "strategy_type",
    required=True,
    type=click.Choice(STRATEGY_TYPES, case_sensitive=True),
    help="Strategy type",
)
@click.option("--average-cpc", type=MICRO_RUBLES, help="Average CPC in micro-rubles")
@click.option("--average-cpa", type=MICRO_RUBLES, help="Average CPA in micro-rubles")
@click.option("--average-crr", type=int, help="Average cost revenue ratio")
@click.option("--spend-limit", type=MICRO_RUBLES, help="Spend limit in micro-rubles")
@click.option(
    "--weekly-spend-limit",
    type=MICRO_RUBLES,
    help="Weekly spend limit in micro-rubles",
)
@click.option("--bid-ceiling", type=MICRO_RUBLES, help="Bid ceiling in micro-rubles")
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option(
    "--priority-goal",
    "priority_goals",
    multiple=True,
    help="Priority goal as GOAL_ID:VALUE; may be repeated",
)
@click.option(
    "--attribution-model",
    type=click.Choice(
        ["LYDC", "FC", "LC", "LSC", "LYDC_WEIGHT", "CROSSTDEVICE"],
        case_sensitive=True,
    ),
    help="Attribution model",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    name,
    strategy_type,
    average_cpc,
    average_cpa,
    average_crr,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
    counter_ids,
    priority_goals,
    attribution_model,
    dry_run,
):
    """Add a strategy"""
    try:
        strategy_data = {
            "Name": name,
            strategy_type: _build_strategy_fields(
                average_cpc,
                average_cpa,
                average_crr,
                spend_limit,
                weekly_spend_limit,
                bid_ceiling,
            ),
        }
        if counter_ids:
            strategy_data["CounterIds"] = {
                "Items": [int(x.strip()) for x in counter_ids.split(",")]
            }
        if priority_goals:
            strategy_data["PriorityGoals"] = {
                "Items": [_parse_priority_goal(goal) for goal in priority_goals]
            }
        if attribution_model:
            strategy_data["AttributionModel"] = attribution_model

        body = {"method": "add", "params": {"Strategies": [strategy_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.strategies().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@strategies.command()
@click.option("--id", "strategy_id", required=True, type=int, help="Strategy ID")
@click.option("--name", help="New strategy name")
@click.option(
    "--type",
    "strategy_type",
    type=click.Choice(STRATEGY_TYPES, case_sensitive=True),
    help="Strategy type to update",
)
@click.option("--average-cpc", type=MICRO_RUBLES, help="Average CPC in micro-rubles")
@click.option("--average-cpa", type=MICRO_RUBLES, help="Average CPA in micro-rubles")
@click.option("--average-crr", type=int, help="Average cost revenue ratio")
@click.option("--spend-limit", type=MICRO_RUBLES, help="Spend limit in micro-rubles")
@click.option(
    "--weekly-spend-limit",
    type=MICRO_RUBLES,
    help="Weekly spend limit in micro-rubles",
)
@click.option("--bid-ceiling", type=MICRO_RUBLES, help="Bid ceiling in micro-rubles")
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option(
    "--priority-goal",
    "priority_goals",
    multiple=True,
    help="Priority goal as GOAL_ID:VALUE; may be repeated",
)
@click.option(
    "--attribution-model",
    type=click.Choice(
        ["LYDC", "FC", "LC", "LSC", "LYDC_WEIGHT", "CROSSTDEVICE"],
        case_sensitive=True,
    ),
    help="Attribution model",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    strategy_id,
    name,
    strategy_type,
    average_cpc,
    average_cpa,
    average_crr,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
    counter_ids,
    priority_goals,
    attribution_model,
    dry_run,
):
    """Update a strategy"""
    try:
        strategy_data = {"Id": strategy_id}
        if name:
            strategy_data["Name"] = name
        strategy_fields = _build_strategy_fields(
            average_cpc,
            average_cpa,
            average_crr,
            spend_limit,
            weekly_spend_limit,
            bid_ceiling,
        )
        if strategy_fields and not strategy_type:
            raise click.UsageError(
                "Provide --type when setting strategy-specific fields"
            )
        if strategy_type:
            strategy_data[strategy_type] = strategy_fields
        if counter_ids:
            strategy_data["CounterIds"] = {
                "Items": [int(x.strip()) for x in counter_ids.split(",")]
            }
        if priority_goals:
            strategy_data["PriorityGoals"] = {
                "Items": [_parse_priority_goal(goal) for goal in priority_goals]
            }
        if attribution_model:
            strategy_data["AttributionModel"] = attribution_model

        body = {"method": "update", "params": {"Strategies": [strategy_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.strategies().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@strategies.command()
@click.option("--id", "strategy_id", required=True, type=int, help="Strategy ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def archive(ctx, strategy_id, dry_run):
    """Archive a strategy"""
    try:
        body = {
            "method": "archive",
            "params": {"SelectionCriteria": {"Ids": [strategy_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.strategies().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@strategies.command()
@click.option("--id", "strategy_id", required=True, type=int, help="Strategy ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def unarchive(ctx, strategy_id, dry_run):
    """Unarchive a strategy"""
    try:
        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [strategy_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )
        result = client.strategies().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

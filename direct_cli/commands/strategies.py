"""
Strategies commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids, parse_json

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

        field_names = (
            fields.split(",") if fields else ["Id", "Name", "Type", "StatusArchived"]
        )

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
@click.option(
    "--params",
    "strategy_params",
    help="Strategy type-specific parameters as JSON",
)
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option("--priority-goals", help="Priority goals as JSON list")
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
    strategy_params,
    counter_ids,
    priority_goals,
    attribution_model,
    dry_run,
):
    """Add a strategy"""
    try:
        strategy_data = {"Name": name, strategy_type: {}}
        if strategy_params:
            parsed = parse_json(strategy_params)
            if not isinstance(parsed, dict):
                raise click.UsageError("--params must be a JSON object, not an array or scalar")
            strategy_data[strategy_type] = parsed
        if counter_ids:
            strategy_data["CounterIds"] = {
                "Items": [int(x.strip()) for x in counter_ids.split(",")]
            }
        if priority_goals:
            parsed_goals = parse_json(priority_goals)
            if not isinstance(parsed_goals, list):
                raise click.UsageError("--priority-goals must be a JSON array")
            strategy_data["PriorityGoals"] = {"Items": parsed_goals}
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
@click.option(
    "--params", "strategy_params", help="Strategy type-specific fields as JSON"
)
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option("--priority-goals", help="Priority goals as JSON list")
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
    strategy_params,
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
        if strategy_type:
            if strategy_params:
                parsed = parse_json(strategy_params)
                if not isinstance(parsed, dict):
                    raise click.UsageError("--params must be a JSON object, not an array or scalar")
                strategy_data[strategy_type] = parsed
            else:
                strategy_data[strategy_type] = {}
        if counter_ids:
            strategy_data["CounterIds"] = {
                "Items": [int(x.strip()) for x in counter_ids.split(",")]
            }
        if priority_goals:
            parsed_goals = parse_json(priority_goals)
            if not isinstance(parsed_goals, list):
                raise click.UsageError("--priority-goals must be a JSON array")
            strategy_data["PriorityGoals"] = {"Items": parsed_goals}
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

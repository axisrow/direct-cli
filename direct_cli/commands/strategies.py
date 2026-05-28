"""
Strategies commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import (
    MICRO_RUBLES,
    get_default_fields,
    parse_ids,
    validate_priority_goal_value,
)

# Canonical list of strategy subtypes, mirroring the choice-of-one
# fields on WSDL StrategyAddItem. The previous list (PR #205 review,
# issue #198 H11) carried five names that do not exist in the WSDL
# (WbMaximumClicksPerBid, WbMaximumConversionRatePerBid,
# AverageCrrPerCampaign, MaxProfitPerFilter, MaxProfitPerCampaign) and
# omitted five that do (AverageCpcPerCampaign, AverageCpcPerFilter,
# PayForConversionCrr, AverageCpaMultipleGoals,
# PayForConversionMultipleGoals).
STRATEGY_TYPES = [
    "WbMaximumClicks",
    "WbMaximumConversionRate",
    "AverageCpc",
    "AverageCpcPerCampaign",
    "AverageCpcPerFilter",
    "AverageCpa",
    "AverageCpaPerCampaign",
    "AverageCpaPerFilter",
    "AverageCpaMultipleGoals",
    "AverageCrr",
    "MaxProfit",
    "PayForConversion",
    "PayForConversionPerCampaign",
    "PayForConversionPerFilter",
    "PayForConversionCrr",
    "PayForConversionMultipleGoals",
]

CPA_STRATEGY_TYPES = {
    "AverageCpa",
    "AverageCpaPerCampaign",
}
FILTER_CPA_STRATEGY_TYPES = {"AverageCpaPerFilter"}
# AverageCpcPerFilter's WSDL AddItem uses FilterAverageCpc, not AverageCpc.
FILTER_CPC_STRATEGY_TYPES = {"AverageCpcPerFilter"}
PAY_FOR_CONVERSION_STRATEGY_TYPES = {
    "PayForConversion",
    "PayForConversionPerFilter",
    "PayForConversionPerCampaign",
}
# CRR-family strategies map --average-crr to Crr (not AverageCrr).
# PayForConversionCrr lives here, not in PAY_FOR_CONVERSION_STRATEGY_TYPES:
# its WSDL AddItem has Crr+GoalId and no Cpa field.
CRR_STRATEGY_TYPES = {
    "AverageCrr",
    "PayForConversionCrr",
}
# Multi-goal strategies. AverageCpaMultipleGoalsAddItem has no GoalId field
# at all (its schema is WeeklySpendLimit/CustomPeriodBudget/...), so only
# PayForConversionMultipleGoals requires --goal-id on add.
MULTI_GOAL_STRATEGY_TYPES = {
    "AverageCpaMultipleGoals",
    "PayForConversionMultipleGoals",
}
GOAL_ID_STRATEGY_TYPES = (
    CPA_STRATEGY_TYPES
    | FILTER_CPA_STRATEGY_TYPES
    | PAY_FOR_CONVERSION_STRATEGY_TYPES
    | CRR_STRATEGY_TYPES
    | {"WbMaximumConversionRate"}
    | {"PayForConversionMultipleGoals"}
)
STRATEGY_FIELD_OPTIONS = {
    "WbMaximumClicks": {
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "WbMaximumConversionRate": {
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
        "goal_id": "GoalId",
    },
    "AverageCpc": {
        "average_cpc": "AverageCpc",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "AverageCpcPerCampaign": {
        "average_cpc": "AverageCpc",
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCpcPerFilter": {
        "average_cpc": "FilterAverageCpc",
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCpa": {
        "average_cpa": "AverageCpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCpaPerCampaign": {
        "average_cpa": "AverageCpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCpaPerFilter": {
        "average_cpa": "FilterAverageCpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCpaMultipleGoals": {
        "weekly_spend_limit": "WeeklySpendLimit",
        "bid_ceiling": "BidCeiling",
    },
    "AverageCrr": {
        "average_crr": "Crr",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "MaxProfit": {
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "PayForConversion": {
        "average_cpa": "Cpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "PayForConversionPerCampaign": {
        "average_cpa": "Cpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "PayForConversionPerFilter": {
        "average_cpa": "Cpa",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "PayForConversionCrr": {
        "average_crr": "Crr",
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
    "PayForConversionMultipleGoals": {
        "goal_id": "GoalId",
        "weekly_spend_limit": "WeeklySpendLimit",
    },
}
STRATEGY_UPDATE_FIELD_OPTIONS = {
    strategy_type: dict(options)
    for strategy_type, options in STRATEGY_FIELD_OPTIONS.items()
}
STRATEGY_UPDATE_FIELD_OPTIONS["PayForConversionMultipleGoals"].pop("goal_id")
CUSTOM_PERIOD_BUDGET_FIELD_OPTIONS = {
    "SpendLimit": "--custom-period-spend-limit",
    "StartDate": "--custom-period-start-date",
    "EndDate": "--custom-period-end-date",
    "AutoContinue": "--custom-period-auto-continue",
}
CUSTOM_PERIOD_BUDGET_FLAGS = set(CUSTOM_PERIOD_BUDGET_FIELD_OPTIONS.values())
EXPLORATION_BUDGET_FIELD_OPTIONS = {
    "MinimumExplorationBudget": "--minimum-exploration-budget",
    "IsMinimumExplorationBudgetCustom": "--minimum-exploration-budget",
}
EXPLORATION_BUDGET_FLAGS = set(EXPLORATION_BUDGET_FIELD_OPTIONS.values())
EXPLORATION_BUDGET_STRATEGY_TYPES = {
    "AverageCpa",
    "MaxProfit",
    "AverageCpaPerCampaign",
    "AverageCpaPerFilter",
    "AverageCrr",
    "AverageCpaMultipleGoals",
}
PRIORITY_GOAL_FIELD_OPTIONS = {
    "GoalId": "--priority-goal",
    "Value": "--priority-goal",
    "IsMetrikaSourceOfValue": "--priority-goal",
}
STRATEGY_FLAG_NAMES = {
    "average_cpc": "--average-cpc",
    "average_cpa": "--average-cpa",
    "average_crr": "--average-crr",
    "goal_id": "--goal-id",
    "spend_limit": "--spend-limit",
    "weekly_spend_limit": "--weekly-spend-limit",
    "bid_ceiling": "--bid-ceiling",
}


def _build_custom_period_budget(
    custom_period_spend_limit,
    custom_period_start_date,
    custom_period_end_date,
    custom_period_auto_continue,
    weekly_spend_limit,
):
    """Build CustomPeriodBudget from typed flags."""
    provided = {
        "--custom-period-spend-limit": custom_period_spend_limit,
        "--custom-period-start-date": custom_period_start_date,
        "--custom-period-end-date": custom_period_end_date,
        "--custom-period-auto-continue": custom_period_auto_continue,
    }
    if not any(value is not None for value in provided.values()):
        return None
    if weekly_spend_limit is not None:
        raise click.UsageError(
            "--weekly-spend-limit cannot be combined with --custom-period-* flags."
        )

    missing = [
        flag_name
        for flag_name, value in provided.items()
        if value is None or value == ""
    ]
    if missing:
        raise click.UsageError("CustomPeriodBudget requires " + ", ".join(missing))

    return {
        "SpendLimit": custom_period_spend_limit,
        "StartDate": custom_period_start_date,
        "EndDate": custom_period_end_date,
        "AutoContinue": custom_period_auto_continue.upper(),
    }


def _build_exploration_budget(
    strategy_type,
    minimum_exploration_budget,
    weekly_spend_limit,
):
    """Build ExplorationBudget from typed flags."""
    if minimum_exploration_budget is None:
        return None
    if strategy_type not in EXPLORATION_BUDGET_STRATEGY_TYPES:
        raise click.UsageError(
            f"--minimum-exploration-budget is not valid for --type {strategy_type}."
        )
    if (
        weekly_spend_limit is not None
        and minimum_exploration_budget > weekly_spend_limit
    ):
        raise click.UsageError(
            "--minimum-exploration-budget must be less than or equal to "
            "--weekly-spend-limit when both flags are provided."
        )
    return {
        "MinimumExplorationBudget": minimum_exploration_budget,
        "IsMinimumExplorationBudgetCustom": "YES",
    }


def _parse_priority_goal(spec: str) -> dict:
    """Parse a priority goal spec in GOAL_ID:VALUE[:YES|NO] format."""
    parts = [part.strip() for part in spec.split(":")]
    if (
        len(parts) not in (2, 3)
        or not parts[0]
        or not parts[1]
        or (len(parts) == 3 and not parts[2])
    ):
        raise click.UsageError(
            "Invalid --priority-goal. Expected GOAL_ID:VALUE[:YES|NO], "
            "for example 123:1000000:YES"
        )
    try:
        item = {"GoalId": int(parts[0]), "Value": int(parts[1])}
    except ValueError:
        raise click.UsageError(
            "Invalid --priority-goal. GOAL_ID and VALUE must be integers"
        )
    validate_priority_goal_value(
        item["Value"], f"Invalid --priority-goal '{spec}'."
    )
    if len(parts) == 3:
        is_metrika_source = parts[2].upper()
        if is_metrika_source not in {"YES", "NO"}:
            raise click.UsageError(
                "Invalid --priority-goal. IsMetrikaSourceOfValue must be YES or NO"
            )
        item["IsMetrikaSourceOfValue"] = is_metrika_source
    return item


def _build_strategy_fields(
    strategy_type,
    average_cpc,
    average_cpa,
    average_crr,
    goal_id,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
    custom_period_spend_limit,
    custom_period_start_date,
    custom_period_end_date,
    custom_period_auto_continue,
    minimum_exploration_budget,
    *,
    update=False,
):
    """Build typed strategy-specific fields."""
    custom_period_values = (
        custom_period_spend_limit,
        custom_period_start_date,
        custom_period_end_date,
        custom_period_auto_continue,
    )
    if strategy_type is None:
        if any(
            value is not None
            for value in (
                average_cpc,
                average_cpa,
                average_crr,
                goal_id,
                spend_limit,
                weekly_spend_limit,
                bid_ceiling,
                *custom_period_values,
                minimum_exploration_budget,
            )
        ):
            raise click.UsageError(
                "Provide --type when setting strategy-specific fields"
            )
        return {}

    if (
        update
        and strategy_type == "AverageCpa"
        and any(value is not None for value in custom_period_values)
    ):
        raise click.UsageError(
            "--custom-period-* flags are not valid for --type AverageCpa "
            "on strategies update."
        )

    field_options = STRATEGY_UPDATE_FIELD_OPTIONS if update else STRATEGY_FIELD_OPTIONS
    allowed_options = field_options[strategy_type]
    provided_options = {
        "average_cpc": average_cpc,
        "average_cpa": average_cpa,
        "average_crr": average_crr,
        "goal_id": goal_id,
        "spend_limit": spend_limit,
        "weekly_spend_limit": weekly_spend_limit,
        "bid_ceiling": bid_ceiling,
    }
    incompatible = [
        STRATEGY_FLAG_NAMES[name]
        for name, value in provided_options.items()
        if value is not None and name not in allowed_options
    ]
    if incompatible:
        allowed_flags = ", ".join(
            sorted(STRATEGY_FLAG_NAMES[name] for name in allowed_options)
        )
        raise click.UsageError(
            f"{', '.join(incompatible)} is not valid for --type {strategy_type}. "
            f"Allowed strategy field flags: {allowed_flags}."
        )

    fields = {}
    if average_cpc is not None:
        fields[allowed_options["average_cpc"]] = average_cpc
    if average_cpa is not None:
        fields[allowed_options["average_cpa"]] = average_cpa
    if average_crr is not None:
        fields[allowed_options["average_crr"]] = average_crr
    if goal_id is not None:
        fields[allowed_options["goal_id"]] = goal_id
    if weekly_spend_limit is not None:
        fields["WeeklySpendLimit"] = weekly_spend_limit
    if bid_ceiling is not None:
        fields["BidCeiling"] = bid_ceiling
    custom_period_budget = _build_custom_period_budget(
        custom_period_spend_limit,
        custom_period_start_date,
        custom_period_end_date,
        custom_period_auto_continue,
        weekly_spend_limit,
    )
    if custom_period_budget:
        fields["CustomPeriodBudget"] = custom_period_budget
    exploration_budget = _build_exploration_budget(
        strategy_type,
        minimum_exploration_budget,
        weekly_spend_limit,
    )
    if exploration_budget:
        fields["ExplorationBudget"] = exploration_budget
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
@click.option("--goal-id", type=int, help="Goal ID for conversion strategies")
@click.option("--spend-limit", type=MICRO_RUBLES, help="Spend limit in micro-rubles")
@click.option(
    "--weekly-spend-limit",
    type=MICRO_RUBLES,
    help="Weekly spend limit in micro-rubles",
)
@click.option("--bid-ceiling", type=MICRO_RUBLES, help="Bid ceiling in micro-rubles")
@click.option(
    "--custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--custom-period-start-date",
    help="CustomPeriodBudget.StartDate (YYYY-MM-DD)",
)
@click.option(
    "--custom-period-end-date",
    help="CustomPeriodBudget.EndDate (YYYY-MM-DD)",
)
@click.option(
    "--custom-period-auto-continue",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="CustomPeriodBudget.AutoContinue value: YES or NO",
)
@click.option(
    "--minimum-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles; "
        "sets IsMinimumExplorationBudgetCustom=YES"
    ),
)
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option(
    "--priority-goal",
    "priority_goals",
    multiple=True,
    help=(
        "Priority goal as GOAL_ID:VALUE[:YES|NO]; may be repeated. "
        "VALUE is in micro-currency (advertiser currency × 1,000,000), "
        "same contract as --average-cpa. Example: 1:1000000 = 1.0 RUB."
    ),
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
    goal_id,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
    custom_period_spend_limit,
    custom_period_start_date,
    custom_period_end_date,
    custom_period_auto_continue,
    minimum_exploration_budget,
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
                strategy_type,
                average_cpc,
                average_cpa,
                average_crr,
                goal_id,
                spend_limit,
                weekly_spend_limit,
                bid_ceiling,
                custom_period_spend_limit,
                custom_period_start_date,
                custom_period_end_date,
                custom_period_auto_continue,
                minimum_exploration_budget,
            ),
        }
        if strategy_type in GOAL_ID_STRATEGY_TYPES and goal_id is None:
            raise click.UsageError("Provide --goal-id for this strategy type")
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
@click.option("--goal-id", type=int, help="Goal ID for conversion strategies")
@click.option("--spend-limit", type=MICRO_RUBLES, help="Spend limit in micro-rubles")
@click.option(
    "--weekly-spend-limit",
    type=MICRO_RUBLES,
    help="Weekly spend limit in micro-rubles",
)
@click.option("--bid-ceiling", type=MICRO_RUBLES, help="Bid ceiling in micro-rubles")
@click.option(
    "--custom-period-spend-limit",
    type=MICRO_RUBLES,
    help="CustomPeriodBudget.SpendLimit in micro-rubles",
)
@click.option(
    "--custom-period-start-date",
    help="CustomPeriodBudget.StartDate (YYYY-MM-DD)",
)
@click.option(
    "--custom-period-end-date",
    help="CustomPeriodBudget.EndDate (YYYY-MM-DD)",
)
@click.option(
    "--custom-period-auto-continue",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="CustomPeriodBudget.AutoContinue value: YES or NO",
)
@click.option(
    "--minimum-exploration-budget",
    type=MICRO_RUBLES,
    help=(
        "ExplorationBudget.MinimumExplorationBudget in micro-rubles; "
        "sets IsMinimumExplorationBudgetCustom=YES"
    ),
)
@click.option("--counter-ids", help="Comma-separated Metrica counter IDs")
@click.option(
    "--priority-goal",
    "priority_goals",
    multiple=True,
    help=(
        "Priority goal as GOAL_ID:VALUE[:YES|NO]; may be repeated. "
        "VALUE is in micro-currency (advertiser currency × 1,000,000), "
        "same contract as --average-cpa. Example: 1:1000000 = 1.0 RUB."
    ),
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
    goal_id,
    spend_limit,
    weekly_spend_limit,
    bid_ceiling,
    custom_period_spend_limit,
    custom_period_start_date,
    custom_period_end_date,
    custom_period_auto_continue,
    minimum_exploration_budget,
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
            strategy_type,
            average_cpc,
            average_cpa,
            average_crr,
            goal_id,
            spend_limit,
            weekly_spend_limit,
            bid_ceiling,
            custom_period_spend_limit,
            custom_period_start_date,
            custom_period_end_date,
            custom_period_auto_continue,
            minimum_exploration_budget,
            update=True,
        )
        if strategy_fields and not strategy_type:
            raise click.UsageError(
                "Provide --type when setting strategy-specific fields"
            )
        if strategy_type and not strategy_fields:
            # Reject empty-subtype no-op (issue #198 sibling of H1/H5/H10):
            # `--type AverageCpa` with no field flags would emit
            # {Id, AverageCpa: {}}, which the live API accepts as a
            # silent no-op.
            raise click.UsageError(
                f"strategies update requires at least one field for "
                f"--type {strategy_type}."
            )
        if strategy_type:
            # GoalId is minOccurs=0 in every Strategy*Base used by
            # Strategy*UpdateItem (cached WSDL strategies.xml), so update
            # must NOT require --goal-id even for the goal-id family —
            # users may change AverageCpa/Crr/WeeklySpendLimit without
            # re-specifying the existing goal. The add command keeps the
            # required-on-add validation because *AddItem.GoalId is
            # minOccurs=1.
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

        if len(strategy_data) == 1:
            # Only `Id` populated — reject the no-op payload (sibling of
            # the H1/H5/H10 empty-payload guards on other resources).
            raise click.UsageError(
                "strategies update requires at least one updatable field."
            )

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

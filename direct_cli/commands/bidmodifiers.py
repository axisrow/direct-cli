"""
BidModifiers commands
"""

import json
import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import parse_ids


@click.group()
def bidmodifiers():
    """Manage bid modifiers"""


@bidmodifiers.command()
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.pass_context
def get(ctx, campaign_ids, adgroup_ids, limit, fetch_all, output_format, output):
    """Get bid modifiers"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        criteria = {}
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": ["Id", "CampaignId", "AdGroupId", "Type", "ModifierValue"],
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        result = client.bidmodifiers().post(data=body)

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


# Map CLI --type values to the nested BidModifier object field name.
# The API derives the adjustment type from the nested field name, not from
# a top-level Type discriminator.
_BIDMODIFIER_TYPE_TO_NESTED = {
    "MOBILE_ADJUSTMENT": "MobileAdjustment",
    "TABLET_ADJUSTMENT": "TabletAdjustment",
    "DESKTOP_ADJUSTMENT": "DesktopAdjustment",
    "DESKTOP_ONLY_ADJUSTMENT": "DesktopOnlyAdjustment",
    "DEMOGRAPHICS_ADJUSTMENT": "DemographicsAdjustment",
    "RETARGETING_ADJUSTMENT": "RetargetingAdjustment",
    "REGIONAL_ADJUSTMENT": "RegionalAdjustment",
    "VIDEO_ADJUSTMENT": "VideoAdjustment",
    "SMART_AD_ADJUSTMENT": "SmartAdAdjustment",
    "SERP_LAYOUT_ADJUSTMENT": "SerpLayoutAdjustment",
    "INCOME_GRADE_ADJUSTMENT": "IncomeGradeAdjustment",
    "AD_GROUP_ADJUSTMENT": "AdGroupAdjustment",
}


@bidmodifiers.command()
@click.option(
    "--campaign-id",
    type=int,
    help="Campaign ID (mutually exclusive with --adgroup-id)",
)
@click.option(
    "--adgroup-id",
    type=int,
    help="Ad group ID (mutually exclusive with --campaign-id)",
)
@click.option(
    "--type",
    "modifier_type",
    required=True,
    type=click.Choice(sorted(_BIDMODIFIER_TYPE_TO_NESTED.keys()), case_sensitive=False),
    help="Bid modifier type; determines the nested object name.",
)
@click.option(
    "--value",
    type=int,
    required=True,
    help="Bid modifier percentage (0-1300).",
)
@click.option(
    "--json",
    "extra_json",
    help=(
        "Extra fields merged into the nested adjustment object "
        "(e.g. Gender/Age for DEMOGRAPHICS, RegionId for REGIONAL)."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(ctx, campaign_id, adgroup_id, modifier_type, value, extra_json, dry_run):
    """Add a new bid modifier

    Unlike ``set`` (which requires an existing ``Id`` and updates a
    modifier), ``add`` creates a new bid modifier on the given campaign
    or ad group.  The Yandex Direct API dispatches on the nested object
    field name (e.g. ``MobileAdjustment``), so ``--type
    MOBILE_ADJUSTMENT`` translates into::

        {"CampaignId": ..., "MobileAdjustment": {"BidModifier": 120}}

    For types with extra fields (``DemographicsAdjustment`` needs
    ``Gender``/``Age``, ``RegionalAdjustment`` needs ``RegionId``,
    ``RetargetingAdjustment`` needs ``RetargetingConditionId``, etc.)
    pass the missing fields via ``--json``; they are merged into the
    nested object.
    """
    try:
        if (campaign_id is None) == (adgroup_id is None):
            raise click.ClickException(
                "Exactly one of --campaign-id or --adgroup-id is required"
            )

        nested_key = _BIDMODIFIER_TYPE_TO_NESTED[modifier_type.upper()]
        nested = {"BidModifier": value}
        if extra_json:
            nested.update(json.loads(extra_json))

        modifier_data = {nested_key: nested}
        if campaign_id is not None:
            modifier_data["CampaignId"] = campaign_id
        else:
            modifier_data["AdGroupId"] = adgroup_id

        body = {"method": "add", "params": {"BidModifiers": [modifier_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bidmodifiers.command()
@click.option(
    "--id",
    "modifier_id",
    type=int,
    help=(
        "Existing BidModifier ID to update. This is the shape Yandex "
        "Direct's ``bidmodifiers/set`` method actually supports — pass "
        "the Id of a modifier created via ``bidmodifiers add`` and the "
        "new ``--value``. Mutually exclusive with --campaign-id/--type."
    ),
)
@click.option(
    "--campaign-id",
    type=int,
    help=(
        "Campaign ID (legacy path, broken by design — kept for "
        "backwards compatibility and regression coverage; the API "
        "rejects this shape with ``required field Id is omitted``). "
        "Use --id for real updates."
    ),
)
@click.option(
    "--type",
    "modifier_type",
    type=click.Choice(sorted(_BIDMODIFIER_TYPE_TO_NESTED.keys()), case_sensitive=False),
    help=(
        "Modifier category (legacy path). Uses the same enum as "
        "``bidmodifiers add`` (MOBILE_ADJUSTMENT / DEMOGRAPHICS_ADJUSTMENT "
        "/ ...), case-insensitive."
    ),
)
@click.option("--value", type=float, required=True, help="Modifier value")
@click.option("--json", "extra_json", help="Additional JSON parameters")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, modifier_id, campaign_id, modifier_type, value, extra_json, dry_run):
    """Set (update) an existing bid modifier

    The Yandex Direct API's ``bidmodifiers/set`` method updates existing
    modifiers by ``Id``. The correct payload shape is simply::

        {"BidModifiers": [{"Id": <long>, "BidModifier": <value>}]}

    To create a new modifier, use ``bidmodifiers add`` instead.

    This CLI command supports two shapes:

    1. **Correct shape** — pass ``--id`` + ``--value``. The request
       body becomes exactly ``{"Id": ..., "BidModifier": ...}`` and is
       accepted by the API.

    2. **Legacy shape** (broken by design) — pass ``--campaign-id`` +
       ``--type`` + ``--value``. The request body is
       ``{"CampaignId": ..., "Type": ..., "BidModifier": ...}`` and the
       API rejects it with ``required field Id is omitted``. This path
       is preserved so the existing regression cassette in
       ``TestWriteBidModifiersSet.test_set_without_id_is_rejected``
       keeps passing; it also gives a clear deprecation signal to
       callers who land on this command by mistake.
    """
    try:
        # Validate the mutex up front.
        if modifier_id is not None and (
            campaign_id is not None or modifier_type is not None
        ):
            raise click.UsageError(
                "--id is mutually exclusive with --campaign-id/--type. "
                "Use --id + --value for the correct bidmodifiers/set shape."
            )

        if modifier_id is None and (campaign_id is None or modifier_type is None):
            raise click.UsageError(
                "Provide either --id (preferred) or both --campaign-id "
                "and --type (legacy)."
            )

        if modifier_id is not None:
            # Correct API shape: Id + BidModifier. Nothing else.
            modifier_data = {"Id": modifier_id, "BidModifier": value}
        else:
            # Legacy broken-by-design path — kept for backwards
            # compatibility with the existing regression test.  The
            # click.Choice above has already validated/normalized
            # modifier_type, so we forward it unchanged.
            modifier_data = {
                "CampaignId": campaign_id,
                "Type": modifier_type,
                "BidModifier": value,
            }

        if extra_json:
            extra = json.loads(extra_json)
            modifier_data.update(extra)

        body = {"method": "set", "params": {"BidModifiers": [modifier_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bidmodifiers.command()
@click.option("--id", "modifier_id", required=True, type=int, help="Modifier ID")
@click.option("--enabled/--disabled", "enabled", default=True, help="Enable or disable")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def toggle(ctx, modifier_id, enabled, dry_run):
    """Toggle bid modifier state"""
    try:
        body = {
            "method": "set",
            "params": {
                "BidModifiers": [
                    {
                        "Id": modifier_id,
                        "Enabled": "YES" if enabled else "NO",
                    }
                ]
            },
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@bidmodifiers.command()
@click.option("--id", "modifier_id", required=True, type=int, help="Modifier ID")
@click.pass_context
def delete(ctx, modifier_id):
    """Delete bid modifier"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [modifier_id]}},
        }

        result = client.bidmodifiers().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


bidmodifiers.add_command(get, name="list")

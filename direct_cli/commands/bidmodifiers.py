"""
BidModifiers commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import get_default_fields, parse_csv_strings, parse_ids


@click.group()
def bidmodifiers():
    """Manage bid modifiers"""


@bidmodifiers.command()
@click.option("--ids", help="Comma-separated bid modifier IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--types", help="Comma-separated bid modifier types")
@click.option(
    "--levels",
    type=click.Choice(["CAMPAIGN", "AD_GROUP"], case_sensitive=False),
    multiple=True,
    default=("CAMPAIGN", "AD_GROUP"),
    show_default=True,
    help="Bid modifier levels to retrieve",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--ad-group-adjustment-field-names",
    help=(
        "Comma-separated AdGroupAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--demographics-adjustment-field-names",
    help=(
        "Comma-separated DemographicsAdjustmentFieldNames "
        "(e.g. Gender,Age,BidModifier,Enabled). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--desktop-adjustment-field-names",
    help=(
        "Comma-separated DesktopAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--desktop-only-adjustment-field-names",
    help=(
        "Comma-separated DesktopOnlyAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--income-grade-adjustment-field-names",
    help=(
        "Comma-separated IncomeGradeAdjustmentFieldNames "
        "(e.g. Grade,BidModifier,Enabled). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--mobile-adjustment-field-names",
    help=(
        "Comma-separated MobileAdjustmentFieldNames "
        "(e.g. BidModifier,OperatingSystemType). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--regional-adjustment-field-names",
    help=(
        "Comma-separated RegionalAdjustmentFieldNames "
        "(e.g. RegionId,BidModifier,Enabled). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--retargeting-adjustment-field-names",
    help=(
        "Comma-separated RetargetingAdjustmentFieldNames "
        "(e.g. RetargetingConditionId,BidModifier,Accessible,Enabled). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--serp-layout-adjustment-field-names",
    help=(
        "Comma-separated SerpLayoutAdjustmentFieldNames "
        "(e.g. SerpLayout,BidModifier,Enabled). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--smart-ad-adjustment-field-names",
    help=(
        "Comma-separated SmartAdAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--smart-tv-adjustment-field-names",
    help=(
        "Comma-separated SmartTvAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--tablet-adjustment-field-names",
    help=(
        "Comma-separated TabletAdjustmentFieldNames "
        "(e.g. BidModifier,OperatingSystemType). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option(
    "--video-adjustment-field-names",
    help=(
        "Comma-separated VideoAdjustmentFieldNames (e.g. BidModifier). "
        "Sent as separate top-level request parameter per the "
        "BidModifiersGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    campaign_ids,
    adgroup_ids,
    types,
    levels,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    ad_group_adjustment_field_names,
    demographics_adjustment_field_names,
    desktop_adjustment_field_names,
    desktop_only_adjustment_field_names,
    income_grade_adjustment_field_names,
    mobile_adjustment_field_names,
    regional_adjustment_field_names,
    retargeting_adjustment_field_names,
    serp_layout_adjustment_field_names,
    smart_ad_adjustment_field_names,
    smart_tv_adjustment_field_names,
    tablet_adjustment_field_names,
    video_adjustment_field_names,
    dry_run,
):
    """Get bid modifiers"""
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        raw_nested = (
            ("AdGroupAdjustmentFieldNames", ad_group_adjustment_field_names),
            ("DemographicsAdjustmentFieldNames", demographics_adjustment_field_names),
            ("DesktopAdjustmentFieldNames", desktop_adjustment_field_names),
            ("DesktopOnlyAdjustmentFieldNames", desktop_only_adjustment_field_names),
            ("IncomeGradeAdjustmentFieldNames", income_grade_adjustment_field_names),
            ("MobileAdjustmentFieldNames", mobile_adjustment_field_names),
            ("RegionalAdjustmentFieldNames", regional_adjustment_field_names),
            ("RetargetingAdjustmentFieldNames", retargeting_adjustment_field_names),
            ("SerpLayoutAdjustmentFieldNames", serp_layout_adjustment_field_names),
            ("SmartAdAdjustmentFieldNames", smart_ad_adjustment_field_names),
            ("SmartTvAdjustmentFieldNames", smart_tv_adjustment_field_names),
            ("TabletAdjustmentFieldNames", tablet_adjustment_field_names),
            ("VideoAdjustmentFieldNames", video_adjustment_field_names),
        )
        parsed_nested = {}
        for wsdl_key, raw_value in raw_nested:
            parsed = parse_csv_strings(raw_value)
            if raw_value is not None and not parsed:
                raise click.UsageError(
                    f"Provide a non-empty comma-separated {wsdl_key} list."
                )
            if parsed:
                parsed_nested[wsdl_key] = parsed

        criteria = {"Levels": [lv.upper() for lv in levels]}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if types:
            criteria["Types"] = [
                item.strip().upper() for item in types.split(",") if item.strip()
            ]

        field_names = (
            fields.split(",") if fields else get_default_fields("bidmodifiers")
        )
        params = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
        }
        params.update(parsed_nested)

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.bidmodifiers().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except click.UsageError:
        raise
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
    "SMART_TV_ADJUSTMENT": "SmartTvAdjustment",
    "DEMOGRAPHICS_ADJUSTMENT": "DemographicsAdjustments",  # plural per WSDL
    "RETARGETING_ADJUSTMENT": "RetargetingAdjustments",  # plural per WSDL
    "REGIONAL_ADJUSTMENT": "RegionalAdjustments",  # plural per WSDL
    "VIDEO_ADJUSTMENT": "VideoAdjustment",
    "SMART_AD_ADJUSTMENT": "SmartAdAdjustment",
    "SERP_LAYOUT_ADJUSTMENT": "SerpLayoutAdjustments",  # plural per WSDL
    "INCOME_GRADE_ADJUSTMENT": "IncomeGradeAdjustments",  # plural per WSDL
    "AD_GROUP_ADJUSTMENT": "AdGroupAdjustment",
}

# Plural fields (derived from _BIDMODIFIER_TYPE_TO_NESTED) require a list value per WSDL
_PLURAL_NESTED_KEYS = {
    v for v in _BIDMODIFIER_TYPE_TO_NESTED.values() if v.endswith("Adjustments")
}

_OPERATING_SYSTEM_TYPE_MODIFIERS = {"MOBILE_ADJUSTMENT", "TABLET_ADJUSTMENT"}

_BIDMODIFIER_ALLOWED_EXTRA_FLAGS = {
    "MOBILE_ADJUSTMENT": {"--operating-system-type"},
    "TABLET_ADJUSTMENT": {"--operating-system-type"},
    "DESKTOP_ADJUSTMENT": set(),
    "DESKTOP_ONLY_ADJUSTMENT": set(),
    "SMART_TV_ADJUSTMENT": set(),
    "VIDEO_ADJUSTMENT": set(),
    "SMART_AD_ADJUSTMENT": set(),
    "AD_GROUP_ADJUSTMENT": set(),
    "DEMOGRAPHICS_ADJUSTMENT": {"--gender", "--age"},
    "RETARGETING_ADJUSTMENT": {"--retargeting-condition-id"},
    "REGIONAL_ADJUSTMENT": {"--region-id"},
    "SERP_LAYOUT_ADJUSTMENT": {"--serp-layout"},
    "INCOME_GRADE_ADJUSTMENT": {"--income-grade"},
}


def _reject_incompatible_extra_flags(
    modifier_type: str,
    provided_flags: dict[str, object],
) -> None:
    """Reject extra flags that do not belong to the selected modifier type."""
    allowed = _BIDMODIFIER_ALLOWED_EXTRA_FLAGS[modifier_type]
    incompatible = [
        flag
        for flag, value in provided_flags.items()
        if value is not None and flag not in allowed
    ]
    if incompatible:
        raise click.UsageError(
            f"{', '.join(sorted(incompatible))} is not compatible with --type "
            f"{modifier_type}."
        )


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
@click.option("--gender", help="Demographics adjustment gender value")
@click.option("--age", help="Demographics adjustment age value")
@click.option("--retargeting-condition-id", type=int, help="Retargeting condition ID")
@click.option("--region-id", type=int, help="Regional adjustment region ID")
@click.option("--serp-layout", help="SERP layout adjustment value")
@click.option("--income-grade", help="Income grade adjustment value")
@click.option(
    "--operating-system-type",
    type=click.Choice(["IOS", "ANDROID"], case_sensitive=False),
    help=(
        "Operating system type for MobileAdjustment.OperatingSystemType or "
        "TabletAdjustment.OperatingSystemType."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    campaign_id,
    adgroup_id,
    modifier_type,
    value,
    gender,
    age,
    retargeting_condition_id,
    region_id,
    serp_layout,
    income_grade,
    operating_system_type,
    dry_run,
):
    """Add a new bid modifier

    Unlike ``set`` (which requires an existing ``Id`` and updates a
    modifier), ``add`` creates a new bid modifier on the given campaign
    or ad group.  The Yandex Direct API dispatches on the nested object
    field name (e.g. ``MobileAdjustment``), so ``--type
    MOBILE_ADJUSTMENT`` translates into::

        {"CampaignId": ..., "MobileAdjustment": {"BidModifier": 120}}

    For types with extra fields, use the corresponding typed flags
    (for example ``--gender`` / ``--age`` for demographics).
    """
    try:
        if (campaign_id is None) == (adgroup_id is None):
            raise click.UsageError(
                "Exactly one of --campaign-id or --adgroup-id is required"
            )

        modifier_type_upper = modifier_type.upper()
        _reject_incompatible_extra_flags(
            modifier_type_upper,
            {
                "--gender": gender,
                "--age": age,
                "--retargeting-condition-id": retargeting_condition_id,
                "--region-id": region_id,
                "--serp-layout": serp_layout,
                "--income-grade": income_grade,
                "--operating-system-type": operating_system_type,
            },
        )

        nested_key = _BIDMODIFIER_TYPE_TO_NESTED[modifier_type_upper]
        nested = {"BidModifier": value}
        if (
            modifier_type_upper in _OPERATING_SYSTEM_TYPE_MODIFIERS
            and operating_system_type
        ):
            nested["OperatingSystemType"] = operating_system_type.upper()
        if modifier_type_upper == "DEMOGRAPHICS_ADJUSTMENT":
            if gender:
                nested["Gender"] = gender
            if age:
                nested["Age"] = age
            if "Gender" not in nested and "Age" not in nested:
                raise click.UsageError(
                    "DEMOGRAPHICS_ADJUSTMENT requires --gender and/or --age"
                )
        elif modifier_type_upper == "RETARGETING_ADJUSTMENT":
            if retargeting_condition_id is None:
                raise click.UsageError(
                    "RETARGETING_ADJUSTMENT requires --retargeting-condition-id"
                )
            nested["RetargetingConditionId"] = retargeting_condition_id
        elif modifier_type_upper == "REGIONAL_ADJUSTMENT":
            if region_id is None:
                raise click.UsageError("REGIONAL_ADJUSTMENT requires --region-id")
            nested["RegionId"] = region_id
        elif modifier_type_upper == "SERP_LAYOUT_ADJUSTMENT":
            if not serp_layout:
                raise click.UsageError("SERP_LAYOUT_ADJUSTMENT requires --serp-layout")
            nested["SerpLayout"] = serp_layout
        elif modifier_type_upper == "INCOME_GRADE_ADJUSTMENT":
            if not income_grade:
                raise click.UsageError(
                    "INCOME_GRADE_ADJUSTMENT requires --income-grade"
                )
            nested["Grade"] = income_grade

        # Plural fields expect a list per WSDL BidModifierAddItem
        if nested_key in _PLURAL_NESTED_KEYS:
            modifier_data = {nested_key: [nested]}
        else:
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

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


_DEPRECATED_BIDMODIFIERS_SET_OPTIONS = {
    "campaign_id": (
        "--campaign-id is no longer accepted on 'bidmodifiers set'; "
        "legacy --campaign-id/--type shape is not supported by "
        "WSDL BidModifierSetItem; use bidmodifiers add to create a new "
        "modifier."
    ),
    "modifier_type": (
        "--type is no longer accepted on 'bidmodifiers set'; "
        "legacy --campaign-id/--type shape is not supported by "
        "WSDL BidModifierSetItem; use bidmodifiers add to create a new "
        "modifier."
    ),
}


def _deprecated_legacy_option(ctx, param, value):
    if value is not None:
        raise click.UsageError(_DEPRECATED_BIDMODIFIERS_SET_OPTIONS[param.name])


@bidmodifiers.command()
@click.option(
    "--id",
    "modifier_id",
    type=int,
    help=(
        "Existing BidModifier ID to update. This is the shape Yandex "
        "Direct's ``bidmodifiers/set`` method actually supports — pass "
        "the Id of a modifier created via ``bidmodifiers add`` and the "
        "new ``--value``."
    ),
)
@click.option(
    "--campaign-id",
    default=None,
    expose_value=False,
    callback=_deprecated_legacy_option,
    is_eager=True,
    hidden=True,
    help="Removed: legacy --campaign-id/--type shape not supported by bidmodifiers set",
)
@click.option(
    "--type",
    "modifier_type",
    default=None,
    expose_value=False,
    callback=_deprecated_legacy_option,
    is_eager=True,
    hidden=True,
    help="Removed: legacy --campaign-id/--type shape not supported by bidmodifiers set",
)
@click.option("--value", type=int, required=True, help="Modifier value")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set(ctx, modifier_id, value, dry_run):
    """Set (update) an existing bid modifier

    The Yandex Direct API's ``bidmodifiers/set`` method updates existing
    modifiers by ``Id``. To create a new modifier, use ``bidmodifiers add``
    instead.
    """
    try:
        if modifier_id is None:
            raise click.UsageError(
                "Provide --id with --value for bidmodifiers set. "
                "The legacy --campaign-id/--type shape is not supported by "
                "WSDL BidModifierSetItem; use bidmodifiers add to create a "
                "new modifier."
            )

        # Correct API shape: Id + BidModifier. Nothing else.
        modifier_data = {"Id": modifier_id, "BidModifier": value}

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
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, modifier_id, dry_run):
    """Delete bid modifier"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [modifier_id]}},
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

"""
BidModifiers commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command
from ..utils import (
    parse_csv_upper,
    parse_ids,
)
from .._flag_validation import reject_incompatible_flags

# Yandex Direct bidmodifiers.get caps SelectionCriteria.CampaignIds at runtime
# (the WSDL declares maxOccurs="unbounded"). Live measurement 2026-06-17 via
# sandbox: --campaign-ids ×10001 → 4001 "Exceed the maximum number of IDs per
# array SelectionCriteria.CampaignIds" (N=1000 accepted). Ids and AdGroupIds
# accepted at N=10000.
BIDMODIFIERS_GET_CRITERIA_LIMITS = {"CampaignIds": 1000}


@click.group()
def bidmodifiers():
    """Manage bid modifiers"""


def _bidmodifiers_get_criteria(
    ids=None, campaign_ids=None, adgroup_ids=None, types=None, levels=(), **_
):
    """SelectionCriteria for ``bidmodifiers get``: a mandatory upper-cased
    ``Levels`` list plus optional Ids/CampaignIds/AdGroupIds id lists and an
    upper-cased ``Types`` list (an empty ``--types`` CSV maps to ``[]``)."""
    criteria = {"Levels": [lv.upper() for lv in levels]}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if types:
        criteria["Types"] = parse_csv_upper(types) or []
    return criteria


get = make_get_command(
    bidmodifiers,
    create_client,
    default_fields_key="bidmodifiers",
    help_text="Get bid modifiers",
    ids_help="Comma-separated bid modifier IDs",
    extra_options=(
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--types", help="Comma-separated bid modifier types"),
        click.option(
            "--levels",
            type=click.Choice(["CAMPAIGN", "AD_GROUP"], case_sensitive=False),
            multiple=True,
            default=("CAMPAIGN", "AD_GROUP"),
            show_default=True,
            help="Bid modifier levels to retrieve",
        ),
    ),
    criteria_builder=_bidmodifiers_get_criteria,
    criteria_limits=BIDMODIFIERS_GET_CRITERIA_LIMITS,
    nested_field_options=(
        (
            "--ad-group-adjustment-field-names",
            "AdGroupAdjustmentFieldNames",
            "Comma-separated AdGroupAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--demographics-adjustment-field-names",
            "DemographicsAdjustmentFieldNames",
            "Comma-separated DemographicsAdjustmentFieldNames "
            "(e.g. Gender,Age,BidModifier,Enabled). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--desktop-adjustment-field-names",
            "DesktopAdjustmentFieldNames",
            "Comma-separated DesktopAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--desktop-only-adjustment-field-names",
            "DesktopOnlyAdjustmentFieldNames",
            "Comma-separated DesktopOnlyAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--income-grade-adjustment-field-names",
            "IncomeGradeAdjustmentFieldNames",
            "Comma-separated IncomeGradeAdjustmentFieldNames "
            "(e.g. Grade,BidModifier,Enabled). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--mobile-adjustment-field-names",
            "MobileAdjustmentFieldNames",
            "Comma-separated MobileAdjustmentFieldNames "
            "(e.g. BidModifier,OperatingSystemType). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--regional-adjustment-field-names",
            "RegionalAdjustmentFieldNames",
            "Comma-separated RegionalAdjustmentFieldNames "
            "(e.g. RegionId,BidModifier,Enabled). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--retargeting-adjustment-field-names",
            "RetargetingAdjustmentFieldNames",
            "Comma-separated RetargetingAdjustmentFieldNames "
            "(e.g. RetargetingConditionId,BidModifier,Accessible,Enabled). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--serp-layout-adjustment-field-names",
            "SerpLayoutAdjustmentFieldNames",
            "Comma-separated SerpLayoutAdjustmentFieldNames "
            "(e.g. SerpLayout,BidModifier,Enabled). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--smart-ad-adjustment-field-names",
            "SmartAdAdjustmentFieldNames",
            "Comma-separated SmartAdAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--smart-tv-adjustment-field-names",
            "SmartTvAdjustmentFieldNames",
            "Comma-separated SmartTvAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--tablet-adjustment-field-names",
            "TabletAdjustmentFieldNames",
            "Comma-separated TabletAdjustmentFieldNames "
            "(e.g. BidModifier,OperatingSystemType). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
        (
            "--video-adjustment-field-names",
            "VideoAdjustmentFieldNames",
            "Comma-separated VideoAdjustmentFieldNames (e.g. BidModifier). "
            "Sent as separate top-level request parameter per the "
            "BidModifiersGetRequest WSDL.",
        ),
    ),
)


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


@bidmodifiers.command()
@click.option(
    "--campaign-id",
    type=click.IntRange(min=1),
    help="Campaign ID (mutually exclusive with --adgroup-id)",
)
@click.option(
    "--adgroup-id",
    type=click.IntRange(min=1),
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
@handle_api_errors
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
    if (campaign_id is None) == (adgroup_id is None):
        raise click.UsageError(
            t("Exactly one of --campaign-id or --adgroup-id is required")
        )

    modifier_type_upper = modifier_type.upper()
    reject_incompatible_flags(
        _BIDMODIFIER_ALLOWED_EXTRA_FLAGS[modifier_type_upper],
        {
            "--gender": gender,
            "--age": age,
            "--retargeting-condition-id": retargeting_condition_id,
            "--region-id": region_id,
            "--serp-layout": serp_layout,
            "--income-grade": income_grade,
            "--operating-system-type": operating_system_type,
        },
        message="{arg0} is not compatible with --type {modifier_type}.",
        type_value=modifier_type_upper,
        type_field="modifier_type",
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
                t("DEMOGRAPHICS_ADJUSTMENT requires --gender and/or --age")
            )
    elif modifier_type_upper == "RETARGETING_ADJUSTMENT":
        if retargeting_condition_id is None:
            raise click.UsageError(
                t("RETARGETING_ADJUSTMENT requires --retargeting-condition-id")
            )
        nested["RetargetingConditionId"] = retargeting_condition_id
    elif modifier_type_upper == "REGIONAL_ADJUSTMENT":
        if region_id is None:
            raise click.UsageError(t("REGIONAL_ADJUSTMENT requires --region-id"))
        nested["RegionId"] = region_id
    elif modifier_type_upper == "SERP_LAYOUT_ADJUSTMENT":
        if not serp_layout:
            raise click.UsageError(t("SERP_LAYOUT_ADJUSTMENT requires --serp-layout"))
        nested["SerpLayout"] = serp_layout
    elif modifier_type_upper == "INCOME_GRADE_ADJUSTMENT":
        if not income_grade:
            raise click.UsageError(t("INCOME_GRADE_ADJUSTMENT requires --income-grade"))
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

    execute_request(ctx, "bidmodifiers", body, dry_run, create_client)


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
    type=click.IntRange(min=1),
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
@handle_api_errors
def set(ctx, modifier_id, value, dry_run):
    """Set (update) an existing bid modifier

    The Yandex Direct API's ``bidmodifiers/set`` method updates existing
    modifiers by ``Id``. To create a new modifier, use ``bidmodifiers add``
    instead.
    """
    if modifier_id is None:
        raise click.UsageError(
            t(
                "Provide --id with --value for bidmodifiers set. "
                "The legacy --campaign-id/--type shape is not supported by "
                "WSDL BidModifierSetItem; use bidmodifiers add to create a "
                "new modifier."
            )
        )

    # Correct API shape: Id + BidModifier. Nothing else.
    modifier_data = {"Id": modifier_id, "BidModifier": value}

    body = {"method": "set", "params": {"BidModifiers": [modifier_data]}}

    execute_request(ctx, "bidmodifiers", body, dry_run, create_client)


delete = make_lifecycle_command(
    bidmodifiers,
    "delete",
    "Delete bid modifier",
    "modifier_id",
    "Modifier ID",
    create_client,
)

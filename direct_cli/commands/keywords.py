"""
Keywords commands
"""

from typing import Any, Dict, List, Optional

import click

from ..api import client_from_ctx, create_client
from ._get import make_get_command
from ..i18n import t
from ..output import (
    format_output,
    handle_api_errors,
)
from ..utils import (
    MICRO_RUBLES,
    add_criteria_csv,
    parse_ids,
)

from .._autotargeting import (
    AUTOTARGETING_BRAND_OPTIONS,
    AUTOTARGETING_CATEGORIES,
    build_autotargeting_settings,
    parse_autotargeting_brand_options,
    parse_autotargeting_categories,
    reject_legacy_autotargeting_mix,
)
from ._execute import execute_request
from ._lifecycle import register_lifecycle_commands
from . import _batch

# Yandex Direct keywords.get caps SelectionCriteria arrays at runtime
# (the WSDL declares them maxOccurs="unbounded"). Live measurement 2026-06-17
# via sandbox: --campaign-ids ×11 → 4001 "Exceed the maximum number of IDs per
# array SelectionCriteria.CampaignIds"; --adgroup-ids ×10001 → 4001 ".AdGroupIds"
# (N=1000 accepted). Ids accepted at N=10000.
KEYWORDS_GET_CRITERIA_LIMITS = {"CampaignIds": 10, "AdGroupIds": 1000}

# Chunk size for batch `keywords add`: items from --from-file / --keywords-json
# are split into chunks of this size and sent in a loop. This is a conservative
# CHUNK SIZE, not the API ceiling — the documented per-call limit is 1000
# (Yandex docs, keywords/add page). Keeping each request small means a partial
# failure rolls back at most this many items, not 1000. The WSDL declares the
# Keywords array maxOccurs="unbounded"; the real cap is runtime policy, not the
# contract.
KEYWORDS_ADD_MAX_BATCH = 10

# Yandex Direct caps the number of keywords per ad group at 200 (same docs).
# Going over the limit doesn't fail pre-flight — the API rejects the excess
# items with per-item errors, which the batch already surfaces. The warning
# below just tells the operator before any chunk is sent.
KEYWORDS_PER_ADGROUP_LIMIT = 200

AUTOTARGETING_CATEGORY_HELP = (
    "AutotargetingCategories item as CATEGORY=YES|NO. Categories: "
    + ", ".join(AUTOTARGETING_CATEGORIES)
)
AUTOTARGETING_BRAND_OPTION_HELP = (
    "AutotargetingBrandOptions item as OPTION=YES|NO. Options: "
    + ", ".join(AUTOTARGETING_BRAND_OPTIONS)
)

_KEYWORD_ROW_FIELDS: Dict[str, str] = {
    "Keyword": "str",
    "AdGroupId": "int",
    "Bid": "micro",
    "ContextBid": "micro",
    "UserParam1": "str",
    "UserParam2": "str",
}

_KEYWORD_BATCH_DEFERRED_FIELDS = {
    "AutotargetingSearchBidIsAuto": "--autotargeting-search-bid-is-auto",
    "StrategyPriority": "--priority",
    "AutotargetingCategories": "--autotargeting-category",
    "AutotargetingBrandOptions": "--autotargeting-brand-option",
    "AutotargetingSettings": "--autotargeting-settings-* flags",
}


def _coerce_keyword_field(field: str, raw_value: Any, row_index: int) -> Any:
    kind = _KEYWORD_ROW_FIELDS[field]
    if isinstance(raw_value, bool):
        raise click.UsageError(
            t("Row {row_index} field {field!r}: expected {kind}, got bool").format(
                row_index=row_index, field=field, kind=kind
            )
        )
    if kind == "str":
        if not isinstance(raw_value, str):
            raise click.UsageError(
                t(
                    "Row {row_index} field {field!r}: expected string, got {arg0}"
                ).format(
                    row_index=row_index, field=field, arg0=type(raw_value).__name__
                )
            )
        return raw_value
    if kind == "int":
        if isinstance(raw_value, int):
            return raw_value
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            raise click.UsageError(
                t(
                    "Row {row_index} field {field!r}: expected integer, got {raw_value!r}"
                ).format(row_index=row_index, field=field, raw_value=raw_value)
            )
    if kind == "micro":
        try:
            return MICRO_RUBLES.convert(raw_value, None, None)
        except click.exceptions.BadParameter as exc:
            raise click.UsageError(
                t("Row {row_index} field {field!r}: {arg0}").format(
                    row_index=row_index, field=field, arg0=exc.message
                )
            )
    raise click.UsageError(
        t("Row {row_index} field {field!r}: unsupported type {kind!r}").format(
            row_index=row_index, field=field, kind=kind
        )
    )


def _normalize_keyword_row(
    row: Any,
    row_index: int,
    default_adgroup_id: Optional[int],
) -> Dict[str, Any]:
    if not isinstance(row, dict):
        raise click.UsageError(
            t("Row {row_index}: expected JSON object, got {arg0}").format(
                row_index=row_index, arg0=type(row).__name__
            )
        )

    deferred = sorted(set(row) & set(_KEYWORD_BATCH_DEFERRED_FIELDS))
    if deferred:
        field = deferred[0]
        flag = _KEYWORD_BATCH_DEFERRED_FIELDS[field]
        raise click.UsageError(
            t(
                "Keyword row {row_index} field {field!r} is intentionally unsupported in batch mode; use the single-item typed option {flag} instead."
            ).format(row_index=row_index, field=field, flag=flag)
        )

    unknown = sorted(set(row) - set(_KEYWORD_ROW_FIELDS))
    if unknown:
        allowed = ", ".join(_KEYWORD_ROW_FIELDS)
        raise click.UsageError(
            t(
                "Unknown field {arg0!r} in keyword row {row_index}; allowed: {allowed}"
            ).format(arg0=unknown[0], row_index=row_index, allowed=allowed)
        )

    item: Dict[str, Any] = {}
    for field in _KEYWORD_ROW_FIELDS:
        if field in row and row[field] is not None:
            item[field] = _coerce_keyword_field(field, row[field], row_index)

    if "AdGroupId" not in item:
        if default_adgroup_id is None:
            raise click.UsageError(
                t(
                    "Row {row_index}: missing 'AdGroupId' and no default --adgroup-id provided"
                ).format(row_index=row_index)
            )
        item["AdGroupId"] = default_adgroup_id

    if "Keyword" not in item:
        raise click.UsageError(
            t("Row {row_index}: missing required field 'Keyword'").format(
                row_index=row_index
            )
        )

    return item


def _warn_on_adgroup_overflow(items: List[Dict[str, Any]]) -> None:
    counts: Dict[int, int] = {}
    for item in items:
        adgroup_id = item.get("AdGroupId")
        if adgroup_id is None:
            continue
        counts[adgroup_id] = counts.get(adgroup_id, 0) + 1
    over = sorted(
        (gid, n) for gid, n in counts.items() if n > KEYWORDS_PER_ADGROUP_LIMIT
    )
    if not over:
        return
    click.echo(
        f"Warning: input exceeds the Yandex Direct limit of "
        f"{KEYWORDS_PER_ADGROUP_LIMIT} keywords per ad group; the API will "
        "reject the excess with per-item errors:",
        err=True,
    )
    for gid, count in over:
        excess = count - KEYWORDS_PER_ADGROUP_LIMIT
        click.echo(
            f"  AdGroupId={gid}: {count} keywords ({excess} over the limit)",
            err=True,
        )


@click.group()
def keywords():
    """Manage keywords"""


def _keywords_get_criteria(
    ids=None,
    adgroup_ids=None,
    campaign_ids=None,
    status=None,
    statuses=None,
    states=None,
    modified_since=None,
    serving_statuses=None,
    **_,
):
    """SelectionCriteria for ``keywords get``: optional Ids/AdGroupIds/CampaignIds,
    a singular ``--status`` or upper-cased ``--statuses`` (mutually exclusive),
    upper-cased States/ServingStatuses and a ModifiedSince scalar."""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if adgroup_ids:
        criteria["AdGroupIds"] = parse_ids(adgroup_ids)
    if campaign_ids:
        criteria["CampaignIds"] = parse_ids(campaign_ids)
    if status:
        criteria["Statuses"] = [status]
    add_criteria_csv(criteria, "Statuses", statuses, upper=True)
    add_criteria_csv(criteria, "States", states, upper=True)
    if modified_since:
        criteria["ModifiedSince"] = modified_since
    add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)
    return criteria


get = make_get_command(
    keywords,
    create_client,
    default_fields_key="keywords",
    help_text="Get keywords",
    ids_help="Comma-separated keyword IDs",
    extra_options=(
        click.option("--adgroup-ids", help="Comma-separated ad group IDs"),
        click.option("--campaign-ids", help="Comma-separated campaign IDs"),
        click.option("--status", help="Filter by status"),
        click.option("--statuses", help="Comma-separated statuses"),
        click.option("--states", help="Comma-separated states"),
        click.option("--modified-since", help="ModifiedSince datetime"),
        click.option("--serving-statuses", help="Comma-separated serving statuses"),
    ),
    criteria_builder=_keywords_get_criteria,
    criteria_limits=KEYWORDS_GET_CRITERIA_LIMITS,
    require_criteria_message="Provide at least one typed filter",
    nested_field_options=(
        (
            "--autotargeting-settings-brand-options-field-names",
            "AutotargetingSettingsBrandOptionsFieldNames",
            "Comma-separated AutotargetingSettingsBrandOptionsFieldNames "
            "(e.g. WithoutBrands,WithAdvertiserBrand,WithCompetitorsBrand). "
            "Sent as separate top-level request parameter per the "
            "KeywordsGetRequest WSDL.",
        ),
        (
            "--autotargeting-settings-categories-field-names",
            "AutotargetingSettingsCategoriesFieldNames",
            "Comma-separated AutotargetingSettingsCategoriesFieldNames "
            "(e.g. Exact,Narrow,Alternative,Accessory,Broader). "
            "Sent as separate top-level request parameter per the "
            "KeywordsGetRequest WSDL.",
        ),
    ),
)


@keywords.command()
@click.option(
    "--adgroup-id",
    type=click.IntRange(min=1),
    help="Ad group ID (default in batch mode)",
)
@click.option("--keyword", help="Keyword text (single-item mode)")
@click.option("--bid", type=MICRO_RUBLES, help="Search bid in micro-rubles")
@click.option("--context-bid", type=MICRO_RUBLES, help="Context bid in micro-rubles")
@click.option(
    "--autotargeting-search-bid-is-auto",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSearchBidIsAuto value: YES or NO",
)
@click.option(
    "--priority",
    type=click.Choice(["LOW", "NORMAL", "HIGH"], case_sensitive=False),
    help="StrategyPriority value: LOW, NORMAL, or HIGH",
)
@click.option(
    "--autotargeting-category",
    "autotargeting_categories",
    multiple=True,
    help=AUTOTARGETING_CATEGORY_HELP,
)
@click.option(
    "--autotargeting-brand-option",
    "autotargeting_brand_options",
    multiple=True,
    help=AUTOTARGETING_BRAND_OPTION_HELP,
)
@click.option(
    "--autotargeting-settings-exact",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Exact value: YES or NO",
)
@click.option(
    "--autotargeting-settings-narrow",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Narrow value: YES or NO",
)
@click.option(
    "--autotargeting-settings-alternative",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Alternative value: YES or NO",
)
@click.option(
    "--autotargeting-settings-accessory",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Accessory value: YES or NO",
)
@click.option(
    "--autotargeting-settings-broader",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Broader value: YES or NO",
)
@click.option(
    "--autotargeting-settings-without-brands",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.BrandOptions.WithoutBrands value: YES or NO",
)
@click.option(
    "--autotargeting-settings-with-advertiser-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=("AutotargetingSettings.BrandOptions.WithAdvertiserBrand value: YES or NO"),
)
@click.option(
    "--autotargeting-settings-with-competitors-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=("AutotargetingSettings.BrandOptions.WithCompetitorsBrand value: YES or NO"),
)
@click.option("--user-param-1", help="User parameter 1")
@click.option("--user-param-2", help="User parameter 2")
@click.option(
    "--from-file",
    "from_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    help="Path to JSONL file (one keyword object per line)",
)
@click.option(
    "--keywords-json",
    "keywords_json",
    help="Inline JSON array of keyword objects",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (batch mode supports only json)",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(
    ctx,
    adgroup_id,
    keyword,
    bid,
    context_bid,
    autotargeting_search_bid_is_auto,
    priority,
    autotargeting_categories,
    autotargeting_brand_options,
    autotargeting_settings_exact,
    autotargeting_settings_narrow,
    autotargeting_settings_alternative,
    autotargeting_settings_accessory,
    autotargeting_settings_broader,
    autotargeting_settings_without_brands,
    autotargeting_settings_with_advertiser_brand,
    autotargeting_settings_with_competitors_brand,
    user_param_1,
    user_param_2,
    from_file,
    keywords_json,
    output_format,
    dry_run,
):
    """Add one or many keywords (batch via --from-file / --keywords-json)."""
    modes_used = sum(
        1 for value in (keyword, from_file, keywords_json) if value is not None
    )
    if modes_used == 0:
        raise click.UsageError(
            t(
                "Provide exactly one of: --keyword (single), --from-file (JSONL), "
                "or --keywords-json (inline JSON array)."
            )
        )
    if modes_used > 1:
        raise click.UsageError(
            t(
                "Provide exactly one of: --keyword, --from-file, or "
                "--keywords-json — they are mutually exclusive."
            )
        )

    batch_mode = from_file is not None or keywords_json is not None

    if batch_mode:
        single_item_flags = {
            "--bid": bid,
            "--context-bid": context_bid,
            "--autotargeting-search-bid-is-auto": autotargeting_search_bid_is_auto,
            "--priority": priority,
            "--autotargeting-category": autotargeting_categories,
            "--autotargeting-brand-option": autotargeting_brand_options,
            "--autotargeting-settings-exact": autotargeting_settings_exact,
            "--autotargeting-settings-narrow": autotargeting_settings_narrow,
            "--autotargeting-settings-alternative": (
                autotargeting_settings_alternative
            ),
            "--autotargeting-settings-accessory": autotargeting_settings_accessory,
            "--autotargeting-settings-broader": autotargeting_settings_broader,
            "--autotargeting-settings-without-brands": (
                autotargeting_settings_without_brands
            ),
            "--autotargeting-settings-with-advertiser-brand": (
                autotargeting_settings_with_advertiser_brand
            ),
            "--autotargeting-settings-with-competitors-brand": (
                autotargeting_settings_with_competitors_brand
            ),
            "--user-param-1": user_param_1,
            "--user-param-2": user_param_2,
        }
        unsupported = [
            flag for flag, value in single_item_flags.items() if value not in (None, ())
        ]
        if unsupported:
            raise click.UsageError(
                t("{arg0} supported only with --keyword single-item mode").format(
                    arg0=", ".join(unsupported)
                )
            )
        _bulk_add(
            ctx,
            adgroup_id=adgroup_id,
            from_file=from_file,
            keywords_json=keywords_json,
            output_format=output_format,
            dry_run=dry_run,
        )
        return

    if adgroup_id is None:
        raise click.UsageError(t("Missing option '--adgroup-id'."))

    parsed_autotargeting_categories = parse_autotargeting_categories(
        autotargeting_categories
    )
    parsed_autotargeting_brand_options = parse_autotargeting_brand_options(
        autotargeting_brand_options
    )
    autotargeting_settings = build_autotargeting_settings(
        exact=autotargeting_settings_exact,
        narrow=autotargeting_settings_narrow,
        alternative=autotargeting_settings_alternative,
        accessory=autotargeting_settings_accessory,
        broader=autotargeting_settings_broader,
        without_brands=autotargeting_settings_without_brands,
        with_advertiser_brand=autotargeting_settings_with_advertiser_brand,
        with_competitors_brand=autotargeting_settings_with_competitors_brand,
    )
    reject_legacy_autotargeting_mix(
        autotargeting_settings,
        legacy_candidates=[
            ("--autotargeting-category", bool(autotargeting_categories)),
            ("--autotargeting-brand-option", bool(autotargeting_brand_options)),
        ],
    )

    keyword_data: Dict[str, Any] = {
        "AdGroupId": adgroup_id,
        "Keyword": keyword,
    }
    if bid is not None:
        keyword_data["Bid"] = bid
    if context_bid is not None:
        keyword_data["ContextBid"] = context_bid
    if autotargeting_search_bid_is_auto is not None:
        keyword_data["AutotargetingSearchBidIsAuto"] = (
            autotargeting_search_bid_is_auto.upper()
        )
    if priority is not None:
        keyword_data["StrategyPriority"] = priority.upper()
    if parsed_autotargeting_categories is not None:
        keyword_data["AutotargetingCategories"] = parsed_autotargeting_categories
    if parsed_autotargeting_brand_options is not None:
        keyword_data["AutotargetingBrandOptions"] = parsed_autotargeting_brand_options
    if autotargeting_settings is not None:
        keyword_data["AutotargetingSettings"] = autotargeting_settings
    if user_param_1:
        keyword_data["UserParam1"] = user_param_1
    if user_param_2:
        keyword_data["UserParam2"] = user_param_2

    body = {"method": "add", "params": {"Keywords": [keyword_data]}}

    if dry_run:
        format_output(body, output_format, None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.keywords().post(data=body)
    format_output(result().extract(), output_format, None)


def _bulk_add(
    ctx,
    *,
    adgroup_id: Optional[int],
    from_file: Optional[str],
    keywords_json: Optional[str],
    output_format: str,
    dry_run: bool,
) -> None:
    if output_format != "json":
        raise click.UsageError(
            t(
                "--format other than 'json' is not supported in batch mode "
                "(item-level results may include per-row Errors)."
            )
        )

    if from_file is not None:
        raw_rows = _batch.load_jsonl_rows(from_file)
    else:
        raw_rows = _batch.load_inline_rows(
            keywords_json or "",
            invalid_json_key="--keywords-json: invalid JSON: {arg0}",
            not_array_key="--keywords-json must be a JSON array of keyword objects",
        )

    if not raw_rows:
        raise click.UsageError(t("Input contains no keyword rows."))

    items: List[Dict[str, Any]] = [
        _normalize_keyword_row(row, idx, adgroup_id)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    _batch.send_batch(
        ctx,
        resource="keywords",
        method="add",
        payload_key="Keywords",
        items=items,
        max_batch=KEYWORDS_ADD_MAX_BATCH,
        create_client=create_client,
        dry_run=dry_run,
        noun="keywords",
        on_warn=_warn_on_adgroup_overflow,
    )


_DEPRECATED_KEYWORDS_UPDATE_OPTIONS = {
    "bid": "--bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --bid VALUE",
    "context_bid": "--context-bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --network-bid VALUE",
    "status": "--status is no longer accepted on 'keywords update'; status is not mutable via the keywords API",
}


def _deprecated_bid_option(ctx, param, value):
    if value is not None:
        raise click.UsageError(_DEPRECATED_KEYWORDS_UPDATE_OPTIONS[param.name])


@keywords.command()
@click.option(
    "--id", "keyword_id", required=True, type=click.IntRange(min=1), help="Keyword ID"
)
@click.option("--keyword", help="New keyword text")
@click.option("--user-param-1", help="User parameter 1")
@click.option("--user-param-2", help="User parameter 2")
@click.option(
    "--autotargeting-category",
    "autotargeting_categories",
    multiple=True,
    help=AUTOTARGETING_CATEGORY_HELP,
)
@click.option(
    "--autotargeting-brand-option",
    "autotargeting_brand_options",
    multiple=True,
    help=AUTOTARGETING_BRAND_OPTION_HELP,
)
@click.option(
    "--autotargeting-settings-exact",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Exact value: YES or NO",
)
@click.option(
    "--autotargeting-settings-narrow",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Narrow value: YES or NO",
)
@click.option(
    "--autotargeting-settings-alternative",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Alternative value: YES or NO",
)
@click.option(
    "--autotargeting-settings-accessory",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Accessory value: YES or NO",
)
@click.option(
    "--autotargeting-settings-broader",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.Categories.Broader value: YES or NO",
)
@click.option(
    "--autotargeting-settings-without-brands",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help="AutotargetingSettings.BrandOptions.WithoutBrands value: YES or NO",
)
@click.option(
    "--autotargeting-settings-with-advertiser-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=("AutotargetingSettings.BrandOptions.WithAdvertiserBrand value: YES or NO"),
)
@click.option(
    "--autotargeting-settings-with-competitors-brand",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    help=("AutotargetingSettings.BrandOptions.WithCompetitorsBrand value: YES or NO"),
)
@click.option(
    "--bid",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: use 'bids set --keyword-id ID --bid VALUE'",
)
@click.option(
    "--context-bid",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: use 'bids set --keyword-id ID --network-bid VALUE'",
)
@click.option(
    "--status",
    default=None,
    expose_value=False,
    callback=_deprecated_bid_option,
    is_eager=True,
    hidden=True,
    help="Removed: status is not mutable via keywords update",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def update(
    ctx,
    keyword_id,
    keyword,
    user_param_1,
    user_param_2,
    autotargeting_categories,
    autotargeting_brand_options,
    autotargeting_settings_exact,
    autotargeting_settings_narrow,
    autotargeting_settings_alternative,
    autotargeting_settings_accessory,
    autotargeting_settings_broader,
    autotargeting_settings_without_brands,
    autotargeting_settings_with_advertiser_brand,
    autotargeting_settings_with_competitors_brand,
    dry_run,
):
    """Update keyword text, user params, or autotargeting options."""
    keyword_data = {"Id": keyword_id}
    parsed_autotargeting_categories = parse_autotargeting_categories(
        autotargeting_categories
    )
    parsed_autotargeting_brand_options = parse_autotargeting_brand_options(
        autotargeting_brand_options
    )
    autotargeting_settings = build_autotargeting_settings(
        exact=autotargeting_settings_exact,
        narrow=autotargeting_settings_narrow,
        alternative=autotargeting_settings_alternative,
        accessory=autotargeting_settings_accessory,
        broader=autotargeting_settings_broader,
        without_brands=autotargeting_settings_without_brands,
        with_advertiser_brand=autotargeting_settings_with_advertiser_brand,
        with_competitors_brand=autotargeting_settings_with_competitors_brand,
    )
    reject_legacy_autotargeting_mix(
        autotargeting_settings,
        legacy_candidates=[
            ("--autotargeting-category", bool(autotargeting_categories)),
            ("--autotargeting-brand-option", bool(autotargeting_brand_options)),
        ],
    )

    if keyword:
        keyword_data["Keyword"] = keyword
    if user_param_1 is not None:
        keyword_data["UserParam1"] = user_param_1
    if user_param_2 is not None:
        keyword_data["UserParam2"] = user_param_2
    if parsed_autotargeting_categories is not None:
        keyword_data["AutotargetingCategories"] = parsed_autotargeting_categories
    if parsed_autotargeting_brand_options is not None:
        keyword_data["AutotargetingBrandOptions"] = parsed_autotargeting_brand_options
    if autotargeting_settings is not None:
        keyword_data["AutotargetingSettings"] = autotargeting_settings

    # Reject empty-payload no-op (issue #198 H10).
    if len(keyword_data) == 1:
        raise click.UsageError(
            t(
                "keywords update requires at least one updatable field "
                "(--keyword, --user-param-1, --user-param-2, "
                "--autotargeting-category, --autotargeting-brand-option, "
                "or --autotargeting-settings-* flags)."
            )
        )

    body = {"method": "update", "params": {"Keywords": [keyword_data]}}

    execute_request(ctx, "keywords", body, dry_run, create_client)


register_lifecycle_commands(
    keywords,
    "keyword_id",
    "Keyword ID",
    create_client,
    [
        ("delete", "Delete keyword"),
        ("suspend", "Suspend keyword"),
        ("resume", "Resume keyword"),
    ],
)

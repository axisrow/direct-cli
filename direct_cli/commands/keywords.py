"""
Keywords commands
"""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import (
    format_json,
    format_output,
    handle_api_errors,
    print_error,
    raise_for_api_result_errors,
)
from ..utils import (
    MICRO_RUBLES,
    add_criteria_csv,
    build_common_params,
    get_default_fields,
    parse_csv_strings,
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

# Yandex Direct API "keywords.add" caps a single AddItems request at 10
# items; the WSDL declares maxOccurs="unbounded", so this limit comes from
# the documentation rather than the contract:
# https://yandex.ru/dev/direct/doc/dg/objects/keyword.html
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


def _load_keyword_rows_from_file(path: str) -> List[Any]:
    rows: List[Any] = []
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise click.UsageError(
            t("Cannot read --from-file {path!r}: {exc}").format(path=path, exc=exc)
        )

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise click.UsageError(
                t("Row {line_number}: invalid JSON: {arg0}").format(
                    line_number=line_number, arg0=exc.msg
                )
            )
    return rows


def _load_keyword_rows_from_inline(json_str: str) -> List[Any]:
    try:
        decoded = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise click.UsageError(
            t("--keywords-json: invalid JSON: {arg0}").format(arg0=exc.msg)
        )
    if not isinstance(decoded, list):
        raise click.UsageError(
            t("--keywords-json must be a JSON array of keyword objects")
        )
    return decoded


def _chunked(items: List[Any], size: int) -> Iterator[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


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


def _normalize_add_results(raw: Any) -> List[Any]:
    if isinstance(raw, dict):
        results = raw.get("AddResults")
        if isinstance(results, list):
            return results
        return [raw]
    if isinstance(raw, list):
        return raw
    return [raw]


@click.group()
def keywords():
    """Manage keywords"""


@keywords.command()
@click.option("--ids", help="Comma-separated keyword IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--states", help="Comma-separated states")
@click.option("--modified-since", help="ModifiedSince datetime")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--autotargeting-settings-brand-options-field-names",
    help=(
        "Comma-separated AutotargetingSettingsBrandOptionsFieldNames "
        "(e.g. WithoutBrands,WithAdvertiserBrand,WithCompetitorsBrand). "
        "Sent as separate top-level request parameter per the "
        "KeywordsGetRequest WSDL."
    ),
)
@click.option(
    "--autotargeting-settings-categories-field-names",
    help=(
        "Comma-separated AutotargetingSettingsCategoriesFieldNames "
        "(e.g. Exact,Narrow,Alternative,Accessory,Broader). "
        "Sent as separate top-level request parameter per the "
        "KeywordsGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    adgroup_ids,
    campaign_ids,
    status,
    statuses,
    states,
    modified_since,
    serving_statuses,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    autotargeting_settings_brand_options_field_names,
    autotargeting_settings_categories_field_names,
    dry_run,
):
    """Get keywords"""
    if status and statuses:
        raise click.UsageError(t("--status and --statuses are mutually exclusive"))

    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("keywords")

    parsed_brand_options = parse_csv_strings(
        autotargeting_settings_brand_options_field_names
    )
    if (
        autotargeting_settings_brand_options_field_names is not None
        and not parsed_brand_options
    ):
        raise click.UsageError(
            t(
                "Provide a non-empty comma-separated "
                "AutotargetingSettingsBrandOptionsFieldNames list."
            )
        )

    parsed_categories = parse_csv_strings(autotargeting_settings_categories_field_names)
    if (
        autotargeting_settings_categories_field_names is not None
        and not parsed_categories
    ):
        raise click.UsageError(
            t(
                "Provide a non-empty comma-separated "
                "AutotargetingSettingsCategoriesFieldNames list."
            )
        )

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

    if not criteria:
        raise click.UsageError(t("Provide at least one typed filter"))

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )
    if parsed_brand_options:
        params["AutotargetingSettingsBrandOptionsFieldNames"] = parsed_brand_options
    if parsed_categories:
        params["AutotargetingSettingsCategoriesFieldNames"] = parsed_categories

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.keywords().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@keywords.command()
@click.option("--adgroup-id", type=int, help="Ad group ID (default in batch mode)")
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
        raw_rows = _load_keyword_rows_from_file(from_file)
    else:
        raw_rows = _load_keyword_rows_from_inline(keywords_json or "")

    if not raw_rows:
        raise click.UsageError(t("Input contains no keyword rows."))

    items: List[Dict[str, Any]] = [
        _normalize_keyword_row(row, idx, adgroup_id)
        for idx, row in enumerate(raw_rows, start=1)
    ]

    _warn_on_adgroup_overflow(items)

    chunks = list(_chunked(items, KEYWORDS_ADD_MAX_BATCH))

    if dry_run:
        preview = {
            "chunks": len(chunks),
            "totalItems": len(items),
            "chunkSize": KEYWORDS_ADD_MAX_BATCH,
            "firstChunk": {
                "method": "add",
                "params": {"Keywords": chunks[0]},
            },
        }
        print(format_json(preview, indent=2))
        return

    all_results: List[Any] = []
    try:
        client = client_from_ctx(ctx, create_client)

        for index, chunk in enumerate(chunks, start=1):
            click.echo(
                f"Sending chunk {index}/{len(chunks)}: {len(chunk)} items",
                err=True,
            )
            body = {"method": "add", "params": {"Keywords": chunk}}
            response = client.keywords().post(data=body)
            chunk_results = _normalize_add_results(response().extract())
            # Only items without per-item Errors are "already created" — the
            # partial-success diagnostic must not lie about failed items.
            all_results.extend(
                item
                for item in chunk_results
                if not (isinstance(item, dict) and item.get("Errors"))
            )
            raise_for_api_result_errors(chunk_results)

        format_output({"AddResults": all_results}, "json", None)
    except click.UsageError:
        raise
    except Exception as e:
        if all_results:
            click.echo(
                "Partial success before failure — these keywords were already "
                "created in Yandex Direct (retrying will duplicate them):",
                err=True,
            )
            click.echo(format_json({"AddResults": all_results}, indent=2), err=True)
        print_error(str(e))
        raise click.Abort()


_DEPRECATED_KEYWORDS_UPDATE_OPTIONS = {
    "bid": "--bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --bid VALUE",
    "context_bid": "--context-bid is no longer accepted on 'keywords update'; use: direct bids set --keyword-id ID --network-bid VALUE",
    "status": "--status is no longer accepted on 'keywords update'; status is not mutable via the keywords API",
}


def _deprecated_bid_option(ctx, param, value):
    if value is not None:
        raise click.UsageError(_DEPRECATED_KEYWORDS_UPDATE_OPTIONS[param.name])


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
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

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.keywords().post(data=body)
    format_output(result().extract(), "json", None)


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def delete(ctx, keyword_id, dry_run):
    """Delete keyword"""
    body = {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.keywords().post(data=body)
    format_output(result().extract(), "json", None)


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def suspend(ctx, keyword_id, dry_run):
    """Suspend keyword"""
    body = {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.keywords().post(data=body)
    format_output(result().extract(), "json", None)


@keywords.command()
@click.option("--id", "keyword_id", required=True, type=int, help="Keyword ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def resume(ctx, keyword_id, dry_run):
    """Resume keyword"""
    body = {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [keyword_id]}},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)

    result = client.keywords().post(data=body)
    format_output(result().extract(), "json", None)

"""
Ad Groups commands
"""

from typing import Optional

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import (
    add_criteria_csv,
    get_default_fields,
    parse_csv_strings,
    parse_ids,
)

_TRACKING_PARAMS_MAX_LENGTH = 1024


@click.group()
def adgroups():
    """Manage ad groups"""


def _validate_tracking_params(tracking_params: Optional[str]) -> None:
    """Validate AdGroup*.TrackingParams documented API constraints."""
    if (
        tracking_params is not None
        and len(tracking_params) > _TRACKING_PARAMS_MAX_LENGTH
    ):
        raise click.UsageError(
            "--tracking-params must be at most "
            f"{_TRACKING_PARAMS_MAX_LENGTH} characters"
        )


def _parse_ids_option(value: Optional[str], option_name: str) -> Optional[list[int]]:
    """Parse comma-separated IDs and report bad input as a Click usage error."""
    try:
        return parse_ids(value)
    except ValueError as exc:
        raise click.UsageError(f"{option_name}: {exc}") from exc


def _reject_incompatible_flags(
    group_type: str,
    allowed_flags: set[str],
    provided_flags: dict[str, object],
) -> None:
    """Reject subtype-specific flags that do not apply to ``group_type``."""
    incompatible = [
        flag
        for flag, value in provided_flags.items()
        if value is not None and flag not in allowed_flags
    ]
    if incompatible:
        raise click.UsageError(
            f"{', '.join(sorted(incompatible))} is not compatible with --type "
            f"{group_type}."
        )


@adgroups.command()
@click.option("--ids", help="Comma-separated ad group IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--types", help="Filter by types")
@click.option("--tag-ids", help="Comma-separated tag IDs")
@click.option("--tags", help="Comma-separated tag names")
@click.option("--app-icon-statuses", help="Comma-separated app icon statuses")
@click.option("--serving-statuses", help="Comma-separated serving statuses")
@click.option(
    "--negative-keyword-shared-set-ids",
    help="Comma-separated negative keyword shared set IDs",
)
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    campaign_ids,
    status,
    statuses,
    types,
    tag_ids,
    tags,
    app_icon_statuses,
    serving_statuses,
    negative_keyword_shared_set_ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get ad groups"""
    if status and statuses:
        raise click.UsageError("--status and --statuses are mutually exclusive")

    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = fields.split(",") if fields else get_default_fields("adgroups")

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if status:
            criteria["Statuses"] = [status]
        add_criteria_csv(criteria, "Statuses", statuses, upper=True)
        if types:
            criteria["Types"] = types.split(",")
        add_criteria_csv(criteria, "TagIds", tag_ids, integers=True)
        add_criteria_csv(criteria, "Tags", tags)
        add_criteria_csv(criteria, "AppIconStatuses", app_icon_statuses, upper=True)
        add_criteria_csv(criteria, "ServingStatuses", serving_statuses, upper=True)
        add_criteria_csv(
            criteria,
            "NegativeKeywordSharedSetIds",
            negative_keyword_shared_set_ids,
            integers=True,
        )

        params = {"SelectionCriteria": criteria, "FieldNames": field_names}

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        result = client.adgroups().post(data=body)

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


@adgroups.command()
@click.option("--name", required=True, help="Ad group name")
@click.option("--campaign-id", required=True, type=int, help="Campaign ID")
@click.option(
    "--type",
    "group_type",
    default="TEXT_AD_GROUP",
    help="Ad group type",
)
@click.option(
    "--region-ids",
    required=True,
    help="Comma-separated region IDs (WSDL AdGroupAddItem.RegionIds minOccurs=1)",
)
@click.option("--domain-url", help="Dynamic text ad group domain URL")
@click.option("--feed-id", type=int, help="Smart ad group feed ID")
@click.option("--ad-title-source", help="Smart ad group title source")
@click.option("--ad-body-source", help="Smart ad group body source")
@click.option(
    "--negative-keywords",
    help="Comma-separated ad-group negative keywords for NegativeKeywords.Items",
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated negative keyword shared set IDs for "
        "NegativeKeywordSharedSetIds.Items"
    ),
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for AdGroupAddItem.TrackingParams "
        "(max 1024 chars)"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    name,
    campaign_id,
    group_type,
    region_ids,
    domain_url,
    feed_id,
    ad_title_source,
    ad_body_source,
    negative_keywords,
    negative_keyword_shared_set_ids,
    tracking_params,
    dry_run,
):
    """Add new ad group"""
    try:
        _validate_tracking_params(tracking_params)

        group_type_norm = (group_type or "TEXT_AD_GROUP").upper().replace("-", "_")
        supported_types = {
            "TEXT_AD_GROUP",
            "DYNAMIC_TEXT_AD_GROUP",
            "SMART_AD_GROUP",
        }
        if group_type_norm not in supported_types:
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{group_type!r} is not one of "
                "'TEXT_AD_GROUP', 'DYNAMIC_TEXT_AD_GROUP', 'SMART_AD_GROUP'."
            )
        allowed_flags_by_type = {
            "TEXT_AD_GROUP": set(),
            "DYNAMIC_TEXT_AD_GROUP": {"--domain-url"},
            "SMART_AD_GROUP": {"--feed-id", "--ad-title-source", "--ad-body-source"},
        }
        _reject_incompatible_flags(
            group_type_norm,
            allowed_flags_by_type[group_type_norm],
            {
                "--domain-url": domain_url,
                "--feed-id": feed_id,
                "--ad-title-source": ad_title_source,
                "--ad-body-source": ad_body_source,
            },
        )

        adgroup_data = {"Name": name, "CampaignId": campaign_id}

        if region_ids:
            adgroup_data["RegionIds"] = _parse_ids_option(region_ids, "--region-ids")
        parsed_negative_keywords = parse_csv_strings(negative_keywords)
        if parsed_negative_keywords:
            adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
        parsed_negative_keyword_shared_set_ids = _parse_ids_option(
            negative_keyword_shared_set_ids,
            "--negative-keyword-shared-set-ids",
        )
        if parsed_negative_keyword_shared_set_ids:
            adgroup_data["NegativeKeywordSharedSetIds"] = {
                "Items": parsed_negative_keyword_shared_set_ids
            }
        if tracking_params:
            adgroup_data["TrackingParams"] = tracking_params
        if group_type_norm == "DYNAMIC_TEXT_AD_GROUP":
            if not domain_url:
                raise click.UsageError(
                    "--domain-url is required for DYNAMIC_TEXT_AD_GROUP"
                )
            adgroup_data["DynamicTextAdGroup"] = {"DomainUrl": domain_url}
        elif group_type_norm == "SMART_AD_GROUP":
            if feed_id is None:
                raise click.UsageError("--feed-id is required for SMART_AD_GROUP")
            smart_ad_group = {"FeedId": feed_id}
            if ad_title_source:
                smart_ad_group["AdTitleSource"] = ad_title_source
            if ad_body_source:
                smart_ad_group["AdBodySource"] = ad_body_source
            adgroup_data["SmartAdGroup"] = smart_ad_group

        body = {"method": "add", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--name", help="New ad group name")
@click.option("--status", help="New status")
@click.option("--region-ids", help="Comma-separated region IDs")
@click.option(
    "--negative-keywords",
    help="Comma-separated ad-group negative keywords for NegativeKeywords.Items",
)
@click.option(
    "--negative-keyword-shared-set-ids",
    help=(
        "Comma-separated negative keyword shared set IDs for "
        "NegativeKeywordSharedSetIds.Items"
    ),
)
@click.option(
    "--tracking-params",
    "tracking_params",
    help=(
        "Tracking params query-string for AdGroupUpdateItem.TrackingParams "
        "(max 1024 chars)"
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    adgroup_id,
    name,
    status,
    region_ids,
    negative_keywords,
    negative_keyword_shared_set_ids,
    tracking_params,
    dry_run,
):
    """Update ad group"""
    _validate_tracking_params(tracking_params)

    adgroup_data = {"Id": adgroup_id}

    if name:
        adgroup_data["Name"] = name

    if status:
        adgroup_data["Status"] = status
    if region_ids:
        adgroup_data["RegionIds"] = _parse_ids_option(region_ids, "--region-ids")
    parsed_negative_keywords = parse_csv_strings(negative_keywords)
    if parsed_negative_keywords:
        adgroup_data["NegativeKeywords"] = {"Items": parsed_negative_keywords}
    parsed_negative_keyword_shared_set_ids = _parse_ids_option(
        negative_keyword_shared_set_ids, "--negative-keyword-shared-set-ids"
    )
    if parsed_negative_keyword_shared_set_ids:
        adgroup_data["NegativeKeywordSharedSetIds"] = {
            "Items": parsed_negative_keyword_shared_set_ids
        }
    if tracking_params:
        adgroup_data["TrackingParams"] = tracking_params

    # Reject empty-payload no-op (issue #198 H5).
    if len(adgroup_data) == 1:
        raise click.UsageError(
            "adgroups update requires at least one updatable field "
            "(--name, --status, --region-ids, --negative-keywords, "
            "--negative-keyword-shared-set-ids, or --tracking-params)."
        )

    try:
        body = {"method": "update", "params": {"AdGroups": [adgroup_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@adgroups.command()
@click.option("--id", "adgroup_id", required=True, type=int, help="Ad group ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, adgroup_id, dry_run):
    """Delete ad group"""
    try:
        body = {
            "method": "delete",
            "params": {"SelectionCriteria": {"Ids": [adgroup_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.adgroups().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

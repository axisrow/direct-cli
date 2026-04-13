"""
Reports commands
"""

import json

import click

from ..api import create_client
from ..output import format_output, print_error


def _load_report_types() -> list:
    """Load report type choices from the committed spec snapshot."""
    try:
        from ..reports_coverage import load_cached_reports_spec

        return load_cached_reports_spec()["report_types"]
    except Exception:
        return [
            "ACCOUNT_PERFORMANCE_REPORT",
            "CAMPAIGN_PERFORMANCE_REPORT",
            "ADGROUP_PERFORMANCE_REPORT",
            "AD_PERFORMANCE_REPORT",
            "CRITERIA_PERFORMANCE_REPORT",
            "CUSTOM_REPORT",
            "REACH_AND_FREQUENCY_PERFORMANCE_REPORT",
            "SEARCH_QUERY_PERFORMANCE_REPORT",
        ]


def _load_processing_modes() -> list:
    """Load processing mode choices from the committed spec snapshot."""
    try:
        from ..reports_coverage import load_cached_reports_spec

        return load_cached_reports_spec()["processing_modes"]
    except Exception:
        return ["auto", "online", "offline"]


def _load_date_range_types() -> list:
    """Load date range type choices from the committed spec snapshot."""
    try:
        from ..reports_coverage import load_cached_reports_spec

        return load_cached_reports_spec()["date_range_types"]
    except Exception:
        return [
            "TODAY",
            "YESTERDAY",
            "CUSTOM_DATE",
            "ALL_TIME",
            "LAST_30_DAYS",
            "LAST_14_DAYS",
            "LAST_7_DAYS",
            "THIS_WEEK_MON_TODAY",
            "THIS_WEEK_MON_SUN",
            "LAST_WEEK",
            "LAST_BUSINESS_WEEK",
            "LAST_3_MONTHS",
            "LAST_5_YEARS",
            "AUTO",
        ]


def _parse_filter(filter_str):
    """Parse 'Field:Operator:Value1,Value2' into a Reports API Filter entry."""
    parts = filter_str.split(":", 2)
    if len(parts) != 3:
        raise ValueError(
            f"--filter must be Field:Operator:Value1,Value2, got: {filter_str!r}"
        )
    field, operator, values_raw = parts
    return {
        "Field": field.strip(),
        "Operator": operator.strip().upper(),
        "Values": [v.strip() for v in values_raw.split(",") if v.strip()],
    }


def _parse_order_by(order_str):
    """Parse 'Field[:ASC|DESC]' into a Reports API OrderBy entry."""
    parts = order_str.split(":", 1)
    entry = {"Field": parts[0].strip()}
    if len(parts) == 2:
        entry["SortOrder"] = parts[1].strip().upper()
    return entry


def build_report_request(
    report_type,
    date_from,
    date_to,
    name,
    fields,
    campaign_ids=None,
    adgroup_ids=None,
    date_range_type="CUSTOM_DATE",
    include_vat=True,
    include_discount=True,
    page_limit=None,
    page_offset=None,
    filters=(),
    order_by=(),
):
    """
    Build the Reports API request body from CLI arguments.

    Args:
        report_type: Yandex Direct report type enum value.
        date_from: Start date in ``YYYY-MM-DD`` format.
        date_to: End date in ``YYYY-MM-DD`` format.
        name: User-facing report name.
        fields: Comma-separated field names.
        campaign_ids: Optional comma-separated campaign IDs filter.
        adgroup_ids: Optional comma-separated ad group IDs filter.
        date_range_type: DateRangeType enum value (default CUSTOM_DATE).
        include_vat: Whether to include VAT (default True = "YES").
        include_discount: Whether to include discounts (default True = "YES").
        page_limit: Optional page limit for pagination.
        page_offset: Optional page offset for pagination.
        filters: Sequence of 'Field:Operator:Values' strings.
        order_by: Sequence of 'Field[:ASC|DESC]' strings.

    Returns:
        Reports API request body with CLI-normalized filters and field names.
    """
    field_names = [field.strip() for field in fields.split(",") if field.strip()]
    selection_criteria = {"DateFrom": date_from, "DateTo": date_to}

    # --filter takes precedence; --campaign-ids / --adgroup-ids are shorthand.
    # When both --campaign-ids and --adgroup-ids are provided, --campaign-ids wins.
    if filters:
        selection_criteria["Filter"] = [_parse_filter(f) for f in filters]
    elif campaign_ids and adgroup_ids:
        raise ValueError(
            "--campaign-ids and --adgroup-ids are mutually exclusive; "
            "use --filter for complex selection criteria"
        )
    elif campaign_ids:
        selection_criteria["Filter"] = [
            {
                "Field": "CampaignId",
                "Operator": "IN",
                "Values": [
                    item.strip() for item in campaign_ids.split(",") if item.strip()
                ],
            }
        ]
    elif adgroup_ids:
        selection_criteria["Filter"] = [
            {
                "Field": "AdGroupId",
                "Operator": "IN",
                "Values": [
                    item.strip() for item in adgroup_ids.split(",") if item.strip()
                ],
            }
        ]

    params = {
        "SelectionCriteria": selection_criteria,
        "FieldNames": field_names,
        "ReportName": name,
        "ReportType": report_type,
        "DateRangeType": date_range_type,
        "Format": "TSV",
        "IncludeVAT": "YES" if include_vat else "NO",
        "IncludeDiscount": "YES" if include_discount else "NO",
    }

    if order_by:
        params["OrderBy"] = [_parse_order_by(o) for o in order_by]

    if page_limit is not None or page_offset is not None:
        params["Page"] = {}
        if page_limit is not None:
            params["Page"]["Limit"] = page_limit
        if page_offset is not None:
            params["Page"]["Offset"] = page_offset

    return {"params": params}


@click.group()
def reports():
    """Generate and manage reports"""


@reports.command()
@click.option(
    "--type",
    "report_type",
    required=True,
    type=click.Choice(_load_report_types(), case_sensitive=False),
    help="Report type. Loaded from spec snapshot.",
)
@click.option("--from", "date_from", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--to", "date_to", required=True, help="End date (YYYY-MM-DD)")
@click.option("--name", required=True, help="Report name")
@click.option("--fields", required=True, help="Comma-separated field names")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option(
    "--format",
    "output_format",
    default="json",
    help="Output format (json/table/csv/tsv)",
)
@click.option("--output", help="Output file")
@click.option(
    "--date-range-type",
    default="CUSTOM_DATE",
    type=click.Choice(_load_date_range_types(), case_sensitive=False),
    help="DateRangeType enum (default: CUSTOM_DATE)",
)
@click.option(
    "--processing-mode",
    default=None,
    type=click.Choice(_load_processing_modes(), case_sensitive=False),
    help="Processing mode: auto, online, offline",
)
@click.option(
    "--skip-report-header",
    is_flag=True,
    default=False,
    help="Omit report header row",
)
@click.option(
    "--skip-column-header",
    is_flag=True,
    default=False,
    help="Omit column header row",
)
@click.option(
    "--skip-report-summary",
    is_flag=True,
    default=False,
    help="Omit report summary row",
)
@click.option(
    "--return-money-in-micros",
    is_flag=True,
    default=False,
    help="Return monetary values in micros",
)
@click.option(
    "--language",
    default=None,
    type=click.Choice(["ru", "en"], case_sensitive=False),
    help="Accept-Language for the report",
)
@click.option(
    "--include-vat/--no-include-vat",
    default=True,
    help="Include VAT in report (default: yes)",
)
@click.option(
    "--include-discount/--no-include-discount",
    default=True,
    help="Include discounts in report (default: yes)",
)
@click.option("--page-limit", type=int, default=None, help="Page limit for pagination")
@click.option(
    "--page-offset", type=int, default=None, help="Page offset for pagination"
)
@click.option(
    "--filter",
    "filters",
    multiple=True,
    metavar="FIELD:OPERATOR:VALUES",
    help=(
        "Filter in Field:Operator:Value1,Value2 format (repeatable). "
        "Takes precedence over --campaign-ids / --adgroup-ids."
    ),
)
@click.option(
    "--order-by",
    "order_by",
    multiple=True,
    metavar="FIELD[:ASC|DESC]",
    help="Order by field (repeatable), e.g. --order-by Clicks:DESC",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print request headers and body without calling the API",
)
@click.pass_context
def get(
    ctx,
    report_type,
    date_from,
    date_to,
    name,
    fields,
    campaign_ids,
    adgroup_ids,
    output_format,
    output,
    date_range_type,
    processing_mode,
    skip_report_header,
    skip_column_header,
    skip_report_summary,
    return_money_in_micros,
    language,
    include_vat,
    include_discount,
    page_limit,
    page_offset,
    filters,
    order_by,
    dry_run,
):
    """Get report"""
    try:
        body = build_report_request(
            report_type=report_type.upper(),
            date_from=date_from,
            date_to=date_to,
            name=name,
            fields=fields,
            campaign_ids=campaign_ids,
            adgroup_ids=adgroup_ids,
            date_range_type=date_range_type.upper(),
            include_vat=include_vat,
            include_discount=include_discount,
            page_limit=page_limit,
            page_offset=page_offset,
            filters=filters,
            order_by=order_by,
        )

        request_headers = {}
        if processing_mode:
            request_headers["processingMode"] = processing_mode
        if skip_report_header:
            request_headers["skipReportHeader"] = "true"
        if skip_column_header:
            request_headers["skipColumnHeader"] = "true"
        if skip_report_summary:
            request_headers["skipReportSummary"] = "true"
        if return_money_in_micros:
            request_headers["returnMoneyInMicros"] = "true"
        if language:
            request_headers["Accept-Language"] = language

        if dry_run:
            output_data = {"headers": request_headers, "body": body}
            click.echo(json.dumps(output_data, indent=2, ensure_ascii=False))
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
            processing_mode=processing_mode or "auto",
            return_money_in_micros=return_money_in_micros,
            skip_report_header=skip_report_header,
            skip_column_header=skip_column_header,
            skip_report_summary=skip_report_summary,
        )

        result = client.reports().post(data=body)

        if output_format == "json":
            format_output(result().to_dicts(), "json", output)
        elif output_format == "table":
            format_output(result().to_dicts(), "table", output)
        elif output_format == "csv":
            format_output(result().to_values(), "csv", output, headers=result.columns)
        elif output_format == "tsv":
            format_output(result().to_values(), "tsv", output, headers=result.columns)
        else:
            format_output(result.data, "json", output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@reports.command()
def list_types():
    """List available report types"""
    format_output(_load_report_types(), "json", None)

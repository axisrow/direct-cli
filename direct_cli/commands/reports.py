"""
Reports commands
"""

import click

from ..api import create_client
from ..output import format_output, print_error

REPORT_TYPES = [
    "CAMPAIGN_PERFORMANCE_REPORT",
    "ADGROUP_PERFORMANCE_REPORT",
    "AD_PERFORMANCE_REPORT",
    "CRITERIA_PERFORMANCE_REPORT",
    "CUSTOM_REPORT",
    "REACH_AND_FREQUENCY_CAMPAIGN_REPORT",
    "SEARCH_QUERY_PERFORMANCE_REPORT",
]


@click.group()
def reports():
    """Generate and manage reports"""


@reports.command()
@click.option(
    "--type",
    "report_type",
    required=True,
    type=click.Choice(REPORT_TYPES, case_sensitive=False),
    help=(
        "Report type (case-insensitive). Validated against the official "
        "Yandex Direct report-type enum — see axisrow/direct-cli#25."
    ),
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
):
    """Get report

    The underlying ``create_client`` uses processing mode ``auto``
    — previously the CLI also exposed a ``--mode`` option that was
    declared but never read in the function body, silently dropping
    any value the user passed.  That dead option was removed in
    axisrow/direct-cli#25.
    """
    try:
        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        field_names = [f.strip() for f in fields.split(",")]

        selection_criteria = {"DateFrom": date_from, "DateTo": date_to}

        if campaign_ids:
            selection_criteria["Filter"] = [
                {
                    "Field": "CampaignId",
                    "Operator": "IN",
                    "Values": campaign_ids.split(","),
                }
            ]
        elif adgroup_ids:
            selection_criteria["Filter"] = [
                {
                    "Field": "AdGroupId",
                    "Operator": "IN",
                    "Values": adgroup_ids.split(","),
                }
            ]

        body = {
            "params": {
                "SelectionCriteria": selection_criteria,
                "FieldNames": field_names,
                "ReportName": name,
                "ReportType": report_type,
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV" if output_format in ["tsv", "csv"] else "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "YES",
            }
        }

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
    format_output(REPORT_TYPES, "json", None)

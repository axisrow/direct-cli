"""
Creatives commands
"""

import click

from ..api import client_from_ctx, create_client
from ..output import format_output, handle_api_errors
from ..utils import (
    get_default_fields,
    parse_csv_strings,
    parse_csv_upper,
    parse_ids,
    parse_nested_field_names,
)


@click.group()
def creatives():
    """Manage creatives"""


@creatives.command()
@click.option("--ids", help="Comma-separated creative IDs")
@click.option("--types", help="Comma-separated creative types")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated field names")
@click.option(
    "--cpc-video-creative-field-names",
    help=(
        "Comma-separated CpcVideoCreativeFieldNames (e.g. Duration). "
        "Sent as separate top-level request parameter per the "
        "CreativesGetRequest WSDL."
    ),
)
@click.option(
    "--cpm-video-creative-field-names",
    help=(
        "Comma-separated CpmVideoCreativeFieldNames (e.g. Duration). "
        "Sent as separate top-level request parameter per the "
        "CreativesGetRequest WSDL."
    ),
)
@click.option(
    "--smart-creative-field-names",
    help=(
        "Comma-separated SmartCreativeFieldNames "
        "(e.g. CreativeGroupId,CreativeGroupName,BusinessType). "
        "Sent as separate top-level request parameter per the "
        "CreativesGetRequest WSDL."
    ),
)
@click.option(
    "--video-extension-creative-field-names",
    help=(
        "Comma-separated VideoExtensionCreativeFieldNames (e.g. Duration). "
        "Sent as separate top-level request parameter per the "
        "CreativesGetRequest WSDL."
    ),
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    types,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    cpc_video_creative_field_names,
    cpm_video_creative_field_names,
    smart_creative_field_names,
    video_extension_creative_field_names,
    dry_run,
):
    """Get creatives"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("creatives")

    nested_field_name_options = (
        ("CpcVideoCreativeFieldNames", cpc_video_creative_field_names),
        ("CpmVideoCreativeFieldNames", cpm_video_creative_field_names),
        ("SmartCreativeFieldNames", smart_creative_field_names),
        (
            "VideoExtensionCreativeFieldNames",
            video_extension_creative_field_names,
        ),
    )
    parsed_nested_field_names = parse_nested_field_names(nested_field_name_options)

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    if types:
        criteria["Types"] = parse_csv_upper(types) or []

    params = {"SelectionCriteria": criteria, "FieldNames": field_names}
    params.update(parsed_nested_field_names)

    if limit:
        params["Page"] = {"Limit": limit}

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.creatives().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@creatives.command()
@click.option("--video-id", required=True, help="Video extension creative video ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, video_id, dry_run):
    """Add creative"""
    body = {
        "method": "add",
        "params": {"Creatives": [{"VideoExtensionCreative": {"VideoId": video_id}}]},
    }

    if dry_run:
        format_output(body, "json", None)
        return

    client = client_from_ctx(ctx, create_client)
    result = client.creatives().post(data=body)
    format_output(result().extract(), "json", None)

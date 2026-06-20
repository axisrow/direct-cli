"""
AdImages commands
"""

import click

from ..api import client_from_ctx, create_client
from ..i18n import t
from ..output import format_output, handle_api_errors
from ._execute import execute_request
from ._lifecycle import make_lifecycle_command
from ..utils import (
    add_criteria_csv,
    build_common_params,
    get_default_fields,
    get_options,
    load_base64_file,
    parse_csv_strings,
    parse_ids,
)


@click.group()
def adimages():
    """Manage ad images"""


@adimages.command()
@click.option("--ids", help="Comma-separated image IDs")
@click.option("--image-hashes", help="Comma-separated ad image hashes")
@click.option("--associated", type=click.Choice(["YES", "NO"], case_sensitive=False))
@get_options
@click.pass_context
@handle_api_errors
def get(
    ctx,
    ids,
    image_hashes,
    associated,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    dry_run,
):
    """Get ad images"""
    client = client_from_ctx(ctx, create_client)

    field_names = parse_csv_strings(fields) or get_default_fields("adimages")

    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    add_criteria_csv(criteria, "AdImageHashes", image_hashes)
    if associated:
        criteria["Associated"] = associated.upper()

    params = build_common_params(
        criteria=criteria, field_names=field_names, limit=limit
    )

    body = {"method": "get", "params": params}

    if dry_run:
        format_output(body, "json", None)
        return

    result = client.adimages().post(data=body)

    if fetch_all:
        items = []
        for item in result().iter_items():
            items.append(item)
        format_output(items, output_format, output)
    else:
        data = result().extract()
        format_output(data, output_format, output)


@adimages.command()
@click.option("--name", required=True, help="Image name")
@click.option("--image-data", help="Base64-encoded image data")
@click.option("--image-file", help="Path to an image file to base64-encode")
@click.option("--type", "image_type", help="Ad image type")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
@handle_api_errors
def add(ctx, name, image_data, image_file, image_type, dry_run):
    """Add ad image"""
    if bool(image_data) == bool(image_file):
        raise click.UsageError(t("Provide exactly one of --image-data or --image-file"))

    payload = {
        "Name": name,
        "ImageData": image_data if image_data else load_base64_file(image_file),
    }
    if image_type:
        payload["Type"] = image_type

    body = {"method": "add", "params": {"AdImages": [payload]}}

    execute_request(ctx, "adimages", body, dry_run, create_client)


delete = make_lifecycle_command(
    adimages,
    "delete",
    "Delete ad image",
    "image_hash",
    "Ad image hash",
    create_client,
    id_option="--hash",
    id_type=str,
    criteria_key="AdImageHashes",
)

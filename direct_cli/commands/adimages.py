"""
AdImages commands
"""

import click

from ..api import create_client
from ..i18n import t
from ..output import handle_api_errors
from ._execute import execute_request
from ._get import make_get_command
from ._lifecycle import make_lifecycle_command
from ..utils import (
    add_criteria_csv,
    load_base64_file,
    parse_ids,
)


@click.group()
def adimages():
    """Manage ad images"""


def _adimages_criteria(ids, image_hashes=None, associated=None, **_):
    """SelectionCriteria for ``adimages get``: ``Ids`` + ``AdImageHashes`` +
    ``Associated``."""
    criteria = {}
    if ids:
        criteria["Ids"] = parse_ids(ids)
    add_criteria_csv(criteria, "AdImageHashes", image_hashes)
    if associated:
        criteria["Associated"] = associated.upper()
    return criteria


get = make_get_command(
    adimages,
    create_client,
    default_fields_key="adimages",
    help_text="Get ad images",
    ids_help="Comma-separated image IDs",
    extra_options=(
        click.option("--image-hashes", help="Comma-separated ad image hashes"),
        click.option(
            "--associated", type=click.Choice(["YES", "NO"], case_sensitive=False)
        ),
    ),
    criteria_builder=_adimages_criteria,
)


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

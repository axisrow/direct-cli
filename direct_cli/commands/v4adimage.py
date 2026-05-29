"""Yandex Direct v4 Live ad-image association commands.

Wraps the single v4 ``AdImageAssociation`` method as two typed CLI commands:
``get`` (Action=Get, reads associations via SelectionCriteria) and
``set`` (Action=Set, writes AdImageAssociations[]). No raw ``--json`` is
accepted — all input is typed per the documented contract.
"""

from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_csv_strings, parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG

# Documented moderation statuses for the Get selection criteria.
AD_IMAGE_MODERATE_STATUSES = ("Yes", "No", "Ready", "Sending")


def _get_param(
    logins: Optional[str],
    ad_image_hashes: Optional[str],
    status_moderate: tuple[str, ...],
    ad_ids: Optional[str],
    campaign_ids: Optional[str],
    limit: Optional[int],
    offset: Optional[int],
) -> dict:
    """Build the Action=Get AdImageAssociation parameter.

    All SelectionCriteria fields are optional; an empty criteria returns up
    to 10000 associations per the docs.
    """
    criteria: dict = {}
    # parse_csv_strings/parse_ids return None/[] for degenerate input like
    # "," — only set the key when there are real values, never a null/empty.
    parsed_logins = parse_csv_strings(logins) if logins else None
    if parsed_logins:
        criteria["Logins"] = parsed_logins
    parsed_hashes = parse_csv_strings(ad_image_hashes) if ad_image_hashes else None
    if parsed_hashes:
        criteria["AdImageHashes"] = parsed_hashes
    if status_moderate:
        criteria["StatusAdImageModerate"] = list(status_moderate)
    if ad_ids:
        try:
            parsed_ad_ids = parse_ids(ad_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_ad_ids:
            criteria["AdIDS"] = parsed_ad_ids
    if campaign_ids:
        try:
            parsed_campaign_ids = parse_ids(campaign_ids)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        if parsed_campaign_ids:
            criteria["CampaignIDS"] = parsed_campaign_ids
    if limit is not None:
        criteria["Limit"] = limit
    if offset is not None:
        criteria["Offset"] = offset
    return {"Action": "Get", "SelectionCriteria": criteria}


def _set_param(associations: tuple[str, ...]) -> dict:
    """Build the Action=Set AdImageAssociation parameter.

    Each --association is ``AD_ID`` (detach the image) or ``AD_ID=HASH``
    (attach the image). Per the docs, AdID is required and omitting
    AdImageHash detaches the current image.
    """
    if not associations:
        raise click.UsageError("--association is required for set")
    items = []
    seen_ad_ids = set()
    for spec in associations:
        spec = (spec or "").strip()
        if not spec:
            raise click.UsageError("--association must not be empty")
        if "=" in spec:
            ad_id_text, ad_image_hash = spec.split("=", 1)
            ad_image_hash = ad_image_hash.strip()
        else:
            ad_id_text, ad_image_hash = spec, ""
        ad_id_text = ad_id_text.strip()
        try:
            ad_id = int(ad_id_text)
        except ValueError as exc:
            raise click.UsageError(
                "--association must be AD_ID or AD_ID=HASH with an integer AD_ID"
            ) from exc
        if ad_id <= 0:
            raise click.UsageError("--association AD_ID must be a positive integer")
        if ad_id in seen_ad_ids:
            raise click.UsageError("--association AD_ID values must be unique")
        seen_ad_ids.add(ad_id)
        item: dict = {"AdID": ad_id}
        if ad_image_hash:
            item["AdImageHash"] = ad_image_hash
        items.append(item)
    if len(items) > 10000:
        raise click.UsageError("--association accepts at most 10000 entries")
    return {"Action": "Set", "AdImageAssociations": items}


def _run(ctx, param: dict, output_format: str, output: Optional[str], dry_run: bool):
    if dry_run:
        format_output(build_v4_body("AdImageAssociation", param), "json", None)
        return
    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, "AdImageAssociation", param)
        format_output(data, output_format, output)
    except click.ClickException:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@click.group(epilog=V4_EPILOG)
def v4adimage():
    """Yandex Direct v4 Live ad-image association commands."""


@v4_method_contract("AdImageAssociation")
@v4adimage.command(name="get")
@click.option("--logins", help="Comma-separated client logins")
@click.option("--ad-image-hashes", help="Comma-separated ad image hashes")
@click.option(
    "--status-moderate",
    multiple=True,
    type=click.Choice(AD_IMAGE_MODERATE_STATUSES, case_sensitive=False),
    help="Moderation status filter; repeat for multiple",
)
@click.option("--ad-ids", help="Comma-separated ad IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--limit", type=click.IntRange(min=1, max=10000), help="Page size")
@click.option("--offset", type=click.IntRange(min=0), help="Page offset")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    logins,
    ad_image_hashes,
    status_moderate,
    ad_ids,
    campaign_ids,
    limit,
    offset,
    output_format,
    output,
    dry_run,
):
    """Read ad-to-image associations (empty filter returns up to 10000)."""
    param = _get_param(
        logins,
        ad_image_hashes,
        status_moderate,
        ad_ids,
        campaign_ids,
        limit,
        offset,
    )
    _run(ctx, param, output_format, output, dry_run)


@v4_method_contract("AdImageAssociation")
@v4adimage.command(name="set")
@click.option(
    "--association",
    "associations",
    multiple=True,
    required=True,
    help="AD_ID to detach the image, or AD_ID=HASH to attach; repeat for multiple",
)
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "table", "csv", "tsv"]),
    help="Output format",
)
@click.option("--output", help="Output file")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def set_(ctx, associations, output_format, output, dry_run):
    """Attach or detach ad images (max 10000 associations)."""
    param = _set_param(associations)
    _run(ctx, param, output_format, output, dry_run)

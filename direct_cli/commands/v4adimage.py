"""Yandex Direct v4 Live ad-image association commands.

Wraps the single v4 ``AdImageAssociation`` method as two typed CLI commands:
``get`` (Action=Get, reads associations via SelectionCriteria) and
``set`` (Action=Set, writes AdImageAssociations[]). No raw ``--json`` is
accepted — all input is typed per the documented contract.
"""

from typing import Optional

import click

from ..i18n import t
from ..utils import parse_csv_strings, parse_ids, v4_output_options
from ..v4.emit import emit_or_call_v4
from ..v4.parse import parse_id_value_specs
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
    pairs = parse_id_value_specs(
        associations,
        required_msg=t("--association is required for set"),
        empty_spec_msg=t("--association must not be empty"),
        allow_bare_id=True,
        not_integer_msg=t(
            "--association must be AD_ID or AD_ID=HASH with an integer AD_ID"
        ),
        non_positive_msg=t("--association AD_ID must be a positive integer"),
        duplicate_msg=t("--association AD_ID values must be unique"),
        max_entries=10000,
        max_entries_msg=t("--association accepts at most 10000 entries"),
        max_check="after",
    )
    items: list = []
    for ad_id, ad_image_hash in pairs:
        item: dict = {"AdID": ad_id}
        if ad_image_hash:
            item["AdImageHash"] = ad_image_hash
        items.append(item)
    return {"Action": "Set", "AdImageAssociations": items}


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
@v4_output_options
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
    emit_or_call_v4(ctx, "AdImageAssociation", param, dry_run, output_format, output)


@v4_method_contract("AdImageAssociation")
@v4adimage.command(name="set")
@click.option(
    "--association",
    "associations",
    multiple=True,
    required=True,
    help="AD_ID to detach the image, or AD_ID=HASH to attach; repeat for multiple",
)
@v4_output_options
@click.pass_context
def set_(ctx, associations, output_format, output, dry_run):
    """Attach or detach ad images (max 10000 associations)."""
    param = _set_param(associations)
    emit_or_call_v4(ctx, "AdImageAssociation", param, dry_run, output_format, output)

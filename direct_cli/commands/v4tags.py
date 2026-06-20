"""Yandex Direct v4 Live tag commands."""

from typing import Optional

import click

from ..i18n import t
from ..utils import v4_output_options
from ..v4.emit import emit_or_call_v4
from ..v4.parse import parse_positive_ids
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _tag_ids_param(tag_ids: str) -> list[int]:
    """Parse v4 banner tag IDs."""
    parsed = parse_positive_ids(tag_ids, "--tag-ids")
    if len(parsed) > 30:
        raise click.UsageError(t("--tag-ids accepts at most 30 tag IDs"))
    return parsed


def _get_campaigns_tags_param(campaign_ids: str) -> dict:
    """Build the v4 Live GetCampaignsTags parameter."""
    return {"CampaignIDS": parse_positive_ids(campaign_ids, "--campaign-ids")}


def _get_banners_tags_param(
    campaign_ids: Optional[str], banner_ids: Optional[str]
) -> dict:
    """Build the v4 Live GetBannersTags parameter."""
    if (campaign_ids is not None) == (banner_ids is not None):
        raise click.UsageError(t("Use exactly one of --campaign-ids or --banner-ids"))
    if campaign_ids is not None:
        ids = parse_positive_ids(campaign_ids, "--campaign-ids")
        if len(ids) > 10:
            raise click.UsageError(t("--campaign-ids accepts at most 10 campaign IDs"))
        return {"CampaignIDS": ids}

    ids = parse_positive_ids(banner_ids or "", "--banner-ids")
    if len(ids) > 2000:
        raise click.UsageError(t("--banner-ids accepts at most 2000 banner IDs"))
    return {"BannerIDS": ids}


def _campaign_tag_param(tag_specs: tuple[str, ...], clear_tags: bool) -> list[dict]:
    """Build campaign TagInfo objects from repeated TAG_ID=TEXT specs."""
    if clear_tags:
        if tag_specs:
            raise click.UsageError(t("Use either --tag or --clear-tags, not both"))
        return []
    if not tag_specs:
        raise click.UsageError(t("--tag is required unless --clear-tags is used"))

    tags = []
    seen_texts = set()
    seen_existing_ids = set()
    for spec in tag_specs:
        text = (spec or "").strip()
        tag_id_text, separator, tag_text = text.partition("=")
        if not separator:
            raise click.UsageError(t("--tag must use TAG_ID=TEXT"))
        tag_id_text = tag_id_text.strip()
        tag_text = tag_text.strip()
        try:
            tag_id = int(tag_id_text)
        except ValueError as exc:
            raise click.UsageError(
                t("--tag ID must be a non-negative integer")
            ) from exc
        if tag_id < 0:
            raise click.UsageError(t("--tag ID must be a non-negative integer"))
        if tag_id > 0:
            if tag_id in seen_existing_ids:
                raise click.UsageError(t("--tag IDs must be unique"))
            seen_existing_ids.add(tag_id)
        if not tag_text:
            raise click.UsageError(t("--tag text must not be empty"))
        if len(tag_text) > 25:
            raise click.UsageError(t("--tag text must be 25 characters or fewer"))
        normalized_text = tag_text.casefold()
        if normalized_text in seen_texts:
            raise click.UsageError(t("--tag texts must be unique ignoring case"))
        seen_texts.add(normalized_text)
        tags.append({"TagID": tag_id, "Tag": tag_text})

    if len(tags) > 200:
        raise click.UsageError(t("--tag accepts at most 200 campaign tags"))
    return tags


def _update_campaigns_tags_param(
    campaign_id: int, tag_specs: tuple[str, ...], clear_tags: bool
) -> list[dict]:
    """Build the v4 Live UpdateCampaignsTags parameter."""
    return [
        {
            "CampaignID": campaign_id,
            "Tags": _campaign_tag_param(tag_specs, clear_tags),
        }
    ]


def _update_banners_tags_param(
    banner_ids: str, tag_ids: Optional[str], clear_tags: bool
) -> list[dict]:
    """Build the v4 Live UpdateBannersTags parameter."""
    parsed_banner_ids = parse_positive_ids(banner_ids, "--banner-ids")
    if clear_tags:
        if tag_ids is not None:
            raise click.UsageError(t("Use either --tag-ids or --clear-tags, not both"))
        parsed_tag_ids: list[int] = []
    else:
        if tag_ids is None:
            raise click.UsageError(
                t("--tag-ids is required unless --clear-tags is used")
            )
        parsed_tag_ids = _tag_ids_param(tag_ids)
    return [
        {"BannerID": banner_id, "TagIDS": parsed_tag_ids}
        for banner_id in parsed_banner_ids
    ]


@click.group(epilog=V4_EPILOG)
def v4tags():
    """Yandex Direct v4 Live tag commands."""


@v4_method_contract("GetCampaignsTags")
@v4tags.command(name="get-campaigns")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
@v4_output_options
@click.pass_context
def get_campaigns(ctx, campaign_ids, output_format, output, dry_run):
    """Get campaign tags."""
    param = _get_campaigns_tags_param(campaign_ids)
    emit_or_call_v4(ctx, "GetCampaignsTags", param, dry_run, output_format, output)


@v4_method_contract("GetBannersTags")
@v4tags.command(name="get-banners")
@click.option("--campaign-ids", help="Comma-separated campaign IDs, up to 10")
@click.option("--banner-ids", help="Comma-separated banner IDs, up to 2000")
@v4_output_options
@click.pass_context
def get_banners(ctx, campaign_ids, banner_ids, output_format, output, dry_run):
    """Get banner tag IDs."""
    param = _get_banners_tags_param(campaign_ids, banner_ids)
    emit_or_call_v4(ctx, "GetBannersTags", param, dry_run, output_format, output)


@v4_method_contract("UpdateCampaignsTags")
@v4tags.command(name="update-campaigns")
@click.option(
    "--campaign-id",
    required=True,
    type=click.IntRange(min=1),
    help="Campaign ID",
)
@click.option(
    "--tag",
    "tag_specs",
    multiple=True,
    help="Campaign tag as TAG_ID=TEXT; use 0 for a new tag",
)
@click.option("--clear-tags", is_flag=True, help="Remove all campaign tags")
@v4_output_options
@click.pass_context
def update_campaigns(
    ctx, campaign_id, tag_specs, clear_tags, output_format, output, dry_run
):
    """Replace the campaign tag list."""
    param = _update_campaigns_tags_param(campaign_id, tag_specs, clear_tags)
    emit_or_call_v4(ctx, "UpdateCampaignsTags", param, dry_run, output_format, output)


@v4_method_contract("UpdateBannersTags")
@v4tags.command(name="update-banners")
@click.option("--banner-ids", required=True, help="Comma-separated banner IDs")
@click.option("--tag-ids", help="Comma-separated campaign tag IDs, up to 30")
@click.option("--clear-tags", is_flag=True, help="Remove all banner tags")
@v4_output_options
@click.pass_context
def update_banners(
    ctx, banner_ids, tag_ids, clear_tags, output_format, output, dry_run
):
    """Replace banner tag assignments."""
    param = _update_banners_tags_param(banner_ids, tag_ids, clear_tags)
    emit_or_call_v4(ctx, "UpdateBannersTags", param, dry_run, output_format, output)

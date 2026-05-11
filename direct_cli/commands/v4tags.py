"""Yandex Direct v4 Live tag commands."""

from typing import Optional

import click

from ..api import create_v4_client
from ..output import format_output, print_error
from ..utils import parse_ids
from ..v4 import build_v4_body, call_v4
from ..v4_contracts import v4_method_contract
from .v4shells import V4_EPILOG


def _positive_ids_param(value: str, option_name: str) -> list[int]:
    """Parse a required comma-separated positive integer list."""
    try:
        ids = parse_ids(value)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if not ids:
        raise click.UsageError(f"{option_name} must not be empty")
    if any(item <= 0 for item in ids):
        raise click.UsageError(f"{option_name} must contain only positive integers")
    return ids


def _tag_ids_param(tag_ids: str) -> list[int]:
    """Parse v4 banner tag IDs."""
    parsed = _positive_ids_param(tag_ids, "--tag-ids")
    if len(parsed) > 30:
        raise click.UsageError("--tag-ids accepts at most 30 tag IDs")
    return parsed


def _get_campaigns_tags_param(campaign_ids: str) -> dict:
    """Build the v4 Live GetCampaignsTags parameter."""
    return {"CampaignIDS": _positive_ids_param(campaign_ids, "--campaign-ids")}


def _get_banners_tags_param(
    campaign_ids: Optional[str], banner_ids: Optional[str]
) -> dict:
    """Build the v4 Live GetBannersTags parameter."""
    if (campaign_ids is not None) == (banner_ids is not None):
        raise click.UsageError("Use exactly one of --campaign-ids or --banner-ids")
    if campaign_ids is not None:
        ids = _positive_ids_param(campaign_ids, "--campaign-ids")
        if len(ids) > 10:
            raise click.UsageError("--campaign-ids accepts at most 10 campaign IDs")
        return {"CampaignIDS": ids}

    ids = _positive_ids_param(banner_ids or "", "--banner-ids")
    if len(ids) > 2000:
        raise click.UsageError("--banner-ids accepts at most 2000 banner IDs")
    return {"BannerIDS": ids}


def _campaign_tag_param(tag_specs: tuple[str, ...], clear_tags: bool) -> list[dict]:
    """Build campaign TagInfo objects from repeated TAG_ID=TEXT specs."""
    if clear_tags:
        if tag_specs:
            raise click.UsageError("Use either --tag or --clear-tags, not both")
        return []
    if not tag_specs:
        raise click.UsageError("--tag is required unless --clear-tags is used")

    tags = []
    seen_texts = set()
    seen_existing_ids = set()
    for spec in tag_specs:
        text = (spec or "").strip()
        tag_id_text, separator, tag_text = text.partition("=")
        if not separator:
            raise click.UsageError("--tag must use TAG_ID=TEXT")
        tag_id_text = tag_id_text.strip()
        tag_text = tag_text.strip()
        try:
            tag_id = int(tag_id_text)
        except ValueError as exc:
            raise click.UsageError("--tag ID must be a non-negative integer") from exc
        if tag_id < 0:
            raise click.UsageError("--tag ID must be a non-negative integer")
        if tag_id > 0:
            if tag_id in seen_existing_ids:
                raise click.UsageError("--tag IDs must be unique")
            seen_existing_ids.add(tag_id)
        if not tag_text:
            raise click.UsageError("--tag text must not be empty")
        if len(tag_text) > 25:
            raise click.UsageError("--tag text must be 25 characters or fewer")
        normalized_text = tag_text.casefold()
        if normalized_text in seen_texts:
            raise click.UsageError("--tag texts must be unique ignoring case")
        seen_texts.add(normalized_text)
        tags.append({"TagID": tag_id, "Tag": tag_text})

    if len(tags) > 200:
        raise click.UsageError("--tag accepts at most 200 campaign tags")
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
    parsed_banner_ids = _positive_ids_param(banner_ids, "--banner-ids")
    if clear_tags:
        if tag_ids is not None:
            raise click.UsageError("Use either --tag-ids or --clear-tags, not both")
        parsed_tag_ids: list[int] = []
    else:
        if tag_ids is None:
            raise click.UsageError("--tag-ids is required unless --clear-tags is used")
        parsed_tag_ids = _tag_ids_param(tag_ids)
    return [
        {"BannerID": banner_id, "TagIDS": parsed_tag_ids}
        for banner_id in parsed_banner_ids
    ]


def _call_v4tags(ctx, method: str, param, output_format: str, output: str) -> None:
    """Call one v4 Live tag method and print formatted output."""
    try:
        client = create_v4_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            profile=ctx.obj.get("profile"),
            sandbox=ctx.obj.get("sandbox"),
        )
        data = call_v4(client, method, param)
        format_output(data, output_format, output)
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@click.group(epilog=V4_EPILOG)
def v4tags():
    """Yandex Direct v4 Live tag commands."""


@v4_method_contract("GetCampaignsTags")
@v4tags.command(name="get-campaigns")
@click.option("--campaign-ids", required=True, help="Comma-separated campaign IDs")
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
def get_campaigns(ctx, campaign_ids, output_format, output, dry_run):
    """Get campaign tags."""
    param = _get_campaigns_tags_param(campaign_ids)
    if dry_run:
        format_output(build_v4_body("GetCampaignsTags", param), "json", None)
        return

    _call_v4tags(ctx, "GetCampaignsTags", param, output_format, output)


@v4_method_contract("GetBannersTags")
@v4tags.command(name="get-banners")
@click.option("--campaign-ids", help="Comma-separated campaign IDs, up to 10")
@click.option("--banner-ids", help="Comma-separated banner IDs, up to 2000")
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
def get_banners(ctx, campaign_ids, banner_ids, output_format, output, dry_run):
    """Get banner tag IDs."""
    param = _get_banners_tags_param(campaign_ids, banner_ids)
    if dry_run:
        format_output(build_v4_body("GetBannersTags", param), "json", None)
        return

    _call_v4tags(ctx, "GetBannersTags", param, output_format, output)


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
def update_campaigns(
    ctx, campaign_id, tag_specs, clear_tags, output_format, output, dry_run
):
    """Replace the campaign tag list."""
    param = _update_campaigns_tags_param(campaign_id, tag_specs, clear_tags)
    if dry_run:
        format_output(build_v4_body("UpdateCampaignsTags", param), "json", None)
        return

    _call_v4tags(ctx, "UpdateCampaignsTags", param, output_format, output)


@v4_method_contract("UpdateBannersTags")
@v4tags.command(name="update-banners")
@click.option("--banner-ids", required=True, help="Comma-separated banner IDs")
@click.option("--tag-ids", help="Comma-separated campaign tag IDs, up to 30")
@click.option("--clear-tags", is_flag=True, help="Remove all banner tags")
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
def update_banners(
    ctx, banner_ids, tag_ids, clear_tags, output_format, output, dry_run
):
    """Replace banner tag assignments."""
    param = _update_banners_tags_param(banner_ids, tag_ids, clear_tags)
    if dry_run:
        format_output(build_v4_body("UpdateBannersTags", param), "json", None)
        return

    _call_v4tags(ctx, "UpdateBannersTags", param, output_format, output)

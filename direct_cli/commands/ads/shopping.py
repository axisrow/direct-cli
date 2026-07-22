"""SHOPPING_AD / LISTING_AD (feed-based) payload assembly (#603).

Both subtypes share the WSDL feed-based shape (``FeedId`` + ``DefaultTexts`` +
optional filter/source lists), so one pair of builders covers them and the
caller only picks the container name (``ShoppingAd`` / ``ListingAd``).
"""

from __future__ import annotations

from typing import Any, Optional

import click

from ...i18n import t
from ...utils import parse_condition_specs
from .base import _parse_required_csv_strings, _parse_required_ids

FEED_BASED_ADD_FIELDS = {
    "sitelink_set_id",
    "ad_extensions",
    "business_id",
    "feed_id",
    "feed_filter_conditions",
    "title_sources",
    "text_sources",
    "default_texts",
}

FEED_BASED_UPDATE_FIELDS = {
    "sitelink_set_id",
    "callouts_add",
    "callouts_remove",
    "callouts_set",
    "business_id",
    "feed_filter_conditions",
    "title_sources",
    "text_sources",
    "default_texts",
}


def _build_feed_based_ad_update(
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, Any]],
    business_id: Optional[int],
    feed_filter_conditions: tuple[str, ...],
    title_sources: Optional[str],
    text_sources: Optional[str],
    default_texts: Optional[str],
) -> dict[str, object]:
    """Build ShoppingAdUpdate / ListingAdUpdate payload from typed flags."""
    ad_payload: dict[str, object] = {}

    if sitelink_set_id is not None:
        ad_payload["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        ad_payload["CalloutSetting"] = callout_setting
    if business_id is not None:
        ad_payload["BusinessId"] = business_id
    if feed_filter_conditions:
        try:
            parsed_conditions = parse_condition_specs(list(feed_filter_conditions))
        except ValueError as exc:
            raise click.UsageError(t("--feed-filter-condition: {exc}").format(exc=exc))
        if parsed_conditions:
            ad_payload["FeedFilterConditions"] = {"Items": parsed_conditions}

    parsed_title_sources = _parse_required_csv_strings(title_sources, "--title-sources")
    if parsed_title_sources:
        ad_payload["TitleSources"] = {"Items": parsed_title_sources}
    parsed_text_sources = _parse_required_csv_strings(text_sources, "--text-sources")
    if parsed_text_sources:
        ad_payload["TextSources"] = {"Items": parsed_text_sources}
    parsed_default_texts = _parse_required_csv_strings(default_texts, "--default-texts")
    if parsed_default_texts:
        ad_payload["DefaultTexts"] = parsed_default_texts

    return ad_payload


def _build_feed_based_ad_add(
    feed_id: Optional[int],
    default_texts: Optional[str],
    sitelink_set_id: Optional[int],
    ad_extensions: Optional[str],
    business_id: Optional[int],
    feed_filter_conditions: tuple[str, ...],
    title_sources: Optional[str],
    text_sources: Optional[str],
    container_name: str,
) -> dict[str, object]:
    """Build ShoppingAdAdd / ListingAdAdd payload from typed flags."""
    missing_fields = []
    if feed_id is None:
        missing_fields.append("--feed-id")
    if default_texts is None:
        missing_fields.append("--default-texts")
    if missing_fields:
        raise click.UsageError(
            t("{container_name} requires {arg0}").format(
                container_name=container_name, arg0=", ".join(missing_fields)
            )
        )

    default_text = default_texts.strip() if default_texts else ""
    if not default_text:
        raise click.UsageError(t("--default-texts must contain a value."))

    ad_payload: dict[str, object] = {
        "FeedId": feed_id,
        "DefaultTexts": [default_text],
    }

    if sitelink_set_id is not None:
        ad_payload["SitelinkSetId"] = sitelink_set_id
    parsed_ad_extensions = _parse_required_ids(ad_extensions, "--ad-extensions")
    if parsed_ad_extensions:
        ad_payload["AdExtensionIds"] = parsed_ad_extensions
    if business_id is not None:
        ad_payload["BusinessId"] = business_id
    if feed_filter_conditions:
        if len(feed_filter_conditions) > 30:
            raise click.UsageError(
                t(
                    "{container_name}.FeedFilterConditions accepts at most 30 filters."
                ).format(container_name=container_name)
            )
        try:
            parsed_conditions = parse_condition_specs(list(feed_filter_conditions))
        except ValueError as exc:
            raise click.UsageError(t("--feed-filter-condition: {exc}").format(exc=exc))
        if parsed_conditions:
            ad_payload["FeedFilterConditions"] = parsed_conditions

    parsed_title_sources = _parse_required_csv_strings(title_sources, "--title-sources")
    if parsed_title_sources:
        ad_payload["TitleSources"] = parsed_title_sources
    parsed_text_sources = _parse_required_csv_strings(text_sources, "--text-sources")
    if parsed_text_sources:
        ad_payload["TextSources"] = parsed_text_sources

    return ad_payload

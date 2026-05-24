"""
Ads commands
"""

from typing import Optional

import click

from ..api import create_client
from ..output import format_output, print_error
from ..utils import add_criteria_csv, get_default_fields, parse_ids


@click.group()
def ads():
    """Manage ads"""


def _reject_incompatible_flags(
    ad_type: str,
    allowed_fields: set[str],
    provided: dict[str, object],
    flag_for: dict[str, str],
) -> None:
    """Reject typed flags that do not belong to the selected ad subtype."""
    incompatible = [
        flag_for[name]
        for name, value in provided.items()
        if value is not None and name not in allowed_fields
    ]
    if incompatible:
        allowed_flags = ", ".join(sorted(flag_for[name] for name in allowed_fields))
        raise click.UsageError(
            f"{', '.join(incompatible)} is not compatible with --type {ad_type}. "
            f"Allowed flags for {ad_type}: {allowed_flags}."
        )


def _build_callout_setting(callouts_add, callouts_remove, callouts_set):
    """Build AdExtensionSetting for text-like ad update payloads.

    SET is mutually exclusive with ADD/REMOVE per WSDL OperationEnum
    semantics. Returns None when no callout flag was provided.
    """
    if callouts_set and (callouts_add or callouts_remove):
        raise click.UsageError(
            "--callouts-set is mutually exclusive with "
            "--callouts-add / --callouts-remove. "
            "Use --callouts-set to replace the full callout list, "
            "or --callouts-add / --callouts-remove for incremental edits."
        )
    items = []
    for csv_value, op in (
        (callouts_set, "SET"),
        (callouts_add, "ADD"),
        (callouts_remove, "REMOVE"),
    ):
        if csv_value is None:
            continue
        try:
            ids = parse_ids(csv_value)
        except ValueError as exc:
            raise click.UsageError(f"--callouts-{op.lower()}: {exc}")
        if not ids:
            raise click.UsageError(
                f"--callouts-{op.lower()} must contain at least one ad extension ID."
            )
        for ad_ext_id in ids:
            items.append({"AdExtensionId": ad_ext_id, "Operation": op})
    if not items:
        return None
    return {"AdExtensions": items}


def _build_text_ad_update_base(
    vcard_id: Optional[int],
    image_hash: Optional[str],
    sitelink_set_id: Optional[int],
    callout_setting: Optional[dict[str, object]],
) -> dict[str, object]:
    """Build fields inherited from WSDL TextAdUpdateBase."""
    text_ad_base: dict[str, object] = {}
    if vcard_id:
        text_ad_base["VCardId"] = vcard_id
    if image_hash:
        text_ad_base["AdImageHash"] = image_hash
    if sitelink_set_id:
        text_ad_base["SitelinkSetId"] = sitelink_set_id
    if callout_setting:
        text_ad_base["CalloutSetting"] = callout_setting
    return text_ad_base


def _build_price_extension(
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
):
    """Build TextAd.PriceExtension update payload from typed flags."""
    price_extension = {}
    if price_extension_price is not None:
        price_extension["Price"] = price_extension_price
    if price_extension_old_price is not None:
        price_extension["OldPrice"] = price_extension_old_price
    if price_extension_price_qualifier:
        price_extension["PriceQualifier"] = price_extension_price_qualifier.upper()
    if price_extension_price_currency:
        price_extension["PriceCurrency"] = price_extension_price_currency.upper()
    return price_extension or None


@ads.command()
@click.option("--ids", help="Comma-separated ad IDs")
@click.option("--campaign-ids", help="Comma-separated campaign IDs")
@click.option("--adgroup-ids", help="Comma-separated ad group IDs")
@click.option("--status", help="Filter by status")
@click.option("--statuses", help="Comma-separated statuses")
@click.option("--states", help="Comma-separated states")
@click.option("--types", help="Comma-separated ad types")
@click.option("--mobile", type=click.Choice(["YES", "NO"], case_sensitive=False))
@click.option("--vcard-ids", help="Comma-separated vCard IDs")
@click.option("--sitelink-set-ids", help="Comma-separated sitelink set IDs")
@click.option("--image-hashes", help="Comma-separated ad image hashes")
@click.option(
    "--vcard-moderation-statuses", help="Comma-separated vCard moderation statuses"
)
@click.option(
    "--sitelinks-moderation-statuses",
    help="Comma-separated sitelinks moderation statuses",
)
@click.option(
    "--image-moderation-statuses", help="Comma-separated image moderation statuses"
)
@click.option("--adextension-ids", help="Comma-separated ad extension IDs")
@click.option("--limit", type=int, help="Limit number of results")
@click.option("--fetch-all", is_flag=True, help="Fetch all pages")
@click.option("--format", "output_format", default="json", help="Output format")
@click.option("--output", help="Output file")
@click.option("--fields", help="Comma-separated top-level field names")
@click.option(
    "--text-ad-fields", help="Comma-separated TextAd field names (e.g. Title,Text,Href)"
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def get(
    ctx,
    ids,
    campaign_ids,
    adgroup_ids,
    status,
    statuses,
    states,
    types,
    mobile,
    vcard_ids,
    sitelink_set_ids,
    image_hashes,
    vcard_moderation_statuses,
    sitelinks_moderation_statuses,
    image_moderation_statuses,
    adextension_ids,
    limit,
    fetch_all,
    output_format,
    output,
    fields,
    text_ad_fields,
    dry_run,
):
    """Get ads"""
    if status and statuses:
        raise click.UsageError("--status and --statuses are mutually exclusive")

    try:
        field_names = (
            fields.split(",") if fields else get_default_fields("ads", "FieldNames")
        )

        text_ad_field_names = (
            text_ad_fields.split(",")
            if text_ad_fields
            else get_default_fields("ads", "TextAdFieldNames")
        )

        criteria = {}
        if ids:
            criteria["Ids"] = parse_ids(ids)
        if campaign_ids:
            criteria["CampaignIds"] = parse_ids(campaign_ids)
        if adgroup_ids:
            criteria["AdGroupIds"] = parse_ids(adgroup_ids)
        if status:
            criteria["Statuses"] = [status]
        add_criteria_csv(criteria, "Statuses", statuses, upper=True)
        add_criteria_csv(criteria, "States", states, upper=True)
        add_criteria_csv(criteria, "Types", types, upper=True)
        if mobile:
            criteria["Mobile"] = mobile.upper()
        add_criteria_csv(criteria, "VCardIds", vcard_ids, integers=True)
        add_criteria_csv(criteria, "SitelinkSetIds", sitelink_set_ids, integers=True)
        add_criteria_csv(criteria, "AdImageHashes", image_hashes)
        add_criteria_csv(
            criteria, "VCardModerationStatuses", vcard_moderation_statuses, upper=True
        )
        add_criteria_csv(
            criteria,
            "SitelinksModerationStatuses",
            sitelinks_moderation_statuses,
            upper=True,
        )
        add_criteria_csv(
            criteria, "AdImageModerationStatuses", image_moderation_statuses, upper=True
        )
        add_criteria_csv(criteria, "AdExtensionIds", adextension_ids, integers=True)

        params = {
            "SelectionCriteria": criteria,
            "FieldNames": field_names,
            "TextAdFieldNames": text_ad_field_names,
        }

        if limit:
            params["Page"] = {"Limit": limit}

        body = {"method": "get", "params": params}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)

        if fetch_all:
            items = []
            for item in result().iter_items():
                items.append(item)
            format_output(items, output_format, output)
        else:
            data = result().extract()
            format_output(data, output_format, output)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--adgroup-id", required=True, type=int, help="Ad group ID")
@click.option(
    "--type",
    "ad_type",
    default="TEXT_AD",
    help="Ad type",
)
@click.option("--title", help="Ad title (TEXT_AD / MOBILE_APP_AD)")
@click.option("--text", help="Ad text (TEXT_AD / MOBILE_APP_AD)")
@click.option("--href", help="Ad URL (TEXT_AD / TEXT_IMAGE_AD)")
@click.option("--image-hash", help="Ad image hash (TEXT_IMAGE_AD / MOBILE_APP_AD)")
@click.option(
    "--action",
    help="MOBILE_APP_AD call-to-action (MobileAppAdActionEnum, e.g. INSTALL)",
)
@click.option("--tracking-url", help="MOBILE_APP_AD tracking URL")
@click.option("--age-label", help="MOBILE_APP_AD age label (MobAppAgeLabelEnum)")
@click.option("--title2", help="Second headline (TEXT_AD)")
@click.option("--display-url-path", help="Display URL path (TEXT_AD)")
@click.option(
    "--mobile",
    type=click.Choice(["YES", "NO"], case_sensitive=False),
    default="NO",
    help="Mobile-targeted flag (TEXT_AD)",
)
@click.option("--vcard-id", type=int, help="VCard ID (TEXT_AD)")
@click.option("--sitelink-set-id", type=int, help="Sitelink set ID (TEXT_AD)")
@click.option(
    "--turbo-page-id", type=int, help="Turbo page ID (TEXT_AD / TEXT_IMAGE_AD)"
)
@click.option("--ad-extensions", help="Comma-separated ad extension IDs (TEXT_AD)")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def add(
    ctx,
    adgroup_id,
    ad_type,
    title,
    text,
    href,
    image_hash,
    action,
    tracking_url,
    age_label,
    title2,
    display_url_path,
    mobile,
    vcard_id,
    sitelink_set_id,
    turbo_page_id,
    ad_extensions,
    dry_run,
):
    """Add new ad"""
    try:
        ad_type_norm = (ad_type or "TEXT_AD").upper().replace("-", "_")
        supported_types = {"TEXT_AD", "TEXT_IMAGE_AD", "MOBILE_APP_AD"}
        if ad_type_norm not in supported_types:
            raise click.UsageError(
                "Invalid value for '--type': "
                f"{ad_type!r} is not one of "
                "'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD'."
            )

        # --mobile has a Click default of "NO" so the value is always present
        # in the payload, but the per-subtype guard must reject any explicit
        # use of --mobile on non-TEXT_AD subtypes — including --mobile NO —
        # to avoid silent data loss (issue #198 H2 / #202).
        mobile_source = ctx.get_parameter_source("mobile")
        mobile_explicit = (
            mobile_source != click.core.ParameterSource.DEFAULT
            if mobile_source
            else False
        )
        mobile_provided = mobile if mobile_explicit else None

        type_fields = {
            "TEXT_AD": {
                "title",
                "text",
                "href",
                "image_hash",
                "title2",
                "display_url_path",
                "mobile",
                "vcard_id",
                "sitelink_set_id",
                "turbo_page_id",
                "ad_extensions",
            },
            "TEXT_IMAGE_AD": {"href", "image_hash", "turbo_page_id"},
            "MOBILE_APP_AD": {
                "title",
                "text",
                "image_hash",
                "action",
                "tracking_url",
                "age_label",
            },
        }
        provided = {
            "title": title,
            "text": text,
            "href": href,
            "image_hash": image_hash,
            "action": action,
            "tracking_url": tracking_url,
            "age_label": age_label,
            "title2": title2,
            "display_url_path": display_url_path,
            "mobile": mobile_provided,
            "vcard_id": vcard_id,
            "sitelink_set_id": sitelink_set_id,
            "turbo_page_id": turbo_page_id,
            "ad_extensions": ad_extensions,
        }
        flag_for = {
            "title": "--title",
            "text": "--text",
            "href": "--href",
            "image_hash": "--image-hash",
            "action": "--action",
            "tracking_url": "--tracking-url",
            "age_label": "--age-label",
            "title2": "--title2",
            "display_url_path": "--display-url-path",
            "mobile": "--mobile",
            "vcard_id": "--vcard-id",
            "sitelink_set_id": "--sitelink-set-id",
            "turbo_page_id": "--turbo-page-id",
            "ad_extensions": "--ad-extensions",
        }
        _reject_incompatible_flags(
            ad_type_norm, type_fields[ad_type_norm], provided, flag_for
        )

        ad_data = {"AdGroupId": adgroup_id}
        if ad_type_norm == "TEXT_AD":
            missing_fields = [
                option_name
                for option_name, value in (
                    ("--title", title),
                    ("--text", text),
                    ("--href", href),
                )
                if not value
            ]
            if missing_fields:
                raise click.UsageError("TEXT_AD requires " + ", ".join(missing_fields))
            text_ad = {
                "Mobile": mobile.upper(),
                "Title": title,
                "Text": text,
                "Href": href,
            }
            if image_hash:
                text_ad["AdImageHash"] = image_hash
            if title2:
                text_ad["Title2"] = title2
            if display_url_path:
                text_ad["DisplayUrlPath"] = display_url_path
            if vcard_id:
                text_ad["VCardId"] = vcard_id
            if sitelink_set_id:
                text_ad["SitelinkSetId"] = sitelink_set_id
            if turbo_page_id:
                text_ad["TurboPageId"] = turbo_page_id
            if ad_extensions:
                text_ad["AdExtensionIds"] = parse_ids(ad_extensions)
            ad_data["TextAd"] = text_ad
        elif ad_type_norm == "TEXT_IMAGE_AD":
            if title or text:
                raise click.UsageError(
                    "--title/--text are only valid for TEXT_AD. "
                    "For TEXT_IMAGE_AD, use --image-hash and --href."
                )
            if not image_hash or not href:
                raise click.UsageError(
                    "TEXT_IMAGE_AD requires both --image-hash and --href"
                )
            text_image_ad = {
                "AdImageHash": image_hash,
                "Href": href,
            }
            if turbo_page_id:
                text_image_ad["TurboPageId"] = turbo_page_id
            ad_data["TextImageAd"] = text_image_ad
        elif ad_type_norm == "MOBILE_APP_AD":
            if href:
                raise click.UsageError(
                    "--href does not apply to MOBILE_APP_AD. "
                    "Use --tracking-url instead."
                )
            missing_fields = [
                option_name
                for option_name, value in (
                    ("--title", title),
                    ("--text", text),
                    ("--action", action),
                )
                if not value
            ]
            if missing_fields:
                raise click.UsageError(
                    "MOBILE_APP_AD requires " + ", ".join(missing_fields)
                )
            mobile_app_ad = {
                "Title": title,
                "Text": text,
                "Action": action.upper(),
            }
            if image_hash:
                mobile_app_ad["AdImageHash"] = image_hash
            if tracking_url:
                mobile_app_ad["TrackingUrl"] = tracking_url
            if age_label:
                mobile_app_ad["AgeLabel"] = age_label.upper()
            ad_data["MobileAppAd"] = mobile_app_ad

        body = {"method": "add", "params": {"Ads": [ad_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except click.UsageError:
        raise
    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option(
    "--type",
    "ad_type",
    required=True,
    help="Ad subtype: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD | DYNAMIC_TEXT_AD",
)
@click.option(
    "--status",
    help=(
        "Deprecated: not part of WSDL AdUpdateItem. "
        "Use 'direct ads suspend/resume/archive/unarchive' instead."
    ),
)
@click.option("--title", help="Title (TEXT_AD / MOBILE_APP_AD)")
@click.option("--text", help="Text (TEXT_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)")
@click.option("--href", help="URL (TEXT_AD / TEXT_IMAGE_AD)")
@click.option(
    "--image-hash",
    help="Image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD / DYNAMIC_TEXT_AD)",
)
@click.option(
    "--action",
    help="MOBILE_APP_AD call-to-action (MobileAppAdActionEnum, e.g. INSTALL)",
)
@click.option("--tracking-url", help="MOBILE_APP_AD tracking URL")
@click.option("--age-label", help="MOBILE_APP_AD age label (MobAppAgeLabelEnum)")
@click.option("--title2", help="Second headline (TEXT_AD)")
@click.option("--display-url-path", help="Display URL path (TEXT_AD)")
@click.option("--vcard-id", type=int, help="VCard ID (TEXT_AD / DYNAMIC_TEXT_AD)")
@click.option(
    "--sitelink-set-id",
    type=int,
    help="Sitelink set ID (TEXT_AD / DYNAMIC_TEXT_AD)",
)
@click.option(
    "--turbo-page-id", type=int, help="Turbo page ID (TEXT_AD / TEXT_IMAGE_AD)"
)
@click.option(
    "--callouts-add",
    help=(
        "Comma-separated CALLOUT ad-extension IDs to attach "
        "(Operation=ADD). TEXT_AD / DYNAMIC_TEXT_AD only."
    ),
)
@click.option(
    "--callouts-remove",
    help=(
        "Comma-separated CALLOUT ad-extension IDs to detach "
        "(Operation=REMOVE). TEXT_AD / DYNAMIC_TEXT_AD only."
    ),
)
@click.option(
    "--callouts-set",
    help=(
        "Comma-separated CALLOUT ad-extension IDs that REPLACE the ad's "
        "current callout list (Operation=SET). Mutually exclusive with "
        "--callouts-add / --callouts-remove. TEXT_AD / DYNAMIC_TEXT_AD only."
    ),
)
@click.option(
    "--video-extension-creative-id",
    type=int,
    help="Video extension CreativeId for TextAd.VideoExtension. TEXT_AD only.",
)
@click.option(
    "--price-extension-price",
    type=int,
    help=(
        "PriceExtension.Price as API long units "
        "(price multiplied by 1,000,000). TEXT_AD only."
    ),
)
@click.option(
    "--price-extension-old-price",
    type=int,
    help=(
        "PriceExtension.OldPrice as API long units "
        "(price multiplied by 1,000,000). TEXT_AD only."
    ),
)
@click.option(
    "--price-extension-price-qualifier",
    type=click.Choice(["FROM", "UP_TO", "NONE"], case_sensitive=False),
    help="PriceExtension.PriceQualifier: FROM, UP_TO, or NONE. TEXT_AD only.",
)
@click.option(
    "--price-extension-price-currency",
    type=click.Choice(
        ["RUB", "UAH", "BYN", "USD", "EUR", "KZT", "TRY", "CHF", "UZS"],
        case_sensitive=False,
    ),
    help="PriceExtension.PriceCurrency enum value. TEXT_AD only.",
)
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def update(
    ctx,
    ad_id,
    ad_type,
    status,
    title,
    text,
    href,
    image_hash,
    action,
    tracking_url,
    age_label,
    title2,
    display_url_path,
    vcard_id,
    sitelink_set_id,
    turbo_page_id,
    callouts_add,
    callouts_remove,
    callouts_set,
    video_extension_creative_id,
    price_extension_price,
    price_extension_old_price,
    price_extension_price_qualifier,
    price_extension_price_currency,
    dry_run,
):
    """Update ad"""
    if status:
        raise click.UsageError(
            "Use 'direct ads suspend/resume/archive/unarchive' to change status. "
            "The --status flag is not supported by WSDL AdUpdateItem."
        )

    ad_type_norm = ad_type.upper().replace("-", "_")
    supported_types = {"TEXT_AD", "TEXT_IMAGE_AD", "MOBILE_APP_AD", "DYNAMIC_TEXT_AD"}
    if ad_type_norm not in supported_types:
        raise click.UsageError(
            "Invalid value for '--type': "
            f"{ad_type!r} is not one of "
            "'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD', 'DYNAMIC_TEXT_AD'."
        )

    # Per-WSDL-subtype field allow-list: each --type accepts only the
    # options that map to fields inside its AdUpdateItem subtype. A flag
    # outside the allow-list would be silently dropped by the loop below;
    # reject up front so the user sees the conflict instead of a no-op
    # (issue #198 H2).
    type_fields = {
        "TEXT_AD": {
            "title",
            "text",
            "href",
            "image_hash",
            "title2",
            "display_url_path",
            "vcard_id",
            "sitelink_set_id",
            "turbo_page_id",
            "callouts_add",
            "callouts_remove",
            "callouts_set",
            "video_extension_creative_id",
            "price_extension_price",
            "price_extension_old_price",
            "price_extension_price_qualifier",
            "price_extension_price_currency",
        },
        "DYNAMIC_TEXT_AD": {
            "text",
            "image_hash",
            "vcard_id",
            "sitelink_set_id",
            "callouts_add",
            "callouts_remove",
            "callouts_set",
        },
        "TEXT_IMAGE_AD": {"image_hash", "href", "turbo_page_id"},
        "MOBILE_APP_AD": {
            "title",
            "text",
            "image_hash",
            "action",
            "tracking_url",
            "age_label",
        },
    }
    provided = {
        "title": title,
        "text": text,
        "href": href,
        "image_hash": image_hash,
        "action": action,
        "tracking_url": tracking_url,
        "age_label": age_label,
        "title2": title2,
        "display_url_path": display_url_path,
        "vcard_id": vcard_id,
        "sitelink_set_id": sitelink_set_id,
        "turbo_page_id": turbo_page_id,
        "callouts_add": callouts_add,
        "callouts_remove": callouts_remove,
        "callouts_set": callouts_set,
        "video_extension_creative_id": video_extension_creative_id,
        "price_extension_price": price_extension_price,
        "price_extension_old_price": price_extension_old_price,
        "price_extension_price_qualifier": price_extension_price_qualifier,
        "price_extension_price_currency": price_extension_price_currency,
    }
    flag_for = {
        "title": "--title",
        "text": "--text",
        "href": "--href",
        "image_hash": "--image-hash",
        "action": "--action",
        "tracking_url": "--tracking-url",
        "age_label": "--age-label",
        "title2": "--title2",
        "display_url_path": "--display-url-path",
        "vcard_id": "--vcard-id",
        "sitelink_set_id": "--sitelink-set-id",
        "turbo_page_id": "--turbo-page-id",
        "callouts_add": "--callouts-add",
        "callouts_remove": "--callouts-remove",
        "callouts_set": "--callouts-set",
        "video_extension_creative_id": "--video-extension-creative-id",
        "price_extension_price": "--price-extension-price",
        "price_extension_old_price": "--price-extension-old-price",
        "price_extension_price_qualifier": "--price-extension-price-qualifier",
        "price_extension_price_currency": "--price-extension-price-currency",
    }
    try:
        _reject_incompatible_flags(
            ad_type_norm, type_fields[ad_type_norm], provided, flag_for
        )
    except click.UsageError as exc:
        raise click.UsageError(
            f"{exc.message} --type selects the existing ad subtype update block; "
            "it does not convert an ad between subtypes."
        )

    # Validate up-front so SET vs ADD/REMOVE mutex errors raise UsageError
    # before any payload work, bypassing the generic ``except Exception``
    # net wrapped around the network call below.
    callout_setting = _build_callout_setting(
        callouts_add, callouts_remove, callouts_set
    )
    price_extension = _build_price_extension(
        price_extension_price,
        price_extension_old_price,
        price_extension_price_qualifier,
        price_extension_price_currency,
    )

    ad_data = {"Id": ad_id}

    if ad_type_norm == "TEXT_AD":
        text_ad = _build_text_ad_update_base(
            vcard_id,
            image_hash,
            sitelink_set_id,
            callout_setting,
        )
        if title:
            text_ad["Title"] = title
        if text:
            text_ad["Text"] = text
        if href:
            text_ad["Href"] = href
        if title2:
            text_ad["Title2"] = title2
        if display_url_path:
            text_ad["DisplayUrlPath"] = display_url_path
        if turbo_page_id:
            text_ad["TurboPageId"] = turbo_page_id
        if video_extension_creative_id is not None:
            text_ad["VideoExtension"] = {"CreativeId": video_extension_creative_id}
        if price_extension:
            text_ad["PriceExtension"] = price_extension
        if text_ad:
            ad_data["TextAd"] = text_ad
    elif ad_type_norm == "DYNAMIC_TEXT_AD":
        dynamic_text_ad = _build_text_ad_update_base(
            vcard_id,
            image_hash,
            sitelink_set_id,
            callout_setting,
        )
        if text:
            dynamic_text_ad["Text"] = text
        if dynamic_text_ad:
            ad_data["DynamicTextAd"] = dynamic_text_ad
    elif ad_type_norm == "TEXT_IMAGE_AD":
        text_image_ad = {}
        if image_hash:
            text_image_ad["AdImageHash"] = image_hash
        if href:
            text_image_ad["Href"] = href
        if turbo_page_id:
            text_image_ad["TurboPageId"] = turbo_page_id
        if text_image_ad:
            ad_data["TextImageAd"] = text_image_ad
    elif ad_type_norm == "MOBILE_APP_AD":
        mobile_app_ad = {}
        if title:
            mobile_app_ad["Title"] = title
        if text:
            mobile_app_ad["Text"] = text
        if image_hash:
            mobile_app_ad["AdImageHash"] = image_hash
        if action:
            mobile_app_ad["Action"] = action.upper()
        if tracking_url:
            mobile_app_ad["TrackingUrl"] = tracking_url
        if age_label:
            mobile_app_ad["AgeLabel"] = age_label.upper()
        if mobile_app_ad:
            ad_data["MobileAppAd"] = mobile_app_ad

    # Reject empty-subtype no-ops: ``{Id: N}`` with no subtype block
    # is a silent no-op on the live API (issue #198 H1).
    if len(ad_data) == 1:
        raise click.UsageError(
            f"ads update requires at least one updatable field for "
            f"--type {ad_type_norm}."
        )

    try:
        body = {"method": "update", "params": {"Ads": [ad_data]}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def delete(ctx, ad_id, dry_run):
    """Delete ad"""
    try:
        body = {"method": "delete", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def archive(ctx, ad_id, dry_run):
    """Archive ad"""
    try:
        body = {"method": "archive", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def unarchive(ctx, ad_id, dry_run):
    """Unarchive ad"""
    try:
        body = {
            "method": "unarchive",
            "params": {"SelectionCriteria": {"Ids": [ad_id]}},
        }

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def suspend(ctx, ad_id, dry_run):
    """Suspend ad"""
    try:
        body = {"method": "suspend", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def resume(ctx, ad_id, dry_run):
    """Resume ad"""
    try:
        body = {"method": "resume", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()


@ads.command()
@click.option("--id", "ad_id", required=True, type=int, help="Ad ID")
@click.option("--dry-run", is_flag=True, help="Show request without sending")
@click.pass_context
def moderate(ctx, ad_id, dry_run):
    """Moderate ad"""
    try:
        body = {"method": "moderate", "params": {"SelectionCriteria": {"Ids": [ad_id]}}}

        if dry_run:
            format_output(body, "json", None)
            return

        client = create_client(
            token=ctx.obj.get("token"),
            login=ctx.obj.get("login"),
            sandbox=ctx.obj.get("sandbox"),
        )

        result = client.ads().post(data=body)
        format_output(result().extract(), "json", None)

    except Exception as e:
        print_error(str(e))
        raise click.Abort()

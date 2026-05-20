"""
Ads commands
"""

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

        type_fields = {
            "TEXT_AD": {"title", "text", "href", "image_hash"},
            "TEXT_IMAGE_AD": {"href", "image_hash"},
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
        }
        flag_for = {
            "title": "--title",
            "text": "--text",
            "href": "--href",
            "image_hash": "--image-hash",
            "action": "--action",
            "tracking_url": "--tracking-url",
            "age_label": "--age-label",
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
            ad_data["TextAd"] = {
                "Mobile": "NO",
                "Title": title,
                "Text": text,
                "Href": href,
            }
            if image_hash:
                ad_data["TextAd"]["AdImageHash"] = image_hash
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
            ad_data["TextImageAd"] = {
                "AdImageHash": image_hash,
                "Href": href,
            }
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
    help="Ad subtype: TEXT_AD | TEXT_IMAGE_AD | MOBILE_APP_AD",
)
@click.option(
    "--status",
    help=(
        "Deprecated: not part of WSDL AdUpdateItem. "
        "Use 'direct ads suspend/resume/archive/unarchive' instead."
    ),
)
@click.option("--title", help="Title (TEXT_AD / MOBILE_APP_AD)")
@click.option("--text", help="Text (TEXT_AD / MOBILE_APP_AD)")
@click.option("--href", help="URL (TEXT_AD / TEXT_IMAGE_AD)")
@click.option(
    "--image-hash", help="Image hash (TEXT_AD / TEXT_IMAGE_AD / MOBILE_APP_AD)"
)
@click.option(
    "--action",
    help="MOBILE_APP_AD call-to-action (MobileAppAdActionEnum, e.g. INSTALL)",
)
@click.option("--tracking-url", help="MOBILE_APP_AD tracking URL")
@click.option("--age-label", help="MOBILE_APP_AD age label (MobAppAgeLabelEnum)")
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
    dry_run,
):
    """Update ad"""
    if status:
        raise click.UsageError(
            "Use 'direct ads suspend/resume/archive/unarchive' to change status. "
            "The --status flag is not supported by WSDL AdUpdateItem."
        )

    ad_type_norm = ad_type.upper().replace("-", "_")
    supported_types = {"TEXT_AD", "TEXT_IMAGE_AD", "MOBILE_APP_AD"}
    if ad_type_norm not in supported_types:
        raise click.UsageError(
            "Invalid value for '--type': "
            f"{ad_type!r} is not one of "
            "'TEXT_AD', 'TEXT_IMAGE_AD', 'MOBILE_APP_AD'."
        )

    # Per-WSDL-subtype field allow-list: each --type accepts only the
    # options that map to fields inside its AdUpdateItem subtype. A flag
    # outside the allow-list would be silently dropped by the loop below;
    # reject up front so the user sees the conflict instead of a no-op
    # (issue #198 H2).
    type_fields = {
        "TEXT_AD": {"title", "text", "href", "image_hash"},
        "TEXT_IMAGE_AD": {"image_hash", "href"},
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
    }
    flag_for = {
        "title": "--title",
        "text": "--text",
        "href": "--href",
        "image_hash": "--image-hash",
        "action": "--action",
        "tracking_url": "--tracking-url",
        "age_label": "--age-label",
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

    ad_data = {"Id": ad_id}

    if ad_type_norm == "TEXT_AD":
        text_ad = {}
        if title:
            text_ad["Title"] = title
        if text:
            text_ad["Text"] = text
        if href:
            text_ad["Href"] = href
        if image_hash:
            text_ad["AdImageHash"] = image_hash
        if text_ad:
            ad_data["TextAd"] = text_ad
    elif ad_type_norm == "TEXT_IMAGE_AD":
        text_image_ad = {}
        if image_hash:
            text_image_ad["AdImageHash"] = image_hash
        if href:
            text_image_ad["Href"] = href
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

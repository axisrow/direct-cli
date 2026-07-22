"""Dry-run payload tests for ``adgroups``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _read_dry_run, _rejected, _write_jsonl


def test_adgroups_add_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
    )
    assert body["method"] == "add"
    group = body["params"]["AdGroups"][0]
    # Regression guard: AdGroupAddItem has no top-level Type field;
    # the group type is inferred from MobileAppAdGroup / DynamicTextAdGroup
    # / SmartAdGroup / ... sub-objects exactly like Ads.
    # See https://yandex.ru/dev/direct/doc/ref-v5/adgroups/add.html
    assert "Type" not in group
    assert group["Name"] == "Group A"
    assert group["CampaignId"] == 111
    assert group["RegionIds"] == [1, 225]


def test_adgroups_add_text_feed_params_payload():
    """Issue #284: text ad group feed params use a typed top-level block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["TextAdGroupFeedParams"] == {
        "FeedId": 170,
        "FeedCategoryIds": {"Items": [10, 11]},
    }


def test_adgroups_add_text_feed_params_feed_id_only_payload():
    """Issue #284: category IDs are optional; omitted means all categories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert group["TextAdGroupFeedParams"] == {"FeedId": 170}


def test_adgroups_add_text_feed_params_requires_feed_id_for_categories():
    """Issue #284: FeedId is required when TextAdGroupFeedParams is sent."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Text Feed Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--feed-category-ids",
        "10",
    )
    assert "--feed-id is required when --feed-category-ids is used" in result.output


def test_adgroups_add_tracking_params_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--tracking-params",
        "utm_source=direct",
    )
    group = body["params"]["AdGroups"][0]
    assert group["TrackingParams"] == "utm_source=direct"
    assert "DynamicTextAdGroup" not in group
    assert "SmartAdGroup" not in group


def test_adgroups_add_negative_keywords_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keywords",
        "word1, word2",
    )
    group = body["params"]["AdGroups"][0]
    assert group["NegativeKeywords"] == {"Items": ["word1", "word2"]}


def test_adgroups_add_negative_keyword_shared_set_ids_payload():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group["NegativeKeywordSharedSetIds"] == {"Items": [10, 11]}


def test_adgroups_add_negative_keyword_shared_set_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "1,225",
        "--negative-keyword-shared-set-ids",
        "10,nope",
    )
    assert "--negative-keyword-shared-set-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_add_case_insensitive_default_type():
    """``--type text_ad_group`` (lowercase) still builds a valid payload.

    Regression guard for axisrow/direct-cli#23 — before the fix the CLI
    accepted --type as a free-form string and silently discarded it,
    so users typing the lowercase variant got the default text payload
    without error. Normalization now makes lowercase an explicit
    supported spelling.
    """
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "text_ad_group",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["CampaignId"] == 111


def test_adgroups_add_dynamic_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["DynamicTextAdGroup"] == {"DomainUrl": "example.com"}


def test_adgroups_add_dynamic_autotargeting_categories_payload():
    """Issue #280: dynamic add supports legacy AutotargetingCategories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "BROADER=NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextAdGroup"] == {
        "DomainUrl": "example.com",
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "BROADER", "Value": "NO"},
        ],
    }


def test_adgroups_add_dynamic_autotargeting_settings_payload():
    """Issue #280: dynamic add supports AutotargetingSettings flags."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "1,225",
        "--domain-url",
        "example.com",
        "--autotargeting-settings-exact",
        "yes",
        "--autotargeting-settings-narrow",
        "no",
        "--autotargeting-settings-without-brands",
        "YES",
        "--autotargeting-settings-with-competitors-brand",
        "no",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextAdGroup"] == {
        "DomainUrl": "example.com",
        "AutotargetingSettings": {
            "Categories": {
                "Exact": "YES",
                "Narrow": "NO",
            },
            "BrandOptions": {
                "WithoutBrands": "YES",
                "WithCompetitorsBrand": "NO",
            },
        },
    }


def test_adgroups_add_dynamic_autotargeting_rejects_invalid_category():
    """Issue #280: AutotargetingCategories uses the documented enum."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "NARROW=YES",
    )
    assert "Invalid --autotargeting-category category 'NARROW'" in result.output
    assert "EXACT, ALTERNATIVE, COMPETITOR, BROADER, ACCESSORY" in result.output


def test_adgroups_add_dynamic_autotargeting_rejects_legacy_mix():
    """Issue #280: legacy categories and AutotargetingSettings cannot mix."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "EXACT=YES",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert "AutotargetingSettings flags cannot be combined" in result.output


def test_adgroups_add_dynamic_feed_payload_omits_type():
    """Issue #281: dynamic feed add sets top-level DynamicTextFeedAdGroup."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["DynamicTextFeedAdGroup"] == {"FeedId": 170}


def test_adgroups_add_dynamic_feed_autotargeting_categories_payload():
    """Issue #281: dynamic feed add supports documented categories."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "170",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "ACCESSORY=NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group["DynamicTextFeedAdGroup"] == {
        "FeedId": 170,
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "ACCESSORY", "Value": "NO"},
        ],
    }


def test_adgroups_add_dynamic_feed_requires_feed_id():
    """Issue #281: add docs require DynamicTextFeedAdGroup.FeedId."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "225",
    )
    assert "--feed-id is required for DYNAMIC_TEXT_FEED_AD_GROUP" in result.output


def test_adgroups_add_dynamic_feed_rejects_undocumented_settings():
    """Issue #281: feed subtype only exposes docs-backed category flags."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Feed Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_FEED_AD_GROUP",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert (
        "--autotargeting-settings-exact is not compatible with --type "
        "DYNAMIC_TEXT_FEED_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_banner_keywords_payload_omits_type():
    """Issue #282: CPM banner keyword subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmBannerKeywordsAdGroup"] == {}


def test_adgroups_add_cpm_banner_keywords_accepts_negative_keywords():
    """Issue #282: CPM banner keyword groups still accept negative keywords."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "used,repair",
        "--negative-keyword-shared-set-ids",
        "10",
    )
    group = body["params"]["AdGroups"][0]
    assert group["CpmBannerKeywordsAdGroup"] == {}
    assert group["NegativeKeywords"] == {"Items": ["used", "repair"]}
    assert group["NegativeKeywordSharedSetIds"] == {"Items": [10]}


def test_adgroups_add_cpm_banner_user_profile_payload_omits_type():
    """Issue #282: CPM user-profile subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmBannerUserProfileAdGroup"] == {}


def test_adgroups_add_cpm_user_profile_rejects_empty_negative_keyword_flag():
    """Issue #282: disallowed negative keyword flags reject even empty values."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "",
    )
    assert (
        "--negative-keywords is not compatible with --type "
        "CPM_BANNER_USER_PROFILE_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_payload_omits_type():
    """Issue #282: CPM video subtype sends an empty block."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "1,225",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["RegionIds"] == [1, 225]
    assert group["CpmVideoAdGroup"] == {}


def test_adgroups_add_cpm_user_profile_rejects_negative_keywords():
    """Issue #282: docs disallow negative keywords for user-profile CPM groups."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM User Profile Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_BANNER_USER_PROFILE_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keywords",
        "used",
    )
    assert (
        "--negative-keywords is not compatible with --type "
        "CPM_BANNER_USER_PROFILE_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_rejects_negative_keyword_shared_sets():
    """Issue #282: docs disallow negative keyword sets for CPM video groups."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keyword-shared-set-ids",
        "10",
    )
    assert (
        "--negative-keyword-shared-set-ids is not compatible with --type "
        "CPM_VIDEO_AD_GROUP"
    ) in result.output


def test_adgroups_add_cpm_video_rejects_negative_keyword_shared_sets_before_parse():
    """Issue #282: type incompatibility wins over shared-set ID parsing."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Video Group",
        "--campaign-id",
        "111",
        "--type",
        "CPM_VIDEO_AD_GROUP",
        "--region-ids",
        "225",
        "--negative-keyword-shared-set-ids",
        "notanumber",
    )
    assert (
        "--negative-keyword-shared-set-ids is not compatible with --type "
        "CPM_VIDEO_AD_GROUP"
    ) in result.output
    assert "Invalid ID" not in result.output


def test_adgroups_add_smart_payload_omits_type():
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--type",
        "SMART_AD_GROUP",
        "--region-ids",
        "1,225",
        "--feed-id",
        "77",
        "--ad-title-source",
        "FEED_NAME",
        "--ad-body-source",
        "FEED_NAME",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["SmartAdGroup"] == {
        "FeedId": 77,
        "AdTitleSource": "FEED_NAME",
        "AdBodySource": "FEED_NAME",
    }


def test_adgroups_add_mobile_app_payload_omits_type():
    """Issue #279: add builds top-level MobileAppAdGroup payload."""
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--region-ids",
        "1,225",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "device-type-mobile,DEVICE_TYPE_TABLET",
        "--target-carrier",
        "wi-fi-and-cellular",
        "--target-operating-system-version",
        "14.0",
    )
    group = body["params"]["AdGroups"][0]
    assert "Type" not in group
    assert group["MobileAppAdGroup"] == {
        "StoreUrl": "https://apps.apple.com/app/id123456789",
        "TargetDeviceType": ["DEVICE_TYPE_MOBILE", "DEVICE_TYPE_TABLET"],
        "TargetCarrier": "WI_FI_AND_CELLULAR",
        "TargetOperatingSystemVersion": "14.0",
    }


def test_adgroups_add_mobile_app_requires_documented_fields():
    """Issue #279: WSDL minOccurs=1 mobile add fields are locally required."""
    required_options = [
        ("--store-url", "https://apps.apple.com/app/id123456789"),
        ("--target-device-types", "DEVICE_TYPE_MOBILE"),
        ("--target-carrier", "WI_FI_ONLY"),
        ("--target-operating-system-version", "14.0"),
    ]

    for missing_option, _ in required_options:
        args = [
            "adgroups",
            "add",
            "--name",
            "Mobile App Group",
            "--campaign-id",
            "111",
            "--type",
            "MOBILE_APP_AD_GROUP",
            "--region-ids",
            "225",
        ]
        for option, value in required_options:
            if option != missing_option:
                args.extend([option, value])

        result = _rejected(*args)
        assert missing_option in result.output
        assert "required for MOBILE_APP_AD_GROUP" in result.output


def test_adgroups_add_mobile_app_rejects_invalid_device_type():
    """Issue #279: TargetDeviceType is validated against the API enum."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--region-ids",
        "225",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "DEVICE_TYPE_DESKTOP",
        "--target-carrier",
        "WI_FI_ONLY",
        "--target-operating-system-version",
        "14.0",
    )
    assert "--target-device-types has invalid value 'DEVICE_TYPE_DESKTOP'" in (
        result.output
    )
    assert "DEVICE_TYPE_MOBILE, DEVICE_TYPE_TABLET" in result.output


def test_adgroups_add_rejects_incompatible_subtype_flags():
    text_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--domain-url",
        "example.com",
    )
    dynamic_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--domain-url",
        "example.com",
        "--feed-id",
        "77",
    )
    smart_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "SMART_AD_GROUP",
        "--feed-id",
        "77",
        "--domain-url",
        "example.com",
    )
    text_autotargeting_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--autotargeting-category",
        "EXACT=YES",
    )
    text_mobile_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
    )
    mobile_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Mobile App Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "MOBILE_APP_AD_GROUP",
        "--store-url",
        "https://apps.apple.com/app/id123456789",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
        "--target-carrier",
        "WI_FI_ONLY",
        "--target-operating-system-version",
        "14.0",
        "--feed-id",
        "77",
    )
    cpm_result = _rejected(
        "adgroups",
        "add",
        "--name",
        "CPM Keywords Group",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--type",
        "CPM_BANNER_KEYWORDS_AD_GROUP",
        "--domain-url",
        "example.com",
    )

    assert (
        "--domain-url is not compatible with --type TEXT_AD_GROUP" in text_result.output
    )
    assert (
        "--feed-id is not compatible with --type DYNAMIC_TEXT_AD_GROUP"
        in dynamic_result.output
    )
    assert (
        "--domain-url is not compatible with --type SMART_AD_GROUP"
        in smart_result.output
    )
    assert (
        "--autotargeting-category is not compatible with --type TEXT_AD_GROUP"
        in text_autotargeting_result.output
    )
    assert (
        "--store-url is not compatible with --type TEXT_AD_GROUP"
        in text_mobile_result.output
    )
    assert (
        "--feed-id is not compatible with --type MOBILE_APP_AD_GROUP"
        in mobile_result.output
    )
    assert (
        "--domain-url is not compatible with --type CPM_BANNER_KEYWORDS_AD_GROUP"
        in cpm_result.output
    )


def test_adgroups_add_rejects_text_feed_category_ids_for_dynamic_group():
    """Issue #284: TextAdGroupFeedParams flags apply only to TEXT_AD_GROUP."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Dynamic Group",
        "--campaign-id",
        "111",
        "--type",
        "DYNAMIC_TEXT_AD_GROUP",
        "--region-ids",
        "225",
        "--domain-url",
        "example.com",
        "--feed-category-ids",
        "10",
    )
    assert (
        "--feed-category-ids is not compatible with --type DYNAMIC_TEXT_AD_GROUP"
        in result.output
    )


def test_adgroups_add_rejects_text_feed_category_ids_for_smart_group():
    """Issue #284: TextAdGroupFeedParams category IDs do not apply to smart."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Smart Group",
        "--campaign-id",
        "111",
        "--type",
        "SMART_AD_GROUP",
        "--region-ids",
        "225",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10",
    )
    assert (
        "--feed-category-ids is not compatible with --type SMART_AD_GROUP"
        in result.output
    )


def test_adgroups_update_payload_name_only():
    body = _dry_run("adgroups", "update", "--id", "222", "--name", "Renamed")
    assert body["method"] == "update"
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "Name": "Renamed"}


def test_adgroups_update_tracking_params_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--tracking-params",
        "utm_source=direct",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "TrackingParams": "utm_source=direct"}


def test_adgroups_update_text_feed_params_payload_without_type():
    """Issue #284: update sets top-level TextAdGroupFeedParams without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
        "--feed-category-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "TextAdGroupFeedParams": {
            "FeedId": 170,
            "FeedCategoryIds": {"Items": [10, 11]},
        },
    }


def test_adgroups_update_text_feed_params_feed_id_only_payload():
    """Issue #284: TextAdGroupFeedParamsUpdate can update just FeedId."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "TextAdGroupFeedParams": {"FeedId": 170}}


def test_adgroups_update_text_feed_params_requires_feed_id_for_categories():
    """Issue #284: update cannot send category IDs without FeedId."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-category-ids",
        "10",
    )
    assert "--feed-id is required when --feed-category-ids is used" in result.output


def test_adgroups_update_dynamic_domain_url_payload_without_type():
    """Issue #280: update sets top-level DynamicTextAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "DynamicTextAdGroup": {"DomainUrl": "example.com"}}


def test_adgroups_update_dynamic_autotargeting_categories_payload():
    """Issue #280: update includes DynamicTextAdGroup.AutotargetingCategories."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextAdGroup": {
            "DomainUrl": "example.com",
            "AutotargetingCategories": [
                {"Category": "ALTERNATIVE", "Value": "YES"},
                {"Category": "COMPETITOR", "Value": "NO"},
            ],
        },
    }


def test_adgroups_update_dynamic_autotargeting_settings_payload():
    """Issue #280: update includes DynamicTextAdGroup.AutotargetingSettings."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-settings-alternative",
        "YES",
        "--autotargeting-settings-accessory",
        "no",
        "--autotargeting-settings-broader",
        "yes",
        "--autotargeting-settings-with-advertiser-brand",
        "NO",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextAdGroup": {
            "DomainUrl": "example.com",
            "AutotargetingSettings": {
                "Categories": {
                    "Alternative": "YES",
                    "Accessory": "NO",
                    "Broader": "YES",
                },
                "BrandOptions": {
                    "WithAdvertiserBrand": "NO",
                },
            },
        },
    }


def test_adgroups_update_dynamic_autotargeting_requires_domain_url():
    """Issue #280: DynamicTextAdGroupUpdate.DomainUrl is required by docs/WSDL."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--autotargeting-category",
        "EXACT=YES",
    )
    assert "--domain-url is required for DYNAMIC_TEXT_AD_GROUP" in result.output


def test_adgroups_update_dynamic_autotargeting_rejects_legacy_mix():
    """Issue #280: legacy categories and AutotargetingSettings cannot mix."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--autotargeting-category",
        "EXACT=YES",
        "--autotargeting-settings-exact",
        "YES",
    )
    assert "AutotargetingSettings flags cannot be combined" in result.output


def test_adgroups_update_dynamic_feed_autotargeting_categories_payload():
    """Issue #281: update targets DynamicTextFeedAdGroup with --dynamic-feed."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "DynamicTextFeedAdGroup": {
            "AutotargetingCategories": [
                {"Category": "ALTERNATIVE", "Value": "YES"},
                {"Category": "COMPETITOR", "Value": "NO"},
            ],
        },
    }


def test_adgroups_update_dynamic_feed_requires_category():
    """Issue #281: --dynamic-feed must not be silently ignored."""
    result = _rejected("adgroups", "update", "--id", "222", "--dynamic-feed")
    assert "--dynamic-feed requires --autotargeting-category" in result.output


def test_adgroups_update_rejects_mixed_dynamic_text_and_feed_subtype_flags():
    """Issue #281: update must not emit both dynamic subtype blocks."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "EXACT=YES",
        "--domain-url",
        "example.com",
    )
    assert "DynamicTextAdGroup update flags" in result.output
    assert "--domain-url" in result.output
    assert "DynamicTextFeedAdGroup update flags" in result.output
    assert "--dynamic-feed" in result.output


def test_adgroups_update_rejects_mixed_dynamic_feed_and_mobile_subtype_flags():
    """Issue #281: update must not mix feed subtype with mobile app fields."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--dynamic-feed",
        "--autotargeting-category",
        "EXACT=YES",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
    )
    assert "DynamicTextFeedAdGroup update flags" in result.output
    assert "--dynamic-feed" in result.output
    assert "MobileAppAdGroup update flags" in result.output
    assert "--target-device-types" in result.output


def test_adgroups_update_rejects_mixed_dynamic_and_mobile_subtype_flags():
    """Issue #280: update must not emit two subtype blocks in one item."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--domain-url",
        "example.com",
        "--target-device-types",
        "DEVICE_TYPE_MOBILE",
    )
    assert "DynamicTextAdGroup update flags" in result.output
    assert "--domain-url" in result.output
    assert "MobileAppAdGroup update flags" in result.output
    assert "--target-device-types" in result.output


def test_adgroups_update_mobile_app_payload_without_type():
    """Issue #279: update sets top-level MobileAppAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--target-device-types",
        "device-type-tablet",
        "--target-carrier",
        "wi-fi-only",
        "--target-operating-system-version",
        "13.0",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "MobileAppAdGroup": {
            "TargetDeviceType": ["DEVICE_TYPE_TABLET"],
            "TargetCarrier": "WI_FI_ONLY",
            "TargetOperatingSystemVersion": "13.0",
        },
    }


def test_adgroups_update_mobile_app_rejects_invalid_carrier():
    """Issue #279: TargetCarrier is validated against the API enum."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--target-carrier",
        "CELLULAR_ONLY",
    )
    assert "--target-carrier has invalid value 'CELLULAR_ONLY'" in result.output
    assert "WI_FI_ONLY or WI_FI_AND_CELLULAR" not in result.output
    assert "WI_FI_ONLY, WI_FI_AND_CELLULAR" in result.output


def test_adgroups_update_smart_payload_without_type():
    """Issue #283: update sets top-level SmartAdGroup without --type."""
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--ad-title-source",
        "name",
        "--ad-body-source",
        "description",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {
        "Id": 222,
        "SmartAdGroup": {
            "AdTitleSource": "name",
            "AdBodySource": "description",
        },
    }


def test_adgroups_update_rejects_mixed_text_feed_and_smart_subtype_flags():
    """Issue #284: update must not emit TextAdGroupFeedParams and SmartAdGroup."""
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--feed-id",
        "170",
        "--ad-title-source",
        "name",
    )
    assert "TextAdGroupFeedParams update flags" in result.output
    assert "--feed-id" in result.output
    assert "SmartAdGroup update flags" in result.output
    assert "--ad-title-source" in result.output


def test_adgroups_update_negative_keywords_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keywords",
        "word1, word2",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "NegativeKeywords": {"Items": ["word1", "word2"]}}


def test_adgroups_update_negative_keyword_shared_set_ids_payload():
    body = _dry_run(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    group = body["params"]["AdGroups"][0]
    assert group == {"Id": 222, "NegativeKeywordSharedSetIds": {"Items": [10, 11]}}


def test_adgroups_update_negative_keyword_shared_set_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--negative-keyword-shared-set-ids",
        "10,nope",
    )
    assert "--negative-keyword-shared-set-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_update_region_ids_rejects_invalid_id():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--region-ids",
        "225,nope",
    )
    assert "--region-ids: Invalid ID: 'nope'" in result.output
    assert "Traceback" not in result.output


def test_adgroups_add_tracking_params_accepts_1024_chars():
    tracking_params = "x" * 1024
    body = _dry_run(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--tracking-params",
        tracking_params,
    )
    group = body["params"]["AdGroups"][0]
    assert group["TrackingParams"] == tracking_params


def test_adgroups_add_tracking_params_rejects_1025_chars():
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Group A",
        "--campaign-id",
        "111",
        "--region-ids",
        "225",
        "--tracking-params",
        "x" * 1025,
    )
    assert "--tracking-params must be at most 1024 characters" in result.output


def test_adgroups_update_tracking_params_rejects_1025_chars():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "222",
        "--tracking-params",
        "x" * 1025,
    )
    assert "--tracking-params must be at most 1024 characters" in result.output


def test_adgroups_update_without_tracking_params_or_other_fields_rejected():
    result = _rejected("adgroups", "update", "--id", "222")
    assert "--tracking-params" in result.output
    assert "--negative-keywords" in result.output
    assert "--negative-keyword-shared-set-ids" in result.output
    assert "--domain-url" in result.output
    assert "--dynamic-feed" in result.output
    assert "--autotargeting-category" in result.output
    assert "--autotargeting-settings-* flags" in result.output
    assert "--target-device-types" in result.output
    assert "--target-carrier" in result.output
    assert "--target-operating-system-version" in result.output
    assert "--ad-title-source" in result.output
    assert "--ad-body-source" in result.output
    assert "--offer-retargeting" in result.output
    assert "requires at least one updatable field" in result.output


def test_adgroups_delete_dry_run_payload():
    body = _dry_run("adgroups", "delete", "--id", "55")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [55]}},
    }


_ADGROUPS_GET_NESTED_FIELD_FLAGS = [
    (
        "--autotargeting-settings-brand-options-field-names",
        "AutotargetingSettingsBrandOptionsFieldNames",
        "WithoutBrands,WithAdvertiserBrand",
    ),
    (
        "--autotargeting-settings-categories-field-names",
        "AutotargetingSettingsCategoriesFieldNames",
        "Exact,Narrow,Alternative",
    ),
    (
        "--dynamic-text-ad-group-field-names",
        "DynamicTextAdGroupFieldNames",
        "AutotargetingSettings,DomainUrl",
    ),
    (
        "--dynamic-text-feed-ad-group-field-names",
        "DynamicTextFeedAdGroupFieldNames",
        "Source,FeedId",
    ),
    (
        "--mobile-app-ad-group-field-names",
        "MobileAppAdGroupFieldNames",
        "StoreUrl,TargetDeviceType",
    ),
    (
        "--smart-ad-group-field-names",
        "SmartAdGroupFieldNames",
        "FeedId,AdTitleSource",
    ),
    (
        "--text-ad-group-feed-params-field-names",
        "TextAdGroupFeedParamsFieldNames",
        "FeedId,FeedCategoryIds",
    ),
    (
        "--unified-ad-group-field-names",
        "UnifiedAdGroupFieldNames",
        "OfferRetargeting",
    ),
]


def test_adgroups_get_nested_field_names_payload():
    # AdGroupsGetRequest (WSDL tests/wsdl_cache/adgroups.xml) declares eight
    # nested top-level *FieldNames parameters separate from FieldNames.
    # Verified against live production API on 2026-05-28: Yandex accepts the
    # two AutotargetingSettings* parameters that are not (yet) listed in the
    # public adgroups.get reference (#405 carries the api-status:docs-drift
    # label).
    argv = ["adgroups", "get", "--campaign-ids", "1"]
    expected = {}
    for flag, wsdl_key, sample in _ADGROUPS_GET_NESTED_FIELD_FLAGS:
        argv.extend([flag, sample])
        expected[wsdl_key] = sample.split(",")

    body = _read_dry_run(*argv)

    for wsdl_key, values in expected.items():
        assert body["params"][wsdl_key] == values


def test_adgroups_get_omits_nested_field_names_by_default():
    body = _read_dry_run("adgroups", "get", "--campaign-ids", "1")

    for _, wsdl_key, _ in _ADGROUPS_GET_NESTED_FIELD_FLAGS:
        assert wsdl_key not in body["params"]


def test_adgroups_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["adgroups", "get", "--help"])

    assert result.exit_code == 0
    for flag, _, _ in _ADGROUPS_GET_NESTED_FIELD_FLAGS:
        assert flag in result.output


@pytest.mark.parametrize(
    "flag,wsdl_key",
    [(flag, key) for flag, key, _ in _ADGROUPS_GET_NESTED_FIELD_FLAGS],
)
def test_adgroups_get_rejects_empty_nested_field_names_csv(flag, wsdl_key):
    result = CliRunner().invoke(
        cli,
        ["adgroups", "get", "--campaign-ids", "1", flag, ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert f"Provide a non-empty comma-separated {wsdl_key} list." in result.output


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_adgroups_delete_rejects_non_positive_id(bad):
    result = _rejected("adgroups", "delete", "--id", bad)
    assert result.exit_code == 2, result.output


def test_adgroups_delete_allows_positive_id():
    body = _dry_run("adgroups", "delete", "--id", "7")
    assert body["params"]["SelectionCriteria"]["Ids"] == [7]


def test_adgroups_add_rejects_zero_campaign_id():
    result = _rejected(
        "adgroups", "add", "--campaign-id", "0", "--name", "G", "--region-ids", "225"
    )
    assert result.exit_code == 2, result.output


def test_adgroups_update_rejects_zero_id():
    result = _rejected("adgroups", "update", "--id", "0", "--name", "N")
    assert result.exit_code == 2, result.output


def test_adgroups_add_batch_from_jsonl(tmp_path):
    rows = [
        {"name": "G1", "campaign-id": 11, "region-ids": "225", "type": "TEXT_AD_GROUP"},
        {
            "name": "G2",
            "campaign-id": 22,
            "region-ids": "225,1",
            "type": "DYNAMIC_TEXT_AD_GROUP",
            "domain-url": "https://e.example",
        },
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "add", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 2
    assert body["chunkSize"] == 100
    assert body["firstChunk"]["method"] == "add"
    groups = body["firstChunk"]["params"]["AdGroups"]
    # Row -> build_adgroup_object yields the same object as the single path.
    assert groups[0] == {"Name": "G1", "CampaignId": 11, "RegionIds": [225]}
    assert groups[1] == {
        "Name": "G2",
        "CampaignId": 22,
        "RegionIds": [225, 1],
        "DynamicTextAdGroup": {"DomainUrl": "https://e.example"},
    }


def test_adgroups_add_batch_inline():
    arr = json.dumps(
        [{"name": "G", "campaign-id": 1, "region-ids": "225", "type": "TEXT_AD_GROUP"}]
    )
    body = _dry_run("adgroups", "add", "--adgroups-json", arr)
    assert body["totalItems"] == 1
    assert body["firstChunk"]["params"]["AdGroups"][0] == {
        "Name": "G",
        "CampaignId": 1,
        "RegionIds": [225],
    }


def test_adgroups_add_batch_chunks_at_100(tmp_path):
    rows = [
        {"name": f"G{i}", "campaign-id": 1, "region-ids": "225"} for i in range(250)
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "add", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 250
    assert len(body["firstChunk"]["params"]["AdGroups"]) == 100


def test_adgroups_add_batch_campaign_default_and_override(tmp_path):
    rows = [
        {"name": "G1", "region-ids": "225"},
        {"name": "G2", "campaign-id": 999, "region-ids": "225"},
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "add", "--campaign-id", "5", "--from-file", path)
    groups = body["firstChunk"]["params"]["AdGroups"]
    assert groups[0]["CampaignId"] == 5
    assert groups[1]["CampaignId"] == 999


def test_adgroups_add_batch_rejects_unknown_field(tmp_path):
    path = _write_jsonl(tmp_path, [{"name": "G", "campaign-id": 1, "foo": "bar"}])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Unknown field 'foo' in ad group row 1" in result.output


def test_adgroups_add_batch_rejects_non_object_row(tmp_path):
    path = _write_jsonl(tmp_path, [[1, 2, 3]])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "expected JSON object" in result.output


def test_adgroups_add_batch_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    result = _rejected("adgroups", "add", "--from-file", str(path))
    assert "Input contains no ad group rows" in result.output


def test_adgroups_add_batch_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(
        '{"name":"G","campaign-id":1,"region-ids":"225"}\nnope\n', encoding="utf-8"
    )
    result = _rejected("adgroups", "add", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_adgroups_add_batch_rejects_missing_name_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"campaign-id": 1, "region-ids": "225"}])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "missing required 'name'" in result.output


def test_adgroups_add_batch_rejects_missing_campaign_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"name": "G", "region-ids": "225"}])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "missing 'campaign-id'" in result.output


def test_adgroups_add_batch_rejects_missing_region_ids_in_row(tmp_path):
    # RegionIds is WSDL minOccurs=1; single mode requires --region-ids, so the
    # batch row must require it too (else a malformed body reaches the live API).
    path = _write_jsonl(tmp_path, [{"name": "G", "campaign-id": 1}])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "missing required 'region-ids'" in result.output


def test_adgroups_add_batch_rejects_incompatible_flag_per_row(tmp_path):
    # --domain-url is not valid for TEXT_AD_GROUP; per-row guard wraps it.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "name": "G",
                "campaign-id": 1,
                "region-ids": "225",
                "type": "TEXT_AD_GROUP",
                "domain-url": "https://e.example",
            }
        ],
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output


def test_adgroups_add_batch_rejects_invalid_type_per_row(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": 1, "region-ids": "225", "type": "NOPE"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "Invalid value for '--type'" in result.output


def test_adgroups_add_batch_rejects_missing_required_subtype_field_per_row(tmp_path):
    # SMART_AD_GROUP requires --feed-id; the per-row guard wraps the message.
    path = _write_jsonl(
        tmp_path,
        [
            {
                "name": "G",
                "campaign-id": 1,
                "region-ids": "225",
                "type": "SMART_AD_GROUP",
            }
        ],
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "feed-id" in result.output


def test_adgroups_add_batch_rejects_non_positive_campaign_id_in_row(tmp_path):
    # IntRange(min=1) must apply per row, same as single --campaign-id.
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": -5, "region-ids": "225"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1 field 'campaign-id'" in result.output
    assert "x>=1" in result.output


def test_adgroups_add_batch_rejects_float_campaign_id_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": 5.9, "region-ids": "225"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1 field 'campaign-id'" in result.output


def test_adgroups_add_batch_rejects_non_scalar_field(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": [1], "region-ids": "225"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1 field 'campaign-id'" in result.output
    assert "expected a scalar" in result.output


def test_adgroups_add_batch_rejects_non_list_multi_value(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "name": "G",
                "campaign-id": 1,
                "region-ids": "225",
                "type": "DYNAMIC_TEXT_AD_GROUP",
                "domain-url": "https://e.example",
                "autotargeting-category": 5,
            }
        ],
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1 field 'autotargeting-category'" in result.output
    assert "array of strings" in result.output


def test_adgroups_add_batch_stringifies_scalar_string_field(tmp_path):
    # A JSON int for the string --name field becomes "123" (CLI-token parity).
    path = _write_jsonl(
        tmp_path, [{"name": 123, "campaign-id": 1, "region-ids": "225"}]
    )
    body = _dry_run("adgroups", "add", "--from-file", path)
    assert body["firstChunk"]["params"]["AdGroups"][0]["Name"] == "123"


def test_adgroups_add_batch_rejects_mutex(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": 1, "region-ids": "225"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path, "--adgroups-json", "[]")
    assert "mutually exclusive" in result.output


def test_adgroups_add_batch_rejects_single_flag_in_batch(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"name": "G", "campaign-id": 1, "region-ids": "225"}]
    )
    result = _rejected("adgroups", "add", "--from-file", path, "--name", "X")
    assert "--name supported only with single-item mode" in result.output


def test_adgroups_add_single_still_requires_name():
    result = _rejected("adgroups", "add", "--campaign-id", "1", "--region-ids", "225")
    assert "Missing option '--name'." in result.output


def test_adgroups_add_single_still_requires_region_ids():
    result = _rejected("adgroups", "add", "--name", "G", "--campaign-id", "1")
    assert "Missing option '--region-ids'." in result.output


def test_adgroups_update_batch_from_jsonl(tmp_path):
    rows = [
        {"id": 5, "name": "New A"},
        {"id": 6, "domain-url": "https://e.example"},
    ]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "update", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 2
    assert body["chunkSize"] == 100
    assert body["firstChunk"]["method"] == "update"
    groups = body["firstChunk"]["params"]["AdGroups"]
    # Row -> build_adgroup_update_object yields the same object as single path.
    assert groups[0] == {"Id": 5, "Name": "New A"}
    assert groups[1] == {
        "Id": 6,
        "DynamicTextAdGroup": {"DomainUrl": "https://e.example"},
    }


def test_adgroups_update_batch_inline():
    arr = json.dumps([{"id": 5, "name": "X"}])
    body = _dry_run("adgroups", "update", "--adgroups-json", arr)
    assert body["totalItems"] == 1
    assert body["firstChunk"]["params"]["AdGroups"][0] == {"Id": 5, "Name": "X"}


def test_adgroups_update_batch_chunks_at_100(tmp_path):
    rows = [{"id": i + 1, "name": f"G{i}"} for i in range(250)]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "update", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 250
    assert len(body["firstChunk"]["params"]["AdGroups"]) == 100


def test_adgroups_update_batch_dynamic_feed_per_row(tmp_path):
    rows = [{"id": 5, "dynamic-feed": True, "autotargeting-category": ["EXACT=YES"]}]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("adgroups", "update", "--from-file", path)
    assert body["firstChunk"]["params"]["AdGroups"][0] == {
        "Id": 5,
        "DynamicTextFeedAdGroup": {
            "AutotargetingCategories": [{"Category": "EXACT", "Value": "YES"}]
        },
    }


def test_adgroups_update_batch_dynamic_feed_false_is_noop(tmp_path):
    # dynamic-feed:false is the flag-absent state; without another field the row
    # is an empty-payload no-op and must be rejected.
    path = _write_jsonl(tmp_path, [{"id": 5, "dynamic-feed": False}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "at least one updatable field" in result.output


def test_adgroups_update_batch_rejects_unknown_field(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "foo": "bar"}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Unknown field 'foo' in ad group update row 1" in result.output


def test_adgroups_update_batch_rejects_non_object_row(tmp_path):
    path = _write_jsonl(tmp_path, [[1, 2, 3]])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "expected JSON object" in result.output


def test_adgroups_update_batch_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n", encoding="utf-8")
    result = _rejected("adgroups", "update", "--from-file", str(path))
    assert "Input contains no ad group rows" in result.output


def test_adgroups_update_batch_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id":5,"name":"X"}\nnope\n', encoding="utf-8")
    result = _rejected("adgroups", "update", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_adgroups_update_batch_rejects_missing_id_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"name": "X"}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "missing required 'id'" in result.output


def test_adgroups_update_batch_rejects_non_positive_id_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": -5, "name": "X"}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1 field 'id'" in result.output
    assert "x>=1" in result.output


def test_adgroups_update_batch_rejects_float_id_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5.9, "name": "X"}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1 field 'id'" in result.output


def test_adgroups_update_batch_rejects_empty_payload_per_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "at least one updatable field" in result.output


def test_adgroups_update_batch_rejects_mixed_subtype_per_row(tmp_path):
    # Mixing two subtype blocks in one row is rejected by the per-row guard.
    path = _write_jsonl(
        tmp_path,
        [{"id": 5, "domain-url": "https://e.example", "ad-title-source": "FEED"}],
    )
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output


def test_adgroups_update_batch_rejects_non_bool_dynamic_feed(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "dynamic-feed": "yes"}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1 field 'dynamic-feed'" in result.output
    assert "boolean" in result.output


def test_adgroups_update_batch_rejects_non_list_multi_value(tmp_path):
    path = _write_jsonl(
        tmp_path, [{"id": 5, "dynamic-feed": True, "autotargeting-category": 5}]
    )
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1 field 'autotargeting-category'" in result.output
    assert "array of strings" in result.output


def test_adgroups_update_batch_rejects_mutex(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "name": "X"}])
    result = _rejected(
        "adgroups", "update", "--from-file", path, "--adgroups-json", "[]"
    )
    assert "mutually exclusive" in result.output


def test_adgroups_update_batch_rejects_single_flag_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "name": "X"}])
    result = _rejected("adgroups", "update", "--from-file", path, "--name", "Y")
    assert "--name supported only with single-item mode" in result.output


def test_adgroups_update_batch_rejects_id_flag_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "name": "X"}])
    result = _rejected("adgroups", "update", "--from-file", path, "--id", "9")
    assert "--id supported only with single-item mode" in result.output


def test_adgroups_update_single_still_requires_id():
    result = _rejected("adgroups", "update", "--name", "X")
    assert "Missing option '--id'." in result.output


def test_adgroups_add_single_rejects_empty_region_ids():
    result = _rejected(
        "adgroups", "add", "--name", "G", "--campaign-id", "1", "--region-ids", ""
    )
    assert "--region-ids must not be empty." in result.output


def test_adgroups_add_single_rejects_whitespace_region_ids():
    result = _rejected(
        "adgroups", "add", "--name", "G", "--campaign-id", "1", "--region-ids", "  "
    )
    assert "--region-ids must not be empty." in result.output


def test_adgroups_add_single_rejects_comma_only_region_ids():
    # parse_ids("") via "," split also collapses to empty -> same rejection.
    result = _rejected(
        "adgroups", "add", "--name", "G", "--campaign-id", "1", "--region-ids", ","
    )
    assert "--region-ids must not be empty." in result.output


def test_adgroups_add_single_rejects_multi_blank_segment_region_ids():
    # ", ," -> several blank segments, none with a real token: still empty.
    result = _rejected(
        "adgroups", "add", "--name", "G", "--campaign-id", "1", "--region-ids", ", ,"
    )
    assert "--region-ids must not be empty." in result.output


def test_adgroups_add_single_rejects_empty_negative_keyword_shared_set_ids():
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "G",
        "--campaign-id",
        "1",
        "--region-ids",
        "225",
        "--negative-keyword-shared-set-ids",
        "",
    )
    assert "--negative-keyword-shared-set-ids must not be empty." in result.output


def test_adgroups_add_single_rejects_empty_feed_category_ids():
    # --feed-id present so the empty-feed-category check is what fires (not the
    # "--feed-id is required" guard).
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "G",
        "--campaign-id",
        "1",
        "--region-ids",
        "225",
        "--type",
        "TEXT_AD_GROUP",
        "--feed-id",
        "7",
        "--feed-category-ids",
        "",
    )
    assert "--feed-category-ids must not be empty." in result.output


def test_adgroups_update_single_rejects_empty_region_ids():
    # Pair with a valid --name so the empty-payload guard does not fire first.
    result = _rejected(
        "adgroups", "update", "--id", "5", "--name", "X", "--region-ids", ""
    )
    assert "--region-ids must not be empty." in result.output


def test_adgroups_update_single_rejects_empty_negative_keyword_shared_set_ids():
    result = _rejected(
        "adgroups",
        "update",
        "--id",
        "5",
        "--name",
        "X",
        "--negative-keyword-shared-set-ids",
        "",
    )
    assert "--negative-keyword-shared-set-ids must not be empty." in result.output


def test_adgroups_update_single_rejects_empty_feed_category_ids():
    result = _rejected(
        "adgroups", "update", "--id", "5", "--feed-id", "7", "--feed-category-ids", ""
    )
    assert "--feed-category-ids must not be empty." in result.output


def test_adgroups_add_batch_rejects_empty_region_ids_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"name": "G", "campaign-id": 1, "region-ids": ""}])
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "--region-ids must not be empty." in result.output


def test_adgroups_add_batch_rejects_empty_negative_keyword_shared_set_ids_in_row(
    tmp_path,
):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "name": "G",
                "campaign-id": 1,
                "region-ids": "225",
                "negative-keyword-shared-set-ids": "",
            }
        ],
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "--negative-keyword-shared-set-ids must not be empty." in result.output


def test_adgroups_add_batch_rejects_empty_feed_category_ids_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {
                "name": "G",
                "campaign-id": 1,
                "region-ids": "225",
                "type": "TEXT_AD_GROUP",
                "feed-id": 7,
                "feed-category-ids": "",
            }
        ],
    )
    result = _rejected("adgroups", "add", "--from-file", path)
    assert "Ad group row 1" in result.output
    assert "--feed-category-ids must not be empty." in result.output


def test_adgroups_update_batch_rejects_empty_region_ids_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"id": 5, "name": "X", "region-ids": ""}])
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "--region-ids must not be empty." in result.output


def test_adgroups_update_batch_rejects_empty_negative_keyword_shared_set_ids_in_row(
    tmp_path,
):
    path = _write_jsonl(
        tmp_path,
        [{"id": 5, "name": "X", "negative-keyword-shared-set-ids": ""}],
    )
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "--negative-keyword-shared-set-ids must not be empty." in result.output


def test_adgroups_update_batch_rejects_empty_feed_category_ids_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"id": 5, "feed-id": 7, "feed-category-ids": ""}],
    )
    result = _rejected("adgroups", "update", "--from-file", path)
    assert "Ad group update row 1" in result.output
    assert "--feed-category-ids must not be empty." in result.output


def test_adgroups_add_valid_region_ids_still_passes_through():
    # Guard against over-eager rejection: a non-empty CSV builds the field as
    # before (byte-identical to pre-#570 behavior).
    body = _dry_run(
        "adgroups", "add", "--name", "G", "--campaign-id", "1", "--region-ids", "225"
    )
    assert body["params"]["AdGroups"][0]["RegionIds"] == [225]

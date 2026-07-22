"""Dry-run payload tests for targeting services: ``audiencetargets``,
``dynamictextadtargets``, ``dynamicfeedadtargets``, ``smartadtargets``
and ``retargetinglists``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _ids_csv, _read_dry_run, _rejected


def test_retargeting_get_with_ids_builds_selection_criteria():
    body = _read_dry_run("retargeting", "get", "--ids", "1,2")
    assert body["params"]["SelectionCriteria"] == {"Ids": [1, 2]}


def test_adgroups_add_unified_requires_offer_retargeting():
    """Issue #283: UnifiedAdGroupAdd.OfferRetargeting is required."""
    result = _rejected(
        "adgroups",
        "add",
        "--name",
        "Unified Group",
        "--campaign-id",
        "111",
        "--type",
        "UNIFIED_AD_GROUP",
        "--region-ids",
        "225",
    )
    assert "--offer-retargeting is required for UNIFIED_AD_GROUP" in result.output


def test_retargeting_add_keeps_list_type():
    # NB: ``Type`` here is the *list category* and IS a real top-level
    # API field, unlike the --type hint on ads/adgroups/smartadtargets.
    # The only two valid values per Yandex Direct docs are ``RETARGETING``
    # and ``AUDIENCE`` (verified against
    # https://yandex.ru/dev/direct/doc/ref-v5/retargetinglists/add.html).
    # This test previously asserted ``AUDIENCE_SEGMENT``, which is not
    # a real enum value — the drift was fixed together with the
    # click.Choice validation added in axisrow/direct-cli#25.
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--type",
        "AUDIENCE",
        "--rule",
        "ALL:12345:30|67890:7",
    )
    assert body["method"] == "add"
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg == {
        "Name": "List A",
        "Type": "AUDIENCE",
        "Rules": [
            {
                "Operator": "ALL",
                "Arguments": [
                    {"ExternalId": 12345, "MembershipLifeSpan": 30},
                    {"ExternalId": 67890, "MembershipLifeSpan": 7},
                ],
            }
        ],
    }


def test_retargeting_add_description_payload():
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "High intent users",
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == "High intent users"


def test_retargeting_add_empty_description_payload():
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "",
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == ""


def test_retargeting_add_description_accepts_4096_chars():
    description = "x" * 4096
    body = _dry_run(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        description,
        "--rule",
        "ALL:12345:30",
    )
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Description"] == description


def test_retargeting_add_description_rejects_4097_chars():
    result = _rejected(
        "retargeting",
        "add",
        "--name",
        "List A",
        "--description",
        "x" * 4097,
        "--rule",
        "ALL:12345:30",
    )
    assert "--description must be at most 4096 characters" in result.output


def test_retargeting_add_default_type_is_retargeting():
    """Without ``--type`` the CLI defaults to the API's default RETARGETING.

    Regression guard for axisrow/direct-cli#25 — before the fix ``--type``
    was required=True with no validation. Now it's optional and
    defaults to the same value the API picks when Type is omitted.
    """
    body = _dry_run("retargeting", "add", "--name", "List B", "--rule", "ALL:12345")
    rtg = body["params"]["RetargetingLists"][0]
    assert rtg["Type"] == "RETARGETING"


def test_retargeting_add_unknown_type_is_rejected_by_choice():
    """``click.Choice`` rejects typos / non-enum values up front.

    Regression guard for axisrow/direct-cli#25 — before the fix a
    typo like ``--type AUDIENCE_SEGMENT`` was forwarded verbatim to
    the API, which rejected it with a vague error.
    """
    result = CliRunner().invoke(
        cli,
        [
            "retargeting",
            "add",
            "--name",
            "List bad",
            "--type",
            "AUDIENCE_SEGMENT",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "AUDIENCE_SEGMENT" in combined or "retargeting" in combined.lower()


def test_audiencetargets_add_context_bid():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--retargeting-list-id",
        "200",
        "--bid",
        "12000000",
        "--priority",
        "high",
    )
    assert body["method"] == "add"
    target = body["params"]["AudienceTargets"][0]
    assert target == {
        "AdGroupId": 100,
        "RetargetingListId": 200,
        "ContextBid": 12000000,
        "StrategyPriority": "HIGH",
    }


def test_audiencetargets_add_rejects_invalid_priority():
    result = _rejected(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--retargeting-list-id",
        "200",
        "--priority",
        "MAX",
    )

    assert "Invalid value for '--priority'" in result.output


def test_audiencetargets_add_accepts_interest_id():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "100",
        "--interest-id",
        "300",
    )
    assert body["params"]["AudienceTargets"][0] == {
        "AdGroupId": 100,
        "InterestId": 300,
    }


def test_audiencetargets_set_bids_uses_bids_array():
    body = _dry_run(
        "audiencetargets",
        "set-bids",
        "--id",
        "101",
        "--context-bid",
        "7000000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {
        "Id": 101,
        "ContextBid": 7000000,
        "StrategyPriority": "LOW",
    }


def test_dynamicads_add_payload_uses_webpages_key():
    body = _dry_run(
        "dynamicads",
        "add",
        "--adgroup-id",
        "33",
        "--name",
        "Webpage A",
        "--condition",
        "URL:CONTAINS_ANY:foo|bar",
        "--condition",
        "PAGE_CONTENT:CONTAINS:baz",
        "--bid",
        "3000000",
        "--context-bid",
        "2000000",
        "--priority",
        "HIGH",
    )
    assert body["method"] == "add"
    webpage = body["params"]["Webpages"][0]
    assert webpage["AdGroupId"] == 33
    assert webpage["Name"] == "Webpage A"
    assert webpage["Conditions"] == [
        {"Operand": "URL", "Operator": "CONTAINS_ANY", "Arguments": ["foo", "bar"]},
        {"Operand": "PAGE_CONTENT", "Operator": "CONTAINS", "Arguments": ["baz"]},
    ]
    assert webpage["Bid"] == 3000000
    assert webpage["ContextBid"] == 2000000
    assert webpage["StrategyPriority"] == "HIGH"


def test_dynamicads_set_bids_uses_bids_array():
    body = _dry_run(
        "dynamicads",
        "set-bids",
        "--id",
        "44",
        "--bid",
        "3000000",
        "--context-bid",
        "2000000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    item = body["params"]["Bids"][0]
    assert item == {
        "Id": 44,
        "Bid": 3000000,
        "ContextBid": 2000000,
        "StrategyPriority": "LOW",
    }


def test_smartadtargets_add_uses_typed_flags():
    body = _dry_run(
        "smartadtargets",
        "add",
        "--adgroup-id",
        "55",
        "--name",
        "Audience A",
        "--audience",
        "ALL_SEGMENTS",
        "--condition",
        "CATEGORY_ID:EQUALS:42",
        "--average-cpc",
        "3000000",
        "--average-cpa",
        "4000000",
        "--priority",
        "HIGH",
        "--available-items-only",
        "YES",
    )
    assert body["method"] == "add"
    target = body["params"]["SmartAdTargets"][0]
    assert target == {
        "AdGroupId": 55,
        "Name": "Audience A",
        "Audience": "ALL_SEGMENTS",
        "Conditions": {
            "Items": [
                {
                    "Operand": "CATEGORY_ID",
                    "Operator": "EQUALS",
                    "Arguments": ["42"],
                }
            ]
        },
        "AverageCpc": 3000000,
        "AverageCpa": 4000000,
        "StrategyPriority": "HIGH",
        "AvailableItemsOnly": "YES",
    }


def test_smartadtargets_update_uses_typed_flags():
    body = _dry_run(
        "smartadtargets",
        "update",
        "--id",
        "66",
        "--name",
        "Audience B",
        "--audience",
        "ALL_SEGMENTS",
        "--condition",
        "CATEGORY_ID:EQUALS:42",
        "--average-cpc",
        "3000000",
        "--average-cpa",
        "4000000",
        "--priority",
        "HIGH",
        "--available-items-only",
        "NO",
    )
    target = body["params"]["SmartAdTargets"][0]
    assert target == {
        "Id": 66,
        "Name": "Audience B",
        "Audience": "ALL_SEGMENTS",
        "Conditions": {
            "Items": [
                {
                    "Operand": "CATEGORY_ID",
                    "Operator": "EQUALS",
                    "Arguments": ["42"],
                }
            ]
        },
        "AverageCpc": 3000000,
        "AverageCpa": 4000000,
        "StrategyPriority": "HIGH",
        "AvailableItemsOnly": "NO",
    }


def test_smartadtargets_update_without_fields_errors():
    result = CliRunner().invoke(
        cli,
        [
            "smartadtargets",
            "update",
            "--id",
            "66",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    combined = (result.output or "") + (
        str(result.exception) if result.exception else ""
    )
    assert "Provide at least one field to update" in combined


def test_audiencetargets_get_requires_filter_message_names_workaround():
    # Issue #554: the live API hard-rejects an empty SelectionCriteria for
    # audiencetargets (8000 with no criteria, 4001 with {}), so whole-account
    # paging is impossible. The guard message must say so and point at the
    # campaigns-get → batched campaign-ids workaround.
    result = CliRunner().invoke(
        cli,
        ["audiencetargets", "get", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "whole-account paging is not available" in result.output
    assert "campaigns get" in result.output


def test_dynamicads_get_rejects_over_2_campaign_ids():
    result = CliRunner().invoke(
        cli,
        ["dynamicads", "get", "--campaign-ids", "1,2,3", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "more than 2 elements" in result.output
    assert "dynamicads get" in result.output


def test_dynamicads_get_allows_exactly_2_campaign_ids():
    body = _read_dry_run("dynamicads", "get", "--campaign-ids", "1,2")
    assert body["params"]["SelectionCriteria"]["CampaignIds"] == [1, 2]


def test_dynamicads_get_allows_many_adgroup_ids():
    # Only CampaignIds is capped at 2; AdGroupIds is unbounded on the live API.
    body = _read_dry_run("dynamicads", "get", "--adgroup-ids", _ids_csv(50))
    assert len(body["params"]["SelectionCriteria"]["AdGroupIds"]) == 50


def test_smartadtargets_get_rejects_over_2_campaign_ids():
    result = CliRunner().invoke(
        cli,
        ["smartadtargets", "get", "--campaign-ids", "1,2,3", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2, result.output
    assert "more than 2 elements" in result.output
    assert "smartadtargets get" in result.output


def test_smartadtargets_get_allows_exactly_2_campaign_ids():
    body = _read_dry_run("smartadtargets", "get", "--campaign-ids", "1,2")
    assert body["params"]["SelectionCriteria"]["CampaignIds"] == [1, 2]


def test_smartadtargets_get_allows_many_adgroup_ids():
    body = _read_dry_run("smartadtargets", "get", "--adgroup-ids", _ids_csv(50))
    assert len(body["params"]["SelectionCriteria"]["AdGroupIds"]) == 50


def test_retargeting_update_payload_uses_lists_array():
    body = _dry_run(
        "retargeting",
        "update",
        "--id",
        "55",
        "--name",
        "Renamed",
        "--rule",
        "ANY:12345:30",
    )
    assert body["method"] == "update"
    assert body["params"]["RetargetingLists"][0] == {
        "Id": 55,
        "Name": "Renamed",
        "Rules": [
            {
                "Operator": "ANY",
                "Arguments": [{"ExternalId": 12345, "MembershipLifeSpan": 30}],
            }
        ],
    }


def test_retargeting_update_description_payload():
    body = _dry_run(
        "retargeting",
        "update",
        "--id",
        "55",
        "--description",
        "Updated note",
    )
    assert body["params"]["RetargetingLists"][0] == {
        "Id": 55,
        "Description": "Updated note",
    }


def test_retargeting_update_empty_description_payload():
    body = _dry_run("retargeting", "update", "--id", "55", "--description", "")
    assert body["params"]["RetargetingLists"][0] == {"Id": 55, "Description": ""}


def test_retargeting_update_description_rejects_4097_chars():
    result = _rejected(
        "retargeting",
        "update",
        "--id",
        "55",
        "--description",
        "x" * 4097,
    )
    assert "--description must be at most 4096 characters" in result.output


def test_smartadtargets_set_bids_payload_uses_average_cpc():
    body = _dry_run(
        "smartadtargets",
        "set-bids",
        "--id",
        "11",
        "--average-cpc",
        "1500000",
        "--average-cpa",
        "2500000",
        "--priority",
        "LOW",
    )
    assert body["method"] == "setBids"
    assert body["params"]["Bids"][0] == {
        "Id": 11,
        "AverageCpc": 1500000,
        "AverageCpa": 2500000,
        "StrategyPriority": "LOW",
    }


def test_smartadtargets_delete_dry_run_payload():
    body = _dry_run("smartadtargets", "delete", "--id", "88")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [88]}},
    }


def test_dynamicfeedadtargets_add_payload():
    body = _dry_run(
        "dynamicfeedadtargets",
        "add",
        "--adgroup-id",
        "123",
        "--name",
        "Test Target",
        "--condition",
        "CATEGORY:EQUALS_ANY:shoes|boots",
        "--bid",
        "1500000",
    )
    assert body["method"] == "add"
    target = body["params"]["DynamicFeedAdTargets"][0]
    assert target["AdGroupId"] == 123
    assert target["Name"] == "Test Target"
    assert target["Conditions"] == {
        "Items": [
            {
                "Operand": "CATEGORY",
                "Operator": "EQUALS_ANY",
                "Arguments": ["shoes", "boots"],
            }
        ]
    }
    assert target["Bid"] == 1500000


def test_dynamicfeedadtargets_delete_payload():
    body = _dry_run("dynamicfeedadtargets", "delete", "--id", "42")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_suspend_payload():
    body = _dry_run("dynamicfeedadtargets", "suspend", "--id", "42")
    assert body == {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_resume_payload():
    body = _dry_run("dynamicfeedadtargets", "resume", "--id", "42")
    assert body == {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_dynamicfeedadtargets_set_bids_payload():
    body = _dry_run(
        "dynamicfeedadtargets",
        "set-bids",
        "--id",
        "55",
        "--bid",
        "2000000",
    )
    assert body["method"] == "setBids"
    bid = body["params"]["Bids"][0]
    assert bid["Id"] == 55
    assert bid["Bid"] == 2000000

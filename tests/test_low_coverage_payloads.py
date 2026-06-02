"""Focused offline payload tests for command modules with weaker coverage."""

import json
from unittest.mock import Mock, patch

from click.testing import CliRunner

from direct_cli.cli import cli


class FakeResponse:
    data = {"result": {"ok": True}}

    def __call__(self):
        return self

    def extract(self):
        return self.data

    def iter_items(self):
        return iter([])


def _mock_service_command(module_path, service_name, args):
    service = Mock()
    service.post.return_value = FakeResponse()
    client = Mock()
    getattr(client, service_name).return_value = service

    with patch("direct_cli.cli.get_active_profile", return_value=None):
        with patch(f"{module_path}.create_client", return_value=client):
            result = CliRunner().invoke(cli, args)

    assert result.exit_code == 0, result.output
    service.post.assert_called_once()
    return service.post.call_args.kwargs["data"]


def _dry_run(*args):
    result = CliRunner().invoke(
        cli,
        list(args) + ["--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _failing_run(*args):
    return CliRunner().invoke(
        cli,
        list(args),
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )


def test_changes_check_builds_canonical_payload():
    body = _mock_service_command(
        "direct_cli.commands.changes",
        "changes",
        [
            "changes",
            "check",
            "--campaign-ids",
            "1,2",
            "--timestamp",
            "2026-04-14T00:00:00Z",
            "--fields",
            "CampaignIds,CampaignsStat",
        ],
    )

    assert body == {
        "method": "check",
        "params": {
            "CampaignIds": [1, 2],
            "Timestamp": "2026-04-14T00:00:00Z",
            "FieldNames": ["CampaignIds", "CampaignsStat"],
        },
    }


def test_changes_check_campaigns_builds_canonical_payload():
    body = _mock_service_command(
        "direct_cli.commands.changes",
        "changes",
        [
            "changes",
            "check-campaigns",
            "--timestamp",
            "2026-04-14T00:00:00Z",
        ],
    )

    assert body == {
        "method": "checkCampaigns",
        "params": {"Timestamp": "2026-04-14T00:00:00Z"},
    }


def test_changes_check_dictionaries_builds_canonical_payload():
    body = _mock_service_command(
        "direct_cli.commands.changes",
        "changes",
        ["changes", "check-dictionaries"],
    )

    assert body == {"method": "checkDictionaries", "params": {}}


def test_changes_rejects_bare_datetime():
    result = _failing_run(
        "changes",
        "check-campaigns",
        "--timestamp",
        "2026-04-14T00:00:00",
    )

    assert result.exit_code != 0
    assert "Expected: YYYY-MM-DDTHH:MM:SSZ" in result.output


def test_changes_rejects_malformed_datetime():
    result = _failing_run(
        "changes",
        "check-campaigns",
        "--timestamp",
        "2026-04-14 00:00:00Z",
    )

    assert result.exit_code != 0
    assert "Expected: YYYY-MM-DDTHH:MM:SSZ" in result.output


def test_keywordsresearch_has_search_volume_builds_typed_payload():
    body = _mock_service_command(
        "direct_cli.commands.keywordsresearch",
        "keywordsresearch",
        [
            "keywordsresearch",
            "has-search-volume",
            "--keywords",
            "buy laptop,buy desktop",
            "--region-ids",
            "213,225",
            "--fields",
            "Keyword,HasSearchVolume",
        ],
    )

    assert body == {
        "method": "hasSearchVolume",
        "params": {
            "SelectionCriteria": {
                "RegionIds": [213, 225],
                "Keywords": ["buy laptop", "buy desktop"],
            },
            "FieldNames": ["Keyword", "HasSearchVolume"],
        },
    }


def test_keywordsresearch_deduplicate_builds_typed_payload():
    body = _mock_service_command(
        "direct_cli.commands.keywordsresearch",
        "keywordsresearch",
        ["keywordsresearch", "deduplicate", "--keywords", "foo, bar"],
    )

    assert body == {
        "method": "deduplicate",
        "params": {"Keywords": [{"Keyword": "foo"}, {"Keyword": "bar"}]},
    }


def test_b2b_types_uppercased_and_empties_dropped_adgroups():
    """#497 B2b: adgroups get --types now trims, drops empties, uppercases."""
    body = _dry_run(
        "adgroups", "get", "--campaign-ids", "1", "--types", "text_ad_group, ,"
    )
    assert body["params"]["SelectionCriteria"]["Types"] == ["TEXT_AD_GROUP"]


def test_b2b_types_uppercased_and_empties_dropped_adextensions():
    """#497 B2b: adextensions get --types now trims, drops empties, uppercases."""
    body = _dry_run("adextensions", "get", "--types", "callout,,structured_snippet")
    assert body["params"]["SelectionCriteria"]["Types"] == [
        "CALLOUT",
        "STRUCTURED_SNIPPET",
    ]


def test_b2b_types_uppercased_and_empties_dropped_retargeting():
    """#497 B2b: retargeting get --types now trims, drops empties, uppercases.

    retargeting get has no --dry-run, so capture the request via a mocked client.
    """
    body = _mock_service_command(
        "direct_cli.commands.retargeting",
        "retargeting",
        ["retargeting", "get", "--types", "marketing_list, ,audience"],
    )
    assert body["params"]["SelectionCriteria"]["Types"] == [
        "MARKETING_LIST",
        "AUDIENCE",
    ]


def test_b2b_strategies_types_preserve_mixedcase_drop_empties():
    """#497 B2b: strategy types are MixedCase enums — trimmed but NOT uppercased."""
    body = _dry_run("strategies", "get", "--types", "AverageCpc, ,WbMaximumClicks")
    assert body["params"]["SelectionCriteria"]["Types"] == [
        "AverageCpc",
        "WbMaximumClicks",
    ]


def test_b2b_negativekeywordsharedsets_add_drops_empty_keywords():
    """#497 B2b: NegativeKeywords drops empty items from dirty input."""
    body = _dry_run(
        "negativekeywordsharedsets", "add", "--name", "X", "--keywords", "cheap,,free"
    )
    sets = body["params"]["NegativeKeywordSharedSets"]
    assert sets[0]["NegativeKeywords"] == ["cheap", "free"]


def test_b2b_keywordsresearch_deduplicate_drops_empty_keywords():
    """#497 B2b: deduplicate drops empty keyword items."""
    body = _mock_service_command(
        "direct_cli.commands.keywordsresearch",
        "keywordsresearch",
        ["keywordsresearch", "deduplicate", "--keywords", "a,,b"],
    )
    assert body["params"]["Keywords"] == [{"Keyword": "a"}, {"Keyword": "b"}]


def test_b2b_dictionaries_get_drops_empty_names():
    """#497 B2b: dictionary names trim + drop empties."""
    body = _mock_service_command(
        "direct_cli.commands.dictionaries",
        "dictionaries",
        ["dictionaries", "get", "--names", "Currencies,,GeoRegions"],
    )
    assert body["params"]["DictionaryNames"] == ["Currencies", "GeoRegions"]


def test_strategies_add_typed_fields_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Shared Clicks",
        "--type",
        "WbMaximumClicks",
        "--weekly-spend-limit",
        "1000000000",
        "--bid-ceiling",
        "30000000",
        "--counter-ids",
        "1,2",
        "--priority-goal",
        "123:4560000",
    )

    strategy = body["params"]["Strategies"][0]
    assert body["method"] == "add"
    assert strategy["WbMaximumClicks"] == {
        "BidCeiling": 30000000,
        "WeeklySpendLimit": 1000000000,
    }
    assert strategy["CounterIds"] == {"Items": [1, 2]}
    assert strategy["PriorityGoals"] == {"Items": [{"GoalId": 123, "Value": 4560000}]}


def test_strategies_rejects_legacy_json_blob_flags():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Shared Clicks",
        "--type",
        "WbMaximumClicks",
        "--params",
        '{"SpendLimit":1000000000}',
    )

    assert result.exit_code != 0
    assert "No such option" in result.output
    assert "--params" in result.output


def test_strategies_add_all_typed_strategy_fields_payload():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Average CPA",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
        "--weekly-spend-limit",
        "70000000",
        "--bid-ceiling",
        "8000000",
        "--attribution-model",
        "LYDC",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["AverageCpa"] == {
        "AverageCpa": 4000000,
        "GoalId": 123,
        "WeeklySpendLimit": 70000000,
        "BidCeiling": 8000000,
    }
    assert strategy["AttributionModel"] == "LYDC"


def test_strategies_add_average_crr_payload_uses_api_field_names():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Average CRR",
        "--type",
        "AverageCrr",
        "--average-crr",
        "25",
        "--goal-id",
        "123",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["AverageCrr"] == {"Crr": 25, "GoalId": 123}


def test_strategies_add_average_crr_requires_goal_id():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Average CRR",
        "--type",
        "AverageCrr",
        "--average-crr",
        "25",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Provide --goal-id for this strategy type" in result.output


def test_strategies_add_average_cpa_payload_includes_goal_id():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Average CPA",
        "--type",
        "AverageCpa",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["AverageCpa"] == {"AverageCpa": 4000000, "GoalId": 123}


def test_strategies_add_pay_for_conversion_payload_uses_cpa_field():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Pay for conversion",
        "--type",
        "PayForConversion",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "123",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["PayForConversion"] == {"Cpa": 4000000, "GoalId": 123}


def test_strategies_update_pay_for_conversion_payload_uses_cpa_field():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "PayForConversion",
        "--average-cpa",
        "4000000",
        "--goal-id",
        "456",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["PayForConversion"] == {"Cpa": 4000000, "GoalId": 456}


def test_strategies_update_average_crr_payload_uses_api_field_names():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "AverageCrr",
        "--average-crr",
        "30",
        "--goal-id",
        "456",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["AverageCrr"] == {"Crr": 30, "GoalId": 456}


def test_strategies_add_average_cpc_per_filter_payload_uses_filter_field():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "Per-filter CPC",
        "--type",
        "AverageCpcPerFilter",
        "--average-cpc",
        "1000000",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["AverageCpcPerFilter"] == {"FilterAverageCpc": 1000000}


def test_strategies_add_pay_for_conversion_crr_payload_uses_crr_field():
    body = _dry_run(
        "strategies",
        "add",
        "--name",
        "PFC CRR",
        "--type",
        "PayForConversionCrr",
        "--average-crr",
        "30",
        "--goal-id",
        "123",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy["PayForConversionCrr"] == {"Crr": 30, "GoalId": 123}


def test_strategies_add_multi_goal_rejects_average_cpa():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Multi-goal",
        "--type",
        "AverageCpaMultipleGoals",
        "--average-cpa",
        "1000000",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert (
        "--average-cpa is not valid for --type AverageCpaMultipleGoals" in result.output
    )


def test_strategies_add_wb_maximum_clicks_rejects_unknown_strategy_fields():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "Shared Clicks",
        "--type",
        "WbMaximumClicks",
        "--spend-limit",
        "1000000000",
        "--average-cpc",
        "30000000",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--spend-limit" in result.output
    assert "--average-cpc" in result.output
    assert "WbMaximumClicks" in result.output


def test_strategies_update_multi_goal_rejects_goal_id():
    result = _failing_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "PayForConversionMultipleGoals",
        "--goal-id",
        "123",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert (
        "--goal-id is not valid for --type PayForConversionMultipleGoals"
        in result.output
    )


def test_strategies_add_pay_for_conversion_multi_goal_requires_goal_id():
    result = _failing_run(
        "strategies",
        "add",
        "--name",
        "PFC Multi-goal",
        "--type",
        "PayForConversionMultipleGoals",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Provide --goal-id" in result.output


def test_strategies_update_typed_metadata_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "WbMaximumClicks",
        "--weekly-spend-limit",
        "35000000",
        "--counter-ids",
        "10,20",
        "--priority-goal",
        "123:4560000",
        "--attribution-model",
        "LC",
    )

    strategy = body["params"]["Strategies"][0]
    assert strategy == {
        "Id": 42,
        "WbMaximumClicks": {"WeeklySpendLimit": 35000000},
        "CounterIds": {"Items": [10, 20]},
        "PriorityGoals": {"Items": [{"GoalId": 123, "Value": 4560000}]},
        "AttributionModel": "LC",
    }


def test_strategies_rejects_malformed_priority_goal():
    missing_separator = _failing_run(
        "strategies",
        "add",
        "--name",
        "Broken",
        "--type",
        "WbMaximumClicks",
        "--priority-goal",
        "123",
        "--dry-run",
    )
    non_numeric = _failing_run(
        "strategies",
        "add",
        "--name",
        "Broken",
        "--type",
        "WbMaximumClicks",
        "--priority-goal",
        "abc:xyz",
        "--dry-run",
    )

    assert missing_separator.exit_code != 0
    assert "Expected GOAL_ID:VALUE" in missing_separator.output
    assert non_numeric.exit_code != 0
    assert "must be integers" in non_numeric.output


def test_dynamicads_get_builds_typed_filter_payload():
    body = _dry_run(
        "dynamicads",
        "get",
        "--ids",
        "1,2",
        "--adgroup-ids",
        "3,4",
        "--states",
        "on,suspended",
        "--limit",
        "50",
        "--fields",
        "Id,Name,State",
    )

    assert body == {
        "method": "get",
        "params": {
            "SelectionCriteria": {
                "Ids": [1, 2],
                "AdGroupIds": [3, 4],
                "States": ["ON", "SUSPENDED"],
            },
            "FieldNames": ["Id", "Name", "State"],
            "Page": {"Limit": 50},
        },
    }


def test_dynamicads_add_without_condition_omits_conditions_field():
    """WSDL DynamicTextAdTargetAddItem.Conditions is minOccurs=0.

    Issue #198 H7 — the CLI used to over-constrain by requiring
    ``--condition``. The CLI now mirrors the WSDL and omits the
    ``Conditions`` field when no condition is provided.
    """
    body = _dry_run(
        "dynamicads",
        "add",
        "--adgroup-id",
        "1",
        "--name",
        "Webpage",
    )

    webpage = body["params"]["Webpages"][0]
    assert "Conditions" not in webpage
    assert webpage["AdGroupId"] == 1
    assert webpage["Name"] == "Webpage"


def test_dynamicads_lifecycle_payloads_use_id_selection_criteria():
    for command in ["delete", "suspend", "resume"]:
        body = _dry_run("dynamicads", command, "--id", "42")
        assert body == {
            "method": command,
            "params": {"SelectionCriteria": {"Ids": [42]}},
        }


def test_dynamicads_set_bids_accepts_adgroup_and_campaign_selectors():
    by_adgroup = _dry_run(
        "dynamicads",
        "set-bids",
        "--adgroup-id",
        "7",
        "--context-bid",
        "2000000",
        "--priority",
        "HIGH",
    )
    by_campaign = _dry_run(
        "dynamicads",
        "set-bids",
        "--campaign-id",
        "8",
        "--bid",
        "3000000",
    )

    assert by_adgroup["params"]["Bids"] == [
        {"AdGroupId": 7, "ContextBid": 2000000, "StrategyPriority": "HIGH"}
    ]
    assert by_campaign["params"]["Bids"] == [{"CampaignId": 8, "Bid": 3000000}]


def test_dynamicfeedadtargets_get_requires_typed_filter():
    result = _failing_run("dynamicfeedadtargets", "get", "--dry-run")

    assert result.exit_code != 0
    assert "Provide at least one typed filter" in result.output


def test_dynamicfeedadtargets_get_builds_typed_filter_payload():
    body = _dry_run(
        "dynamicfeedadtargets",
        "get",
        "--ids",
        "1,2",
        "--adgroup-ids",
        "3",
        "--campaign-ids",
        "4",
        "--states",
        "on,off",
        "--limit",
        "25",
    )

    assert body["method"] == "get"
    assert body["params"]["SelectionCriteria"] == {
        "Ids": [1, 2],
        "AdGroupIds": [3],
        "CampaignIds": [4],
        "States": ["ON", "OFF"],
    }
    assert body["params"]["Page"] == {"Limit": 25}


def test_dynamicfeedadtargets_add_without_conditions_omits_conditions():
    body = _dry_run(
        "dynamicfeedadtargets",
        "add",
        "--adgroup-id",
        "33",
        "--name",
        "Feed target",
        "--bid",
        "5000000",
    )

    target = body["params"]["DynamicFeedAdTargets"][0]
    assert target == {"AdGroupId": 33, "Name": "Feed target", "Bid": 5000000}
    assert "Conditions" not in target


def test_dynamicfeedadtargets_add_normalizes_available_items_only():
    body = _dry_run(
        "dynamicfeedadtargets",
        "add",
        "--adgroup-id",
        "33",
        "--name",
        "Feed target",
        "--condition",
        "CATEGORY:EQUALS:shoes",
        "--available-items-only",
        "no",
    )

    target = body["params"]["DynamicFeedAdTargets"][0]
    assert target["AvailableItemsOnly"] == "NO"
    assert target["Conditions"] == {
        "Items": [{"Operand": "CATEGORY", "Operator": "EQUALS", "Arguments": ["shoes"]}]
    }


def test_audiencetargets_add_requires_target_kind():
    result = _failing_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "1",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert (
        "Provide at least one of --retargeting-list-id or --interest-id"
        in result.output
    )


def test_audiencetargets_add_accepts_both_target_kinds():
    body = _dry_run(
        "audiencetargets",
        "add",
        "--adgroup-id",
        "10",
        "--retargeting-list-id",
        "20",
        "--interest-id",
        "30",
        "--bid",
        "4000000",
        "--priority",
        "LOW",
    )

    assert body["params"]["AudienceTargets"] == [
        {
            "AdGroupId": 10,
            "RetargetingListId": 20,
            "InterestId": 30,
            "ContextBid": 4000000,
            "StrategyPriority": "LOW",
        }
    ]


def test_audiencetargets_get_builds_typed_filter_payload():
    body = _dry_run(
        "audiencetargets",
        "get",
        "--ids",
        "1",
        "--campaign-ids",
        "2",
        "--states",
        "on",
        "--limit",
        "15",
        "--fields",
        "Id,State",
    )

    assert body == {
        "method": "get",
        "params": {
            "SelectionCriteria": {
                "Ids": [1],
                "CampaignIds": [2],
                "States": ["ON"],
            },
            "FieldNames": ["Id", "State"],
            "Page": {"Limit": 15},
        },
    }


def test_audiencetargets_lifecycle_payloads_use_id_selection_criteria():
    for command in ["delete", "suspend", "resume"]:
        body = _dry_run("audiencetargets", command, "--id", "42")
        assert body == {
            "method": command,
            "params": {"SelectionCriteria": {"Ids": [42]}},
        }


def test_audiencetargets_set_bids_requires_selector_and_bid_fields():
    no_selector = _failing_run(
        "audiencetargets",
        "set-bids",
        "--context-bid",
        "1000000",
        "--dry-run",
    )
    no_bid = _failing_run("audiencetargets", "set-bids", "--id", "42", "--dry-run")

    assert no_selector.exit_code != 0
    assert "Provide a target selector" in no_selector.output
    assert no_bid.exit_code != 0
    assert "Provide at least one bid field" in no_bid.output


def test_dynamicads_set_bids_requires_selector_and_bid_fields():
    no_selector = _failing_run(
        "dynamicads",
        "set-bids",
        "--bid",
        "1000000",
        "--dry-run",
    )
    no_bid = _failing_run("dynamicads", "set-bids", "--id", "42", "--dry-run")

    assert no_selector.exit_code != 0
    assert "Provide a target selector" in no_selector.output
    assert no_bid.exit_code != 0
    assert "Provide at least one bid field" in no_bid.output


def test_dynamicfeedadtargets_set_bids_requires_selector_and_bid_fields():
    no_selector = _failing_run(
        "dynamicfeedadtargets",
        "set-bids",
        "--bid",
        "1000000",
        "--dry-run",
    )
    no_bid = _failing_run("dynamicfeedadtargets", "set-bids", "--id", "42", "--dry-run")

    assert no_selector.exit_code != 0
    assert "Provide a target selector" in no_selector.output
    assert no_bid.exit_code != 0
    assert "Provide at least one bid" in no_bid.output


def test_ads_get_rejects_status_and_statuses_together():
    result = _failing_run(
        "ads",
        "get",
        "--status",
        "ACCEPTED",
        "--statuses",
        "ACCEPTED",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "--status and --statuses are mutually exclusive" in result.output


def test_ads_get_builds_full_typed_filter_payload():
    body = _dry_run(
        "ads",
        "get",
        "--ids",
        "1",
        "--campaign-ids",
        "2",
        "--adgroup-ids",
        "3",
        "--statuses",
        "accepted,draft",
        "--states",
        "on",
        "--types",
        "text_ad",
        "--mobile",
        "yes",
        "--vcard-ids",
        "4",
        "--sitelink-set-ids",
        "5",
        "--image-hashes",
        "hash-a,hash-b",
        "--vcard-moderation-statuses",
        "accepted",
        "--sitelinks-moderation-statuses",
        "accepted",
        "--image-moderation-statuses",
        "accepted",
        "--adextension-ids",
        "6",
        "--limit",
        "10",
        "--fields",
        "Id,Type",
        "--text-ad-field-names",
        "Title,Text",
    )

    assert body == {
        "method": "get",
        "params": {
            "SelectionCriteria": {
                "Ids": [1],
                "CampaignIds": [2],
                "AdGroupIds": [3],
                "Statuses": ["ACCEPTED", "DRAFT"],
                "States": ["ON"],
                "Types": ["TEXT_AD"],
                "Mobile": "YES",
                "VCardIds": [4],
                "SitelinkSetIds": [5],
                "AdImageHashes": ["hash-a", "hash-b"],
                "VCardModerationStatuses": ["ACCEPTED"],
                "SitelinksModerationStatuses": ["ACCEPTED"],
                "AdImageModerationStatuses": ["ACCEPTED"],
                "AdExtensionIds": [6],
            },
            "FieldNames": ["Id", "Type"],
            "TextAdFieldNames": ["Title", "Text"],
            "Page": {"Limit": 10},
        },
    }


def test_ads_add_rejects_incomplete_text_ad():
    result = _failing_run(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--title",
        "Only title",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "TEXT_AD requires --text, --href" in result.output


def test_ads_add_rejects_incomplete_text_image_ad():
    missing_hash = _failing_run(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--type",
        "TEXT_IMAGE_AD",
        "--href",
        "https://example.com",
        "--dry-run",
    )
    missing_href = _failing_run(
        "ads",
        "add",
        "--adgroup-id",
        "1",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "hash",
        "--dry-run",
    )

    assert missing_hash.exit_code != 0
    assert "TEXT_IMAGE_AD requires --image-hash" in missing_hash.output
    assert missing_href.exit_code != 0
    assert (
        "TEXT_IMAGE_AD requires either --href or --turbo-page-id."
        in missing_href.output
    )


def test_ads_update_text_ad_builds_textad_payload():
    """TEXT_AD subtype: --title/--text/--href produce a TextAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "99",
        "--type",
        "TEXT_AD",
        "--title",
        "New title",
        "--text",
        "New text",
        "--href",
        "https://example.com",
    )

    assert body == {
        "method": "update",
        "params": {
            "Ads": [
                {
                    "Id": 99,
                    "TextAd": {
                        "Title": "New title",
                        "Text": "New text",
                        "Href": "https://example.com",
                    },
                }
            ]
        },
    }


def test_ads_update_text_image_ad_builds_textimagead_payload():
    """TEXT_IMAGE_AD subtype: --image-hash + --href produce a single
    TextImageAd block (per WSDL TextImageAdUpdate)."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "99",
        "--type",
        "TEXT_IMAGE_AD",
        "--image-hash",
        "hash",
        "--href",
        "https://example.com",
    )

    assert body == {
        "method": "update",
        "params": {
            "Ads": [
                {
                    "Id": 99,
                    "TextImageAd": {
                        "AdImageHash": "hash",
                        "Href": "https://example.com",
                    },
                }
            ]
        },
    }


def test_ads_update_mobile_app_ad_builds_mobileapp_payload():
    """MOBILE_APP_AD subtype: all six flags map into a MobileAppAd block."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "99",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "App title",
        "--text",
        "App text",
        "--image-hash",
        "icon-hash",
        "--action",
        "INSTALL",
        "--tracking-url",
        "https://track.example",
        "--age-label",
        "AGE_12",
    )

    assert body == {
        "method": "update",
        "params": {
            "Ads": [
                {
                    "Id": 99,
                    "MobileAppAd": {
                        "Title": "App title",
                        "Text": "App text",
                        "AdImageHash": "icon-hash",
                        "Action": "INSTALL",
                        "TrackingUrl": "https://track.example",
                        "AgeLabel": "AGE_12",
                    },
                }
            ]
        },
    }


def test_ads_update_requires_explicit_type():
    """ads update without --type must fail with a clear error rather
    than guessing the subtype from the flags present."""
    result = _failing_run(
        "ads",
        "update",
        "--id",
        "99",
        "--title",
        "New title",
    )
    assert result.exit_code != 0
    assert "Missing option '--type'" in result.output


def test_ads_update_rejects_status_flag():
    """Status changes go through suspend/resume/archive/unarchive (#183)."""
    result = _failing_run(
        "ads",
        "update",
        "--id",
        "1",
        "--type",
        "TEXT_AD",
        "--status",
        "SUSPENDED",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "not supported by WSDL AdUpdateItem" in result.output


def test_ads_add_text_image_ad_rejects_title_and_text():
    """TEXT_IMAGE_AD has no Title/Text in WSDL TextImageAdAdd (#183)."""
    for extra in (
        ["--title", "T"],
        ["--text", "Body"],
        ["--title", "T", "--text", "Body"],
    ):
        result = _failing_run(
            "ads",
            "add",
            "--adgroup-id",
            "1",
            "--type",
            "TEXT_IMAGE_AD",
            "--image-hash",
            "hash",
            "--href",
            "https://example.com",
            *extra,
            "--dry-run",
        )
        assert result.exit_code != 0, f"expected failure for extras={extra}"
        assert "is not compatible with --type TEXT_IMAGE_AD" in result.output


def test_ads_add_mobile_app_ad_builds_payload():
    """MOBILE_APP_AD builds a MobileAppAd payload (#183)."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "100",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "Install our app",
        "--text",
        "Best mobile shopping experience",
        "--action",
        "INSTALL",
        "--tracking-url",
        "https://tracker.example.com/click",
        "--image-hash",
        "hash-mobile",
    )
    assert body["method"] == "add"
    ad = body["params"]["Ads"][0]
    assert "Type" not in ad
    assert ad["AdGroupId"] == 100
    assert ad["MobileAppAd"] == {
        "Title": "Install our app",
        "Text": "Best mobile shopping experience",
        "Action": "INSTALL",
        "TrackingUrl": "https://tracker.example.com/click",
        "AdImageHash": "hash-mobile",
    }


def test_ads_add_mobile_app_ad_rejects_href():
    """MobileAppAdAdd has no Href field; passing --href would silently
    drop the user's URL. CLI must reject the combination loudly."""
    result = _failing_run(
        "ads",
        "add",
        "--adgroup-id",
        "100",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "T",
        "--text",
        "B",
        "--action",
        "GET",
        "--href",
        "https://example.com",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "--href is not compatible with --type MOBILE_APP_AD" in result.output


def test_ads_add_mobile_app_ad_requires_action():
    result = _failing_run(
        "ads",
        "add",
        "--adgroup-id",
        "100",
        "--type",
        "MOBILE_APP_AD",
        "--title",
        "T",
        "--text",
        "B",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "MOBILE_APP_AD requires --action" in result.output


def test_ads_lifecycle_payloads_use_id_selection_criteria():
    for command in ["delete", "suspend", "resume", "archive", "unarchive", "moderate"]:
        body = _dry_run("ads", command, "--id", "42")
        assert body == {
            "method": command,
            "params": {"SelectionCriteria": {"Ids": [42]}},
        }

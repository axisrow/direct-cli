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
            "2026-04-14T00:00:00",
            "--fields",
            "CampaignId,ChangesIn",
        ],
    )

    assert body == {
        "method": "check",
        "params": {
            "CampaignIds": [1, 2],
            "Timestamp": "2026-04-14T00:00:00Z",
            "FieldNames": ["CampaignId", "ChangesIn"],
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
            "2026-04-14T00:00:00",
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


def test_changes_rejects_noncanonical_datetime():
    result = _failing_run(
        "changes",
        "check-campaigns",
        "--timestamp",
        "2026-04-14T00:00:00Z",
    )

    assert result.exit_code != 0
    assert "Expected: YYYY-MM-DDTHH:MM:SS" in result.output


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


def test_strategies_add_typed_fields_payload():
    body = _dry_run(
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
        "--counter-ids",
        "1,2",
        "--priority-goal",
        "123:4560000",
    )

    strategy = body["params"]["Strategies"][0]
    assert body["method"] == "add"
    assert strategy["WbMaximumClicks"] == {
        "AverageCpc": 30000000,
        "SpendLimit": 1000000000,
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
    assert "No such option: --params" in result.output


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
        "--average-crr",
        "25",
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
        "AverageCrr": 25,
        "WeeklySpendLimit": 70000000,
        "BidCeiling": 8000000,
    }
    assert strategy["AttributionModel"] == "LYDC"


def test_strategies_update_typed_metadata_payload():
    body = _dry_run(
        "strategies",
        "update",
        "--id",
        "42",
        "--type",
        "WbMaximumClicks",
        "--average-cpc",
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
        "WbMaximumClicks": {"AverageCpc": 35000000},
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


def test_dynamicads_add_requires_condition():
    result = _failing_run(
        "dynamicads",
        "add",
        "--adgroup-id",
        "1",
        "--name",
        "Webpage",
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "Provide at least one --condition" in result.output


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
    assert target["Conditions"] == [
        {"Operand": "CATEGORY", "Operator": "EQUALS", "Arguments": ["shoes"]}
    ]


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
    assert "Provide target selection and bid fields" in no_selector.output
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
    assert "Provide target selection and bid fields" in no_selector.output
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
        "--text-ad-fields",
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
    assert "TEXT_IMAGE_AD requires both --image-hash and --href" in missing_hash.output
    assert missing_href.exit_code != 0
    assert "TEXT_IMAGE_AD requires both --image-hash and --href" in missing_href.output


def test_ads_update_combines_text_and_image_fields():
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "99",
        "--status",
        "SUSPENDED",
        "--title",
        "New title",
        "--text",
        "New text",
        "--href",
        "https://example.com",
        "--image-hash",
        "hash",
    )

    assert body == {
        "method": "update",
        "params": {
            "Ads": [
                {
                    "Id": 99,
                    "Status": "SUSPENDED",
                    "TextAd": {
                        "Title": "New title",
                        "Text": "New text",
                        "Href": "https://example.com",
                    },
                    "TextImageAd": {"AdImageHash": "hash"},
                }
            ]
        },
    }


def test_ads_lifecycle_payloads_use_id_selection_criteria():
    for command in ["delete", "suspend", "resume", "archive", "unarchive", "moderate"]:
        body = _dry_run("ads", command, "--id", "42")
        assert body == {
            "method": command,
            "params": {"SelectionCriteria": {"Ids": [42]}},
        }

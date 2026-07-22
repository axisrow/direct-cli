"""Dry-run payload tests for ``campaigns add`` / ``update`` / ``get``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _failing_run, _read_dry_run, _rejected
from tests.test_dry_run_strategy_smart import _cpa_base_args, _smart_network_base


def test_campaigns_get_text_campaign_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--fields",
        "Id,Name,State",
        "--text-campaign-field-names",
        "BiddingStrategy",
    )

    assert body["params"]["FieldNames"] == ["Id", "Name", "State"]
    assert body["params"]["TextCampaignFieldNames"] == ["BiddingStrategy"]


def test_campaigns_get_campaign_specific_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--text-campaign-field-names",
        "BiddingStrategy,PriorityGoals",
        "--mobile-app-campaign-field-names",
        "Settings,BiddingStrategy",
        "--dynamic-text-campaign-field-names",
        "BiddingStrategy,Settings",
        "--cpm-banner-campaign-field-names",
        "BiddingStrategy,Settings",
        "--smart-campaign-field-names",
        "BiddingStrategy,Settings",
        "--unified-campaign-field-names",
        "BiddingStrategy,PriorityGoals",
    )

    params = body["params"]
    assert params["TextCampaignFieldNames"] == ["BiddingStrategy", "PriorityGoals"]
    assert params["MobileAppCampaignFieldNames"] == ["Settings", "BiddingStrategy"]
    assert params["DynamicTextCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["CpmBannerCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["SmartCampaignFieldNames"] == ["BiddingStrategy", "Settings"]
    assert params["UnifiedCampaignFieldNames"] == ["BiddingStrategy", "PriorityGoals"]


def test_campaigns_get_strategy_placement_fields_dry_run():
    body = _read_dry_run(
        "campaigns",
        "get",
        "--text-campaign-search-strategy-placement-types-field-names",
        "SearchResults,ProductGallery",
        "--dynamic-text-campaign-search-strategy-placement-types-field-names",
        "SearchResults,DynamicPlaces",
        "--unified-campaign-search-strategy-placement-types-field-names",
        "SearchResults,Maps,SearchOrganizationList",
        "--unified-campaign-package-bidding-strategy-platforms-field-names",
        "SearchResult,Network",
    )

    params = body["params"]
    assert params["TextCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "ProductGallery",
    ]
    assert params["DynamicTextCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "DynamicPlaces",
    ]
    assert params["UnifiedCampaignSearchStrategyPlacementTypesFieldNames"] == [
        "SearchResults",
        "Maps",
        "SearchOrganizationList",
    ]
    assert params["UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames"] == [
        "SearchResult",
        "Network",
    ]


def test_campaigns_get_omits_campaign_specific_fields_by_default():
    body = _read_dry_run("campaigns", "get", "--fields", "Id,Name,State")

    omitted_keys = {
        "TextCampaignFieldNames",
        "TextCampaignSearchStrategyPlacementTypesFieldNames",
        "MobileAppCampaignFieldNames",
        "DynamicTextCampaignFieldNames",
        "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames",
        "CpmBannerCampaignFieldNames",
        "SmartCampaignFieldNames",
        "UnifiedCampaignFieldNames",
        "UnifiedCampaignSearchStrategyPlacementTypesFieldNames",
        "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames",
    }
    assert body["params"]["FieldNames"] == ["Id", "Name", "State"]
    assert omitted_keys.isdisjoint(body["params"])


def test_campaigns_get_rejects_empty_fields_csv():
    result = CliRunner().invoke(
        cli,
        ["campaigns", "get", "--fields", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "--fields must contain at least one value" in result.output


def test_campaigns_get_rejects_empty_campaign_specific_fields_csv():
    result = CliRunner().invoke(
        cli,
        [
            "campaigns",
            "get",
            "--fields",
            "Id",
            "--text-campaign-field-names",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "--text-campaign-field-names must contain at least one value" in result.output
    )


def test_campaigns_add_default_text_campaign_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C1",
        "--start-date",
        "2026-04-10",
    )
    assert body["method"] == "add"
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Name"] == "C1"
    assert campaign["StartDate"] == "2026-04-10"
    assert "TextCampaign" in campaign
    # CLI currently always builds a TextCampaign and never sets a
    # top-level Type — confirm both invariants.
    assert "Type" not in campaign


def test_campaigns_add_with_budget():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C2",
        "--start-date",
        "2026-04-10",
        "--budget",
        "500000000",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DailyBudget"] == {"Amount": 500000000, "Mode": "STANDARD"}


def test_campaigns_update_with_budget():
    body = _dry_run("campaigns", "update", "--id", "555", "--budget", "100000000")
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 555
    assert campaign["DailyBudget"] == {"Amount": 100000000, "Mode": "STANDARD"}


def test_campaigns_add_case_insensitive_text_type():
    """``--type text_campaign`` (lowercase) builds a TextCampaign.

    Regression guard for axisrow/direct-cli#23 — before the fix --type
    was silently ignored and the CLI always built a TextCampaign
    anyway, which masked typos like ``--type text_campaing``.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-case",
        "--start-date",
        "2026-04-10",
        "--type",
        "text_campaign",
    )
    campaign = body["params"]["Campaigns"][0]
    assert "TextCampaign" in campaign
    assert "Type" not in campaign


def test_campaigns_add_dynamic_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-dynamic",
        "--start-date",
        "2026-04-10",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DynamicTextCampaign"] == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
    }


def test_campaigns_add_smart_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-smart",
        "--start-date",
        "2026-04-10",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
        "--counter-id",
        "123",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {
                "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
                "AverageCpcPerFilter": {"FilterAverageCpc": 1000000},
            },
        },
        "CounterId": 123,
    }


def test_campaigns_add_smart_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--filter-average-cpc",
        "1000000",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart == {
        "CounterId": 123,
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {
                "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
                "AverageCpcPerFilter": {"FilterAverageCpc": 1000000},
            },
        },
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "AttributionModel": "AUTO",
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_add_smart_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "700",
        "--package-platform-search",
        "YES",
        "--package-platform-network",
        "NO",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "BiddingStrategy" not in smart
    assert smart == {
        "CounterId": 123,
        "PackageBiddingStrategy": {
            "StrategyId": 700,
            "Platforms": {"Search": "YES", "Network": "NO"},
        },
    }


def test_campaigns_add_smart_default_network_strategy_no_filter_average_cpc():
    # After #368 the typed SmartCampaign.BiddingStrategy.Network builder
    # honours the WSDL: ``StrategyAverageCpcPerFilterAdd.FilterAverageCpc``
    # is ``minOccurs=0`` (campaigns.xml 1447), so the legacy default of
    # ``AVERAGE_CPC_PER_FILTER`` without a value is a valid payload — no
    # CLI-side requirement is layered on top of the WSDL.
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "C-default-network",
        "--start-date",
        "2026-04-10",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "42",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "AVERAGE_CPC_PER_FILTER"}


def test_campaigns_add_smart_priority_goals_payload():
    # Issue #369: SmartCampaignAddItem.PriorityGoals is a top-level sibling on
    # the SmartCampaign block (WSDL tests/wsdl_cache/campaigns.xml line 2209
    # ``PriorityGoals`` typed as ``PriorityGoalsArray`` minOccurs=0). Items
    # carry GoalId (xsd:long, minOccurs=1), Value (xsd:long, minOccurs=1) and
    # the optional IsMetrikaSourceOfValue (general:YesNoEnum, minOccurs=0)
    # per the ``PriorityGoalsItem`` complex type (WSDL lines 1928-1934).
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Priority Goals",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--filter-average-cpc",
        "1000000",
        "--priority-goals",
        "1234567:80000000,9876543:20000000:YES",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80000000},
            {"GoalId": 9876543, "Value": 20000000, "IsMetrikaSourceOfValue": "YES"},
        ]
    }
    # PriorityGoals is independent of BiddingStrategy — the default
    # AVERAGE_CPC_PER_FILTER Network branch must still be present.
    network = smart["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == "AVERAGE_CPC_PER_FILTER"


def test_campaigns_add_smart_priority_goals_with_package_strategy_payload():
    # SmartCampaign.PriorityGoals (#369) and SmartCampaign.PackageBiddingStrategy
    # are declared as independent ``minOccurs=0`` siblings on the
    # SmartCampaignAddItem complexType (WSDL tests/wsdl_cache/campaigns.xml
    # lines 2202-2214 — no ``xsd:choice`` wrapping them), so combining
    # --priority-goals with --package-strategy-id must produce a payload
    # carrying BOTH fields. The shared smart_package_incompatible guard
    # documents the mutex it does enforce and intentionally excludes
    # --priority-goals.
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Pkg+PG",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "42",
        "--package-platform-search",
        "yes",
        "--package-platform-network",
        "yes",
        "--priority-goals",
        "1234567:80000000",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "PackageBiddingStrategy" in smart
    assert smart["PriorityGoals"] == {"Items": [{"GoalId": 1234567, "Value": 80000000}]}


def test_campaigns_add_smart_legacy_filter_average_cpc_with_typed_network_rejected():
    # Mixing legacy --filter-average-cpc with the new typed surface must
    # fail rather than silently dropping one input.
    result = _rejected(
        *_smart_network_base(),
        "--filter-average-cpc",
        "1000000",
        "--smart-network-bid-ceiling",
        "5000000",
    )
    assert "--filter-average-cpc cannot be combined" in result.output


def test_campaigns_add_smart_legacy_filter_average_cpc_wrong_strategy_rejected():
    # Legacy bridge only fires for AVERAGE_CPC_PER_FILTER; explicit other
    # --network-strategy must error.
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--filter-average-cpc",
        "1000000",
    )
    assert "--filter-average-cpc" in result.output


def test_campaigns_add_rejects_smart_package_without_required_platforms():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package Bad",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--package-strategy-id",
        "700",
    )
    assert "--package-platform-search" in result.output
    assert "--package-platform-network" in result.output


def test_campaigns_add_rejects_incompatible_subtype_flags():
    text_result = _rejected(
        "campaigns",
        "add",
        "--name",
        "C-text",
        "--start-date",
        "2026-04-10",
        "--type",
        "TEXT_CAMPAIGN",
        "--counter-id",
        "123",
    )
    smart_result = _rejected(
        "campaigns",
        "add",
        "--name",
        "C-smart",
        "--start-date",
        "2026-04-10",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        "--network-strategy",
        "SERVING_OFF",
        "--filter-average-cpc",
        "1000000",
    )

    assert (
        "--counter-id is not compatible with --type TEXT_CAMPAIGN" in text_result.output
    )
    assert "AVERAGE_CPC_PER_FILTER" in smart_result.output


def test_campaigns_add_average_cpa_search_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1234567",
        "--average-cpa",
        "500000000",
        "--bid-ceiling",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {
        "AverageCpa": 500000000,
        "GoalId": 1234567,
        "BidCeiling": 1000000000,
    }


def test_campaigns_add_pay_for_conversion_crr_search_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "555",
        "--crr",
        "8",
    )
    search = body["params"]["Campaigns"][0]["TextCampaign"]["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "PAY_FOR_CONVERSION_CRR"
    # WSDL StrategyPayForConversionCrrAdd: Crr + GoalId both minOccurs=1.
    assert search["PayForConversionCrr"] == {"Crr": 8, "GoalId": 555}


def test_campaigns_add_priority_goals_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1234567:80000000:YES,9876543:20000000",
        "--bid-ceiling",
        "1000000000",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80000000, "IsMetrikaSourceOfValue": "YES"},
            {"GoalId": 9876543, "Value": 20000000},
        ]
    }
    search = text["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA_MULTIPLE_GOALS"
    assert search["AverageCpaMultipleGoals"] == {"BidCeiling": 1000000000}


def test_campaigns_add_counter_ids_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--counter-ids",
        "111,222,333",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["CounterIds"] == {"Items": [111, 222, 333]}


def test_campaigns_add_text_campaign_optional_controls_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--relevant-keywords-budget-percent",
        "40",
        "--relevant-keywords-mode",
        "optimal",
        "--relevant-keywords-optimize-goal-id",
        "0",
        "--attribution-model",
        "auto",
        "--negative-keyword-shared-set-ids",
        "10,11,12",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["Settings"] == [{"Option": "ADD_METRICA_TAG", "Value": "YES"}]
    assert text["RelevantKeywords"] == {
        "BudgetPercent": 40,
        "Mode": "OPTIMAL",
        "OptimizeGoalId": 0,
    }
    assert text["AttributionModel"] == "AUTO"
    assert text["NegativeKeywordSharedSetIds"] == {"Items": [10, 11, 12]}


def test_campaigns_add_text_package_bidding_strategy_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--counter-ids",
        "111,222",
        "--attribution-model",
        "AUTO",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert "BiddingStrategy" not in text
    assert text["CounterIds"] == {"Items": [111, 222]}
    assert text["AttributionModel"] == "AUTO"
    assert text["PackageBiddingStrategy"] == {
        "StrategyId": 700,
        "Platforms": {
            "SearchResult": "YES",
            "ProductGallery": "NO",
            "Network": "YES",
            "DynamicPlaces": "NO",
        },
    }


def test_campaigns_add_unified_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified == {
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "CounterIds": {"Items": [111, 222]},
        "AttributionModel": "AUTO",
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_add_unified_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "NO",
        "--package-platform-maps",
        "YES",
        "--package-platform-search-organization-list",
        "NO",
        "--package-platform-network",
        "YES",
        "--package-platform-dynamic-places",
        "NO",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert "BiddingStrategy" not in unified
    assert unified == {
        "Settings": [],
        "PackageBiddingStrategy": {
            "StrategyId": 700,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "NO",
                "Maps": "YES",
                "SearchOrganizationList": "NO",
                "Network": "YES",
                "DynamicPlaces": "NO",
            },
        },
    }


def test_campaigns_update_text_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80000000:YES,9876543:20000000",
        "--relevant-keywords-mode",
        "maximum",
        "--relevant-keywords-optimize-goal-id",
        "0",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "TextCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80000000,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20000000, "Operation": "SET"},
                ]
            },
            "RelevantKeywords": {
                "Mode": "MAXIMUM",
                "OptimizeGoalId": 0,
            },
            "AttributionModel": "AUTO",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_update_unified_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80000000:YES,9876543:20000000",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "UnifiedCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80000000,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20000000, "Operation": "SET"},
                ]
            },
            "AttributionModel": "AUTO",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_update_text_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--counter-ids",
        "111",
        "--attribution-model",
        "LC",
        "--package-strategy-from-campaign-id",
        "456",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "NO",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text == {
        "CounterIds": {"Items": [111]},
        "AttributionModel": "LC",
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 456,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "YES",
                "Network": "NO",
            },
        },
    }


def test_campaigns_update_unified_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "456",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-maps",
        "NO",
        "--package-platform-search-organization-list",
        "YES",
        "--package-platform-network",
        "NO",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified == {
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 456,
            "Platforms": {
                "SearchResult": "YES",
                "ProductGallery": "YES",
                "Maps": "NO",
                "SearchOrganizationList": "YES",
                "Network": "NO",
            },
        },
    }


def test_campaigns_add_dynamic_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dynamic Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--dynamic-placement-search-results",
        "YES",
        "--dynamic-placement-product-gallery",
        "NO",
        "--counter-ids",
        "111,222",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "AUTO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dynamic == {
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "CounterIds": {"Items": [111, 222]},
        "PlacementTypes": [
            {"Type": "SEARCH_RESULTS", "Value": "YES"},
            {"Type": "PRODUCT_GALLERY", "Value": "NO"},
        ],
        "AttributionModel": "AUTO",
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_update_dynamic_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=NO",
        "--dynamic-placement-search-results",
        "NO",
        "--dynamic-placement-product-gallery",
        "YES",
        "--counter-ids",
        "111,222",
        "--priority-goals",
        "1234567:80000000:YES,9876543:20000000",
        "--tracking-params",
        "utm_source=direct",
        "--attribution-model",
        "LC",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "DynamicTextCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "NO"}],
            "PlacementTypes": [
                {"Type": "SEARCH_RESULTS", "Value": "NO"},
                {"Type": "PRODUCT_GALLERY", "Value": "YES"},
            ],
            "CounterIds": {"Items": [111, 222]},
            "PriorityGoals": {
                "Items": [
                    {
                        "GoalId": 1234567,
                        "Value": 80000000,
                        "IsMetrikaSourceOfValue": "YES",
                        "Operation": "SET",
                    },
                    {"GoalId": 9876543, "Value": 20000000, "Operation": "SET"},
                ]
            },
            "AttributionModel": "LC",
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
            "TrackingParams": "utm_source=direct",
        },
    }


def test_campaigns_add_dynamic_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dynamic Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "700",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert "BiddingStrategy" not in dynamic
    assert dynamic == {
        "Settings": [],
        "PackageBiddingStrategy": {"StrategyId": 700},
    }


def test_campaigns_update_dynamic_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "456",
    )
    dynamic = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dynamic == {
        "PackageBiddingStrategy": {"StrategyFromCampaignId": 456},
    }


def test_campaigns_add_rejects_dynamic_package_platforms():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Dynamic Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
    )
    assert "--package-platform-search-result" in result.output
    assert "DYNAMIC_TEXT_CAMPAIGN" in result.output


def test_campaigns_add_notification_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--sms-events",
        "FINISHED,moderation",
        "--sms-time-from",
        "09:00",
        "--sms-time-to",
        "18:00",
        "--notification-email",
        "ops@example.com",
        "--notification-check-position-interval",
        "15",
        "--notification-warning-balance",
        "20",
        "--notification-send-account-news",
        "no",
        "--notification-send-warnings",
        "YES",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "SmsSettings": {
            "Events": ["FINISHED", "MODERATION"],
            "TimeFrom": "09:00",
            "TimeTo": "18:00",
        },
        "EmailSettings": {
            "Email": "ops@example.com",
            "CheckPositionInterval": 15,
            "WarningBalance": 20,
            "SendAccountNews": "NO",
            "SendWarnings": "YES",
        },
    }
    # Lives at campaign level, sibling of TextCampaign.
    assert "Notification" not in campaign["TextCampaign"]


def test_campaigns_add_time_targeting_payload():
    schedule_row = "1,0,0,50,50,100,100,150,200,200,150,100,100,80,70,100,100,100,50,50,40,30,0,0,0"
    body = _dry_run(
        *_cpa_base_args(),
        "--time-targeting-schedule",
        schedule_row,
        "--consider-working-weekends",
        "YES",
        "--holidays-suspend-on-holidays",
        "no",
        "--holidays-bid-percent",
        "50",
        "--holidays-start-hour",
        "10",
        "--holidays-end-hour",
        "20",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["TimeTargeting"] == {
        "Schedule": {"Items": [schedule_row]},
        "ConsiderWorkingWeekends": "YES",
        "HolidaysSchedule": {
            "SuspendOnHolidays": "NO",
            "BidPercent": 50,
            "StartHour": 10,
            "EndHour": 20,
        },
    }
    assert "TimeTargeting" not in campaign["TextCampaign"]


def test_campaigns_add_campaign_level_controls_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--client-info",
        "Client A",
        "--time-zone",
        "Europe/Moscow",
        "--negative-keywords",
        "used,repair",
        "--blocked-ips",
        "192.0.2.1,198.51.100.2",
        "--excluded-sites",
        "example.com,example.net",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["ClientInfo"] == "Client A"
    assert campaign["TimeZone"] == "Europe/Moscow"
    assert campaign["NegativeKeywords"] == {"Items": ["used", "repair"]}
    assert campaign["BlockedIps"] == {"Items": ["192.0.2.1", "198.51.100.2"]}
    assert campaign["ExcludedSites"] == {"Items": ["example.com", "example.net"]}


def test_campaigns_update_campaign_level_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--client-info",
        "Client B",
        "--sms-events",
        "FINISHED",
        "--notification-email",
        "ops@example.com",
        "--notification-send-warnings",
        "NO",
        "--time-zone",
        "Asia/Bangkok",
        "--negative-keywords",
        "used",
        "--blocked-ips",
        "192.0.2.1",
        "--excluded-sites",
        "example.com",
        "--time-targeting-schedule",
        "1A0123456789ABCDEFGHIJKL",
        "--consider-working-weekends",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "ClientInfo": "Client B",
        "Notification": {
            "SmsSettings": {"Events": ["FINISHED"]},
            "EmailSettings": {
                "Email": "ops@example.com",
                "SendWarnings": "NO",
            },
        },
        "TimeZone": "Asia/Bangkok",
        "NegativeKeywords": {"Items": ["used"]},
        "BlockedIps": {"Items": ["192.0.2.1"]},
        "ExcludedSites": {"Items": ["example.com"]},
        "TimeTargeting": {
            "Schedule": {"Items": ["1A0123456789ABCDEFGHIJKL"]},
            "ConsiderWorkingWeekends": "NO",
        },
    }


def test_campaigns_time_targeting_requires_consider_working_weekends():
    result = _rejected(
        *_cpa_base_args(),
        "--time-targeting-schedule",
        "1A0123456789ABCDEFGHIJKL",
    )
    assert "--consider-working-weekends" in result.output


def test_campaigns_holidays_requires_suspend_on_holidays():
    result = _rejected(
        *_cpa_base_args(),
        "--consider-working-weekends",
        "YES",
        "--holidays-bid-percent",
        "50",
    )
    assert "--holidays-suspend-on-holidays" in result.output


def test_campaigns_rejects_invalid_sms_events():
    result = _rejected(*_cpa_base_args(), "--sms-events", "BROKEN")
    assert "--sms-events" in result.output
    assert "invalid value" in result.output


def test_campaigns_rejects_empty_negative_keywords():
    result = _rejected(*_cpa_base_args(), "--negative-keywords", ",")
    assert "--negative-keywords" in result.output


def test_campaigns_rejects_too_long_client_info():
    result = _rejected(*_cpa_base_args(), "--client-info", "x" * 256)
    assert "--client-info must be at most 255 characters" in result.output


def test_campaigns_rejects_invalid_notification_interval():
    result = _rejected(
        *_cpa_base_args(),
        "--notification-check-position-interval",
        "10",
    )
    assert "--notification-check-position-interval" in result.output


def test_campaigns_rejects_invalid_sms_time_step():
    result = _rejected(*_cpa_base_args(), "--sms-time-from", "09:10")
    assert "--sms-time-from" in result.output


def test_campaigns_rejects_non_canonical_sms_time_format():
    result = _rejected(*_cpa_base_args(), "--sms-time-from", "9:00")
    assert "--sms-time-from" in result.output
    assert "HH:MM" in result.output


def test_campaigns_rejects_legacy_notification_blob_with_guidance():
    result = _rejected(*_cpa_base_args(), "--notification", "{}")
    assert "--notification is no longer accepted" in result.output
    assert "--notification-email" in result.output


def test_campaigns_update_rejects_legacy_notification_blob_with_guidance():
    result = _rejected("campaigns", "update", "--id", "123", "--notification", "{}")
    assert "--notification is no longer accepted" in result.output
    assert "--notification-email" in result.output


def test_campaigns_rejects_legacy_time_targeting_blob_with_guidance():
    result = _rejected(*_cpa_base_args(), "--time-targeting", "{}")
    assert "--time-targeting is no longer accepted" in result.output
    assert "--time-targeting-schedule" in result.output


def test_campaigns_rejects_too_many_blocked_ips():
    result = _rejected(
        *_cpa_base_args(),
        "--blocked-ips",
        ",".join(f"192.0.2.{index}" for index in range(26)),
    )
    assert "--blocked-ips must contain at most 25 items" in result.output


def test_campaigns_rejects_holidays_bid_percent_with_suspend_yes():
    result = _rejected(
        *_cpa_base_args(),
        "--consider-working-weekends",
        "YES",
        "--holidays-suspend-on-holidays",
        "YES",
        "--holidays-bid-percent",
        "50",
    )
    assert "--holidays-bid-percent" in result.output


def test_campaigns_add_rejects_relevant_keywords_without_budget_percent():
    result = _rejected(*_cpa_base_args(), "--relevant-keywords-mode", "OPTIMAL")
    assert "--relevant-keywords-budget-percent" in result.output


def test_campaigns_add_rejects_package_strategy_without_required_platforms():
    result = _rejected(*_cpa_base_args(), "--package-strategy-id", "700")
    assert "--package-platform-search-result" in result.output
    assert "--package-platform-product-gallery" in result.output
    assert "--package-platform-network" in result.output


def test_campaigns_add_rejects_package_strategy_with_strategy_inputs():
    result = _rejected(
        *_cpa_base_args(),
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "YES",
        "--search-strategy",
        "AVERAGE_CPA",
    )
    assert "PackageBiddingStrategy cannot be combined" in result.output
    assert "--search-strategy" in result.output


def test_campaigns_add_rejects_unified_package_strategy_with_counter_ids():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified Package Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--package-platform-search-result",
        "YES",
        "--package-platform-product-gallery",
        "YES",
        "--package-platform-network",
        "YES",
        "--counter-ids",
        "111",
    )
    assert "UnifiedCampaign.PackageBiddingStrategy cannot be combined" in result.output
    assert "--counter-ids" in result.output


def test_campaigns_add_unified_priority_goals_standalone_payload():
    """Issue #373: PriorityGoals on UnifiedCampaign add WITHOUT any
    BiddingStrategy / PackageBiddingStrategy choice.

    The canonical WSDL declares ``UnifiedCampaignAddItem.PriorityGoals``
    (line 2165) as an independent ``minOccurs=0`` sibling alongside
    ``BiddingStrategy`` (line 2162, also ``minOccurs=0``) and
    ``PackageBiddingStrategy`` (line 2168, ``minOccurs=0``) on a plain
    ``xsd:sequence`` — no ``xsd:choice`` wrapper exists. The payload
    must therefore carry PriorityGoals on its own and let the
    per-side BiddingStrategy fall back to its HIGHEST_POSITION /
    SERVING_OFF defaults.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Goals Standalone",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--priority-goals",
        "1234567:80000000,9876543:20000000:YES",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80000000},
            {"GoalId": 9876543, "Value": 20000000, "IsMetrikaSourceOfValue": "YES"},
        ]
    }
    # The default per-side BiddingStrategy is still emitted.
    bidding = unified["BiddingStrategy"]
    assert bidding["Search"]["BiddingStrategyType"] == "HIGHEST_POSITION"
    assert bidding["Network"]["BiddingStrategyType"] == "SERVING_OFF"


def test_campaigns_add_rejects_unified_priority_goals_with_incompatible_strategy():
    """Issue #373: a per-side strategy explicitly chosen with a subtype
    builder that does not consume PriorityGoals must be rejected
    up-front — otherwise the subtype builder would silently drop the
    user's goals."""
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified Goals + AVERAGE_CPC",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--unified-network-average-cpc",
        "5000000",
        "--priority-goals",
        "1:50000000",
    )
    assert "--priority-goals on UnifiedCampaign is only valid with" in result.output
    assert "AVERAGE_CPA_MULTIPLE_GOALS" in result.output


def test_campaigns_add_unified_priority_goals_with_mixed_strategy_sides_payload():
    """Issue #373: PriorityGoals is accepted when only ONE side's chosen
    subtype consumes it. Per WSDL ``UnifiedCampaignAddItem`` exposes
    ``BiddingStrategy``, ``PriorityGoals`` and
    ``PackageBiddingStrategy`` as independent ``minOccurs=0`` siblings
    (lines 2160-2172). The MAX_PROFIT Network side consumes the items
    via ``sub_campaign_block``; the Search side keeps its AVERAGE_CPC
    subtype payload untouched."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Mixed PG",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--unified-search-average-cpc",
        "5000000",
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1234567:80000000",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified["PriorityGoals"] == {
        "Items": [{"GoalId": 1234567, "Value": 80000000}]
    }
    bidding = unified["BiddingStrategy"]
    assert bidding["Search"]["BiddingStrategyType"] == "AVERAGE_CPC"
    assert bidding["Network"]["BiddingStrategyType"] == "MAX_PROFIT"


def test_campaigns_add_unified_priority_goals_payload():
    """Issue #373: UnifiedCampaignAddItem.PriorityGoals payload shape.

    WSDL evidence (``tests/wsdl_cache/campaigns.xml``):
    * ``UnifiedCampaignAddItem.PriorityGoals`` — line 2165, typed as
      ``PriorityGoalsArray`` (minOccurs=0, maxOccurs=1).
    * ``PriorityGoalsItem`` (lines 1928-1934) — fields GoalId (xsd:long,
      minOccurs=1), Value (xsd:long, minOccurs=1) and the optional
      IsMetrikaSourceOfValue (general:YesNoEnum, minOccurs=0).

    PriorityGoals lives on the UnifiedCampaign parent block, not on the
    BiddingStrategy subtype — the Search (#363) / Network (#366)
    builders route the items to ``sub_campaign_block["PriorityGoals"]``
    when the chosen subtype accepts them.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Priority Goals",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--network-strategy",
        "MAX_PROFIT",
        "--priority-goals",
        "1234567:80000000,9876543:20000000:YES",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80000000},
            {"GoalId": 9876543, "Value": 20000000, "IsMetrikaSourceOfValue": "YES"},
        ]
    }
    network = unified["BiddingStrategy"]["Network"]
    assert network["BiddingStrategyType"] == "MAX_PROFIT"


def test_campaigns_add_unified_priority_goals_with_package_strategy_payload():
    """Issue #373: PriorityGoals + PackageBiddingStrategy on add (WSDL allows).

    ``UnifiedCampaignAddItem.PriorityGoals`` (WSDL
    ``tests/wsdl_cache/campaigns.xml`` line 2165) and
    ``UnifiedCampaignAddItem.PackageBiddingStrategy`` (line 2168-2169)
    are declared as independent ``minOccurs=0`` siblings on the same
    ``xsd:sequence`` (no ``xsd:choice`` wrapper). Mirrors the
    SmartCampaign precedent that lifted the same mutex in #369/#392
    (SmartCampaignAddItem lines 2202-2214). The payload must carry
    BOTH fields when the user supplies them.
    """
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified PG+Pkg",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "42",
        "--package-platform-search-result",
        "yes",
        "--package-platform-product-gallery",
        "yes",
        "--package-platform-network",
        "yes",
        "--priority-goals",
        "1234567:80000000,9876543:20000000:YES",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert "PackageBiddingStrategy" in unified
    assert unified["PriorityGoals"] == {
        "Items": [
            {"GoalId": 1234567, "Value": 80000000},
            {"GoalId": 9876543, "Value": 20000000, "IsMetrikaSourceOfValue": "YES"},
        ]
    }


def test_campaigns_update_unified_priority_goals_with_package_strategy_payload():
    """Issue #373: PriorityGoals + PackageBiddingStrategy on update (WSDL allows).

    ``UnifiedCampaignUpdateItem.PriorityGoals`` (WSDL
    ``tests/wsdl_cache/campaigns.xml`` line 2259) and
    ``UnifiedCampaignUpdateItem.PackageBiddingStrategy`` (lines
    2260-2262) are declared as nillable siblings on the same
    ``xsd:sequence``. The update path must emit both fields and
    PriorityGoals carries the per-item ``Operation`` field from the
    update-only ``PriorityGoalsUpdateItem`` shape (WSDL lines
    1935-1942).
    """
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--priority-goals",
        "1234567:80000000:YES",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert "PackageBiddingStrategy" in unified
    assert unified["PriorityGoals"] == {
        "Items": [
            {
                "GoalId": 1234567,
                "Value": 80000000,
                "IsMetrikaSourceOfValue": "YES",
                "Operation": "SET",
            },
        ]
    }


def test_campaigns_add_rejects_unified_client_info():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--client-info",
        "Client A",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--client-info" in result.output


def test_campaigns_update_rejects_unified_notification():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-send-warnings",
        "YES",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--notification-send-warnings" in result.output


def test_campaigns_add_unified_allows_supported_email_notification_fields():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Email",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-email",
        "ops@example.com",
        "--notification-send-account-news",
        "YES",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "EmailSettings": {
            "Email": "ops@example.com",
            "SendAccountNews": "YES",
        }
    }


def test_campaigns_update_unified_allows_supported_email_notification_fields():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--notification-email",
        "ops@example.com",
        "--notification-send-account-news",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Notification"] == {
        "EmailSettings": {
            "Email": "ops@example.com",
            "SendAccountNews": "NO",
        }
    }


def test_campaigns_add_rejects_unified_sms_notification():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Unified SMS",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
        "--sms-events",
        "FINISHED",
    )
    assert "UnifiedCampaign cannot be combined" in result.output
    assert "--sms-events" in result.output


def test_campaigns_rejects_too_many_negative_keyword_shared_set_ids():
    result = _rejected(
        *_cpa_base_args(),
        "--negative-keyword-shared-set-ids",
        "10,11,12,13",
    )
    assert (
        "--negative-keyword-shared-set-ids must contain at most 3 items"
        in result.output
    )


def test_campaigns_update_text_subtype_fields_require_type():
    result = _rejected("campaigns", "update", "--id", "123", "--counter-ids", "111")
    assert "--counter-ids requires --type" in result.output


def test_campaigns_update_rejects_partial_package_platforms():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--package-platform-dynamic-places",
        "YES",
    )
    assert "--package-platform-search-result" in result.output


def test_campaigns_help_exposes_typed_campaign_level_flags_not_json_blobs():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--notification " not in result.output
        assert "--time-targeting " not in result.output
        assert "--notification-email" in result.output
        assert "--time-targeting-schedule" in result.output
        assert "--negative-keywords" in result.output
        assert "--blocked-ips" in result.output
        assert "--excluded-sites" in result.output


def test_campaigns_help_exposes_text_and_unified_campaign_optional_flags():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--counter-ids" in result.output
        assert "--priority-goals" in result.output
        assert "--relevant-keywords-budget-percent" in result.output
        assert "--attribution-model" in result.output
        assert "--package-strategy-id" in result.output
        assert "--package-platform-search-result" in result.output
        assert "--package-platform-maps" in result.output
        assert "--package-platform-search-organization-list" in result.output
        assert "--negative-keyword-shared-set-ids" in result.output


def test_campaigns_help_exposes_cpm_banner_optional_flags():
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        assert "--average-cpm" in result.output
        assert "--average-cpv" in result.output
        assert "--strategy-spend-limit" in result.output
        assert "--strategy-start-date" in result.output
        assert "--strategy-end-date" in result.output
        assert "--strategy-auto-continue" in result.output
        assert "--frequency-cap-impressions" in result.output
        assert "--frequency-cap-period-days" in result.output
        assert "--frequency-cap-period-all" in result.output
        assert "--video-target" in result.output


def test_campaigns_help_exposes_mobile_app_search_strategy_flags():
    common_flags = {
        "--mobile-search-weekly-spend-limit",
        "--mobile-search-bid-ceiling",
        "--mobile-search-custom-period-spend-limit",
        "--mobile-search-custom-period-start-date",
        "--mobile-search-custom-period-end-date",
        "--mobile-search-custom-period-auto-continue",
        "--mobile-search-average-cpc",
        "--mobile-search-average-cpi",
        "--mobile-search-clicks-per-week",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in common_flags:
            assert flag in result.output
    add_help = CliRunner().invoke(cli, ["campaigns", "add", "--help"]).output
    update_help = CliRunner().invoke(cli, ["campaigns", "update", "--help"]).output
    assert "--mobile-search-budget-type" not in add_help
    assert "--mobile-search-budget-type" in update_help


def test_campaigns_help_exposes_mobile_app_network_strategy_flags():
    common_flags = {
        "--mobile-network-weekly-spend-limit",
        "--mobile-network-bid-ceiling",
        "--mobile-network-custom-period-spend-limit",
        "--mobile-network-custom-period-start-date",
        "--mobile-network-custom-period-end-date",
        "--mobile-network-custom-period-auto-continue",
        "--mobile-network-average-cpc",
        "--mobile-network-average-cpi",
        "--mobile-network-clicks-per-week",
        "--mobile-network-limit-percent",
    }
    for command in ("add", "update"):
        result = CliRunner().invoke(cli, ["campaigns", command, "--help"])
        assert result.exit_code == 0
        for flag in common_flags:
            assert flag in result.output
    add_help = CliRunner().invoke(cli, ["campaigns", "add", "--help"]).output
    update_help = CliRunner().invoke(cli, ["campaigns", "update", "--help"]).output
    assert "--mobile-network-budget-type" not in add_help
    assert "--mobile-network-budget-type" in update_help


def test_campaigns_add_text_tracking_params_payload():
    body = _dry_run(
        *_cpa_base_args(),
        "--tracking-params",
        "utm_source=direct&utm_campaign={campaign_id}",
    )
    text = body["params"]["Campaigns"][0]["TextCampaign"]
    assert text["TrackingParams"] == "utm_source=direct&utm_campaign={campaign_id}"


def test_campaigns_add_dynamic_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_medium=cpc",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    assert dyn["TrackingParams"] == "utm_source=direct&utm_medium=cpc"


def test_campaigns_add_smart_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "111",
        "--filter-average-cpc",
        "5000000",
        "--tracking-params",
        "utm_source=direct",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart["TrackingParams"] == "utm_source=direct"


def test_campaigns_add_mobile_app_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
            "Network": {"BiddingStrategyType": "SERVING_OFF"},
        },
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
    }


def test_campaigns_add_mobile_app_average_cpi_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPI",
        "--mobile-search-average-cpi",
        "5000000",
        "--mobile-search-weekly-spend-limit",
        "1000000000",
        "--mobile-search-bid-ceiling",
        "12500000",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile["BiddingStrategy"] == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPI",
            "AverageCpi": {
                "AverageCpi": 5000000,
                "WeeklySpendLimit": 1000000000,
                "BidCeiling": 12500000,
            },
        },
        "Network": {"BiddingStrategyType": "SERVING_OFF"},
    }


def test_campaigns_add_mobile_app_weekly_click_package_search_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Click Package",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-search-clicks-per-week",
        "100",
        "--mobile-search-average-cpc",
        "7250000",
    )
    search = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WEEKLY_CLICK_PACKAGE",
        "WeeklyClickPackage": {
            "ClicksPerWeek": 100,
            "AverageCpc": 7250000,
        },
    }


def test_campaigns_add_mobile_app_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-custom-period-spend-limit",
        "1000000000",
        "--mobile-search-custom-period-start-date",
        "2026-06-01",
        "--mobile-search-custom-period-end-date",
        "2026-06-30",
        "--mobile-search-custom-period-auto-continue",
        "NO",
    )
    search = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_impressions_below_search_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "IMPRESSIONS_BELOW_SEARCH",
    )
    assert "IMPRESSIONS_BELOW_SEARCH is disabled" in result.output


def test_campaigns_add_mobile_app_rejects_missing_required_search_field():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Missing CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_INSTALL",
    )
    assert "PAY_FOR_INSTALL requires --mobile-search-average-cpi" in result.output


def test_campaigns_add_mobile_app_rejects_search_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--mobile-search-average-cpc",
        "5000000",
    )
    assert "MobileAppCampaign search detail flags require --search-strategy" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_partial_custom_period_budget():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Partial Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--mobile-search-average-cpc",
        "5000000",
        "--mobile-search-custom-period-spend-limit",
        "1000000000",
    )
    assert "CustomPeriodBudget requires all custom-period flags" in result.output
    assert "--mobile-search-custom-period-start-date" in result.output


def test_campaigns_add_mobile_app_rejects_weekly_click_package_bid_conflict():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Click Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-search-clicks-per-week",
        "100",
        "--mobile-search-average-cpc",
        "7250000",
        "--mobile-search-bid-ceiling",
        "10000000",
    )
    assert "cannot combine --mobile-search-average-cpc" in result.output


def test_campaigns_add_mobile_app_average_cpi_network_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5000000",
        "--mobile-network-weekly-spend-limit",
        "1000000000",
        "--mobile-network-bid-ceiling",
        "12500000",
    )
    mobile = body["params"]["Campaigns"][0]["MobileAppCampaign"]
    assert mobile["BiddingStrategy"] == {
        "Search": {"BiddingStrategyType": "HIGHEST_POSITION"},
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPI",
            "AverageCpi": {
                "AverageCpi": 5000000,
                "WeeklySpendLimit": 1000000000,
                "BidCeiling": 12500000,
            },
        },
    }


def test_campaigns_add_mobile_app_network_default_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-limit-percent",
        "30",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 30},
    }


def test_campaigns_add_mobile_app_network_wb_maximum_clicks_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-custom-period-spend-limit",
        "1000000000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "NO",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
        "WbMaximumClicks": {
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "NO",
            }
        },
    }


def test_campaigns_add_mobile_app_average_cpi_network_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network CPI Custom Period",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5000000",
        "--mobile-network-custom-period-spend-limit",
        "1000000000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["MobileAppCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPI",
        "AverageCpi": {
            "AverageCpi": 5000000,
            "CustomPeriodBudget": {
                "SpendLimit": 1000000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_mobile_app_rejects_missing_required_network_field():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Missing Network CPI",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_INSTALL",
    )
    assert "PAY_FOR_INSTALL requires --mobile-network-average-cpi" in result.output


def test_campaigns_add_mobile_app_rejects_network_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--mobile-network-average-cpc",
        "5000000",
    )
    assert "MobileAppCampaign network detail flags require --network-strategy" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_network_default_non_limit_detail():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default Detail",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-average-cpc",
        "5000000",
    )
    assert "NETWORK_DEFAULT does not accept --mobile-network-average-cpc" in (
        result.output
    )


def test_campaigns_add_mobile_app_rejects_network_default_limit_percent_step():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Default Limit",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--mobile-network-limit-percent",
        "25",
    )
    assert "must be a multiple of 10 from 10 to 100" in result.output


def test_campaigns_add_mobile_app_rejects_network_weekly_click_package_bid_conflict():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Mobile App Network Click Conflict",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-network-clicks-per-week",
        "100",
        "--mobile-network-average-cpc",
        "7250000",
        "--mobile-network-bid-ceiling",
        "10000000",
    )
    assert "cannot combine --mobile-network-average-cpc" in result.output


def test_campaigns_add_cpm_banner_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--video-target",
        "VIEWS",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm == {
        "BiddingStrategy": {
            "Search": {"BiddingStrategyType": "SERVING_OFF"},
            "Network": {"BiddingStrategyType": "MANUAL_CPM"},
        },
        "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
        "CounterIds": {"Items": [111, 222]},
        "FrequencyCap": {"Impressions": 5, "PeriodDays": 7},
        "VideoTarget": "VIEWS",
    }


def test_campaigns_add_cpm_banner_wb_maximum_impressions_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Strategy",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120500000",
        "--strategy-spend-limit",
        "1000250000",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm["BiddingStrategy"] == {
        "Search": {"BiddingStrategyType": "SERVING_OFF"},
        "Network": {
            "BiddingStrategyType": "WB_MAXIMUM_IMPRESSIONS",
            "WbMaximumImpressions": {
                "AverageCpm": 120500000,
                "SpendLimit": 1000250000,
            },
        },
    }


def test_campaigns_add_cpm_banner_cp_average_cpv_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner CPV",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "CP_AVERAGE_CPV",
        "--average-cpv",
        "5000000",
        "--strategy-spend-limit",
        "1000000000",
        "--strategy-start-date",
        "2026-06-01",
        "--strategy-end-date",
        "2026-06-30",
        "--strategy-auto-continue",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["CpmBannerCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "CP_AVERAGE_CPV",
        "CpAverageCpv": {
            "AverageCpv": 5000000,
            "SpendLimit": 1000000000,
            "StartDate": "2026-06-01",
            "EndDate": "2026-06-30",
            "AutoContinue": "YES",
        },
    }


def test_campaigns_add_cpm_banner_campaign_frequency_cap_all_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-all",
    )
    cpm = body["params"]["Campaigns"][0]["CpmBannerCampaign"]
    assert cpm["FrequencyCap"] == {"Impressions": 5, "PeriodDays": None}


def test_campaigns_add_rejects_partial_frequency_cap():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
    )
    assert "--frequency-cap-impressions" in result.output
    assert "--frequency-cap-period-days" in result.output


def test_campaigns_add_cpm_banner_rejects_bidding_strategy_flags():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120000000",
        "--average-cpv",
        "5000000",
        "--strategy-spend-limit",
        "1000000000",
    )
    assert "WB_MAXIMUM_IMPRESSIONS does not accept --average-cpv" in result.output


def test_campaigns_add_cpm_banner_rejects_missing_strategy_fields():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "CPM Banner Controls",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "CP_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120000000",
        "--strategy-spend-limit",
        "1000000000",
    )
    assert "CP_MAXIMUM_IMPRESSIONS requires" in result.output
    assert "--strategy-start-date" in result.output
    assert "--strategy-end-date" in result.output
    assert "--strategy-auto-continue" in result.output


def test_campaigns_add_unified_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Unified Track",
        "--start-date",
        "2026-06-01",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_medium=cpc",
    )
    unified = body["params"]["Campaigns"][0]["UnifiedCampaign"]
    assert unified["TrackingParams"] == "utm_source=direct&utm_medium=cpc"


def test_campaigns_add_tracking_params_on_unsupported_type_rejected():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "X",
        "--start-date",
        "2026-06-01",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "--tracking-params" in result.output
    assert "MOBILE_APP_CAMPAIGN" in result.output


def test_campaigns_update_text_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct&utm_campaign={campaign_id}",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["Id"] == 123
    assert campaign["TextCampaign"] == {
        "TrackingParams": "utm_source=direct&utm_campaign={campaign_id}",
    }


def test_campaigns_update_dynamic_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["DynamicTextCampaign"] == {"TrackingParams": "utm_source=direct"}


def test_campaigns_update_smart_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {"TrackingParams": "utm_source=direct"}


def test_campaigns_update_smart_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--setting",
        "ADD_TO_FAVORITES=YES",
        "--counter-id",
        "456",
        "--priority-goals",
        "1234567:80000000:YES,9876543:20000000:NO",
        "--attribution-model",
        "AUTO",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "Settings": [{"Option": "ADD_TO_FAVORITES", "Value": "YES"}],
        "CounterId": 456,
        "PriorityGoals": {
            "Items": [
                {
                    "GoalId": 1234567,
                    "Value": 80000000,
                    "IsMetrikaSourceOfValue": "YES",
                    "Operation": "SET",
                },
                {
                    "GoalId": 9876543,
                    "Value": 20000000,
                    "IsMetrikaSourceOfValue": "NO",
                    "Operation": "SET",
                },
            ]
        },
        "AttributionModel": "AUTO",
        "TrackingParams": "utm_source=direct",
    }


def test_campaigns_update_mobile_app_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--setting",
        "ENABLE_AUTOFOCUS=NO",
        "--negative-keyword-shared-set-ids",
        "10,11",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "Settings": [{"Option": "ENABLE_AUTOFOCUS", "Value": "NO"}],
            "NegativeKeywordSharedSetIds": {"Items": [10, 11]},
        },
    }


def test_campaigns_update_mobile_app_wb_maximum_clicks_search_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-custom-period-spend-limit",
        "1000000000",
        "--mobile-search-custom-period-start-date",
        "2026-06-01",
        "--mobile-search-custom-period-end-date",
        "2026-06-30",
        "--mobile-search-custom-period-auto-continue",
        "YES",
        "--mobile-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                    "WbMaximumClicks": {
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpc_weekly_budget_clears_custom_period():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--mobile-search-average-cpc",
        "5000000",
        "--mobile-search-weekly-spend-limit",
        "1000000000",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": 5000000,
                        "WeeklySpendLimit": 1000000000,
                        "CustomPeriodBudget": None,
                        "BudgetType": "WEEKLY_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_budget_type_without_matching_budget():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_BUDGET requires --mobile-search-weekly-spend-limit" in (
        result.output
    )


def test_campaigns_update_mobile_app_rejects_budget_type_without_supported_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPI",
        "--mobile-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "AVERAGE_CPI does not accept --mobile-search-budget-type" in result.output


def test_campaigns_update_mobile_app_wb_maximum_clicks_network_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-custom-period-spend-limit",
        "1000000000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
        "--mobile-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "WB_MAXIMUM_CLICKS",
                    "WbMaximumClicks": {
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpc_network_weekly_budget_clears_custom_period():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC",
        "--mobile-network-average-cpc",
        "5000000",
        "--mobile-network-weekly-spend-limit",
        "1000000000",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "AVERAGE_CPC",
                    "AverageCpc": {
                        "AverageCpc": 5000000,
                        "WeeklySpendLimit": 1000000000,
                        "CustomPeriodBudget": None,
                        "BudgetType": "WEEKLY_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_average_cpi_network_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPI",
        "--mobile-network-average-cpi",
        "5000000",
        "--mobile-network-custom-period-spend-limit",
        "1000000000",
        "--mobile-network-custom-period-start-date",
        "2026-06-01",
        "--mobile-network-custom-period-end-date",
        "2026-06-30",
        "--mobile-network-custom-period-auto-continue",
        "YES",
        "--mobile-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "MobileAppCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "AVERAGE_CPI",
                    "AverageCpi": {
                        "AverageCpi": 5000000,
                        "CustomPeriodBudget": {
                            "SpendLimit": 1000000000,
                            "StartDate": "2026-06-01",
                            "EndDate": "2026-06-30",
                            "AutoContinue": "YES",
                        },
                        "WeeklySpendLimit": None,
                        "BudgetType": "CUSTOM_PERIOD_BUDGET",
                    },
                }
            }
        },
    }


def test_campaigns_update_mobile_app_rejects_network_budget_type_without_matching_budget():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_CLICKS",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_BUDGET requires --mobile-network-weekly-spend-limit" in (
        result.output
    )


def test_campaigns_update_mobile_app_rejects_network_budget_type_without_supported_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "MOBILE_APP_CAMPAIGN",
        "--network-strategy",
        "WEEKLY_CLICK_PACKAGE",
        "--mobile-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "WEEKLY_CLICK_PACKAGE does not accept --mobile-network-budget-type" in (
        result.output
    )


def test_campaigns_update_cpm_banner_campaign_optional_controls_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--setting",
        "ADD_METRICA_TAG=YES",
        "--counter-ids",
        "111,222",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--video-target",
        "CLICKS",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "Settings": [{"Option": "ADD_METRICA_TAG", "Value": "YES"}],
            "CounterIds": {"Items": [111, 222]},
            "FrequencyCap": {"Impressions": 5, "PeriodDays": 7},
            "VideoTarget": "CLICKS",
        },
    }


def test_campaigns_update_cpm_banner_strategy_search_only_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--search-strategy",
        "SERVING_OFF",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Search": {"BiddingStrategyType": "SERVING_OFF"},
            },
        },
    }


def test_campaigns_update_cpm_banner_wb_decreased_price_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS",
        "--average-cpm",
        "120000000",
        "--strategy-spend-limit",
        "1000000000",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": (
                        "WB_DECREASED_PRICE_FOR_REPEATED_IMPRESSIONS"
                    ),
                    "WbDecreasedPriceForRepeatedImpressions": {
                        "AverageCpm": 120000000,
                        "SpendLimit": 1000000000,
                    },
                },
            },
        },
    }


def test_campaigns_update_cpm_banner_campaign_frequency_cap_all_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-all",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 123,
        "CpmBannerCampaign": {
            "FrequencyCap": {"Impressions": 5, "PeriodDays": None},
        },
    }


def test_campaigns_update_rejects_partial_frequency_cap():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-period-days",
        "7",
    )
    assert "--frequency-cap-impressions" in result.output
    assert "--frequency-cap-period-days" in result.output


def test_campaigns_update_cpm_banner_strategy_details_require_network_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--average-cpm",
        "120000000",
        "--strategy-spend-limit",
        "1000000000",
    )
    assert "strategy detail flags require --network-strategy" in result.output


def test_campaigns_update_rejects_conflicting_frequency_cap_period_flags():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--frequency-cap-impressions",
        "5",
        "--frequency-cap-period-days",
        "7",
        "--frequency-cap-period-all",
    )
    assert "--frequency-cap-period-days" in result.output
    assert "--frequency-cap-period-all" in result.output


def test_campaigns_update_smart_package_bidding_strategy_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--package-strategy-from-campaign-id",
        "700",
        "--package-platform-search",
        "YES",
        "--package-platform-network",
        "NO",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["SmartCampaign"] == {
        "PackageBiddingStrategy": {
            "StrategyFromCampaignId": 700,
            "Platforms": {"Search": "YES", "Network": "NO"},
        },
    }


def test_campaigns_update_rejects_smart_text_package_platforms():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "SMART_CAMPAIGN",
        "--package-platform-search-result",
        "YES",
    )
    assert "--package-platform-search-result" in result.output
    assert "SMART_CAMPAIGN" in result.output


def test_campaigns_update_unified_tracking_params_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "UNIFIED_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign["UnifiedCampaign"] == {"TrackingParams": "utm_source=direct"}


def test_campaigns_update_tracking_params_without_type_rejected():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "--tracking-params" in result.output
    assert "--type" in result.output


def test_campaigns_update_tracking_params_on_cpm_banner_rejected():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--tracking-params",
        "utm_source=direct",
    )
    assert "--tracking-params" in result.output
    assert "CPM_BANNER_CAMPAIGN" in result.output


def test_campaigns_update_backward_compat_no_type():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--name",
        "Renamed",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {"Id": 123, "Name": "Renamed"}


def test_campaigns_update_type_without_subtype_fields_rejected():
    # --type without any subtype-specific value must not silently
    # build an empty TextCampaign/DynamicTextCampaign/SmartCampaign block.
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
    )
    assert "TEXT_CAMPAIGN" in result.output


def test_campaigns_add_dynamic_text_campaign_with_cpa():
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Dyn CPA",
        "--start-date",
        "2026-06-01",
        "--type",
        "DYNAMIC_TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "42",
        "--average-cpa",
        "200000000",
        "--counter-ids",
        "555",
    )
    dyn = body["params"]["Campaigns"][0]["DynamicTextCampaign"]
    search = dyn["BiddingStrategy"]["Search"]
    assert search["BiddingStrategyType"] == "AVERAGE_CPA"
    assert search["AverageCpa"] == {"AverageCpa": 200000000, "GoalId": 42}
    assert dyn["CounterIds"] == {"Items": [555]}


def test_campaigns_add_smart_campaign_keeps_counter_id_singular():
    """Regression: SMART_CAMPAIGN still uses singular --counter-id."""
    body = _dry_run(
        "campaigns",
        "add",
        "--name",
        "Smart",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "987",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert smart["CounterId"] == 987
    assert "CounterIds" not in smart


def test_campaigns_add_rejects_average_cpa_for_highest_position():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--average-cpa",
        "100000000",
    )
    assert "--average-cpa" in result.output and "CPA-shaped" in result.output


def test_campaigns_add_rejects_goal_id_for_highest_position():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
    )
    assert "--goal-id" in result.output or "CPA-shaped" in result.output


def test_campaigns_add_rejects_priority_goals_for_single_goal_strategy():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000000",
        "--priority-goals",
        "1:50000000,2:50000000",
    )
    assert "--priority-goals" in result.output and "MULTIPLE_GOALS" in result.output


def test_campaigns_add_rejects_priority_goals_bad_shape_missing_weight():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_priority_goals_non_integer():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "abc:80",
    )
    assert "--priority-goals" in result.output
    assert "must be integers" in result.output


def test_campaigns_add_rejects_priority_goals_no_separator():
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:80000000,broken",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_priority_goals_value_below_micro_min():
    # Issue #387: PriorityGoalsItem.Value is xsd:long in advertiser
    # currency × 1,000,000 (per add-text-campaign and strategies-types
    # docs). Reject raw-ruble inputs (Value < MICRO_RUBLE_MIN = 100_000)
    # at CLI parse time so the API does not silently interpret e.g.
    # ``Value: 500`` as 0.0005 advertiser-currency units.
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:500,2:500",
    )
    assert "--priority-goals" in result.output
    assert "micro-currency" in result.output
    # The error must include the helpful "did you mean" suggestion
    # pointing at the micro-currency conversion.
    assert "500000000" in result.output


def test_campaigns_add_rejects_priority_goals_negative_value():
    # WSDL PriorityGoalsItem.Value is xsd:long with no minInclusive
    # facet, but Yandex docs require a non-negative monetary value.
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:-1000000,2:1000000",
    )
    assert "--priority-goals" in result.output
    assert "non-negative" in result.output


def test_campaigns_add_rejects_counter_ids_for_smart_campaign():
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart no counter-ids",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "987",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--filter-average-cpc",
        "1000000",
        "--counter-ids",
        "111",
    )
    assert "--counter-ids" in result.output and "SMART_CAMPAIGN" in result.output


def test_campaigns_add_rejects_counter_ids_empty():
    result = _rejected(*_cpa_base_args(), "--counter-ids", "")
    assert "--counter-ids" in result.output


def test_campaigns_add_rejects_bid_ceiling_for_pay_for_conversion_crr():
    """WSDL StrategyPayForConversionCrrAdd has no BidCeiling field."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--crr",
        "8",
        "--bid-ceiling",
        "1000000",
    )
    assert "--bid-ceiling" in result.output
    assert "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_bid_ceiling_for_pay_for_conversion_multiple_goals():
    """WSDL StrategyPayForConversionMultipleGoalsAdd has no BidCeiling field."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
        "--priority-goals",
        "1:50000000,2:50000000",
        "--bid-ceiling",
        "1000000",
    )
    assert "--bid-ceiling" in result.output
    assert "PayForConversionMultipleGoals" in result.output


def test_campaigns_add_rejects_pay_for_conversion_crr_without_crr():
    """PayForConversionCrr.Crr is minOccurs=1 — CLI must demand --crr."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
    )
    assert "--crr" in result.output
    assert "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_pay_for_conversion_crr_without_goal_id():
    """PayForConversionCrr.GoalId is minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--network-strategy",
        "SERVING_OFF",
        "--crr",
        "8",
    )
    assert "--goal-id" in result.output


def test_campaigns_add_rejects_average_cpa_strategy_without_required_fields():
    """StrategyAverageCpaAdd: AverageCpa + GoalId both minOccurs=1."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
    )
    out = result.output
    assert "--average-cpa" in out and "--goal-id" in out


def test_campaigns_add_rejects_multiple_goals_strategy_without_priority_goals():
    """StrategyAverageCpaMultipleGoals requires PriorityGoals at WSDL."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA_MULTIPLE_GOALS",
        "--network-strategy",
        "SERVING_OFF",
    )
    assert "--priority-goals" in result.output


def test_campaigns_add_rejects_crr_for_average_cpa():
    """--crr is only valid for PAY_FOR_CONVERSION_CRR."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "AVERAGE_CPA",
        "--network-strategy",
        "SERVING_OFF",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000",
        "--crr",
        "8",
    )
    assert "--crr" in result.output and "PayForConversionCrr" in result.output


def test_campaigns_add_rejects_text_campaign_with_per_campaign_network_strategy():
    """Per-Campaign/Per-Filter exist only on SmartCampaign; rejecting them
    for TEXT_CAMPAIGN prevents emitting WSDL-invalid keys."""
    result = _rejected(
        *_cpa_base_args(),
        "--search-strategy",
        "HIGHEST_POSITION",
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--goal-id",
        "1",
        "--average-cpa",
        "100000",
    )
    # Without --network-strategy in the typed-subtype map, --average-cpa
    # has no CPA-shaped strategy to land on → CLI rejects.
    assert "CPA-shaped" in result.output


def test_campaigns_get_empty_fields_raises_usage_error_not_abort():
    # The UsageError from _parse_csv_option must keep exit code 2 (UsageError),
    # not be swallowed by ``except Exception`` and downgraded to Abort (1).
    result = CliRunner().invoke(
        cli,
        ["campaigns", "get", "--fields", ",", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code == 2
    assert "Aborted!" not in result.output


def test_campaigns_delete_dry_run_payload():
    body = _dry_run("campaigns", "delete", "--id", "42")
    assert body == {
        "method": "delete",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_campaigns_archive_dry_run_payload():
    body = _dry_run("campaigns", "archive", "--id", "42")
    assert body == {
        "method": "archive",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_campaigns_unarchive_dry_run_payload():
    body = _dry_run("campaigns", "unarchive", "--id", "42")
    assert body == {
        "method": "unarchive",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_campaigns_suspend_dry_run_payload():
    body = _dry_run("campaigns", "suspend", "--id", "42")
    assert body == {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_campaigns_resume_dry_run_payload():
    body = _dry_run("campaigns", "resume", "--id", "42")
    assert body == {
        "method": "resume",
        "params": {"SelectionCriteria": {"Ids": [42]}},
    }


def test_campaigns_add_money_flag_rejects_decimal_rubles():
    result = _failing_run(
        "campaigns",
        "add",
        "--name",
        "CPM",
        "--start-date",
        "2026-06-01",
        "--type",
        "CPM_BANNER_CAMPAIGN",
        "--network-strategy",
        "WB_MAXIMUM_IMPRESSIONS",
        "--average-cpm",
        "120.5",
    )
    assert result.exit_code != 0
    assert "Expected integer (micro-rubles)" in result.output


def test_campaigns_update_money_flag_rejects_small_micro_value():
    result = _failing_run(
        "campaigns",
        "update",
        "--id",
        "123",
        "--type",
        "TEXT_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC",
        "--text-search-average-cpc",
        "15",
    )
    assert result.exit_code != 0
    assert "seems too low for micro-rubles" in result.output
    assert "Did you mean 15000000?" in result.output


_CAMPAIGNS_GET_CANONICAL_FIELD_NAMES_FLAGS = [
    (
        "--cpm-banner-campaign-field-names",
        "CpmBannerCampaignFieldNames",
        "CounterIds,FrequencyCap,Settings",
    ),
    (
        "--dynamic-text-campaign-field-names",
        "DynamicTextCampaignFieldNames",
        "PlacementTypes,CounterIds,Settings",
    ),
    (
        "--dynamic-text-campaign-search-strategy-placement-types-field-names",
        "DynamicTextCampaignSearchStrategyPlacementTypesFieldNames",
        "SearchResults,ProductGallery,DynamicPlaces",
    ),
    (
        "--mobile-app-campaign-field-names",
        "MobileAppCampaignFieldNames",
        "Settings,BiddingStrategy,NegativeKeywordSharedSetIds",
    ),
    (
        "--smart-campaign-field-names",
        "SmartCampaignFieldNames",
        "CounterId,Settings,BiddingStrategy",
    ),
    (
        "--text-campaign-field-names",
        "TextCampaignFieldNames",
        "CounterIds,Settings,BiddingStrategy",
    ),
    (
        "--text-campaign-search-strategy-placement-types-field-names",
        "TextCampaignSearchStrategyPlacementTypesFieldNames",
        "SearchResults,ProductGallery,DynamicPlaces",
    ),
    (
        "--unified-campaign-field-names",
        "UnifiedCampaignFieldNames",
        "CounterIds,Settings,BiddingStrategy",
    ),
    (
        "--unified-campaign-package-bidding-strategy-platforms-field-names",
        "UnifiedCampaignPackageBiddingStrategyPlatformsFieldNames",
        "SearchResult,ProductGallery,Maps,Network",
    ),
    (
        "--unified-campaign-search-strategy-placement-types-field-names",
        "UnifiedCampaignSearchStrategyPlacementTypesFieldNames",
        "SearchResults,Maps,SearchOrganizationList",
    ),
]


def test_campaigns_get_canonical_field_names_flags_payload():
    # CampaignsGetRequest (WSDL tests/wsdl_cache/campaigns.xml) declares
    # ten nested top-level *FieldNames parameters separate from FieldNames.
    # PR #409 renames the legacy `--*-fields` flags to the WSDL-canonical
    # `--*-field-names` form so the parameter name maps 1:1 to the CLI.
    # This is a breaking change.
    argv = ["campaigns", "get"]
    expected = {}
    for flag, wsdl_key, sample in _CAMPAIGNS_GET_CANONICAL_FIELD_NAMES_FLAGS:
        argv.extend([flag, sample])
        expected[wsdl_key] = sample.split(",")

    body = _read_dry_run(*argv)

    for wsdl_key, values in expected.items():
        assert body["params"][wsdl_key] == values


def test_campaigns_get_help_exposes_canonical_field_names_flags():
    result = CliRunner().invoke(cli, ["campaigns", "get", "--help"])

    assert result.exit_code == 0
    for flag, _, _ in _CAMPAIGNS_GET_CANONICAL_FIELD_NAMES_FLAGS:
        assert flag in result.output, f"missing flag in --help output: {flag}"


def test_campaigns_get_legacy_field_aliases_removed():
    # Breaking change (#409): the old `--text-campaign-fields` style flags
    # were renamed to the WSDL-canonical `--*-field-names` form. The legacy
    # names must no longer be accepted by Click.
    result = CliRunner().invoke(
        cli,
        ["campaigns", "get", "--text-campaign-fields", "BiddingStrategy", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert "No such option" in result.output or "no such option" in result.output


def test_campaigns_delete_rejects_zero_id():
    result = _rejected("campaigns", "delete", "--id", "0")
    assert result.exit_code == 2, result.output


def test_campaigns_update_allows_positive_id():
    body = _dry_run("campaigns", "update", "--id", "9", "--name", "X")
    assert body["params"]["Campaigns"][0]["Id"] == 9

"""Dry-run payload tests for SMART campaign search/network bidding strategies
(and the shared CPA base helper).

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""


from tests.test_dry_run_shared import _dry_run, _rejected


def test_ads_add_smart_ad_builder_ad_payload():
    """Issue #278: SMART_AD_BUILDER_AD add supports LogoExtensionHash."""
    body = _dry_run(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--logo-extension-hash",
        "logoabcdefghijklmnop",
    )
    assert body["params"]["Ads"][0] == {
        "AdGroupId": 12345,
        "SmartAdBuilderAd": {
            "LogoExtensionHash": "logoabcdefghijklmnop",
        },
    }


def test_ads_add_smart_ad_builder_ad_rejects_erir_description():
    """Issue #278: SmartAdBuilderAdAdd exposes LogoExtensionHash only."""
    result = _rejected(
        "ads",
        "add",
        "--adgroup-id",
        "12345",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--erir-ad-description",
        "Smart builder ad",
    )
    assert (
        "--erir-ad-description is not compatible with --type SMART_AD_BUILDER_AD"
        in result.output
    )


def test_ads_update_smart_ad_builder_ad_payload():
    """Issue #271: SMART_AD_BUILDER_AD update supports compact fields."""
    body = _dry_run(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--logo-extension-hash",
        "logoabcdefghijklmnop",
        "--erir-ad-description",
        "Smart builder ad",
    )
    assert body["params"]["Ads"][0] == {
        "Id": 999,
        "SmartAdBuilderAd": {
            "LogoExtensionHash": "logoabcdefghijklmnop",
            "ErirAdDescription": "Smart builder ad",
        },
    }


def test_ads_update_smart_ad_builder_rejects_unrelated_flag():
    """Issue #271: SmartAdBuilderAd has no Creative block in ads.update."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
        "--creative-id",
        "111",
    )
    assert (
        "--creative-id is not compatible with --type SMART_AD_BUILDER_AD"
        in result.output
    )
    assert "does not convert an ad between subtypes" in result.output


def test_ads_update_smart_ad_builder_noop_rejected():
    """Issue #271: SmartAdBuilderAd update without fields stays a no-op error."""
    result = _rejected(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "SMART_AD_BUILDER_AD",
    )
    assert (
        "ads update requires at least one updatable field for "
        "--type SMART_AD_BUILDER_AD"
    ) in result.output


def _smart_search_base():
    return [
        "campaigns",
        "add",
        "--name",
        "Smart Search",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
        # Network defaults to AVERAGE_CPC_PER_FILTER + filter-average-cpc
        # (this PR's scope is Search; Network is owned by #368).
        "--filter-average-cpc",
        "1000000",
    ]


def test_campaigns_add_smart_search_average_cpc_per_campaign_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--smart-search-bid-ceiling",
        "9000000",
        "--smart-search-weekly-spend-limit",
        "50000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "AverageCpc": 5000000,
            "WeeklySpendLimit": 50000000,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_search_average_cpc_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-search-filter-average-cpc",
        "3000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_add_smart_search_average_cpc_per_filter_minimal_payload():
    # WSDL: StrategyAverageCpcPerFilterAdd.FilterAverageCpc is minOccurs=0,
    # so an empty payload subtype block is legal.
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "AVERAGE_CPC_PER_FILTER"}


def test_campaigns_add_smart_search_average_cpa_per_campaign_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-search-average-cpa",
        "4000000",
        "--smart-search-goal-id",
        "111",
        "--smart-search-bid-ceiling",
        "9000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {
            "AverageCpa": 4000000,
            "GoalId": 111,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_search_average_cpa_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-filter-average-cpa",
        "4500000",
        "--smart-search-goal-id",
        "222",
        "--smart-search-cp-spend-limit",
        "100000000",
        "--smart-search-cp-start-date",
        "2026-06-01",
        "--smart-search-cp-end-date",
        "2026-06-30",
        "--smart-search-cp-auto-continue",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "FilterAverageCpa": 4500000,
            "GoalId": 222,
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-search-cpa",
        "6000000",
        "--smart-search-goal-id",
        "333",
        "--smart-search-weekly-spend-limit",
        "50000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {
            "Cpa": 6000000,
            "GoalId": 333,
            "WeeklySpendLimit": 50000000,
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-search-cpa",
        "5500000",
        "--smart-search-goal-id",
        "444",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_add_smart_search_average_roi_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1500000",
        "--smart-search-goal-id",
        "555",
        "--smart-search-profitability",
        "200000",
        "--smart-search-bid-ceiling",
        "10000000",
        "--smart-search-exploration-min",
        "20000000",
        "--smart-search-exploration-min-custom",
        "YES",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
            "BidCeiling": 10000000,
            "Profitability": 200000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 20000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_smart_search_average_crr_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "25",
        "--smart-search-goal-id",
        "666",
        "--smart-search-weekly-spend-limit",
        "40000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 25,
            "GoalId": 666,
            "WeeklySpendLimit": 40000000,
        },
    }


def test_campaigns_add_smart_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_add_smart_search_serving_off_payload():
    body = _dry_run(
        *_smart_search_base(),
        "--search-strategy",
        "SERVING_OFF",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_smart_search_default_serving_off_payload():
    # No --search-strategy at all → SERVING_OFF default; preserved from
    # pre-#367 behavior.
    body = _dry_run(*_smart_search_base())
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_smart_search_requires_average_cpc():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
    )
    assert "--smart-search-average-cpc" in result.output


def test_campaigns_add_smart_search_requires_filter_average_cpa_and_goal():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
    )
    assert "--smart-search-filter-average-cpa" in result.output
    assert "--smart-search-goal-id" in result.output


def test_campaigns_add_smart_search_rejects_wrong_subtype_flag():
    # --smart-search-average-cpa belongs only to AverageCpaPerCampaign;
    # using it with AVERAGE_CPC_PER_CAMPAIGN must raise.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--smart-search-average-cpa",
        "4000000",
    )
    assert "--smart-search-average-cpa" in result.output


def test_campaigns_add_smart_search_rejects_bid_ceiling_on_crr():
    # WSDL StrategyAverageCrrAdd has no BidCeiling field.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
        "--smart-search-bid-ceiling",
        "10000000",
    )
    assert "--smart-search-bid-ceiling" in result.output


def test_campaigns_add_smart_search_rejects_exploration_on_cpc_per_campaign():
    # WSDL StrategyAverageCpcPerCampaignAdd has no ExplorationBudget.
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--smart-search-exploration-min",
        "1000000",
        "--smart-search-exploration-min-custom",
        "YES",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_search_rejects_partial_custom_period_budget():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--smart-search-cp-spend-limit",
        "100000000",
        # Missing start-date / end-date / auto-continue.
    )
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_smart_search_rejects_partial_exploration_budget():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1500000",
        "--smart-search-goal-id",
        "555",
        "--smart-search-exploration-min",
        "20000000",
        # missing --smart-search-exploration-min-custom
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_search_rejects_detail_without_strategy():
    # When --search-strategy is omitted but typed flags are present, the
    # builder must fail rather than silently picking SERVING_OFF.
    result = _rejected(
        *_smart_search_base(),
        "--smart-search-average-cpc",
        "5000000",
    )
    assert "SmartCampaign search detail flags" in result.output


def test_campaigns_add_smart_search_rejects_serving_off_with_details():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "SERVING_OFF",
        "--smart-search-average-cpc",
        "5000000",
    )
    assert "SERVING_OFF" in result.output


def test_campaigns_add_smart_search_rejects_invalid_strategy():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "BOGUS_STRATEGY",
    )
    assert "SMART_CAMPAIGN" in result.output


def test_campaigns_update_smart_search_average_cpc_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 55,
        "SmartCampaign": {
            "BiddingStrategy": {
                "Search": {
                    "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
                    "AverageCpcPerCampaign": {"AverageCpc": 5000000},
                }
            }
        },
    }


def test_campaigns_update_smart_search_average_cpc_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-search-filter-average-cpc",
        "3000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_update_smart_search_average_cpa_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-search-average-cpa",
        "4000000",
        "--smart-search-goal-id",
        "111",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000, "GoalId": 111},
    }


def test_campaigns_update_smart_search_average_cpa_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-filter-average-cpa",
        "4500000",
        "--smart-search-goal-id",
        "222",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {"FilterAverageCpa": 4500000, "GoalId": 222},
    }


def test_campaigns_update_smart_search_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-search-cpa",
        "6000000",
        "--smart-search-goal-id",
        "333",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {"Cpa": 6000000, "GoalId": 333},
    }


def test_campaigns_update_smart_search_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-search-cpa",
        "5500000",
        "--smart-search-goal-id",
        "444",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_update_smart_search_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_ROI",
        "--smart-search-reserve-return",
        "30",
        "--smart-search-roi-coef",
        "1500000",
        "--smart-search-goal-id",
        "555",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
        },
    }


def test_campaigns_update_smart_search_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CRR",
        "--smart-search-crr",
        "25",
        "--smart-search-goal-id",
        "666",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {"Crr": 25, "GoalId": 666},
    }


def test_campaigns_update_smart_search_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-search-crr",
        "15",
        "--smart-search-goal-id",
        "777",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_update_smart_search_partial_field_no_required_check():
    # On update, WSDL minOccurs=1 required-field validation is skipped so
    # users can change a single field. The builder must still accept the
    # subtype without rejecting (matches CpmBanner / MobileApp update
    # semantics).
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        # Only --smart-search-average-cpa, no --smart-search-goal-id
        "--smart-search-average-cpa",
        "4000000",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000},
    }


def test_campaigns_update_smart_search_omits_bidding_strategy_when_unused():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "BiddingStrategy" not in smart
    assert smart == {"CounterId": 123}


def test_campaigns_update_smart_search_rejects_package_with_search_flags():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
    )
    assert "PackageBiddingStrategy" in result.output


def test_campaigns_update_smart_search_rejects_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
    )
    assert "SmartCampaign search detail flags" in result.output


def test_campaigns_add_rejects_smart_search_with_package_strategy():
    # Regression for codex adversarial review: --smart-search-* flags must
    # not be silently dropped when PackageBiddingStrategy is in use.
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package + Search bad",
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
        "YES",
        "--smart-search-average-cpc",
        "5000000",
    )
    assert "PackageBiddingStrategy" in result.output
    assert "--smart-search-average-cpc" in result.output


def test_campaigns_update_smart_search_budget_type_weekly_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-weekly-spend-limit",
        "40000000",
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "WeeklySpendLimit": 40000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_smart_search_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-search-cp-spend-limit",
        "100000000",
        "--smart-search-cp-start-date",
        "2026-06-01",
        "--smart-search-cp-end-date",
        "2026-06-30",
        "--smart-search-cp-auto-continue",
        "YES",
        "--smart-search-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    search = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Search"
    ]
    assert search == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_smart_search_budget_type_rejects_inconsistency():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        # WEEKLY_BUDGET but no --smart-search-weekly-spend-limit
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--smart-search-weekly-spend-limit" in result.output


def test_campaigns_add_smart_search_budget_type_is_update_only():
    result = _rejected(
        *_smart_search_base(),
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--smart-search-budget-type",
        "WEEKLY_BUDGET",
    )
    # The add command doesn't even register the flag (mirrors how
    # --mobile-search-budget-type is update-only). Click rejects it as
    # "No such option".
    assert (
        "--smart-search-budget-type" in result.output
        or "No such option" in result.output
    )


def _smart_network_base():
    # Search side is built by the shared #367 builder with its default
    # ``SERVING_OFF`` Search container so this fixture exercises ONLY the
    # Network branch (matches the structure of the ``_smart_search_base``
    # helper above).
    return [
        "campaigns",
        "add",
        "--name",
        "Smart Network",
        "--start-date",
        "2026-06-01",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
    ]


def test_campaigns_add_smart_network_default_payload():
    # NETWORK_DEFAULT carries an optional ``LimitPercent`` and nothing
    # else (campaigns.xml 1510-1514). With the percent flag the builder
    # must emit ``Network.NetworkDefault.LimitPercent``.
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--smart-network-limit-percent",
        "80",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "NETWORK_DEFAULT",
        "NetworkDefault": {"LimitPercent": 80},
    }


def test_campaigns_add_smart_network_default_without_limit_percent_payload():
    # ``StrategyNetworkDefaultAdd.LimitPercent`` is ``minOccurs=0``, so
    # an empty NetworkDefault choice without LimitPercent is legal — the
    # builder emits only ``BiddingStrategyType`` for the Network block.
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "NETWORK_DEFAULT",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "NETWORK_DEFAULT"}


def test_campaigns_add_smart_network_average_cpc_per_campaign_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-bid-ceiling",
        "9000000",
        "--smart-network-weekly-spend-limit",
        "50000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "AverageCpc": 5000000,
            "WeeklySpendLimit": 50000000,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_network_average_cpc_per_filter_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-network-filter-average-cpc",
        "3000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_add_smart_network_average_cpa_per_campaign_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-network-average-cpa",
        "4000000",
        "--smart-network-goal-id",
        "111",
        "--smart-network-bid-ceiling",
        "9000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {
            "AverageCpa": 4000000,
            "GoalId": 111,
            "BidCeiling": 9000000,
        },
    }


def test_campaigns_add_smart_network_average_cpa_per_filter_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-network-filter-average-cpa",
        "4500000",
        "--smart-network-goal-id",
        "222",
        "--smart-network-cp-spend-limit",
        "100000000",
        "--smart-network-cp-start-date",
        "2026-06-01",
        "--smart-network-cp-end-date",
        "2026-06-30",
        "--smart-network-cp-auto-continue",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "FilterAverageCpa": 4500000,
            "GoalId": 222,
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
        },
    }


def test_campaigns_add_smart_network_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-network-cpa",
        "6000000",
        "--smart-network-goal-id",
        "333",
        "--smart-network-weekly-spend-limit",
        "50000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {
            "Cpa": 6000000,
            "GoalId": 333,
            "WeeklySpendLimit": 50000000,
        },
    }


def test_campaigns_add_smart_network_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-network-cpa",
        "5500000",
        "--smart-network-goal-id",
        "444",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_add_smart_network_average_roi_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_ROI",
        "--smart-network-reserve-return",
        "30",
        "--smart-network-roi-coef",
        "1500000",
        "--smart-network-goal-id",
        "555",
        "--smart-network-profitability",
        "200000",
        "--smart-network-bid-ceiling",
        "10000000",
        "--smart-network-exploration-min",
        "20000000",
        "--smart-network-exploration-min-custom",
        "YES",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
            "BidCeiling": 10000000,
            "Profitability": 200000,
            "ExplorationBudget": {
                "MinimumExplorationBudget": 20000000,
                "IsMinimumExplorationBudgetCustom": "YES",
            },
        },
    }


def test_campaigns_add_smart_network_average_crr_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CRR",
        "--smart-network-crr",
        "25",
        "--smart-network-goal-id",
        "666",
        "--smart-network-weekly-spend-limit",
        "40000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {
            "Crr": 25,
            "GoalId": 666,
            "WeeklySpendLimit": 40000000,
        },
    }


def test_campaigns_add_smart_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-network-crr",
        "15",
        "--smart-network-goal-id",
        "777",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_add_smart_network_serving_off_payload():
    body = _dry_run(
        *_smart_network_base(),
        "--network-strategy",
        "SERVING_OFF",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {"BiddingStrategyType": "SERVING_OFF"}


def test_campaigns_add_smart_network_requires_average_cpc():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
    )
    assert "--smart-network-average-cpc" in result.output


def test_campaigns_add_smart_network_requires_filter_average_cpa_and_goal():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPA_PER_FILTER",
    )
    assert "--smart-network-filter-average-cpa" in result.output
    assert "--smart-network-goal-id" in result.output


def test_campaigns_add_smart_network_rejects_wrong_subtype_flag():
    # --smart-network-average-cpa belongs only to AverageCpaPerCampaign;
    # using it with AVERAGE_CPC_PER_CAMPAIGN must raise.
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-average-cpa",
        "4000000",
    )
    assert "--smart-network-average-cpa" in result.output


def test_campaigns_add_smart_network_rejects_bid_ceiling_on_crr():
    # WSDL StrategyAverageCrrAdd has no BidCeiling field
    # (campaigns.xml 1465-1473).
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CRR",
        "--smart-network-crr",
        "15",
        "--smart-network-goal-id",
        "777",
        "--smart-network-bid-ceiling",
        "10000000",
    )
    assert "--smart-network-bid-ceiling" in result.output


def test_campaigns_add_smart_network_rejects_exploration_on_cpc_per_campaign():
    # WSDL StrategyAverageCpcPerCampaignAdd has no ExplorationBudget
    # (campaigns.xml 1437-1444).
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-exploration-min",
        "1000000",
        "--smart-network-exploration-min-custom",
        "YES",
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_network_rejects_limit_percent_on_non_network_default():
    # ``LimitPercent`` lives on ``StrategyNetworkDefaultAdd`` only
    # (campaigns.xml 1510-1514).
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-limit-percent",
        "50",
    )
    assert "--smart-network-limit-percent" in result.output


def test_campaigns_add_smart_network_rejects_partial_custom_period_budget():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-cp-spend-limit",
        "100000000",
        # Missing start-date / end-date / auto-continue.
    )
    assert "CustomPeriodBudget" in result.output


def test_campaigns_add_smart_network_rejects_partial_exploration_budget():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_ROI",
        "--smart-network-reserve-return",
        "30",
        "--smart-network-roi-coef",
        "1500000",
        "--smart-network-goal-id",
        "555",
        "--smart-network-exploration-min",
        "20000000",
        # missing --smart-network-exploration-min-custom
    )
    assert "ExplorationBudget" in result.output


def test_campaigns_add_smart_network_rejects_detail_without_strategy():
    # Typed flag without --network-strategy must fail rather than
    # silently picking a default subtype.
    result = _rejected(
        *_smart_network_base(),
        "--smart-network-average-cpc",
        "5000000",
    )
    assert "SmartCampaign network detail flags" in result.output


def test_campaigns_add_smart_network_rejects_serving_off_with_details():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "SERVING_OFF",
        "--smart-network-average-cpc",
        "5000000",
    )
    assert "SERVING_OFF" in result.output


def test_campaigns_add_smart_network_rejects_invalid_strategy():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "BOGUS_STRATEGY",
    )
    assert "SMART_CAMPAIGN" in result.output


def test_campaigns_add_smart_network_rejects_weekly_and_custom_period():
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-weekly-spend-limit",
        "50000000",
        "--smart-network-cp-spend-limit",
        "100000000",
        "--smart-network-cp-start-date",
        "2026-06-01",
        "--smart-network-cp-end-date",
        "2026-06-30",
        "--smart-network-cp-auto-continue",
        "YES",
    )
    assert "--smart-network-weekly-spend-limit" in result.output
    assert "--smart-network-cp-spend-limit" in result.output


def test_campaigns_add_smart_network_budget_type_is_update_only():
    # The add command does not register --smart-network-budget-type, so
    # Click rejects it before the builder runs (matches the
    # ``--smart-search-budget-type`` convention from #367).
    result = _rejected(
        *_smart_network_base(),
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
        "--smart-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert (
        "--smart-network-budget-type" in result.output
        or "No such option" in result.output
    )


def test_campaigns_update_smart_network_default_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "NETWORK_DEFAULT",
        "--smart-network-limit-percent",
        "70",
    )
    campaign = body["params"]["Campaigns"][0]
    assert campaign == {
        "Id": 55,
        "SmartCampaign": {
            "BiddingStrategy": {
                "Network": {
                    "BiddingStrategyType": "NETWORK_DEFAULT",
                    "NetworkDefault": {"LimitPercent": 70},
                }
            }
        },
    }


def test_campaigns_update_smart_network_average_cpc_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {"AverageCpc": 5000000},
    }


def test_campaigns_update_smart_network_average_cpc_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_FILTER",
        "--smart-network-filter-average-cpc",
        "3000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_FILTER",
        "AverageCpcPerFilter": {"FilterAverageCpc": 3000000},
    }


def test_campaigns_update_smart_network_average_cpa_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-network-average-cpa",
        "4000000",
        "--smart-network-goal-id",
        "111",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000, "GoalId": 111},
    }


def test_campaigns_update_smart_network_average_cpa_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-network-filter-average-cpa",
        "4500000",
        "--smart-network-goal-id",
        "222",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {"FilterAverageCpa": 4500000, "GoalId": 222},
    }


def test_campaigns_update_smart_network_pay_for_conversion_per_campaign_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "--smart-network-cpa",
        "6000000",
        "--smart-network-goal-id",
        "333",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_CAMPAIGN",
        "PayForConversionPerCampaign": {"Cpa": 6000000, "GoalId": 333},
    }


def test_campaigns_update_smart_network_pay_for_conversion_per_filter_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_PER_FILTER",
        "--smart-network-cpa",
        "5500000",
        "--smart-network-goal-id",
        "444",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_PER_FILTER",
        "PayForConversionPerFilter": {"Cpa": 5500000, "GoalId": 444},
    }


def test_campaigns_update_smart_network_average_roi_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_ROI",
        "--smart-network-reserve-return",
        "30",
        "--smart-network-roi-coef",
        "1500000",
        "--smart-network-goal-id",
        "555",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_ROI",
        "AverageRoi": {
            "ReserveReturn": 30,
            "RoiCoef": 1500000,
            "GoalId": 555,
        },
    }


def test_campaigns_update_smart_network_average_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CRR",
        "--smart-network-crr",
        "25",
        "--smart-network-goal-id",
        "666",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CRR",
        "AverageCrr": {"Crr": 25, "GoalId": 666},
    }


def test_campaigns_update_smart_network_pay_for_conversion_crr_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "PAY_FOR_CONVERSION_CRR",
        "--smart-network-crr",
        "15",
        "--smart-network-goal-id",
        "777",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "PAY_FOR_CONVERSION_CRR",
        "PayForConversionCrr": {"Crr": 15, "GoalId": 777},
    }


def test_campaigns_update_smart_network_partial_field_no_required_check():
    # On update, WSDL minOccurs=1 required-field validation is skipped so
    # users can patch a single field (matches Search / CpmBanner /
    # MobileApp update semantics).
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        # Only --smart-network-average-cpa, no --smart-network-goal-id
        "--smart-network-average-cpa",
        "4000000",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
        "AverageCpaPerCampaign": {"AverageCpa": 4000000},
    }


def test_campaigns_update_smart_network_omits_bidding_strategy_when_unused():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--counter-id",
        "123",
    )
    smart = body["params"]["Campaigns"][0]["SmartCampaign"]
    assert "BiddingStrategy" not in smart
    assert smart == {"CounterId": 123}


def test_campaigns_update_smart_network_search_and_network_both_set_payload():
    # Updating Search + Network in one shot should emit both nested keys
    # under the single ``BiddingStrategy`` container.
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--search-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-search-average-cpc",
        "5000000",
        "--network-strategy",
        "AVERAGE_CPA_PER_CAMPAIGN",
        "--smart-network-average-cpa",
        "4000000",
        "--smart-network-goal-id",
        "111",
    )
    bidding = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"]
    assert bidding == {
        "Search": {
            "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
            "AverageCpcPerCampaign": {"AverageCpc": 5000000},
        },
        "Network": {
            "BiddingStrategyType": "AVERAGE_CPA_PER_CAMPAIGN",
            "AverageCpaPerCampaign": {"AverageCpa": 4000000, "GoalId": 111},
        },
    }


def test_campaigns_update_smart_network_rejects_package_with_network_flags():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--package-strategy-id",
        "700",
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
    )
    assert "PackageBiddingStrategy" in result.output


def test_campaigns_update_smart_network_rejects_detail_without_strategy():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
    )
    assert "SmartCampaign network detail flags" in result.output


def test_campaigns_update_smart_network_budget_type_weekly_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-weekly-spend-limit",
        "40000000",
        "--smart-network-budget-type",
        "WEEKLY_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPC_PER_CAMPAIGN",
        "AverageCpcPerCampaign": {
            "WeeklySpendLimit": 40000000,
            "CustomPeriodBudget": None,
            "BudgetType": "WEEKLY_BUDGET",
        },
    }


def test_campaigns_update_smart_network_budget_type_custom_period_payload():
    body = _dry_run(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPA_PER_FILTER",
        "--smart-network-cp-spend-limit",
        "100000000",
        "--smart-network-cp-start-date",
        "2026-06-01",
        "--smart-network-cp-end-date",
        "2026-06-30",
        "--smart-network-cp-auto-continue",
        "YES",
        "--smart-network-budget-type",
        "CUSTOM_PERIOD_BUDGET",
    )
    network = body["params"]["Campaigns"][0]["SmartCampaign"]["BiddingStrategy"][
        "Network"
    ]
    assert network == {
        "BiddingStrategyType": "AVERAGE_CPA_PER_FILTER",
        "AverageCpaPerFilter": {
            "CustomPeriodBudget": {
                "SpendLimit": 100000000,
                "StartDate": "2026-06-01",
                "EndDate": "2026-06-30",
                "AutoContinue": "YES",
            },
            "WeeklySpendLimit": None,
            "BudgetType": "CUSTOM_PERIOD_BUDGET",
        },
    }


def test_campaigns_update_smart_network_budget_type_rejects_inconsistency():
    result = _rejected(
        "campaigns",
        "update",
        "--id",
        "55",
        "--type",
        "SMART_CAMPAIGN",
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        # WEEKLY_BUDGET but no --smart-network-weekly-spend-limit
        "--smart-network-budget-type",
        "WEEKLY_BUDGET",
    )
    assert "--smart-network-weekly-spend-limit" in result.output


def test_campaigns_add_rejects_smart_network_with_package_strategy():
    # Regression mirror of ``smart_search_with_package_strategy``: typed
    # --smart-network-* flags must not be silently dropped when
    # PackageBiddingStrategy is in use on add.
    #
    # On add the existing PackageBiddingStrategy check raises at the
    # subtype-level flag-incompatibility gate (--network-strategy is
    # rejected before the builder runs).
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package + Network bad",
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
        "YES",
        "--network-strategy",
        "AVERAGE_CPC_PER_CAMPAIGN",
        "--smart-network-average-cpc",
        "5000000",
    )
    # PackageBiddingStrategy + any subtype-specific flag must be rejected.
    assert (
        "PackageBiddingStrategy" in result.output or "--smart-network" in result.output
    )


def test_campaigns_add_rejects_smart_network_detail_flag_with_package_strategy():
    # Adversarial regression: when PackageBiddingStrategy is in use the
    # SmartCampaign add path takes a branch that bypasses the per-subtype
    # builder altogether. Without an explicit entry in the package
    # incompatibility map, a bare --smart-network-* detail flag (no
    # --network-strategy, no --filter-average-cpc) would be silently
    # dropped — the user would expect their bid intent applied but the
    # API would only receive the package strategy. The mutex must list
    # every #368 typed flag.
    result = _rejected(
        "campaigns",
        "add",
        "--name",
        "Smart Package + Network detail bad",
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
        "YES",
        "--smart-network-average-cpc",
        "5000000",
    )
    assert "PackageBiddingStrategy" in result.output
    assert "--smart-network-average-cpc" in result.output


def _cpa_base_args():
    return [
        "campaigns",
        "add",
        "--name",
        "CPA Campaign",
        "--start-date",
        "2026-06-01",
        "--type",
        "TEXT_CAMPAIGN",
    ]

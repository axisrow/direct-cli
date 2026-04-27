"""Resource mapping and supported method registry for Yandex Direct API v4 Live (JSON).

v4 Live exposes a single RPC endpoint (live/v4/json/) — the operation name is
carried in the JSON body, not the URL. RESOURCE_MAPPING_V4_LIVE is therefore a
single-entry dict so the tapi-wrapper2 framework still sees a well-formed
mapping. The catalogue of operations the client knows about is in
SUPPORTED_V4_METHODS — every entry here corresponds to an "actual_no_v5_analogue"
method from docs/v4_methods_matrix.md.
"""

RESOURCE_MAPPING_V4_LIVE = {
    "v4live": {
        "resource": "live/v4/json/",
        "docs": "https://yandex.com/dev/direct/doc/dg-v4/en/live/concepts",
        "methods": [],
    },
}


SUPPORTED_V4_METHODS: dict[str, dict] = {
    # Finance — high priority candidates from the matrix.
    # Note: GetBalance was removed by Yandex from v4 Live (error_code 509);
    # use the v5 client and read campaigns.get → Funds instead.
    "GetClientsUnits":         {"group": "finance"},
    "GetCreditLimits":         {"group": "finance"},
    "TransferMoney":           {"group": "finance"},
    "PayCampaigns":            {"group": "finance"},
    "PayCampaignsByCard":      {"group": "finance"},
    "CheckPayment":            {"group": "finance"},
    "CreateInvoice":           {"group": "finance"},
    # Shared account
    "AccountManagement":       {"group": "shared_account"},
    "EnableSharedAccount":     {"group": "shared_account"},
    # Events
    "GetEventsLog":            {"group": "events"},
    # Goals
    "GetStatGoals":            {"group": "goals"},
    "GetRetargetingGoals":     {"group": "goals"},
    # Wordstat
    "CreateNewWordstatReport": {"group": "wordstat"},
    "GetWordstatReportList":   {"group": "wordstat"},
    "GetWordstatReport":       {"group": "wordstat"},
    "DeleteWordstatReport":    {"group": "wordstat"},
    # Forecast
    "CreateNewForecast":       {"group": "forecast"},
    "GetForecastList":         {"group": "forecast"},
    "GetForecast":             {"group": "forecast"},
    "DeleteForecastReport":    {"group": "forecast"},
    # Offline reports
    "DeleteOfflineReport":     {"group": "offline_reports"},
    "DeleteReport":            {"group": "offline_reports"},
    # Tags (Live-only)
    "GetBannersTags":          {"group": "tags"},
    "GetCampaignsTags":        {"group": "tags"},
    "UpdateBannersTags":       {"group": "tags"},
    "UpdateCampaignsTags":     {"group": "tags"},
    # Ad image association
    "AdImageAssociation":      {"group": "ad_image"},
    # Keyword suggestions — phrase-suggestion engine, no real v5 analogue
    "GetKeywordsSuggestion":   {"group": "keywords"},
    # API meta
    "PingAPI":                 {"group": "meta"},
    "PingAPI_X":               {"group": "meta"},
    "GetVersion":              {"group": "meta"},
    "GetAvailableVersions":    {"group": "meta"},
}

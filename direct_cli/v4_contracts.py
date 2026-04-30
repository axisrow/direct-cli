"""Contract registry for Yandex Direct v4 Live methods."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from direct_cli._vendor.tapi_yandex_direct.v4 import SUPPORTED_V4_METHODS

PARAM_ARRAY = "array"
PARAM_OBJECT = "object"
PARAM_OPTIONAL_OBJECT = "optional-object"
PARAM_SCALAR = "scalar"
PARAM_UNDOCUMENTED = "undocumented"

SAFETY_READ = "read"
SAFETY_WRITE = "write"
SAFETY_DANGEROUS = "dangerous"
SAFETY_ASYNC = "async"
SAFETY_MIXED = "mixed"

SOURCE_CONFIRMED_LIVE = "confirmed-live"
SOURCE_DOCS = "docs"
SOURCE_UNDOCUMENTED = "undocumented"


@dataclass(frozen=True)
class V4MethodContract:
    """A known v4 Live method contract."""

    method: str
    group: str
    param_shape: str
    login_placement: str
    safety: str
    source_status: str
    live_probe_allowed: bool
    example_param: Any = None
    notes: str = ""


V4_METHOD_CONTRACTS: dict[str, V4MethodContract] = {
    "GetClientsUnits": V4MethodContract(
        method="GetClientsUnits",
        group="finance",
        param_shape=PARAM_ARRAY,
        login_placement="param is a list of client logins",
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param=["client-login"],
        notes="Live rejects object params with error_code=9; pass the login array directly.",
    ),
    "GetCreditLimits": V4MethodContract(
        method="GetCreditLimits",
        group="finance",
        param_shape=PARAM_ARRAY,
        login_placement=(
            "param is a list of client logins; finance_token and "
            "operation_num are top-level v4 Live body fields"
        ),
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=False,
        example_param=["client-login"],
        notes=(
            "Requires finance_token and operation_num at the top level. "
            "Live probe without them returns error_code=350."
        ),
    ),
    "TransferMoney": V4MethodContract(
        method="TransferMoney",
        group="finance",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains FromCampaigns/ToCampaigns; finance_token and "
            "operation_num are top-level v4 Live body fields"
        ),
        safety=SAFETY_DANGEROUS,
        source_status=SOURCE_DOCS,
        live_probe_allowed=False,
        example_param={
            "FromCampaigns": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
            "ToCampaigns": [{"CampaignID": 456, "Sum": 100.5, "Currency": "RUB"}],
        },
        notes=(
            "Official v4 docs define campaign-to-campaign transfer with "
            "Currency on each transfer item. "
            "This CLI exposes dry-run only; the method is not live-probed."
        ),
    ),
    "PayCampaigns": V4MethodContract(
        method="PayCampaigns",
        group="finance",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains Payments/ContractID/PayMethod; finance_token and "
            "operation_num are top-level v4 Live body fields"
        ),
        safety=SAFETY_DANGEROUS,
        source_status=SOURCE_DOCS,
        live_probe_allowed=False,
        example_param={
            "Payments": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
            "ContractID": "contract-id",
            "PayMethod": "Bank",
        },
        notes=(
            "Official v4 docs define agency credit-limit payment with "
            "Currency on each payment item and PayMethod Bank/Overdraft. "
            "This CLI exposes dry-run only; the method is not live-probed."
        ),
    ),
    "PayCampaignsByCard": V4MethodContract(
        method="PayCampaignsByCard",
        group="finance",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_DANGEROUS,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "CheckPayment": V4MethodContract(
        method="CheckPayment",
        group="finance",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains CustomTransactionID; global --login uses "
            "Client-Login header"
        ),
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param={"CustomTransactionID": "A123456789012345678901234567890B"},
        notes=(
            "Official public docs were not found. Sandbox v4 Live rejects "
            "PaymentID with error_code=71 and requires CustomTransactionID; "
            "a valid 32-character unknown CustomTransactionID reaches method "
            "validation and returns error_code=370."
        ),
    ),
    "CreateInvoice": V4MethodContract(
        method="CreateInvoice",
        group="finance",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains Payments; finance_token and operation_num are "
            "top-level v4 Live body fields"
        ),
        safety=SAFETY_DANGEROUS,
        source_status=SOURCE_DOCS,
        live_probe_allowed=False,
        example_param={
            "Payments": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
        },
        notes=(
            "Official v4 docs define invoice creation with Payments[]."
            "CampaignID/Sum/Currency and a URL response. The method has no "
            "v5 equivalent and requires finance_token plus operation_num."
        ),
    ),
    "AccountManagement": V4MethodContract(
        method="AccountManagement",
        group="shared_account",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains only documented method fields; global --login uses "
            "Client-Login header"
        ),
        safety=SAFETY_MIXED,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param={"Action": "Get"},
        notes=(
            "Action=Get is live-confirmed read-only and returns "
            "Accounts[].Amount/Currency; the docs-backed Update action changes "
            "shared-account settings with Accounts[].AccountID, AccountDayBudget, "
            "SmsNotification, and EmailNotification. The v4account Update command "
            "is production dry-run-only and can be sent live only with --sandbox."
        ),
    ),
    "EnableSharedAccount": V4MethodContract(
        method="EnableSharedAccount",
        group="shared_account",
        param_shape=PARAM_OBJECT,
        login_placement="param contains Login for the client shared account",
        safety=SAFETY_DANGEROUS,
        source_status=SOURCE_DOCS,
        live_probe_allowed=False,
        example_param={"Login": "client-login"},
        notes=(
            "Official v4 docs define one Login field. Enabling a shared account "
            "transfers campaign funds, so this CLI requires dry-run in production "
            "and permits live execution only with --sandbox."
        ),
    ),
    "GetEventsLog": V4MethodContract(
        method="GetEventsLog",
        group="events",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains timestamps, Currency, and optional Limit/Offset; "
            "global --login uses Client-Login header"
        ),
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param={
            "TimestampFrom": "2026-04-14T00:00:00",
            "TimestampTo": "2026-04-14T01:00:00",
            "Currency": "RUB",
        },
        notes="Currency is required by live API; omitting it returns error_code=245.",
    ),
    "GetStatGoals": V4MethodContract(
        method="GetStatGoals",
        group="goals",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains only documented method fields; global --login uses "
            "Client-Login header"
        ),
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param={"CampaignIDS": [123]},
        notes="Official docs and live probe confirm CampaignIDS.",
    ),
    "GetRetargetingGoals": V4MethodContract(
        method="GetRetargetingGoals",
        group="goals",
        param_shape=PARAM_OBJECT,
        login_placement=(
            "param contains only documented method fields; global --login uses "
            "Client-Login header"
        ),
        safety=SAFETY_READ,
        source_status=SOURCE_CONFIRMED_LIVE,
        live_probe_allowed=True,
        example_param={"CampaignIDS": [123]},
        notes="Standalone public method page was not discoverable; live probe confirms CampaignIDS.",
    ),
    "CreateNewWordstatReport": V4MethodContract(
        method="CreateNewWordstatReport",
        group="wordstat",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_ASYNC,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetWordstatReportList": V4MethodContract(
        method="GetWordstatReportList",
        group="wordstat",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetWordstatReport": V4MethodContract(
        method="GetWordstatReport",
        group="wordstat",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "DeleteWordstatReport": V4MethodContract(
        method="DeleteWordstatReport",
        group="wordstat",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "CreateNewForecast": V4MethodContract(
        method="CreateNewForecast",
        group="forecast",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_ASYNC,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetForecastList": V4MethodContract(
        method="GetForecastList",
        group="forecast",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetForecast": V4MethodContract(
        method="GetForecast",
        group="forecast",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "DeleteForecastReport": V4MethodContract(
        method="DeleteForecastReport",
        group="forecast",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "DeleteOfflineReport": V4MethodContract(
        method="DeleteOfflineReport",
        group="offline_reports",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "DeleteReport": V4MethodContract(
        method="DeleteReport",
        group="offline_reports",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetBannersTags": V4MethodContract(
        method="GetBannersTags",
        group="tags",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetCampaignsTags": V4MethodContract(
        method="GetCampaignsTags",
        group="tags",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "UpdateBannersTags": V4MethodContract(
        method="UpdateBannersTags",
        group="tags",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "UpdateCampaignsTags": V4MethodContract(
        method="UpdateCampaignsTags",
        group="tags",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "AdImageAssociation": V4MethodContract(
        method="AdImageAssociation",
        group="ad_image",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_WRITE,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetKeywordsSuggestion": V4MethodContract(
        method="GetKeywordsSuggestion",
        group="keywords",
        param_shape=PARAM_UNDOCUMENTED,
        login_placement="unknown",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "PingAPI": V4MethodContract(
        method="PingAPI",
        group="meta",
        param_shape=PARAM_OPTIONAL_OBJECT,
        login_placement="none",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "PingAPI_X": V4MethodContract(
        method="PingAPI_X",
        group="meta",
        param_shape=PARAM_OPTIONAL_OBJECT,
        login_placement="none",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetVersion": V4MethodContract(
        method="GetVersion",
        group="meta",
        param_shape=PARAM_OPTIONAL_OBJECT,
        login_placement="none",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
    "GetAvailableVersions": V4MethodContract(
        method="GetAvailableVersions",
        group="meta",
        param_shape=PARAM_OPTIONAL_OBJECT,
        login_placement="none",
        safety=SAFETY_READ,
        source_status=SOURCE_UNDOCUMENTED,
        live_probe_allowed=False,
    ),
}


def get_v4_contract(method: str) -> V4MethodContract:
    """Return the known contract for one v4 Live method."""
    try:
        return V4_METHOD_CONTRACTS[method]
    except KeyError as exc:
        valid_methods = ", ".join(sorted(V4_METHOD_CONTRACTS))
        raise ValueError(
            f"Unknown v4 Live method {method!r}. Valid methods: {valid_methods}"
        ) from exc


def v4_method_contract(method: str):
    """Attach a v4 Live method contract to a Click command."""
    contract = get_v4_contract(method)

    def decorator(command):
        command.v4_method = method
        command.v4_contract = contract
        return command

    return decorator


def validate_v4_contract_registry() -> list[str]:
    """Return registry consistency errors."""
    errors = []

    supported = set(SUPPORTED_V4_METHODS)
    registered = set(V4_METHOD_CONTRACTS)
    missing = sorted(supported - registered)
    stale = sorted(registered - supported)
    if missing:
        errors.append(f"Missing v4 contract entries: {missing}")
    if stale:
        errors.append(f"Stale v4 contract entries: {stale}")

    valid_shapes = {
        PARAM_ARRAY,
        PARAM_OBJECT,
        PARAM_OPTIONAL_OBJECT,
        PARAM_SCALAR,
        PARAM_UNDOCUMENTED,
    }
    valid_safety = {
        SAFETY_READ,
        SAFETY_WRITE,
        SAFETY_DANGEROUS,
        SAFETY_ASYNC,
        SAFETY_MIXED,
    }
    valid_sources = {
        SOURCE_CONFIRMED_LIVE,
        SOURCE_DOCS,
        SOURCE_UNDOCUMENTED,
    }

    for method, contract in sorted(V4_METHOD_CONTRACTS.items()):
        expected_group = SUPPORTED_V4_METHODS.get(method, {}).get("group")
        if expected_group and contract.group != expected_group:
            errors.append(
                f"{method} group mismatch: {contract.group!r} != {expected_group!r}"
            )
        if contract.method != method:
            errors.append(f"{method} contract.method mismatch: {contract.method!r}")
        if contract.param_shape not in valid_shapes:
            errors.append(f"{method} has invalid param_shape: {contract.param_shape}")
        if contract.safety not in valid_safety:
            errors.append(f"{method} has invalid safety: {contract.safety}")
        if contract.source_status not in valid_sources:
            errors.append(
                f"{method} has invalid source_status: {contract.source_status}"
            )
        if not contract.login_placement:
            errors.append(f"{method} missing login_placement")
        if contract.live_probe_allowed and contract.safety not in {
            SAFETY_READ,
            SAFETY_MIXED,
        }:
            errors.append(f"{method} live probe allowed for unsafe safety")
        if contract.live_probe_allowed and contract.example_param is None:
            errors.append(f"{method} live probe missing example_param")

    return errors

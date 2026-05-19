import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from direct_cli._vendor.tapi_yandex_direct.v4 import SUPPORTED_V4_METHODS
from direct_cli.cli import cli
from direct_cli.v4 import build_v4_body, call_v4
from direct_cli.v4_contracts import (
    PARAM_ARRAY,
    PARAM_OBJECT,
    PARAM_OPTIONAL_OBJECT,
    PARAM_SCALAR,
    PARAM_UNDOCUMENTED,
    SOURCE_CONFIRMED_LIVE,
    SOURCE_DOCS,
    V4_METHOD_CONTRACTS,
    get_v4_contract,
    v4_method_contract,
    validate_v4_body_shape,
    validate_v4_contract_registry,
)

V4_CLI_DRY_RUN_FIXTURES = {
    "balance": ["balance", "--logins", "client-login"],
    "v4account.account-management": [
        "v4account",
        "account-management",
        "--action",
        "Update",
        "--account-id",
        "1",
        "--money-in-sms",
        "Yes",
    ],
    "v4account.enable-shared-account": [
        "v4account",
        "enable-shared-account",
        "--client-login",
        "client-login",
    ],
    "v4events.get-events-log": [
        "v4events",
        "get-events-log",
        "--from",
        "2026-04-14T00:00:00",
        "--to",
        "2026-04-14T01:00:00",
    ],
    "v4finance.check-payment": [
        "v4finance",
        "check-payment",
        "--custom-transaction-id",
        "A123456789012345678901234567890B",
    ],
    "v4finance.create-invoice": [
        "v4finance",
        "create-invoice",
        "--payment",
        "123=100.50",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "1",
    ],
    "v4finance.get-clients-units": [
        "v4finance",
        "get-clients-units",
        "--logins",
        "client-login",
    ],
    "v4finance.get-credit-limits": [
        "v4finance",
        "get-credit-limits",
        "--logins",
        "client-login",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "1",
    ],
    "v4finance.pay-campaigns": [
        "v4finance",
        "pay-campaigns",
        "--campaign-ids",
        "123",
        "--amount",
        "100.50",
        "--pay-method",
        "Bank",
        "--contract-id",
        "contract-id",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "1",
    ],
    "v4finance.transfer-money": [
        "v4finance",
        "transfer-money",
        "--from-campaign-id",
        "123",
        "--to-campaign-id",
        "456",
        "--amount",
        "100.50",
        "--finance-token",
        "finance-token",
        "--operation-num",
        "1",
    ],
    "v4forecast.create": [
        "v4forecast",
        "create",
        "--phrases",
        "buy laptop",
    ],
    "v4forecast.delete": ["v4forecast", "delete", "--forecast-id", "1"],
    "v4forecast.get": ["v4forecast", "get", "--forecast-id", "1"],
    "v4forecast.list": ["v4forecast", "list"],
    "v4goals.get-retargeting-goals": [
        "v4goals",
        "get-retargeting-goals",
        "--campaign-ids",
        "123",
    ],
    "v4goals.get-stat-goals": [
        "v4goals",
        "get-stat-goals",
        "--campaign-ids",
        "123",
    ],
    "v4tags.get-banners": ["v4tags", "get-banners", "--banner-ids", "123"],
    "v4tags.get-campaigns": [
        "v4tags",
        "get-campaigns",
        "--campaign-ids",
        "123",
    ],
    "v4tags.update-banners": [
        "v4tags",
        "update-banners",
        "--banner-ids",
        "123",
        "--tag-ids",
        "1",
    ],
    "v4tags.update-campaigns": [
        "v4tags",
        "update-campaigns",
        "--campaign-id",
        "123",
        "--tag",
        "0=test",
    ],
    "v4wordstat.create-report": [
        "v4wordstat",
        "create-report",
        "--phrases",
        "buy laptop",
    ],
    "v4wordstat.delete-report": [
        "v4wordstat",
        "delete-report",
        "--report-id",
        "1",
    ],
    "v4wordstat.get-report": ["v4wordstat", "get-report", "--report-id", "1"],
    "v4wordstat.list-reports": ["v4wordstat", "list-reports"],
}


def _v4_cli_command_methods() -> dict[str, str]:
    """Return CLI command label -> registered v4 Live method."""
    commands = {}
    for group_name, command in sorted(cli.commands.items()):
        method = getattr(command, "v4_method", None)
        if method:
            commands[group_name] = method
        if hasattr(command, "commands"):
            for command_name, subcommand in sorted(command.commands.items()):
                method = getattr(subcommand, "v4_method", None)
                if method:
                    commands[f"{group_name}.{command_name}"] = method
    return commands


def _v4_dry_run_body(argv: list[str]) -> dict:
    result = CliRunner().invoke(cli, list(argv) + ["--dry-run"])
    assert result.exit_code == 0, (
        f"command failed: direct {' '.join(argv)} --dry-run\n"
        f"output: {result.output}\n"
        f"exception: {result.exception}"
    )
    return json.loads(result.output)


def test_v4_contract_registry_covers_supported_methods_exactly():
    assert validate_v4_contract_registry() == []
    assert set(V4_METHOD_CONTRACTS) == set(SUPPORTED_V4_METHODS)


def test_v4_contract_registry_has_explicit_policy_for_every_method():
    for method, contract in V4_METHOD_CONTRACTS.items():
        assert contract.method == method
        assert contract.group == SUPPORTED_V4_METHODS[method]["group"]
        assert contract.param_shape
        assert contract.login_placement
        assert contract.safety
        assert contract.source_status
        assert isinstance(contract.live_probe_allowed, bool)


def test_v4_cli_dry_run_fixtures_cover_exposed_contract_commands():
    commands = _v4_cli_command_methods()

    assert set(V4_CLI_DRY_RUN_FIXTURES) == set(commands), (
        "V4 dry-run shape fixtures are out of date.\n"
        f"Missing fixtures: {sorted(set(commands) - set(V4_CLI_DRY_RUN_FIXTURES))}\n"
        f"Stale fixtures: {sorted(set(V4_CLI_DRY_RUN_FIXTURES) - set(commands))}"
    )


@pytest.mark.parametrize("command_label", sorted(V4_CLI_DRY_RUN_FIXTURES))
def test_v4_cli_dry_run_body_matches_registered_param_shape(command_label):
    method = _v4_cli_command_methods()[command_label]
    body = _v4_dry_run_body(V4_CLI_DRY_RUN_FIXTURES[command_label])

    assert validate_v4_body_shape(method, body) == []


def test_v4_body_shape_validator_rejects_wrong_param_shape():
    assert validate_v4_body_shape(
        "GetClientsUnits",
        {"method": "GetClientsUnits", "param": {"Login": "client-login"}},
    ) == ["GetClientsUnits param must be an array"]

    assert validate_v4_body_shape(
        "CheckPayment",
        {"method": "CheckPayment", "param": ["A123456789012345678901234567890B"]},
    ) == ["CheckPayment param must be an object"]

    assert validate_v4_body_shape(
        "GetForecastList",
        {"method": "GetForecastList", "param": 123},
    ) == ["GetForecastList param must be omitted or an object"]

    assert validate_v4_body_shape(
        "GetForecast",
        {"method": "GetForecast", "param": {"ForecastID": 1}},
    ) == ["GetForecast param must be a scalar"]

    assert validate_v4_body_shape(
        "PayCampaignsByCard",
        {"method": "PayCampaignsByCard", "param": {}},
    ) == ["PayCampaignsByCard param shape is undocumented"]


def test_confirmed_contracts_are_not_undocumented():
    confirmed = [
        contract
        for contract in V4_METHOD_CONTRACTS.values()
        if contract.source_status == SOURCE_CONFIRMED_LIVE
    ]

    assert {contract.method for contract in confirmed} == {
        "AccountManagement",
        "GetClientsUnits",
        "GetCreditLimits",
        "CheckPayment",
        "GetEventsLog",
        "GetStatGoals",
        "GetRetargetingGoals",
    }
    for contract in confirmed:
        assert contract.param_shape != PARAM_UNDOCUMENTED
        assert contract.example_param is not None

    assert {
        contract.method for contract in confirmed if contract.live_probe_allowed
    } == {
        "AccountManagement",
        "GetClientsUnits",
        "CheckPayment",
        "GetEventsLog",
        "GetStatGoals",
        "GetRetargetingGoals",
    }


def test_get_clients_units_contract_uses_array_param():
    contract = get_v4_contract("GetClientsUnits")

    assert contract.example_param == ["client-login"]
    assert build_v4_body("GetClientsUnits", ["client-login"]) == {
        "method": "GetClientsUnits",
        "param": ["client-login"],
    }


def test_account_management_get_contract_returns_money_balance():
    contract = get_v4_contract("AccountManagement")

    assert contract.example_param == {"Action": "Get"}
    assert "docs-backed Update action" in contract.notes
    assert build_v4_body("AccountManagement", {"Action": "Get"}) == {
        "method": "AccountManagement",
        "param": {"Action": "Get"},
    }


def test_account_management_update_contract_uses_shared_account_objects():
    param = {
        "Action": "Update",
        "Accounts": [
            {
                "AccountID": 1327944,
                "SmsNotification": {
                    "MoneyInSms": "Yes",
                    "MoneyOutSms": "Yes",
                },
                "EmailNotification": {
                    "Email": "agrom@yandex.ru",
                    "MoneyWarningValue": 25,
                },
            }
        ],
    }

    assert build_v4_body("AccountManagement", param) == {
        "method": "AccountManagement",
        "param": param,
    }


def test_enable_shared_account_contract_is_docs_backed_dangerous_object():
    contract = get_v4_contract("EnableSharedAccount")

    assert contract.param_shape == PARAM_OBJECT
    assert contract.source_status == SOURCE_DOCS
    assert contract.example_param == {"Login": "client-login"}
    assert build_v4_body("EnableSharedAccount", contract.example_param) == {
        "method": "EnableSharedAccount",
        "param": {"Login": "client-login"},
    }


def test_get_credit_limits_contract_uses_login_array_and_finance_top_level():
    contract = get_v4_contract("GetCreditLimits")

    assert contract.param_shape == PARAM_ARRAY
    assert contract.example_param == ["client-login"]
    assert "finance_token" in contract.login_placement
    assert build_v4_body("GetCreditLimits", ["client-login"]) == {
        "method": "GetCreditLimits",
        "param": ["client-login"],
    }


def test_v4finance_money_contracts_are_docs_backed_dangerous_objects():
    transfer = get_v4_contract("TransferMoney")
    pay = get_v4_contract("PayCampaigns")
    create_invoice = get_v4_contract("CreateInvoice")

    assert transfer.param_shape == PARAM_OBJECT
    assert transfer.source_status == SOURCE_DOCS
    assert "finance_token" in transfer.login_placement
    assert build_v4_body("TransferMoney", transfer.example_param) == {
        "method": "TransferMoney",
        "param": {
            "FromCampaigns": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
            "ToCampaigns": [{"CampaignID": 456, "Sum": 100.5, "Currency": "RUB"}],
        },
    }

    assert pay.param_shape == PARAM_OBJECT
    assert pay.source_status == SOURCE_DOCS
    assert "finance_token" in pay.login_placement
    assert build_v4_body("PayCampaigns", pay.example_param) == {
        "method": "PayCampaigns",
        "param": {
            "Payments": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
            "ContractID": "contract-id",
            "PayMethod": "Bank",
        },
    }

    assert create_invoice.param_shape == PARAM_OBJECT
    assert create_invoice.source_status == SOURCE_DOCS
    assert "finance_token" in create_invoice.login_placement
    assert "PayCampaignsByCard" in V4_METHOD_CONTRACTS
    assert get_v4_contract("PayCampaignsByCard").param_shape == PARAM_UNDOCUMENTED
    assert build_v4_body("CreateInvoice", create_invoice.example_param) == {
        "method": "CreateInvoice",
        "param": {
            "Payments": [{"CampaignID": 123, "Sum": 100.5, "Currency": "RUB"}],
        },
    }


def test_v4tags_contracts_are_docs_backed_objects_and_arrays():
    get_campaigns = get_v4_contract("GetCampaignsTags")
    get_banners = get_v4_contract("GetBannersTags")
    update_campaigns = get_v4_contract("UpdateCampaignsTags")
    update_banners = get_v4_contract("UpdateBannersTags")

    assert get_campaigns.param_shape == PARAM_OBJECT
    assert get_campaigns.source_status == SOURCE_DOCS
    assert get_campaigns.example_param == {"CampaignIDS": [3193279, 1634563]}
    assert build_v4_body("GetCampaignsTags", get_campaigns.example_param) == {
        "method": "GetCampaignsTags",
        "param": {"CampaignIDS": [3193279, 1634563]},
    }

    assert get_banners.param_shape == PARAM_OBJECT
    assert get_banners.source_status == SOURCE_DOCS
    assert get_banners.example_param == {"BannerIDS": [2571700, 2571745]}
    assert build_v4_body("GetBannersTags", get_banners.example_param) == {
        "method": "GetBannersTags",
        "param": {"BannerIDS": [2571700, 2571745]},
    }

    assert update_campaigns.param_shape == PARAM_ARRAY
    assert update_campaigns.source_status == SOURCE_DOCS
    assert "removes tags not listed" in update_campaigns.notes
    assert build_v4_body("UpdateCampaignsTags", update_campaigns.example_param) == {
        "method": "UpdateCampaignsTags",
        "param": [
            {
                "CampaignID": 3193279,
                "Tags": [
                    {"TagID": 0, "Tag": "akapulko"},
                    {"TagID": 16590, "Tag": "orange"},
                ],
            }
        ],
    }

    assert update_banners.param_shape == PARAM_ARRAY
    assert update_banners.source_status == SOURCE_DOCS
    assert "removes previously assigned tags" in update_banners.notes
    assert build_v4_body("UpdateBannersTags", update_banners.example_param) == {
        "method": "UpdateBannersTags",
        "param": [{"BannerID": 2571700, "TagIDS": [16590, 16734]}],
    }


def test_v4forecast_contracts_are_docs_backed_objects_and_scalars():
    create = get_v4_contract("CreateNewForecast")
    list_forecasts = get_v4_contract("GetForecastList")
    get = get_v4_contract("GetForecast")
    delete = get_v4_contract("DeleteForecastReport")

    assert create.param_shape == PARAM_OBJECT
    assert create.source_status == SOURCE_DOCS
    assert create.example_param == {
        "Phrases": ["buy laptop"],
        "Currency": "RUB",
        "GeoID": [213],
    }
    assert build_v4_body("CreateNewForecast", create.example_param) == {
        "method": "CreateNewForecast",
        "param": create.example_param,
    }

    assert list_forecasts.param_shape == PARAM_OPTIONAL_OBJECT
    assert list_forecasts.source_status == SOURCE_DOCS
    assert build_v4_body("GetForecastList") == {"method": "GetForecastList"}

    assert get.param_shape == PARAM_SCALAR
    assert get.source_status == SOURCE_DOCS
    assert build_v4_body("GetForecast", get.example_param) == {
        "method": "GetForecast",
        "param": 123,
    }

    assert delete.param_shape == PARAM_SCALAR
    assert delete.source_status == SOURCE_DOCS
    assert build_v4_body("DeleteForecastReport", delete.example_param) == {
        "method": "DeleteForecastReport",
        "param": 123,
    }


def test_check_payment_contract_uses_custom_transaction_id_object():
    contract = get_v4_contract("CheckPayment")

    assert contract.param_shape == PARAM_OBJECT
    assert contract.source_status == SOURCE_CONFIRMED_LIVE
    assert "PaymentID" in contract.notes
    assert "CustomTransactionID" in contract.login_placement
    assert contract.example_param == {
        "CustomTransactionID": "A123456789012345678901234567890B"
    }
    assert build_v4_body("CheckPayment", contract.example_param) == {
        "method": "CheckPayment",
        "param": {"CustomTransactionID": "A123456789012345678901234567890B"},
    }


def test_get_events_log_contract_uses_timestamp_object_with_currency():
    contract = get_v4_contract("GetEventsLog")

    assert contract.param_shape == PARAM_OBJECT
    assert contract.example_param == {
        "TimestampFrom": "2026-04-14T00:00:00",
        "TimestampTo": "2026-04-14T01:00:00",
        "Currency": "RUB",
    }
    assert build_v4_body("GetEventsLog", contract.example_param) == {
        "method": "GetEventsLog",
        "param": contract.example_param,
    }


def test_v4_call_helper_preserves_non_dict_params():
    response = Mock()
    response.return_value.extract.return_value = [{"Login": "x", "UnitsRest": 1}]
    resource = Mock()
    resource.post.return_value = response
    client = Mock()
    client.v4live.return_value = resource

    result = call_v4(client, "GetClientsUnits", ["x"])

    resource.post.assert_called_once_with(
        data={"method": "GetClientsUnits", "param": ["x"]}
    )
    assert result == [{"Login": "x", "UnitsRest": 1}]


def test_v4_adapter_sends_login_as_header_without_mutating_param():
    from direct_cli._vendor.tapi_yandex_direct.v4.adapter import V4LiveClientAdapter

    adapter = V4LiveClientAdapter()
    api_params = {
        "access_token": "token",
        "login": "client-login",
        "language": "en",
        "is_sandbox": False,
    }

    request = adapter.get_request_kwargs(
        api_params,
        data={"method": "GetStatGoals", "param": {"CampaignIDS": [123]}},
    )
    body = json.loads(request["data"])

    assert body["param"] == {"CampaignIDS": [123]}
    assert body["token"] == "token"
    assert body["locale"] == "en"
    assert request["headers"]["Client-Login"] == "client-login"


def test_v4_adapter_sends_finance_credentials_as_top_level_body_fields():
    from direct_cli._vendor.tapi_yandex_direct.v4.adapter import V4LiveClientAdapter

    adapter = V4LiveClientAdapter()
    api_params = {
        "access_token": "token",
        "login": "agency-login",
        "language": "en",
        "is_sandbox": False,
        "finance_token": "finance-token",
        "operation_num": 42,
    }

    request = adapter.get_request_kwargs(
        api_params,
        data={"method": "GetCreditLimits", "param": ["client-login"]},
    )
    body = json.loads(request["data"])

    assert body["param"] == ["client-login"]
    assert body["finance_token"] == "finance-token"
    assert body["operation_num"] == 42
    assert body["token"] == "token"
    assert body["locale"] == "en"
    assert request["headers"]["Client-Login"] == "agency-login"


def test_v4_goal_contracts_keep_global_login_at_transport_level():
    for method in ("GetStatGoals", "GetRetargetingGoals"):
        contract = get_v4_contract(method)

        assert "Client-Login header" in contract.login_placement
        assert contract.example_param == {"CampaignIDS": [123]}
        assert build_v4_body(method, contract.example_param) == {
            "method": method,
            "param": {"CampaignIDS": [123]},
        }


def test_v4_method_contract_decorator_attaches_known_contract():
    command = Mock()

    decorated = v4_method_contract("GetClientsUnits")(command)

    assert decorated is command
    assert command.v4_method == "GetClientsUnits"
    assert command.v4_contract == get_v4_contract("GetClientsUnits")


def test_get_v4_contract_rejects_unknown_method_with_helpful_error():
    try:
        get_v4_contract("WrongMethod")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown v4 method")

    assert "Unknown v4 Live method 'WrongMethod'" in message
    assert "GetClientsUnits" in message

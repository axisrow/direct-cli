import json
from unittest.mock import Mock

from direct_cli._vendor.tapi_yandex_direct.v4 import SUPPORTED_V4_METHODS
from direct_cli.v4 import build_v4_body, call_v4
from direct_cli.v4_contracts import (
    PARAM_ARRAY,
    PARAM_OBJECT,
    PARAM_UNDOCUMENTED,
    SOURCE_CONFIRMED_LIVE,
    SOURCE_DOCS,
    V4_METHOD_CONTRACTS,
    get_v4_contract,
    v4_method_contract,
    validate_v4_contract_registry,
)


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

    assert transfer.param_shape == PARAM_OBJECT
    assert transfer.source_status == SOURCE_DOCS
    assert "finance_token" in transfer.login_placement
    assert build_v4_body("TransferMoney", transfer.example_param) == {
        "method": "TransferMoney",
        "param": {
            "FromCampaigns": [{"CampaignID": 123, "Sum": 100.5}],
            "ToCampaigns": [{"CampaignID": 456, "Sum": 100.5}],
        },
    }

    assert pay.param_shape == PARAM_OBJECT
    assert pay.source_status == SOURCE_DOCS
    assert "finance_token" in pay.login_placement
    assert build_v4_body("PayCampaigns", pay.example_param) == {
        "method": "PayCampaigns",
        "param": {
            "Payments": [{"CampaignID": 123, "Sum": 100.5}],
            "ContractID": "contract-id",
            "PayMethod": "CREDIT",
        },
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

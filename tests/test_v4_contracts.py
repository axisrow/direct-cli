import json
from unittest.mock import Mock

from direct_cli._vendor.tapi_yandex_direct.v4 import SUPPORTED_V4_METHODS
from direct_cli.v4 import build_v4_body, call_v4
from direct_cli.v4_contracts import (
    PARAM_UNDOCUMENTED,
    SOURCE_CONFIRMED_LIVE,
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
        "GetStatGoals",
        "GetRetargetingGoals",
    }
    for contract in confirmed:
        assert contract.param_shape != PARAM_UNDOCUMENTED
        assert contract.live_probe_allowed
        assert contract.example_param is not None


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
    assert build_v4_body("AccountManagement", {"Action": "Get"}) == {
        "method": "AccountManagement",
        "param": {"Action": "Get"},
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

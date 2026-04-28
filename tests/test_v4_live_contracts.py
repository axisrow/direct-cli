import os
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv

from direct_cli.api import create_client, create_v4_client
from direct_cli.v4 import call_v4

load_dotenv()


pytestmark = pytest.mark.v4_live_read


def _credentials():
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    login = os.getenv("YANDEX_DIRECT_LOGIN")
    if not token or not login:
        pytest.skip("YANDEX_DIRECT_TOKEN and YANDEX_DIRECT_LOGIN are required")
    return token, login


def _campaign_id(token: str, login: str) -> int:
    client = create_client(token=token, login=login)
    body = {
        "method": "get",
        "params": {
            "FieldNames": ["Id"],
            "Page": {"Limit": 1},
        },
    }
    data = client.campaigns().post(data=body)().extract()
    campaigns = data.get("Campaigns", []) if isinstance(data, dict) else data
    if not campaigns:
        pytest.skip("No campaign available for v4 goals live probes")
    return campaigns[0]["Id"]


def _finance_credentials():
    finance_token = os.getenv("YANDEX_DIRECT_FINANCE_TOKEN")
    operation_num = os.getenv("YANDEX_DIRECT_OPERATION_NUM")
    if not finance_token or not operation_num:
        pytest.skip(
            "YANDEX_DIRECT_FINANCE_TOKEN and YANDEX_DIRECT_OPERATION_NUM are required"
        )
    try:
        return finance_token, int(operation_num)
    except ValueError:
        pytest.skip("YANDEX_DIRECT_OPERATION_NUM must be an integer")


def _events_window() -> tuple[str, str]:
    timestamp_to = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(
        days=1
    )
    timestamp_from = timestamp_to - timedelta(hours=1)
    return (
        timestamp_from.strftime("%Y-%m-%dT%H:%M:%S"),
        timestamp_to.strftime("%Y-%m-%dT%H:%M:%S"),
    )


def test_v4_live_get_clients_units_contract():
    token, login = _credentials()
    client = create_v4_client(token=token, login=login)

    data = call_v4(client, "GetClientsUnits", [login])

    assert isinstance(data, list)
    assert data
    assert {"Login", "UnitsRest"} <= set(data[0])


def test_v4_live_account_management_get_contract():
    token, login = _credentials()
    client = create_v4_client(token=token, login=login, language="ru")

    data = call_v4(client, "AccountManagement", {"Action": "Get"})

    assert isinstance(data, dict)
    assert isinstance(data.get("Accounts"), list)
    assert data["Accounts"]
    assert {"Login", "Amount", "Currency"} <= set(data["Accounts"][0])


def test_v4_live_goals_contracts():
    token, login = _credentials()
    campaign_id = _campaign_id(token, login)
    client = create_v4_client(token=token, login=login)

    stat_goals = call_v4(client, "GetStatGoals", {"CampaignIDS": [campaign_id]})
    retargeting_goals = call_v4(
        client,
        "GetRetargetingGoals",
        {"CampaignIDS": [campaign_id]},
    )

    assert isinstance(stat_goals, list)
    assert isinstance(retargeting_goals, list)
    if stat_goals:
        assert {"CampaignID", "GoalID", "Name"} <= set(stat_goals[0])
    if retargeting_goals:
        assert {"GoalID", "Name"} <= set(retargeting_goals[0])


def test_v4_live_get_events_log_contract():
    token, login = _credentials()
    timestamp_from, timestamp_to = _events_window()
    client = create_v4_client(token=token, login=login)

    data = call_v4(
        client,
        "GetEventsLog",
        {
            "TimestampFrom": timestamp_from,
            "TimestampTo": timestamp_to,
            "Currency": "RUB",
            "Limit": 1,
        },
    )

    assert data is not None


def test_v4_live_get_credit_limits_contract():
    token, login = _credentials()
    finance_token, operation_num = _finance_credentials()
    client = create_v4_client(
        token=token,
        login=login,
        finance_token=finance_token,
        operation_num=operation_num,
    )

    data = call_v4(client, "GetCreditLimits", [login])

    assert data is not None

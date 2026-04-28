import os

import pytest
from dotenv import load_dotenv

from direct_cli.api import create_client, create_v4_client
from direct_cli.v4 import call_v4

load_dotenv()


pytestmark = [
    pytest.mark.v4_live_read,
    pytest.mark.skipif(
        os.getenv("YANDEX_DIRECT_V4_LIVE_READ") != "1",
        reason="Set YANDEX_DIRECT_V4_LIVE_READ=1 to run v4 live read probes",
    ),
]


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

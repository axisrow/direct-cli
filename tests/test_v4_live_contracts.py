import os
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv

from direct_cli._vendor.tapi_yandex_direct.exceptions import V4LiveError
from direct_cli.api import create_client, create_v4_client
from direct_cli.v4 import call_v4

load_dotenv()


pytestmark = pytest.mark.v4_live_read


def _credentials():
    """Resolve test credentials with env > profile > skip priority.

    Tests intentionally invert the CLI priority chain: env vars win over the
    active ``direct auth`` profile. This way a developer machine with an
    active profile cannot silently hit production on a plain ``pytest``
    invocation — the suite either uses explicit env vars, or falls back to
    the saved profile only when env vars are absent, or skips entirely.
    Contract is documented in CLAUDE.md and README.md.
    """
    token = os.getenv("YANDEX_DIRECT_TOKEN")
    login = os.getenv("YANDEX_DIRECT_LOGIN")
    if not token or not login:
        try:
            from direct_cli.auth import get_credentials

            token, login = get_credentials(None, None)
        except (ValueError, RuntimeError, ImportError):
            pytest.skip(
                "credentials required: set YANDEX_DIRECT_TOKEN+YANDEX_DIRECT_LOGIN "
                "or run 'direct auth login'"
            )
    if not token or not login:
        pytest.skip(
            "credentials required: set YANDEX_DIRECT_TOKEN+YANDEX_DIRECT_LOGIN "
            "or run 'direct auth login'"
        )
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
    timestamp_to = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
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


def test_v4_live_create_invoice_contract_opt_in_write():
    if os.getenv("YANDEX_DIRECT_LIVE_FINANCE_WRITE") != "1":
        pytest.skip("YANDEX_DIRECT_LIVE_FINANCE_WRITE=1 is required")
    campaign_id = os.getenv("YANDEX_DIRECT_TEST_CAMPAIGN_ID")
    if not campaign_id:
        pytest.skip("YANDEX_DIRECT_TEST_CAMPAIGN_ID is required")
    try:
        parsed_campaign_id = int(campaign_id)
    except ValueError:
        pytest.skip("YANDEX_DIRECT_TEST_CAMPAIGN_ID must be an integer")
    token, login = _credentials()
    finance_token, operation_num = _finance_credentials()
    client = create_v4_client(
        token=token,
        login=login,
        finance_token=finance_token,
        operation_num=operation_num,
    )

    data = call_v4(
        client,
        "CreateInvoice",
        {
            "Payments": [
                {
                    "CampaignID": parsed_campaign_id,
                    "Sum": 1.0,
                    "Currency": "RUB",
                }
            ]
        },
    )

    assert data is not None


def test_v4_sandbox_check_payment_custom_transaction_id_contract():
    if os.getenv("YANDEX_DIRECT_V4_SANDBOX_CONTRACT") != "1":
        pytest.skip("YANDEX_DIRECT_V4_SANDBOX_CONTRACT=1 is required")
    token, login = _credentials()
    client = create_v4_client(token=token, login=login, sandbox=True)

    with pytest.raises(V4LiveError) as exc_info:
        call_v4(
            client,
            "CheckPayment",
            {"CustomTransactionID": "A123456789012345678901234567890B"},
        )

    assert exc_info.value.error_code == 370
    assert exc_info.value.error_str == "Transaction does not exist"


def test_v4_live_tags_get_campaigns_contract():
    token, login = _credentials()
    campaign_id = _campaign_id(token, login)
    client = create_v4_client(token=token, login=login)

    data = call_v4(client, "GetCampaignsTags", {"CampaignIDS": [campaign_id]})

    assert isinstance(data, list)
    if data:
        assert {"CampaignID", "Tags"} <= set(data[0])


def test_v4_live_tags_get_banners_contract():
    token, login = _credentials()
    campaign_id = _campaign_id(token, login)
    client = create_v4_client(token=token, login=login)

    data = call_v4(client, "GetBannersTags", {"CampaignIDS": [campaign_id]})

    assert isinstance(data, list)
    if data:
        # TODO: tighten to {"BannerID", "TagIDS"} once live response is observed.
        # UpdateBannersTags writes TagIDS (v4_contracts.py:419), so the read
        # method likely returns the same field — confirm at first live run.
        assert "BannerID" in data[0]


# ── v4 account-level report lifecycle (opt-in, no cassettes) ────────────
#
# Wordstat reports and forecast reports live in the account-wide list and
# are not draft resources of a disposable campaign. They are gated by
# YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1 to keep the default ``pytest`` run
# free of mutating live calls. Created IDs are tracked in
# ``~/.direct-cli/test-orphans.json`` so an interrupted run can finish
# cleanup on the next invocation — see ``tests/_orphan_store.py``.


_REPORT_WRITE_ENV = "YANDEX_DIRECT_V4_LIVE_REPORT_WRITE"


def test_v4_live_wordstat_lifecycle_opt_in_write():
    if os.getenv(_REPORT_WRITE_ENV) != "1":
        pytest.skip(f"{_REPORT_WRITE_ENV}=1 is required")
    from tests import _orphan_store

    token, login = _credentials()
    client = create_v4_client(token=token, login=login)

    _orphan_store.drain(
        "v4wordstat", lambda rid: call_v4(client, "DeleteWordstatReport", rid)
    )

    report_id = call_v4(
        client,
        "CreateNewWordstatReport",
        {"Phrases": ["купить ноутбук"], "GeoID": [0]},
    )
    assert (
        isinstance(report_id, int) and report_id > 0
    ), f"unexpected CreateNewWordstatReport response: {report_id!r}"
    _orphan_store.add("v4wordstat", report_id)
    try:
        reports = call_v4(client, "GetWordstatReportList")
        assert isinstance(reports, list)
        ours = next(
            (item for item in reports if item.get("ReportID") == report_id), None
        )
        assert ours is not None, f"created report {report_id} not in list"
        assert {"ReportID", "StatusReport"} <= set(ours)
    finally:
        try:
            call_v4(client, "DeleteWordstatReport", report_id)
            _orphan_store.remove("v4wordstat", report_id)
        except Exception:
            # Leave the ID in the store; next run's ``drain`` will retry.
            pass


def test_v4_live_forecast_lifecycle_opt_in_write():
    if os.getenv(_REPORT_WRITE_ENV) != "1":
        pytest.skip(f"{_REPORT_WRITE_ENV}=1 is required")
    from tests import _orphan_store

    token, login = _credentials()
    client = create_v4_client(token=token, login=login)

    _orphan_store.drain(
        "v4forecast", lambda fid: call_v4(client, "DeleteForecastReport", fid)
    )

    forecast_id = call_v4(
        client,
        "CreateNewForecast",
        {"Phrases": ["купить ноутбук"], "GeoID": [213], "Currency": "RUB"},
    )
    assert (
        isinstance(forecast_id, int) and forecast_id > 0
    ), f"unexpected CreateNewForecast response: {forecast_id!r}"
    _orphan_store.add("v4forecast", forecast_id)
    try:
        forecasts = call_v4(client, "GetForecastList")
        assert isinstance(forecasts, list)
        ours = next(
            (item for item in forecasts if item.get("ForecastID") == forecast_id),
            None,
        )
        assert ours is not None, f"created forecast {forecast_id} not in list"
        assert {"ForecastID", "StatusForecast"} <= set(ours)
    finally:
        try:
            call_v4(client, "DeleteForecastReport", forecast_id)
            _orphan_store.remove("v4forecast", forecast_id)
        except Exception:
            pass

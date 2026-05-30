from pathlib import Path

from direct_cli.wsdl_coverage import CLI_TO_API_SERVICE
from direct_cli._vendor.tapi_yandex_direct import YandexDirect
from direct_cli._vendor.tapi_yandex_direct.endpoints import (
    DIRECT_API_PRODUCTION_ROOT,
    DIRECT_API_SANDBOX_ROOT,
    DIRECT_DEBUG_ROOT,
    get_direct_api_root,
)
from direct_cli._vendor.tapi_yandex_direct.tapi_yandex_direct import (
    YandexDirectClientAdapter,
)
from direct_cli._vendor.tapi_yandex_direct.v4.adapter import V4LiveClientAdapter


def test_dependency_uses_axisrow_fork():
    vendor_init = (
        Path(__file__).resolve().parent.parent
        / "direct_cli/_vendor/tapi_yandex_direct/__init__.py"
    )
    assert vendor_init.exists(), (
        "Vendored tapi_yandex_direct not found in direct_cli/_vendor/"
    )


def test_tapi_transport_exposes_cli_resource_executors():
    client = YandexDirect(access_token="test-token")
    missing = [
        cli_name
        for cli_name in sorted(CLI_TO_API_SERVICE)
        if not hasattr(client, cli_name)
    ]

    assert missing == []


def test_direct_api_root_helper_templates_tld():
    # The host constants are ``{tld}`` templates; the helper substitutes the
    # TLD (default ``com`` for the v5 JSON API) and selects prod vs sandbox.
    assert get_direct_api_root({}) == DIRECT_API_PRODUCTION_ROOT.format(tld="com")
    assert get_direct_api_root({"is_sandbox": False}) == (
        DIRECT_API_PRODUCTION_ROOT.format(tld="com")
    )
    assert get_direct_api_root({"is_sandbox": True}) == (
        DIRECT_API_SANDBOX_ROOT.format(tld="com")
    )
    # An explicit TLD (the v4 Live API uses ``ru``) is honored.
    assert get_direct_api_root({}, tld="ru") == (
        DIRECT_API_PRODUCTION_ROOT.format(tld="ru")
    )


def test_v5_adapter_uses_com_hosts():
    adapter = YandexDirectClientAdapter()

    assert adapter.get_api_root({"is_sandbox": False}, "campaigns") == (
        DIRECT_API_PRODUCTION_ROOT.format(tld="com")
    )
    assert adapter.get_api_root({"is_sandbox": True}, "campaigns") == (
        DIRECT_API_SANDBOX_ROOT.format(tld="com")
    )
    assert adapter.get_api_root({"is_sandbox": False}, "debugtoken") == (
        DIRECT_DEBUG_ROOT
    )


def test_v4_adapter_uses_ru_hosts():
    adapter = V4LiveClientAdapter()

    assert adapter.get_api_root({"is_sandbox": False}, "live") == (
        DIRECT_API_PRODUCTION_ROOT.format(tld="ru")
    )
    assert adapter.get_api_root({"is_sandbox": True}, "live") == (
        DIRECT_API_SANDBOX_ROOT.format(tld="ru")
    )

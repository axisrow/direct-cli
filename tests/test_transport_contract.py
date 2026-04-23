from pathlib import Path

from direct_cli.wsdl_coverage import CLI_TO_API_SERVICE
from direct_cli._vendor.tapi_yandex_direct import YandexDirect


def test_dependency_uses_axisrow_fork():
    vendor_init = (
        Path(__file__).resolve().parent.parent
        / "direct_cli/_vendor/tapi_yandex_direct/__init__.py"
    )
    assert vendor_init.exists(), "Vendored tapi_yandex_direct not found in direct_cli/_vendor/"


def test_tapi_transport_exposes_cli_resource_executors():
    client = YandexDirect(access_token="test-token")
    missing = [
        cli_name
        for cli_name in sorted(CLI_TO_API_SERVICE)
        if not hasattr(client, cli_name)
    ]

    assert missing == []

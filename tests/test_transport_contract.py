from pathlib import Path

from direct_cli.wsdl_coverage import CLI_TO_API_SERVICE
from tapi_yandex_direct import YandexDirect


def test_dependency_uses_axisrow_fork():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")

    assert "github.com/axisrow/tapi-yandex-direct.git" in content


def test_tapi_transport_exposes_cli_resource_executors():
    client = YandexDirect(access_token="test-token")
    missing = [
        cli_name
        for cli_name in sorted(CLI_TO_API_SERVICE)
        if not hasattr(client, cli_name)
    ]

    assert missing == []

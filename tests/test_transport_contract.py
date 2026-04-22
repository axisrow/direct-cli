from pathlib import Path

from direct_cli.wsdl_coverage import CLI_TO_API_SERVICE
from tapi_yandex_direct import YandexDirect


FIXED_TAPI_YANDEX_DIRECT_SHA = "ced2c9177a7e1488dea9da68a699c9a7ec3a1af8"


def test_dependency_is_pinned_to_dynamicfeedadtargets_fix():
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")

    assert "github.com/axisrow/tapi-yandex-direct.git" in content
    assert FIXED_TAPI_YANDEX_DIRECT_SHA in content
    assert "tapi-yandex-direct.git@feature/advideos" not in content


def test_tapi_transport_exposes_cli_resource_executors():
    client = YandexDirect(access_token="test-token")
    missing = [
        cli_name
        for cli_name in sorted(CLI_TO_API_SERVICE)
        if not hasattr(client, cli_name)
    ]

    assert missing == []

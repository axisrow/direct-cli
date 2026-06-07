from pathlib import Path


def test_check_all_docs_urls_prefers_checkout_imports():
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_all_docs_urls.py"
    source = script.read_text(encoding="utf-8")

    root_insert = "sys.path.insert(0, str(Path(__file__).resolve().parent.parent))"
    direct_cli_import = (
        "from direct_cli._vendor.tapi_yandex_direct.resource_mapping "
        "import RESOURCE_MAPPING_V5"
    )

    assert root_insert in source
    assert direct_cli_import in source
    assert source.index(root_insert) < source.index(direct_cli_import)

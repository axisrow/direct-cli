"""Unit tests for scripts/audit_wire_shape.py.

Pure-parser tests — no network. Validate that the HTML→schema extractor
correctly isolates the request section, captures every JSON key, and
distinguishes nested item objects from their parent container.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_PATH = REPO_ROOT / "scripts" / "audit_wire_shape.py"

# Load the script as a module without exec'ing it from CLI. Register it
# in sys.modules so dataclasses.dataclass can resolve cls.__module__.
_spec = importlib.util.spec_from_file_location("audit_wire_shape", _AUDIT_PATH)
audit = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["audit_wire_shape"] = audit
_spec.loader.exec_module(audit)


# A miniature mock of a Yandex Live 4 docs page. Reproduces the same
# tag-stripped shape that strip_html produces on the real PayCampaigns
# page: a TOC at the top that repeats both section headings, then the
# real schema block, then the response section.
_MOCK_LIVE_PAGE = """
Содержание Описание метода Входные данные Результирующие данные Примеры
Метод PayCampaigns ... тут описание ...
Новое в версии Live 4 Входной параметр Currency стал обязательным.
Входные данные
Ниже показана структура входных данных в формате JSON.
{
   &quot;method&quot; : &quot;PayCampaigns&quot;,
   &quot;finance_token&quot; : (string),
   &quot;operation_num&quot; : (int),
   &quot;param&quot; : {  /* PayCampaignsInfo */
       &quot;Payments&quot; : [
           {  /* PayCampElement */
              &quot;CampaignID&quot; : (int),
              &quot;Sum&quot; : (float),
              &quot;Currency&quot; : (string)
           } ...
       ],
       &quot;ContractID&quot; : (string),
       &quot;PayMethod&quot; : (string)
   }
}
Ниже приведено описание параметров.
Параметр Описание Требуется PayCampElement CampaignID Идентификатор кампании. Да
Sum Сумма. Да Currency Валюта. Да
Результирующие данные
{
   &quot;data&quot; : { &quot;ResultCode&quot; : (int) }
}
""".strip()


def test_extract_request_section_skips_toc_and_keeps_body():
    section = audit.extract_request_section(_MOCK_LIVE_PAGE)
    assert "PayCampElement" in section
    assert "ResultCode" not in section, (
        "response-side fields must NOT leak into the request section"
    )


def test_parse_schema_blocks_captures_paycampelement_with_currency():
    blocks = audit.parse_schema_blocks(_MOCK_LIVE_PAGE)
    # Both the parent container and the item type are captured.
    assert "PayCampaignsInfo" in blocks
    assert "PayCampElement" in blocks
    pay = blocks["PayCampElement"]
    # The Live 4 obligatory Currency field is present — the same key that
    # PR #441/#442/#443 erroneously dropped after auditing the legacy
    # /reference/ page which lacks it.
    assert "Currency" in pay


def test_parse_schema_blocks_excludes_response_fields():
    blocks = audit.parse_schema_blocks(_MOCK_LIVE_PAGE)
    # ResultCode only appears in the response section — it must not show
    # up under any request-side TypeName.
    for fields in blocks.values():
        assert "ResultCode" not in fields


def test_parse_live4_hints_extracts_newly_required():
    hints = audit.parse_live4_hints(_MOCK_LIVE_PAGE)
    assert "Currency" in hints["newly_required"], (
        "the «Входной параметр Currency стал обязательным» line "
        "must be recognised as a newly-required Live 4 field"
    )


def test_collect_example_keys_walks_nested_lists_and_dicts():
    example = {
        "FromCampaigns": [
            {"CampaignID": 1, "Sum": 1.0, "Currency": "RUB"}
        ],
        "ToCampaigns": [
            {"CampaignID": 2, "Sum": 1.0, "Currency": "RUB"}
        ],
    }
    keys = audit._collect_example_keys(example)
    assert keys == {
        "FromCampaigns",
        "ToCampaigns",
        "CampaignID",
        "Sum",
        "Currency",
    }


def test_collect_example_keys_handles_none_and_scalars():
    assert audit._collect_example_keys(None) == set()
    assert audit._collect_example_keys(42) == set()
    assert audit._collect_example_keys(["a", "b"]) == set()


def test_looks_like_captcha_recognises_markers():
    assert audit.looks_like_captcha("<title>Captcha</title>")
    assert audit.looks_like_captcha("<div data-id='smartCAPTCHA'>")
    assert audit.looks_like_captcha("function showCaptcha(){...}")
    assert not audit.looks_like_captcha(_MOCK_LIVE_PAGE)


@pytest.mark.parametrize(
    ("docs", "method", "expected"),
    [
        # Doubled base: chop the duplicate tail, then append the method.
        (
            "https://yandex.ru/dev/direct/doc/ru/campaigns/campaigns",
            "add",
            "https://yandex.ru/dev/direct/doc/ru/campaigns/add",
        ),
        # Single-segment base: the resource name must be preserved, NOT
        # dropped to ``…/ru/get`` (regression guard — that silently
        # mis-audited 4 v5 groups: vcards/smartadtargets/dynamic*).
        (
            "https://yandex.ru/dev/direct/doc/ru/dynamictextadtargets",
            "get",
            "https://yandex.ru/dev/direct/doc/ru/dynamictextadtargets/get",
        ),
        (
            "https://yandex.ru/dev/direct/doc/ru/vcards",
            "get",
            "https://yandex.ru/dev/direct/doc/ru/vcards/get",
        ),
    ],
)
def test_v5_per_method_url_chops_duplicate_tail(docs, method, expected):
    assert audit._v5_per_method_url(docs, method) == expected


def test_audit_v5_treats_wsdl_base_as_single_group_target(monkeypatch):
    # A service whose `docs` is a WSDL endpoint (#463) must NOT have per-method
    # URLs derived from it — that would produce garbage like `…?wsdl/get`.
    # It is audited as one group-level target instead.
    fetched_urls: list[str] = []

    def fake_fetch_doc(url, retries, pause):
        fetched_urls.append(url)
        return audit.FetchResult(
            url=url, status="ok", html="<html></html>", attempts=1
        )

    monkeypatch.setattr(audit, "fetch_doc", fake_fetch_doc)
    monkeypatch.setattr(
        audit,
        "RESOURCE_MAPPING_V5",
        {
            "vcards": {
                "resource": "json/v5/vcards",
                "docs": "https://api.direct.yandex.com/v5/vcards?wsdl",
                "methods": ["get", "add", "delete"],
            }
        },
    )
    monkeypatch.setattr(audit, "CLI_TO_API_SERVICE", {"vcards": "vcards"})

    audit.audit_v5(retries=1, pause=0)

    wsdl = "https://api.direct.yandex.com/v5/vcards?wsdl"
    assert fetched_urls == [wsdl]
    assert not any("?wsdl/" in u for u in fetched_urls)

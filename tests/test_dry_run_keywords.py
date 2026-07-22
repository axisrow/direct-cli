"""Dry-run payload tests for ``keywords`` and ``negativekeywordsharedsets``.

Split out of the historical monolithic ``tests/test_dry_run.py`` (issue #604).
See :mod:`tests.test_dry_run_shared` for the shared invocation helpers and
``tests/test_dry_run.py`` for the rationale behind the whole suite.
"""

import json

from click.testing import CliRunner

from direct_cli.cli import cli
from tests.test_dry_run_shared import _dry_run, _read_dry_run, _rejected, _write_jsonl


def test_keywords_add_payload_with_bids():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "купить пиццу",
        "--bid",
        "15000000",
        "--context-bid",
        "5000000",
    )
    assert body["method"] == "add"
    keyword = body["params"]["Keywords"][0]
    assert keyword["AdGroupId"] == 12
    assert keyword["Keyword"] == "купить пиццу"
    assert keyword["Bid"] == 15000000
    assert keyword["ContextBid"] == 5000000


def test_keywords_add_payload_with_scalar_autotargeting_fields():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-search-bid-is-auto",
        "yes",
        "--priority",
        "high",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingSearchBidIsAuto": "YES",
        "StrategyPriority": "HIGH",
    }


def test_keywords_add_payload_with_autotargeting_categories():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-category",
        "exact=yes",
        "--autotargeting-category",
        "BROADER=NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingCategories": [
            {"Category": "EXACT", "Value": "YES"},
            {"Category": "BROADER", "Value": "NO"},
        ],
    }


def test_keywords_add_payload_with_autotargeting_brand_options():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-brand-option",
        "without_brands=yes",
        "--autotargeting-brand-option",
        "WITH_ADVERTISER_BRAND=NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingBrandOptions": [
            {"Option": "WITHOUT_BRANDS", "Value": "YES"},
            {"Option": "WITH_ADVERTISER_BRAND", "Value": "NO"},
        ],
    }


def test_keywords_add_payload_with_autotargeting_settings():
    body = _dry_run(
        "keywords",
        "add",
        "--adgroup-id",
        "12",
        "--keyword",
        "---autotargeting",
        "--autotargeting-settings-exact",
        "yes",
        "--autotargeting-settings-narrow",
        "no",
        "--autotargeting-settings-without-brands",
        "YES",
        "--autotargeting-settings-with-competitors-brand",
        "no",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "AdGroupId": 12,
        "Keyword": "---autotargeting",
        "AutotargetingSettings": {
            "Categories": {
                "Exact": "YES",
                "Narrow": "NO",
            },
            "BrandOptions": {
                "WithoutBrands": "YES",
                "WithCompetitorsBrand": "NO",
            },
        },
    }


def test_keywords_add_rejects_scalar_autotargeting_flags_in_batch_mode(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 100}])
    for flag, value in (
        ("--priority", "HIGH"),
        ("--autotargeting-search-bid-is-auto", "YES"),
        ("--autotargeting-category", "EXACT=YES"),
        ("--autotargeting-brand-option", "WITHOUT_BRANDS=YES"),
        ("--autotargeting-settings-exact", "YES"),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "keywords",
                "add",
                "--from-file",
                path,
                flag,
                value,
                "--dry-run",
            ],
        )
        assert result.exit_code != 0
        assert "single-item mode" in result.output
        assert flag in result.output


def test_keywords_add_rejects_single_item_flags_in_batch_mode(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 100}])
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--from-file",
            path,
            "--bid",
            "15000000",
            "--context-bid",
            "5000000",
            "--user-param-1",
            "segment-a",
            "--user-param-2",
            "segment-b",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "single-item mode" in result.output
    assert "--bid" in result.output
    assert "--context-bid" in result.output
    assert "--user-param-1" in result.output
    assert "--user-param-2" in result.output


def test_keywords_update_payload_keyword_text():
    body = _dry_run("keywords", "update", "--id", "777", "--keyword", "new text")
    keyword = body["params"]["Keywords"][0]
    assert keyword == {"Id": 777, "Keyword": "new text"}


def test_keywords_update_payload_user_params():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--user-param-1",
        "seg-a",
        "--user-param-2",
        "seg-b",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {"Id": 777, "UserParam1": "seg-a", "UserParam2": "seg-b"}


def test_keywords_update_rejects_noop_payload():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "requires at least one updatable field" in result.output
    assert "--autotargeting-settings-* flags" in result.output


def test_keywords_update_payload_with_autotargeting_categories():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-category",
        "ALTERNATIVE=YES",
        "--autotargeting-category",
        "competitor=no",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingCategories": [
            {"Category": "ALTERNATIVE", "Value": "YES"},
            {"Category": "COMPETITOR", "Value": "NO"},
        ],
    }


def test_keywords_update_payload_with_autotargeting_brand_options():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-brand-option",
        "WITHOUT_BRANDS=NO",
        "--autotargeting-brand-option",
        "with_advertiser_brand=yes",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingBrandOptions": [
            {"Option": "WITHOUT_BRANDS", "Value": "NO"},
            {"Option": "WITH_ADVERTISER_BRAND", "Value": "YES"},
        ],
    }


def test_keywords_update_payload_with_autotargeting_settings():
    body = _dry_run(
        "keywords",
        "update",
        "--id",
        "777",
        "--autotargeting-settings-alternative",
        "YES",
        "--autotargeting-settings-accessory",
        "no",
        "--autotargeting-settings-broader",
        "yes",
        "--autotargeting-settings-with-advertiser-brand",
        "NO",
    )
    keyword = body["params"]["Keywords"][0]
    assert keyword == {
        "Id": 777,
        "AutotargetingSettings": {
            "Categories": {
                "Alternative": "YES",
                "Accessory": "NO",
                "Broader": "YES",
            },
            "BrandOptions": {
                "WithAdvertiserBrand": "NO",
            },
        },
    }


def test_keywords_autotargeting_settings_rejects_legacy_category_mix():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-category",
            "EXACT=YES",
            "--autotargeting-settings-exact",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert "--autotargeting-category" in result.output


def test_keywords_autotargeting_settings_rejects_legacy_brand_option_mix():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS=YES",
            "--autotargeting-settings-without-brands",
            "YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    assert "--autotargeting-brand-option" in result.output


def test_keywords_autotargeting_category_requires_category_value_pair():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-category",
            "EXACT",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "CATEGORY=YES|NO" in result.output


def test_keywords_autotargeting_category_rejects_unknown_category():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-category",
            "UNKNOWN=YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid --autotargeting-category category" in result.output
    assert "EXACT" in result.output


def test_keywords_autotargeting_category_rejects_unknown_value():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-category",
            "EXACT=MAYBE",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "expected YES or NO" in result.output


def test_keywords_autotargeting_brand_option_requires_option_value_pair():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "add",
            "--adgroup-id",
            "12",
            "--keyword",
            "---autotargeting",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "OPTION=YES|NO" in result.output


def test_keywords_autotargeting_brand_option_rejects_unknown_option():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITH_COMPETITORS_BRAND=YES",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "Invalid --autotargeting-brand-option option" in result.output
    assert "WITHOUT_BRANDS" in result.output


def test_keywords_autotargeting_brand_option_rejects_unknown_value():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "update",
            "--id",
            "777",
            "--autotargeting-brand-option",
            "WITHOUT_BRANDS=MAYBE",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "expected YES or NO" in result.output


def test_keywords_add_payload_batch_from_jsonl(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {"Keyword": "buy laptop", "AdGroupId": 100, "Bid": 10000000},
            {"Keyword": "buy desktop", "AdGroupId": 100},
            {"Keyword": "купить тест", "AdGroupId": 200, "UserParam1": "src=a"},
        ],
    )
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["chunks"] == 1
    assert body["totalItems"] == 3
    assert body["chunkSize"] == 10
    keywords = body["firstChunk"]["params"]["Keywords"]
    assert body["firstChunk"]["method"] == "add"
    assert keywords[0] == {
        "Keyword": "buy laptop",
        "AdGroupId": 100,
        "Bid": 10000000,
    }
    assert keywords[2] == {
        "Keyword": "купить тест",
        "AdGroupId": 200,
        "UserParam1": "src=a",
    }


def test_keywords_add_payload_batch_inline():
    inline = json.dumps(
        [
            {"Keyword": "kw-a", "AdGroupId": 1},
            {"Keyword": "kw-b", "AdGroupId": 1, "ContextBid": 5000000},
        ]
    )
    body = _dry_run("keywords", "add", "--keywords-json", inline)
    assert body["totalItems"] == 2
    assert body["chunks"] == 1
    assert body["firstChunk"]["params"]["Keywords"][1]["ContextBid"] == 5000000


def test_keywords_add_payload_batch_chunks_at_10(tmp_path):
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(25)]
    path = _write_jsonl(tmp_path, rows)
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["chunks"] == 3
    assert body["totalItems"] == 25
    first_chunk = body["firstChunk"]["params"]["Keywords"]
    assert len(first_chunk) == 10
    assert [k["Keyword"] for k in first_chunk] == [f"kw-{i}" for i in range(10)]


def test_keywords_add_payload_adgroup_override(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [
            {"Keyword": "kw-default"},
            {"Keyword": "kw-override", "AdGroupId": 200},
        ],
    )
    body = _dry_run("keywords", "add", "--adgroup-id", "100", "--from-file", path)
    items = body["firstChunk"]["params"]["Keywords"]
    assert items[0] == {"Keyword": "kw-default", "AdGroupId": 100}
    assert items[1] == {"Keyword": "kw-override", "AdGroupId": 200}


def test_keywords_add_payload_micro_rubles_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Bid": 15000000}],
    )
    body = _dry_run("keywords", "add", "--from-file", path)
    assert body["firstChunk"]["params"]["Keywords"][0]["Bid"] == 15000000


def test_keywords_add_rejects_unknown_field_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Foo": "bar"}],
    )
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Unknown field 'Foo' in keyword row 1" in result.output


def test_keywords_add_rejects_autotargeting_row_fields_in_batch(tmp_path):
    deferred_fields = {
        "AutotargetingSearchBidIsAuto": ("YES", "--autotargeting-search-bid-is-auto"),
        "StrategyPriority": ("HIGH", "--priority"),
        "AutotargetingCategories": (
            [{"Category": "EXACT", "Value": "YES"}],
            "--autotargeting-category",
        ),
        "AutotargetingBrandOptions": (
            [{"Option": "WITHOUT_BRANDS", "Value": "YES"}],
            "--autotargeting-brand-option",
        ),
        "AutotargetingSettings": (
            {"Categories": {"Exact": "YES"}},
            "--autotargeting-settings-* flags",
        ),
    }

    for field, (value, expected_flag) in deferred_fields.items():
        path = _write_jsonl(
            tmp_path,
            [{"Keyword": "kw", "AdGroupId": 1, field: value}],
        )
        result = _rejected("keywords", "add", "--from-file", path)
        assert f"field '{field}' is intentionally unsupported" in result.output
        assert "batch mode" in result.output
        assert expected_flag in result.output


def test_keywords_add_rejects_autotargeting_inline_batch_row():
    inline = json.dumps(
        [
            {
                "Keyword": "kw",
                "AdGroupId": 1,
                "AutotargetingSearchBidIsAuto": "YES",
            }
        ]
    )
    result = _rejected("keywords", "add", "--keywords-json", inline)
    assert "AutotargetingSearchBidIsAuto" in result.output
    assert "intentionally unsupported in batch mode" in result.output


def test_keywords_add_rejects_invalid_jsonl(tmp_path):
    path = tmp_path / "broken.jsonl"
    path.write_text(
        '{"Keyword": "ok", "AdGroupId": 1}\n{"Keyword": broken\n',
        encoding="utf-8",
    )
    result = _rejected("keywords", "add", "--from-file", str(path))
    assert "Row 2: invalid JSON" in result.output


def test_keywords_add_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("\n   \n", encoding="utf-8")
    result = _rejected("keywords", "add", "--from-file", str(path))
    assert "Input contains no keyword rows" in result.output


def test_keywords_add_rejects_empty_json_array():
    result = _rejected("keywords", "add", "--keywords-json", "[]")
    assert "Input contains no keyword rows" in result.output


def test_keywords_add_rejects_non_object_row_in_inline():
    result = _rejected("keywords", "add", "--keywords-json", "[1, 2, 3]")
    assert "Row 1" in result.output
    assert "expected JSON object" in result.output


def test_keywords_add_rejects_mutex(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--keyword",
        "x",
        "--adgroup-id",
        "1",
        "--from-file",
        path,
    )
    assert "Provide exactly one of" in result.output


def test_keywords_add_rejects_mutex_file_and_inline(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--from-file",
        path,
        "--keywords-json",
        "[]",
    )
    assert "Provide exactly one of" in result.output


def test_keywords_add_rejects_missing_required_in_row(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw"}])
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1" in result.output
    assert "AdGroupId" in result.output


def test_keywords_add_rejects_too_low_bid_in_row(tmp_path):
    path = _write_jsonl(
        tmp_path,
        [{"Keyword": "kw", "AdGroupId": 1, "Bid": 50000}],
    )
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1 field 'Bid'" in result.output


def test_keywords_add_rejects_non_json_format_in_batch(tmp_path):
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": 1}])
    result = _rejected(
        "keywords",
        "add",
        "--from-file",
        path,
        "--format",
        "table",
    )
    assert "batch mode" in result.output


def test_keywords_add_rejects_no_mode():
    result = _rejected("keywords", "add")
    assert "Provide exactly one of" in result.output


def test_keywords_add_single_still_raises_on_item_error(monkeypatch):
    """Single-mode (non-batch) must still bubble item-level Errors."""
    import importlib

    keywords_module = importlib.import_module("direct_cli.commands.keywords")
    from direct_cli.output import DirectAPIResultError

    class _StubExtract:
        def extract(self):
            return {
                "AddResults": [{"Id": 0, "Errors": [{"Code": 8500, "Message": "bad"}]}]
            }

    class _StubResult:
        def __call__(self):
            return _StubExtract()

    class _StubKeywords:
        def post(self, data):
            return _StubResult()

    class _StubClient:
        def keywords(self):
            return _StubKeywords()

    monkeypatch.setattr(keywords_module, "create_client", lambda **_: _StubClient())
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--token",
            "T",
            "--login",
            "L",
            "keywords",
            "add",
            "--adgroup-id",
            "1",
            "--keyword",
            "kw",
        ],
    )
    assert result.exit_code != 0
    # Single-mode goes through format_output → raise_for_api_result_errors,
    # which DirectAPIResultError-then-Abort. CLI surfaces it via print_error.
    assert "Yandex Direct API returned errors" in result.output or isinstance(
        result.exception, DirectAPIResultError
    )


def test_keywords_add_rejects_bool_in_row(tmp_path):
    """JSON booleans must NOT be silently coerced to 1/0 for int/micro fields."""
    path = _write_jsonl(tmp_path, [{"Keyword": "kw", "AdGroupId": True}])
    result = _rejected("keywords", "add", "--from-file", path)
    assert "Row 1 field 'AdGroupId'" in result.output
    assert "bool" in result.output


def test_keywords_add_empty_string_keyword_counts_as_mode():
    """`--keyword ''` must register as mode-provided, not fall through to
    'Provide exactly one of' (mode-detection uses `is not None`, not
    truthiness)."""
    body = _dry_run("keywords", "add", "--keyword", "", "--adgroup-id", "1")
    assert body["params"]["Keywords"][0] == {"AdGroupId": 1, "Keyword": ""}


def test_keywords_add_batch_warns_when_over_200_per_adgroup(tmp_path):
    """Pre-flight warning when input has >200 keywords for the same AdGroupId
    (Yandex Direct limit)."""
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(201)]
    rows.append({"Keyword": "ok", "AdGroupId": 2})
    path = _write_jsonl(tmp_path, rows)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["keywords", "add", "--from-file", str(path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "exceeds the Yandex Direct limit of 200" in result.output
    assert "AdGroupId=1: 201 keywords (1 over the limit)" in result.output
    # AdGroupId=2 is within the limit; must NOT be flagged.
    assert "AdGroupId=2" not in result.output


def test_keywords_add_batch_no_warning_under_200(tmp_path):
    """No warning when every adgroup is within the 200-keyword limit."""
    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(150)]
    path = _write_jsonl(tmp_path, rows)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["keywords", "add", "--from-file", str(path), "--dry-run"],
    )
    assert result.exit_code == 0
    assert "exceeds the Yandex Direct limit" not in result.output


def test_keywords_add_batch_partial_success_on_failure(tmp_path, monkeypatch):
    """If a later chunk raises, already-created Ids must be surfaced to the
    user (via stderr) so a retry doesn't create duplicates."""
    import importlib

    keywords_module = importlib.import_module("direct_cli.commands.keywords")

    rows = [{"Keyword": f"kw-{i}", "AdGroupId": 1} for i in range(15)]
    path = _write_jsonl(tmp_path, rows)

    call_count = {"n": 0}

    class _StubExtract:
        def extract(self):
            return {"AddResults": [{"Id": i + 1} for i in range(10)]}

    class _StubResult:
        def __call__(self):
            return _StubExtract()

    class _StubKeywords:
        def post(self, data):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _StubResult()
            raise RuntimeError("network blip on second chunk")

    class _StubClient:
        def keywords(self):
            return _StubKeywords()

    monkeypatch.setattr(keywords_module, "create_client", lambda **_: _StubClient())
    # CliRunner's default mixes stderr into result.output, which is what
    # we want here — the partial-results message goes to stderr but lands
    # in the combined output buffer regardless of Click version.
    result = CliRunner().invoke(
        cli,
        [
            "--token",
            "T",
            "--login",
            "L",
            "keywords",
            "add",
            "--from-file",
            str(path),
        ],
    )
    assert result.exit_code != 0
    assert "Partial success before failure" in result.output
    assert '"Id": 1' in result.output
    assert '"Id": 10' in result.output


def test_negativekeywordsharedsets_add_splits_keywords():
    body = _dry_run(
        "negativekeywordsharedsets",
        "add",
        "--name",
        "Set A",
        "--keywords",
        "купить, продам , скачать",
    )
    assert body["method"] == "add"
    nks = body["params"]["NegativeKeywordSharedSets"][0]
    assert nks == {
        "Name": "Set A",
        "NegativeKeywords": ["купить", "продам", "скачать"],
    }


def test_negativekeywordsharedsets_update_keywords():
    body = _dry_run(
        "negativekeywordsharedsets",
        "update",
        "--id",
        "12",
        "--keywords",
        "слово,фраза",
    )
    nks = body["params"]["NegativeKeywordSharedSets"][0]
    assert nks == {"Id": 12, "NegativeKeywords": ["слово", "фраза"]}


def test_negativekeywordsharedsets_update_empty_payload_not_swallowed():
    # The ClickException from the empty-payload guard must surface as a native
    # Click error, not be re-wrapped by ``except Exception`` into print_error +
    # Abort (which prefixes the message with the error marker and "Aborted!").
    result = CliRunner().invoke(
        cli,
        ["negativekeywordsharedsets", "update", "--id", "1", "--dry-run"],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )
    assert result.exit_code != 0
    assert "Provide at least one of --name or --keywords" in result.output
    assert "Aborted!" not in result.output


def test_keywords_suspend_dry_run_payload():
    body = _dry_run("keywords", "suspend", "--id", "77")
    assert body == {
        "method": "suspend",
        "params": {"SelectionCriteria": {"Ids": [77]}},
    }


def test_keywords_get_nested_field_names_payload():
    # KeywordsGetRequest (WSDL tests/wsdl_cache/keywords.xml) declares two
    # nested top-level *FieldNames parameters separate from FieldNames:
    # AutotargetingSettingsBrandOptionsFieldNames
    # (AutotargetingBrandOptionsFieldEnum: WithoutBrands,
    # WithAdvertiserBrand, WithCompetitorsBrand) and
    # AutotargetingSettingsCategoriesFieldNames
    # (AutotargetingCategoriesFieldEnum: Exact, Narrow, Alternative,
    # Accessory, Broader).
    body = _read_dry_run(
        "keywords",
        "get",
        "--ids",
        "1",
        "--autotargeting-settings-brand-options-field-names",
        "WithoutBrands,WithAdvertiserBrand,WithCompetitorsBrand",
        "--autotargeting-settings-categories-field-names",
        "Exact,Narrow,Alternative",
    )

    params = body["params"]
    assert params["AutotargetingSettingsBrandOptionsFieldNames"] == [
        "WithoutBrands",
        "WithAdvertiserBrand",
        "WithCompetitorsBrand",
    ]
    assert params["AutotargetingSettingsCategoriesFieldNames"] == [
        "Exact",
        "Narrow",
        "Alternative",
    ]


def test_keywords_get_omits_nested_field_names_by_default():
    body = _read_dry_run("keywords", "get", "--ids", "1")

    assert "AutotargetingSettingsBrandOptionsFieldNames" not in body["params"]
    assert "AutotargetingSettingsCategoriesFieldNames" not in body["params"]


def test_keywords_get_help_exposes_nested_field_names():
    result = CliRunner().invoke(cli, ["keywords", "get", "--help"])

    assert result.exit_code == 0
    assert "--autotargeting-settings-brand-options-field-names" in result.output
    assert "--autotargeting-settings-categories-field-names" in result.output


def test_keywords_get_rejects_empty_brand_options_field_names_csv():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "get",
            "--autotargeting-settings-brand-options-field-names",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated "
        "AutotargetingSettingsBrandOptionsFieldNames list." in result.output
    )


def test_keywords_get_rejects_empty_categories_field_names_csv():
    result = CliRunner().invoke(
        cli,
        [
            "keywords",
            "get",
            "--autotargeting-settings-categories-field-names",
            ",",
            "--dry-run",
        ],
        env={"YANDEX_DIRECT_TOKEN": "test-token", "YANDEX_DIRECT_LOGIN": ""},
    )

    assert result.exit_code != 0
    assert (
        "Provide a non-empty comma-separated "
        "AutotargetingSettingsCategoriesFieldNames list." in result.output
    )


def test_keywords_delete_rejects_zero_id():
    result = _rejected("keywords", "delete", "--id", "0")
    assert result.exit_code == 2, result.output


def test_keywords_update_rejects_zero_id():
    result = _rejected("keywords", "update", "--id", "0", "--keyword", "foo")
    assert result.exit_code == 2, result.output

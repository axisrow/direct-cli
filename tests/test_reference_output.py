"""Human-readable default output for local reference commands (issue #578).

Reference commands (``trackingparams``, ``dictionaries list-names``) list values
for a person, so they default to the human-readable ``text`` format and keep the
machine formats (json/table/csv/tsv) as ``--format`` options via
``reference_output_options``. ``YANDEX_DIRECT_CLI_LOCALE=en`` is pinned by the
conftest autouse fixture (irrelevant here — the reference data is language-neutral
or Russian by source).
"""

import json

import pytest
from click.testing import CliRunner

from direct_cli.cli import cli
from direct_cli.output import format_csv, format_table, format_text, format_tsv


def _run(*args):
    return CliRunner().invoke(cli, list(args))


# ── format_text unit ──────────────────────────────────────────────────────


def test_format_text_list_of_dicts_blocks():
    out = format_text([{"A": "1", "B": "x"}, {"A": "2", "B": "y"}])
    assert out == "A: 1\nB: x\n\nA: 2\nB: y"


def test_format_text_list_of_scalars_one_per_line():
    assert format_text(["Currencies", "GeoRegions"]) == "Currencies\nGeoRegions"


def test_format_text_dict_is_key_value():
    assert format_text({"profile": "p", "source": "env"}) == "profile: p\nsource: env"


def test_format_text_empty_list_and_scalar():
    assert format_text([]) == ""
    assert format_text(42) == "42"


# ── scalar-list rendering in table/csv/tsv (previously a Python repr) ─────


def test_format_table_scalar_list_single_column():
    out = format_table(["Currencies", "GeoRegions"])
    assert "Value" in out and "Currencies" in out
    assert "['Currencies'" not in out  # not the old str(data) repr


def test_format_csv_tsv_scalar_list_single_column():
    assert format_csv(["a", "b"]).splitlines() == ["Value", "a", "b"]
    assert format_tsv(["a", "b"]).splitlines() == ["Value", "a", "b"]


# ── trackingparams ────────────────────────────────────────────────────────


def test_trackingparams_default_is_text_not_json():
    result = _run("trackingparams")
    assert result.exit_code == 0
    assert "{campaign_id}" in result.output
    assert not result.output.lstrip().startswith("[")
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.output)


def test_trackingparams_format_json():
    result = _run("trackingparams", "--format", "json")
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(row["Parameter"] == "{campaign_id}" for row in data)


def test_trackingparams_rejects_unknown_format():
    result = _run("trackingparams", "--format", "xml")
    assert result.exit_code == 2
    assert "Invalid value for '--format'" in result.output


# ── dictionaries list-names ───────────────────────────────────────────────


def test_list_names_default_is_text():
    result = _run("dictionaries", "list-names")
    assert result.exit_code == 0
    assert "Currencies" in result.output.split("\n")
    assert not result.output.lstrip().startswith("[")


def test_list_names_format_json():
    result = _run("dictionaries", "list-names", "--format", "json")
    assert result.exit_code == 0
    assert "Currencies" in json.loads(result.output)


@pytest.mark.parametrize("fmt", ["text", "json", "table", "csv", "tsv"])
def test_list_names_all_formats_succeed(fmt):
    result = _run("dictionaries", "list-names", "--format", fmt)
    assert result.exit_code == 0, result.output
    assert "Currencies" in result.output

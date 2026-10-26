"""Table format keeps exact API numeric text (#901).

tabulate's default numparse parsed numeric strings into floats and printed
six significant digits ("123456.78" -> 123457). The other formats never
touched the values; these tests pin both sides of that boundary.
"""

import json

from direct_cli.output import (
    format_csv,
    format_json,
    format_output,
    format_table,
    format_text,
    format_tsv,
)

_EXAMPLE = [{"Cost": "123456.78", "AvgCpc": "123.456789"}]


def test_table_keeps_issue_example_values_verbatim():
    out = format_table(_EXAMPLE)
    assert "123456.78" in out
    assert "123.456789" in out
    assert "123457" not in out
    assert "123.457" not in out


def test_table_keeps_large_amount():
    # Six-significant-digit floatfmt turned this into 10000000000 (#901).
    out = format_table([{"Cost": "9999999999.99"}])
    assert "9999999999.99" in out
    assert "10000000000" not in out


def test_table_keeps_multi_decimal_fraction():
    out = format_table([{"AvgCpc": "0.123456789"}])
    assert "0.123456789" in out


def test_table_renders_typed_float_like_json():
    # str(float) is the shortest round-trip repr — the same text json prints.
    assert "123.456789" in format_table([{"AvgCpc": 123.456789}])
    value = 9999999999.99
    assert json.dumps(value) in format_table([{"Cost": value}])


def test_table_dict_shape_keeps_values():
    out = format_table({"Cost": "123456.78", "AvgCpc": "123.456789"})
    assert "123456.78" in out
    assert "123.456789" in out


def test_table_keeps_numeric_columns_right_aligned():
    # Rendered like the pre-fix tabulate did for this input (verified against
    # main): numeric columns stay right-aligned, headers longest in column.
    out = format_table([{"Id": "1", "Cost": "12.5"}])
    assert "|   Cost |" in out
    assert "|   12.5 |" in out


def test_table_mixed_column_stays_left_aligned():
    # "abcdef" makes the column non-numeric, so "12.5" is left-aligned.
    out = format_table([{"V": "abcdef"}, {"V": "12.5"}])
    assert "| 12.5   |" in out


def test_table_none_cell_stays_blank():
    # A blank cell must not break the column's numeric alignment (numparse
    # ignored missing values the same way).
    out = format_table([{"Cost": "12.5"}, {"Cost": None}])
    assert "|   12.5 |" in out
    assert "None" not in out


def test_other_formats_keep_values_verbatim():
    assert "123456.78" in format_json(_EXAMPLE)
    assert "123.456789" in format_json(_EXAMPLE)
    assert "123456.78,123.456789" in format_csv(_EXAMPLE)
    assert "123456.78\t123.456789" in format_tsv(_EXAMPLE)
    assert "Cost: 123456.78" in format_text(_EXAMPLE)


def test_format_output_table_entry_point_keeps_values():
    out = format_output(_EXAMPLE, "table")
    assert "123456.78" in out
    assert "123.456789" in out

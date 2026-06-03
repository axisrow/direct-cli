"""Unit tests for the shared field-name option helpers (direct_cli/utils.py).

``parse_field_names_option`` and ``parse_nested_field_names`` replace a
field-name parsing helper that was byte-identically duplicated in
``ads``/``strategies`` and inlined in five more command modules. These tests
lock the error string-key and the non-empty accumulation behavior so the
dedup stays behavior-preserving.
"""

import pytest
from click import UsageError

from direct_cli import i18n
from direct_cli.utils import (
    parse_field_names_option,
    parse_nested_field_names,
)


@pytest.fixture(autouse=True)
def _pin_english_locale():
    """These helpers are called directly (not via the CLI), so t() uses the
    process-level active locale (default Russian). Pin English to assert the
    stable English source strings, then restore."""
    previous = i18n.get_active_locale()
    i18n.set_active_locale("en")
    try:
        yield
    finally:
        i18n.set_active_locale(previous)


def test_parse_field_names_option_none_for_unset():
    assert parse_field_names_option("FieldNames", None) is None


def test_parse_field_names_option_valid_trims_and_drops_empties():
    assert parse_field_names_option("FieldNames", " Id , Name , ") == ["Id", "Name"]


def test_parse_field_names_option_rejects_explicitly_empty_csv():
    # raw_value is non-None but resolves to empty -> UsageError, with the
    # WSDL key echoed verbatim into the (English) message.
    with pytest.raises(UsageError) as exc:
        parse_field_names_option("TextAdFieldNames", " , ")
    assert exc.value.format_message() == (
        "Provide a non-empty comma-separated TextAdFieldNames list."
    )


def test_parse_field_names_option_rejects_empty_for_a_second_key():
    # A different wsdl_key must render in the same message slot, proving the
    # {wsdl_key} placeholder (and the single shared catalog key) is preserved.
    with pytest.raises(UsageError) as exc:
        parse_field_names_option("ContractFieldNames", "")
    assert exc.value.format_message() == (
        "Provide a non-empty comma-separated ContractFieldNames list."
    )


def test_parse_nested_field_names_keeps_only_non_empty_in_order():
    result = parse_nested_field_names(
        [
            ("AFieldNames", None),
            ("BFieldNames", "x,y"),
            ("CFieldNames", None),
            ("DFieldNames", "z"),
        ]
    )
    assert result == {"BFieldNames": ["x", "y"], "DFieldNames": ["z"]}
    assert list(result) == ["BFieldNames", "DFieldNames"]


def test_parse_nested_field_names_all_unset_is_empty_dict():
    assert (
        parse_nested_field_names([("AFieldNames", None), ("BFieldNames", None)]) == {}
    )


def test_parse_nested_field_names_raises_on_explicitly_empty_member():
    with pytest.raises(UsageError) as exc:
        parse_nested_field_names([("AFieldNames", "ok"), ("BFieldNames", " , ")])
    assert exc.value.format_message() == (
        "Provide a non-empty comma-separated BFieldNames list."
    )

"""Unit tests for the shared subtype-flag guard (direct_cli/_flag_validation.py).

``reject_incompatible_flags`` unifies the campaigns/adgroups/bidmodifiers
"flag is not valid for this --type" guards. These tests lock:

- the caller-owns-message contract — each resource keeps its own i18n source
  string and placeholder ({command_type}/{group_type}/{modifier_type}), so the
  rendered text is byte-identical to the pre-dedup per-module guards;
- the unified "provided" condition ``value not in (None, ())`` — both ``None``
  and the empty tuple ``()`` count as "not provided".
"""

import pytest
from click import UsageError

from direct_cli import i18n
from direct_cli._flag_validation import reject_incompatible_flags

_GROUP_MSG = "{arg0} is not compatible with --type {group_type}."
_COMMAND_MSG = "{arg0} is not compatible with --type {command_type}."
_MODIFIER_MSG = "{arg0} is not compatible with --type {modifier_type}."


@pytest.fixture(autouse=True)
def _pin_english_locale():
    """The helper is called directly (not via the CLI), so t() uses the
    process-level active locale (default Russian). Pin English to assert the
    stable English source strings, then restore."""
    previous = i18n.get_active_locale()
    i18n.set_active_locale("en")
    try:
        yield
    finally:
        i18n.set_active_locale(previous)


def test_no_incompatible_flags_does_not_raise():
    reject_incompatible_flags(
        {"--allowed"},
        {"--allowed": "v", "--other": None},
        message=_GROUP_MSG,
        type_value="TEXT_AD_GROUP",
        type_field="group_type",
    )


def test_allowed_flag_present_does_not_raise():
    reject_incompatible_flags(
        {"--region-id"},
        {"--region-id": 225},
        message=_MODIFIER_MSG,
        type_value="REGIONAL_ADJUSTMENT",
        type_field="modifier_type",
    )


def test_group_type_message_renders_with_sorted_arg0():
    # Two incompatible flags passed out of order -> rendered sorted, ", "-joined.
    with pytest.raises(UsageError) as exc:
        reject_incompatible_flags(
            set(),
            {"--zeta": "v", "--alpha": "v"},
            message=_GROUP_MSG,
            type_value="TEXT_AD_GROUP",
            type_field="group_type",
        )
    assert exc.value.format_message() == (
        "--alpha, --zeta is not compatible with --type TEXT_AD_GROUP."
    )


def test_command_type_message_key_and_render():
    with pytest.raises(UsageError) as exc:
        reject_incompatible_flags(
            {"--setting"},
            {"--goal-id": 1},
            message=_COMMAND_MSG,
            type_value="TEXT_CAMPAIGN",
            type_field="command_type",
        )
    assert exc.value.format_message() == (
        "--goal-id is not compatible with --type TEXT_CAMPAIGN."
    )


def test_modifier_type_message_key_and_render():
    with pytest.raises(UsageError) as exc:
        reject_incompatible_flags(
            {"--region-id"},
            {"--gender": "GENDER_MALE"},
            message=_MODIFIER_MSG,
            type_value="REGIONAL_ADJUSTMENT",
            type_field="modifier_type",
        )
    assert exc.value.format_message() == (
        "--gender is not compatible with --type REGIONAL_ADJUSTMENT."
    )


def test_empty_tuple_value_is_treated_as_not_provided():
    # The crux of the condition unification: a multiple=() flag absent from the
    # CLI must NOT be reported as incompatible, even when outside allowed_flags.
    reject_incompatible_flags(
        set(),
        {"--autotargeting-category": ()},
        message=_GROUP_MSG,
        type_value="TEXT_AD_GROUP",
        type_field="group_type",
    )


def test_none_value_is_treated_as_not_provided():
    reject_incompatible_flags(
        set(),
        {"--domain-url": None},
        message=_GROUP_MSG,
        type_value="TEXT_AD_GROUP",
        type_field="group_type",
    )


def test_non_empty_value_outside_allowed_raises():
    with pytest.raises(UsageError):
        reject_incompatible_flags(
            set(),
            {"--domain-url": "https://example.com"},
            message=_GROUP_MSG,
            type_value="TEXT_AD_GROUP",
            type_field="group_type",
        )

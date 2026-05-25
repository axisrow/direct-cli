"""Regression for issue #236.

When a user passes an option that does not exist on the selected
subcommand, the CLI augments Click's stock ``NoSuchOption`` error with a
hint pointing at sibling subcommands (within the same group) that *do*
declare the option. The first line of the message is still the standard
``Error: No such option '--X'``, so legacy substring asserts keep
working.
"""

from click.testing import CliRunner

from direct_cli.cli import cli


def _invoke(*argv: str):
    return CliRunner().invoke(cli, list(argv))


def test_ads_update_unknown_option_hints_at_ads_add():
    """--ad-extensions exists only in `ads add` — hint must say so."""
    result = _invoke(
        "ads",
        "update",
        "--id",
        "1",
        "--type",
        "TEXT_AD",
        "--ad-extensions",
        "1,2",
        "--dry-run",
    )
    assert result.exit_code == 2
    # First line preserves the stock Click message (substring contract
    # from tests/test_dry_run.py:1209).
    assert "No such option" in result.output
    assert "--ad-extensions" in result.output
    # Hint points the user at the sibling that accepts the flag.
    assert "Hint:" in result.output
    assert "`direct ads add`" in result.output
    assert "`direct ads update`" in result.output
    assert "`direct ads update --help`" in result.output


def test_ads_update_unknown_mobile_hints_at_ads_add():
    """--mobile is the original symptom from issue #236 along with
    --ad-extensions."""
    result = _invoke(
        "ads",
        "update",
        "--id",
        "1",
        "--type",
        "TEXT_AD",
        "--mobile",
        "NO",
        "--dry-run",
    )
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--mobile" in result.output
    assert "Hint:" in result.output
    assert "`direct ads add`" in result.output


def test_campaigns_update_unknown_option_hints_at_campaigns_add():
    """campaigns add carries many flags absent from campaigns update —
    --filter-average-cpc is one of them."""
    result = _invoke(
        "campaigns",
        "update",
        "--id",
        "1",
        "--filter-average-cpc",
        "1000000",
    )
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--filter-average-cpc" in result.output
    assert "Hint:" in result.output
    assert "`direct campaigns add`" in result.output


def test_typo_with_no_sibling_match_falls_back_to_help_hint():
    """When no sibling declares the option, we just point at --help."""
    result = _invoke("ads", "update", "--id", "1", "--this-flag-does-not-exist", "X")
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--this-flag-does-not-exist" in result.output
    # No sibling has this — make sure we did not hallucinate one.
    assert "is accepted by" not in result.output
    # We still nudge to --help.
    assert "`direct ads update --help`" in result.output


def test_unknown_option_on_subgroup_also_gets_hint():
    """Unknown option passed to a group node (not a leaf command) — e.g.
    `direct ads --bogus get` — still goes through DirectCliGroup.parse_args
    and gets the help-hint fallback (no siblings can declare it because the
    siblings here are the root group's children)."""
    result = _invoke("ads", "--bogus-group-flag", "get")
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--bogus-group-flag" in result.output
    # parent is the root `cli`; siblings (campaigns, adgroups, ...) don't
    # share command-level options. We expect the help fallback, not silence.
    assert "`direct ads --help`" in result.output


def test_unknown_option_on_root_group_is_unchanged():
    """Root-level unknown options keep Click's default formatting; we do
    not have meaningful sibling info to add."""
    result = _invoke("--definitely-not-a-root-flag", "campaigns", "get")
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--definitely-not-a-root-flag" in result.output
    # We deliberately do not augment at the root.
    assert "Hint:" not in result.output


def test_hidden_deprecated_callback_still_takes_precedence():
    """`keywords update --bid` is a hidden deprecated trap with a
    custom message (keywords.py:_DEPRECATED_KEYWORDS_UPDATE_OPTIONS).
    The flag exists on the command (hidden), so parse_args succeeds and
    our NoSuchOption hook is never reached — the existing message wins.
    """
    result = _invoke("keywords", "update", "--id", "1", "--bid", "5")
    assert result.exit_code == 2
    assert "is no longer accepted on 'keywords update'" in result.output
    assert "direct bids set" in result.output
    # Our hook must not have fired.
    assert "Hint:" not in result.output


def test_no_foo_secondary_opt_is_recognised_as_sibling_option():
    """Regression for the Copilot/claude review on PR #237: Click stores
    the negative spelling of ``--foo/--no-foo`` switches in
    ``param.secondary_opts``, not ``param.opts``. ``agencyclients add``
    declares ``--send-warnings/--no-send-warnings`` and so does
    ``add-passport-organization``; ``agencyclients update`` does not.
    The hint must point at the right siblings.
    """
    result = _invoke(
        "agencyclients",
        "update",
        "--client-id",
        "1",
        "--no-send-warnings",
    )
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "--no-send-warnings" in result.output
    assert "Hint:" in result.output
    assert "`direct agencyclients add`" in result.output
    assert "`direct agencyclients add-passport-organization`" in result.output


def test_existing_substring_assert_for_ad_extensions_still_holds():
    """Backwards-compat: the assert from tests/test_dry_run.py:1209 must
    continue to match — our augmentation only appends to the message."""
    result = _invoke(
        "ads",
        "update",
        "--id",
        "999",
        "--type",
        "TEXT_AD",
        "--ad-extensions",
        "1,2",
        "--dry-run",
    )
    assert result.exit_code != 0
    assert "No such option" in result.output and "--ad-extensions" in result.output

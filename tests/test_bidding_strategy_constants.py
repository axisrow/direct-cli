"""Guard tests for the bidding-strategy subtype constants (Finding 8, #491 C2).

``direct_cli/_bidding_strategy.py`` exposes ~99 per-side ``_*_SUBTYPES`` /
``_*_SUPPORTS_*`` constants; ``campaigns.py`` imports 25 of them by name to
route typed strategy flags. Many share identical *values* across contexts
(TEXT vs UNIFIED, search vs network), but the names are intentionally
**separate**: each carries its own WSDL provenance, and aliasing across
contexts would create false coupling (a future WSDL change to one context
would silently drag the other). Finding 8's "dedupe via aliases" was therefore
rejected as low-value/unsafe; this guard is the lasting deliverable.

It pins three invariants so the later Phase-C refactors (C3-C8) cannot
regress silently:

1. **Import contract** — every name ``campaigns.py`` imports from
   ``_bidding_strategy`` still resolves (catches a silently broken import).
2. **Golden snapshot** — the 19 imported subtype *sets* keep their exact
   values (catches an accidental value change).
3. **Anti-merge** — the look-alike-but-different TEXT/UNIFIED pairs stay
   distinct (the ``AverageRoi`` trap), so no "optimizer" merges them.
"""

import ast
from pathlib import Path

import direct_cli._bidding_strategy as bs
from direct_cli._bidding_strategy import (
    _TEXT_NETWORK_BID_CEILING_SUBTYPES,
    _TEXT_NETWORK_GOAL_ID_SUBTYPES,
    _UNIFIED_NETWORK_BID_CEILING_SUBTYPES,
    _UNIFIED_NETWORK_GOAL_ID_SUBTYPES,
)

_CAMPAIGNS_PY = (
    Path(__file__).resolve().parent.parent / "direct_cli" / "commands" / "campaigns.py"
)

# Golden snapshot of the 19 subtype *sets* imported by campaigns.py, captured
# from the runtime values. A mismatch means a constant's value drifted.
_GOLDEN_SETS = {
    "_TEXT_NETWORK_AVERAGE_CPA_SUBTYPES": {"AverageCpa"},
    "_TEXT_NETWORK_BID_CEILING_SUBTYPES": {
        "AverageCpa",
        "AverageCpaMultipleGoals",
        "AverageRoi",
        "WbMaximumClicks",
        "WbMaximumConversionRate",
        "WeeklyClickPackage",
    },
    "_TEXT_NETWORK_CRR_SUBTYPES": {"AverageCrr", "PayForConversionCrr"},
    "_TEXT_NETWORK_GOAL_ID_SUBTYPES": {
        "AverageCpa",
        "AverageCrr",
        "AverageRoi",
        "PayForConversion",
        "PayForConversionCrr",
        "WbMaximumConversionRate",
    },
    "_TEXT_NETWORK_REQUIRES_PRIORITY_GOALS": {
        "AverageCpaMultipleGoals",
        "MaxProfit",
        "PayForConversionMultipleGoals",
    },
    "_TEXT_SEARCH_SUPPORTS_AVERAGE_CPA": {"AverageCpa"},
    "_TEXT_SEARCH_SUPPORTS_BID_CEILING": {
        "AverageCpa",
        "AverageCpaMultipleGoals",
        "AverageRoi",
        "WbMaximumClicks",
        "WbMaximumConversionRate",
        "WeeklyClickPackage",
    },
    "_TEXT_SEARCH_SUPPORTS_CRR": {"AverageCrr", "PayForConversionCrr"},
    "_TEXT_SEARCH_SUPPORTS_GOAL_ID": {
        "AverageCpa",
        "AverageCrr",
        "AverageRoi",
        "PayForConversion",
        "PayForConversionCrr",
        "WbMaximumConversionRate",
    },
    "_UNIFIED_NETWORK_AVERAGE_CPA_SUBTYPES": {"AverageCpa"},
    "_UNIFIED_NETWORK_BID_CEILING_SUBTYPES": {
        "AverageCpa",
        "AverageCpaMultipleGoals",
        "WbMaximumClicks",
        "WbMaximumConversionRate",
    },
    "_UNIFIED_NETWORK_CRR_SUBTYPES": {"AverageCrr", "PayForConversionCrr"},
    "_UNIFIED_NETWORK_GOAL_ID_SUBTYPES": {
        "AverageCpa",
        "AverageCrr",
        "PayForConversion",
        "PayForConversionCrr",
        "WbMaximumConversionRate",
    },
    "_UNIFIED_NETWORK_REQUIRES_PRIORITY_GOALS": {
        "AverageCpaMultipleGoals",
        "MaxProfit",
        "PayForConversionMultipleGoals",
    },
    "_UNIFIED_SEARCH_REQUIRES_PRIORITY_GOALS": {
        "AverageCpaMultipleGoals",
        "MaxProfit",
        "PayForConversionMultipleGoals",
    },
    "_UNIFIED_SEARCH_SUPPORTS_AVERAGE_CPA": {"AverageCpa"},
    "_UNIFIED_SEARCH_SUPPORTS_BID_CEILING": {
        "AverageCpa",
        "AverageCpaMultipleGoals",
        "WbMaximumClicks",
        "WbMaximumConversionRate",
    },
    "_UNIFIED_SEARCH_SUPPORTS_CRR": {"AverageCrr", "PayForConversionCrr"},
    "_UNIFIED_SEARCH_SUPPORTS_GOAL_ID": {
        "AverageCpa",
        "AverageCrr",
        "PayForConversion",
        "PayForConversionCrr",
        "WbMaximumConversionRate",
    },
}

# Non-set members imported by campaigns.py — pinned by existence + kind, not
# by value (their contents are larger and more volatile than the subtype sets).
_EXPECTED_LIST_NAMES = {"BUDGET_TYPES"}
_EXPECTED_DICT_NAMES = {
    "TEXT_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE",
    "UNIFIED_CAMPAIGN_NETWORK_STRATEGY_TO_WSDL_SUBTYPE",
    "_TEXT_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE",
    "_UNIFIED_CAMPAIGN_SEARCH_STRATEGY_TO_WSDL_SUBTYPE",
}
_EXPECTED_CALLABLE_NAMES = {"get_bidding_strategy_builder"}


def _imported_bidding_strategy_names():
    """Names campaigns.py imports from .._bidding_strategy (parsed from source)."""
    tree = ast.parse(_CAMPAIGNS_PY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "_bidding_strategy":
            return {alias.name for alias in node.names}
    raise AssertionError("no `from .._bidding_strategy import (...)` in campaigns.py")


def test_import_contract_every_imported_name_resolves():
    # Every name campaigns.py imports must still exist on the module, or the
    # import would break at load time (a silent regression for a later refactor).
    imported = _imported_bidding_strategy_names()
    missing = sorted(name for name in imported if not hasattr(bs, name))
    assert (
        not missing
    ), f"campaigns.py imports names absent from _bidding_strategy: {missing}"


def test_import_contract_matches_known_membership():
    # Two-sided check: the import block equals the union of the names this guard
    # knows about. Adding/removing an import without updating the snapshot fails
    # here — forcing a deliberate update of the golden set.
    imported = _imported_bidding_strategy_names()
    known = (
        set(_GOLDEN_SETS)
        | _EXPECTED_LIST_NAMES
        | _EXPECTED_DICT_NAMES
        | _EXPECTED_CALLABLE_NAMES
    )
    assert imported == known, (
        "import block drifted from the guard snapshot.\n"
        f"  only in campaigns.py import: {sorted(imported - known)}\n"
        f"  only in guard snapshot:      {sorted(known - imported)}"
    )


def test_golden_snapshot_subtype_sets_unchanged():
    for name, expected in _GOLDEN_SETS.items():
        actual = getattr(bs, name)
        assert actual == expected, f"{name} value drifted: {sorted(actual)!r}"


def test_non_set_members_have_expected_kind():
    for name in _EXPECTED_LIST_NAMES:
        assert isinstance(getattr(bs, name), list), name
    for name in _EXPECTED_DICT_NAMES:
        assert isinstance(getattr(bs, name), dict), name
    for name in _EXPECTED_CALLABLE_NAMES:
        assert callable(getattr(bs, name)), name


def test_lookalike_text_vs_unified_sets_stay_distinct():
    # The AverageRoi trap: UnifiedCampaign network does NOT support AverageRoi,
    # so these TEXT/UNIFIED pairs are value-similar but MUST stay different.
    # Pin the non-equality so no future dedup merges them.
    assert _TEXT_NETWORK_BID_CEILING_SUBTYPES != _UNIFIED_NETWORK_BID_CEILING_SUBTYPES
    assert _TEXT_NETWORK_GOAL_ID_SUBTYPES != _UNIFIED_NETWORK_GOAL_ID_SUBTYPES
    assert "AverageRoi" in _TEXT_NETWORK_BID_CEILING_SUBTYPES
    assert "AverageRoi" not in _UNIFIED_NETWORK_BID_CEILING_SUBTYPES
    assert "AverageRoi" in _TEXT_NETWORK_GOAL_ID_SUBTYPES
    assert "AverageRoi" not in _UNIFIED_NETWORK_GOAL_ID_SUBTYPES

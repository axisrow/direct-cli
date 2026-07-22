"""Dry-run payload tests for direct-cli write commands.

These tests use the ``--dry-run`` flag to verify the JSON request body
that direct-cli builds for every mutating command, **without** making any
HTTP calls. They run in the default pytest set (no markers, no token
needed) and complete in well under a second.

Why this file exists
--------------------

Until this PR, direct-cli had **zero** test coverage for write
operations. The Type-field bug in ``ads add`` (sending an explicit
top-level ``"Type"`` key that the Yandex Direct API rejects) shipped to
production specifically because no one had ever exercised an ``add``
command against a real API; the only mutating command anyone happened
to try was ``ads add``, and only after a user reported the failure
through the MCP plugin (axisrow/yandex-direct-mcp-plugin#60).

The audit that motivated this file (axisrow/yandex-direct-mcp-plugin#61)
counted **44 mutating commands across 28 services with 0% coverage**.
This file closes that gap by exercising every write command that has
a ``--dry-run`` flag and asserting the exact request body shape.

Two more occurrences of the same Type bug were found by this audit and
fixed alongside these tests:

* ``adgroups add`` — confirmed against the official Yandex Direct API
  v5 docs (https://yandex.ru/dev/direct/doc/ref-v5/adgroups/add.html);
  ``AdGroupAddItem`` has no top-level ``Type``.
* ``smartadtargets add`` / ``smartadtargets update`` — the legacy
  ``--type`` CLI option doesn't map to any real ``SmartAdTargetAddItem``
  field (real fields are ``TargetingId``, ``Bid``, ``Priority``).

Each test for an ``add`` command includes a regression assertion that
``"Type"`` is **not** present at the top level of the resource item, so
that re-introducing the bug breaks CI immediately.

Coverage scope
--------------

The suite covers both payload-building write commands (``add``,
``update``, ``set``) and the main single-action lifecycle
commands that now expose ``--dry-run`` (``delete``,
``suspend``, ``resume``, ``moderate``, ``archive``,
``unarchive``) so that trivial
``SelectionCriteria`` regressions are also caught in CI.

Part of axisrow/yandex-direct-mcp-plugin#61.

Module layout (issue #604)
--------------------------

This file used to hold all ~1400 dry-run tests in a single 24 898-line
module. It is now a thematic package of sibling modules; this file keeps
the shared rationale above plus a structural guard so the split cannot
silently drop a module.

* :mod:`tests.test_dry_run_shared` — the ``_dry_run`` / ``_read_dry_run`` /
  ``_rejected`` / ``_failing_run`` / ``_ids_csv`` / ``_write_jsonl``
  invocation helpers every other module imports.
* :mod:`tests.test_dry_run_common` — cross-cutting behaviour: generic
  ``get`` ``SelectionCriteria`` semantics, ``reports get``, micro-rubles
  validation and API error-hint enrichment.
* :mod:`tests.test_dry_run_campaigns` — ``campaigns add`` / ``update`` /
  ``get``.
* :mod:`tests.test_dry_run_strategy_smart` — SMART campaign search/network
  bidding strategies (plus the shared CPA base helper).
* :mod:`tests.test_dry_run_strategy_text` — TEXT campaign search/network
  bidding strategies.
* :mod:`tests.test_dry_run_strategy_unified` — UNIFIED campaign
  search/network bidding strategies.
* :mod:`tests.test_dry_run_strategies` — the ``strategies`` service
  (packaged bidding strategies).
* :mod:`tests.test_dry_run_ads` — ``ads``, ``adimages``, ``advideos``,
  ``creatives``.
* :mod:`tests.test_dry_run_adgroups` — ``adgroups``.
* :mod:`tests.test_dry_run_keywords` — ``keywords``,
  ``negativekeywordsharedsets``.
* :mod:`tests.test_dry_run_bids` — ``bids``, ``keywordbids``,
  ``bidmodifiers``.
* :mod:`tests.test_dry_run_targets` — ``audiencetargets``,
  ``dynamictextadtargets``, ``dynamicfeedadtargets``, ``smartadtargets``,
  ``retargetinglists``.
* :mod:`tests.test_dry_run_extensions` — ``sitelinks``, ``vcards``,
  ``adextensions``, ``feeds``.
* :mod:`tests.test_dry_run_clients` — ``clients``, ``agencyclients``.

When adding a dry-run test, put it in the module that owns the service and
import the helpers from :mod:`tests.test_dry_run_shared`; do not re-add
tests here.
"""

import importlib

import pytest

#: Every thematic module the historical monolith was split into (issue #604).
#: ``tests/test_api_coverage.py`` scans this same ``test_dry_run*.py`` glob when
#: resolving ``DRY_RUN_PAYLOAD_EXCLUSIONS`` rationales, so a module that stops
#: being importable would silently weaken that guard.
DRY_RUN_MODULES = (
    "tests.test_dry_run_shared",
    "tests.test_dry_run_common",
    "tests.test_dry_run_campaigns",
    "tests.test_dry_run_strategy_smart",
    "tests.test_dry_run_strategy_text",
    "tests.test_dry_run_strategy_unified",
    "tests.test_dry_run_strategies",
    "tests.test_dry_run_ads",
    "tests.test_dry_run_adgroups",
    "tests.test_dry_run_keywords",
    "tests.test_dry_run_bids",
    "tests.test_dry_run_targets",
    "tests.test_dry_run_extensions",
    "tests.test_dry_run_clients",
)


@pytest.mark.parametrize("module_name", DRY_RUN_MODULES)
def test_dry_run_module_is_importable(module_name):
    """Each split module must import cleanly and carry at least one test.

    Guards the issue #604 split: a module that disappears (or loses every
    test to a bad merge) would otherwise shrink dry-run coverage without any
    test turning red.
    """
    module = importlib.import_module(module_name)
    tests = [name for name in vars(module) if name.startswith("test_")]
    if module_name == "tests.test_dry_run_shared":
        assert not tests, "the shared helper module must not define tests"
    else:
        assert tests, f"{module_name} defines no tests"

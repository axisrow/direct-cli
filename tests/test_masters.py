"""
Tests for `direct masters` — the Мастер кампаний (Campaign Wizard) browser group.

Мастер кампаний has no API surface at all (see direct_cli/browser/__init__.py),
so unlike every other command module these tests never call a real API and
never launch a real browser.

``get`` (per-campaign overview) is a DOM parser exercised against small fake
Page/Locator objects that implement just the Playwright surface it calls
(locator/nth/count/inner_text/get_attribute/goto) — see
tests/fixtures/masters_wizard_overview.html for the live page structure these
fakes are modeled on.

``list`` reads the campaigns grid's own JSON data call instead of the DOM
(issue #639 found the grid is a virtualized SPA with no Мастер-related DOM to
scrape) — see tests/fixtures/masters_grid_campaigns.json for the trimmed real
GridCampaigns response these tests replay, and FakePage's ``request``/``on``
additions below for how that replay is faked.
"""

import ast
import contextlib
import inspect
import json
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import click
import pytest
from click.testing import CliRunner

from direct_cli.browser import _clock
from direct_cli.browser import masters as browser_masters
from direct_cli.browser.masters import PlaywrightError
from direct_cli.browser.session import (
    BrowserAuthError,
    BrowserCaptchaError,
    BrowserSessionError,
)
from direct_cli.cli import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# `_IMAGES_GHOST_GRACE_S` (issue #687) makes `_wait_for_images_editor` hold a
# "no StubN, no ContentImage yet" reading for real wall-clock seconds before
# trusting it as a genuinely empty image set, to survive a live ghost render
# pass no fake page here ever produces. Every test in this module drives fake
# Page/Locator objects with no real timing behaviour at all, so patched to 0
# for the whole module — otherwise every empty-image-set test (there are
# many, across several classes) would pay the real production grace period.
_images_ghost_grace_patch = patch.object(browser_masters, "_IMAGES_GHOST_GRACE_S", 0.0)

# Issue #767: every poll loop in `direct_cli/browser/` has two time sources —
# the deadline (`_clock.now()`) and the tick (`page.wait_for_timeout`, a real
# in-browser sleep in production). `FakePage.wait_for_timeout` is a no-op, so
# with a REAL deadline clock any test whose awaited condition never becomes
# true busy-spun for the full production timeout: `_STAT_TILES_TIMEOUT_MS`
# (30s), `_OVERVIEW_LOAD_TIMEOUT_MS` (30s), `_DRAFT_OVERVIEW_DETECT_TIMEOUT_MS`
# (15s)... five such tests in this file alone burned 135s of wall clock.
#
# Installing a module-wide fake clock that ONLY advances inside
# `wait_for_timeout` makes each loop run exactly `timeout_ms // tick_ms` ticks
# — the same iteration count as before, so no coverage is lost — but in
# microseconds instead of seconds, and deterministically rather than as a race
# against host CPU speed (the CPU-dependence issue #715 patched per-call).
_FAKE_CLOCK = {"now": 0.0}


def _fake_now():
    return _FAKE_CLOCK["now"]


def _advance_fake_clock(timeout_ms):
    """Advance the module-wide fake clock by a `wait_for_timeout` tick.

    Every `FakePage`-like stand-in in this module routes its
    `wait_for_timeout` here (directly, or via `super()`), so a subclass that
    overrides `wait_for_timeout` purely to count ticks must still call this —
    otherwise its loop's deadline never arrives and the test hangs.
    """
    _FAKE_CLOCK["now"] += (timeout_ms or 0) / 1000


def setUpModule():
    _images_ghost_grace_patch.start()
    _clock.set_clock(_fake_now)


def tearDownModule():
    _clock.set_clock(time.monotonic)
    _images_ghost_grace_patch.stop()


def _load_grid_campaigns_fixture():
    with open(FIXTURES_DIR / "masters_grid_campaigns.json", encoding="utf-8") as f:
        return json.load(f)


class _FakeLocatorHandle:
    """One matched element — the subset of Playwright's Locator API the parser uses.

    ``click``/``fill``/``check``/``uncheck``/``press``/``is_visible`` support
    ``update_master``'s ``_set_*`` functions (issue #631) and
    ``create_master``'s private helpers (issue #632) — ``on_click``/
    ``on_fill``/``on_check``/``on_press`` are optional no-arg/one-arg
    callbacks so tests can model the fake page's mutable state changing
    (mirrors ``_FakeTextLocatorHandle.on_click`` used by suspend/resume
    tests). ``input_value``/``is_checked`` support the post-save/post-create
    read-back verification in ``_verify_saved``/``_verify_created`` — they
    read the SAME mutable ``checked``/``value`` state ``fill``/``check``/
    ``uncheck`` write, via ``state`` dict callables (``get_value``/
    ``get_checked``), so a test can model "the reload shows what was
    actually saved" instead of "whatever was passed to fill/check".
    """

    def __init__(
        self,
        text="",
        attrs=None,
        raises=False,
        visible=True,
        on_click=None,
        on_fill=None,
        on_check=None,
        on_press=None,
        get_value=None,
        get_checked=None,
        on_upload=None,
        sub_locators=None,
        role_options=None,
        evaluate_result=None,
    ):
        self._text = text
        self._attrs = attrs or {}
        self._raises = raises
        self._visible = visible
        self._on_click = on_click
        self._on_fill = on_fill
        self._on_check = on_check
        self._on_press = on_press
        self._get_value = get_value
        self._get_checked = get_checked
        self._on_upload = on_upload
        # Result Locator.evaluate(js) should return for this handle — models
        # the structural content-ID resolution
        # ``_IMAGE_STATUS_CONTENT_ID_JS`` performs (issue #817): a fake status
        # button carries the content ID its structural walk would find,
        # rather than the reader trusting a positional index.
        self._evaluate_result = evaluate_result
        # Every `timeout=` this handle's click() was called with, in order
        # (issue #779 review) — see click().
        self.click_timeouts = []
        # {selector: _FakeLocatorHandle} for a SCOPED child lookup — models
        # Playwright's Locator.locator(), e.g. `label.locator("xpath=.//input
        # [...]")` (issue #656: _set_region reads a checkbox scoped off the
        # matched label handle itself, not via a second independent
        # page.locator() call built from the same selector string).
        self._sub_locators = sub_locators or {}
        # [_FakeLocatorHandle, ...] this handle's own get_by_role() call
        # enumerates — models Locator.get_by_role() scoped off an
        # already-matched locator (e.g. ``page.locator(listbox_testid).first
        # .get_by_role("option")``), used by ``_add_metrika_counter``/
        # ``_add_audience_tag`` (issue #648/#681) to enumerate an
        # autocomplete popup's option rows.
        self._role_options = role_options or []

    def locator(self, selector):
        handle = self._sub_locators.get(selector)
        return _FakeLocator([handle] if handle is not None else [])

    def get_by_role(self, role, name=None, exact=False):
        if name is None:
            return _FakeGetByTextLocator(list(self._role_options))
        matched = []
        for handle in self._role_options:
            text = handle.inner_text()
            if exact:
                if text == name:
                    matched.append(handle)
            elif name in text:
                matched.append(handle)
        return _FakeGetByTextLocator(matched)

    def inner_text(self, timeout=None):
        if self._raises:
            # Real Playwright raises its own Error (a TimeoutError subclass) when
            # an element is missing — masters.py's `except PlaywrightError` must
            # catch exactly this class, so the test uses the real one too.
            raise PlaywrightError("element not found")
        return self._text

    def get_attribute(self, name):
        return self._attrs.get(name)

    def evaluate(self, script, arg=None):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._evaluate_result

    def is_visible(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._visible

    def wait_for(self, state="visible", timeout=None):
        # Models Locator.wait_for(state="visible") — used by _read_goal_price
        # instead of a one-shot is_visible() snapshot (issue #696). Raises
        # the same PlaywrightError a real timeout would when the element is
        # absent/detached/not visible, so a test can model "field never
        # rendered" without a separate polling loop.
        if self._raises or not self._visible:
            raise PlaywrightError("Timeout waiting for element state")

    def click(self, timeout=None):
        # Record every click's timeout, including the ones that raise
        # (issue #779 review): a trigger that ISN'T on the page is exactly
        # the call whose missing `timeout=` costs Playwright's 30s default,
        # and this fake raises instantly, so the argument is the only
        # observable an offline test has for that cost.
        self.click_timeouts.append(timeout)
        if self._raises:
            raise PlaywrightError("element detached")
        if not self._visible:
            # Real Playwright's click() carries an actionability auto-wait
            # and times out (raising) against an element that never becomes
            # visible — models that terminal case. A handle whose
            # is_visible() flips True after some number of calls (see
            # test_does_not_raise_when_option_is_still_hydrating) still
            # succeeds here, since that test never calls click() while
            # _visible is False.
            raise PlaywrightError("Timeout waiting for element to be visible")
        if self._on_click is not None:
            self._on_click()

    def fill(self, value):
        if self._raises:
            raise PlaywrightError("element detached")
        self._text = value
        if self._on_fill is not None:
            self._on_fill(value)

    def type(self, value, delay=None):  # noqa: A003 - mirrors Playwright's Locator.type
        # Same fake behaviour as fill() — _fill_landing_url uses type()
        # instead of fill() because the real element is a contenteditable
        # <div>, not an <input>/<textarea> (issue #650), but the fake only
        # needs to record what was entered.
        self.fill(value)

    def text_content(self):
        # Supports _type_landing_url's retry-with-verify loop (issue #690):
        # it reads this back after every type() to confirm the widget didn't
        # drop characters, same underlying state fill()/type() write to.
        if self._raises:
            raise PlaywrightError("element detached")
        return self._text

    def check(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_check is not None:
            self._on_check(True)

    def uncheck(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_check is not None:
            self._on_check(False)

    def press(self, key):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_press is not None:
            self._on_press(key)

    def input_value(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_value() if self._get_value is not None else self._text

    def is_checked(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_checked() if self._get_checked is not None else False

    def count(self):
        # Playwright's `Locator.first` is itself a Locator, so `.first.count()`
        # is legal and answers "did the selector match anything?" — 0 when it
        # matched nothing (which is what `raises=True` models here, since
        # `_FakeLocator.first` hands back a raising handle for an empty match),
        # 1 otherwise. `_set_region` uses exactly this to decide whether the
        # region popup is already open before clicking the launcher again.
        return 0 if self._raises else 1

    def set_input_files(self, path):
        # Models Playwright's Locator.set_input_files() on the image manager
        # modal's hidden <input type="file"> (issue #670, Этап D) — a fake
        # test supplies ``on_upload`` to mutate whatever shared state models
        # "a new image now appears in the modal's selected panel".
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_upload is not None:
            self._on_upload(path)

    def scroll_into_view_if_needed(self, timeout=None):
        # Models Locator.scroll_into_view_if_needed() — delete_master
        # (issue #782 cycle-review follow-up) calls this as a best-effort
        # nudge against the virtualized campaigns grid, wrapped in its own
        # try/except, so this only needs to mirror "raises the same way
        # every other action does when the element never resolved/detached".
        if self._raises:
            raise PlaywrightError("element detached")


class _DynamicAttrsLocatorHandle(_FakeLocatorHandle):
    """A handle whose ``get_attribute`` reads LIVE state via a callable.

    ``_FakeLocatorHandle.get_attribute`` reads a snapshot dict fixed at
    construction time — insufficient for the "Директ помогает" toggle
    (issue #724), whose ``data-checked`` must reflect whatever the sibling
    label's click handler last wrote to shared test state. ``get_attrs`` is
    called on every ``get_attribute()``, mirroring how a real re-read always
    sees the DOM's current attribute value.
    """

    def __init__(self, *args, get_attrs, **kwargs):
        super().__init__(*args, **kwargs)
        self._get_attrs = get_attrs

    def get_attribute(self, name):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._get_attrs().get(name)


class _FakeContentEditableHandle(_FakeLocatorHandle):
    """A slot that models the REAL contenteditable semantics (issue #655 review).

    ``_FakeLocatorHandle.type()`` delegates to ``fill()``, which REPLACES the
    field's content — real ``Locator.type()`` on a ``contenteditable``
    APPENDS from the caret, which is the entire reason ``_clear_text_field``
    exists. A fake that replaces cannot observe a missing/failed clear, so it
    silently passes code that would splice the caller's value into Yandex's
    AI-generated copy (or leave that copy in place entirely).

    ``supports_modifier`` models Playwright <1.44, where ``ControlOrMeta`` is
    rejected server-side with ``Unknown modifier`` — the failure mode that
    makes the suppressed clear a no-op on the versions ``pyproject.toml``
    permits.
    """

    def __init__(self, *args, supports_modifier=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._supports_modifier = supports_modifier
        self._selected_all = False

    def type(self, value, delay=None):  # noqa: A003 - mirrors Locator.type
        if self._raises:
            raise PlaywrightError("element detached")
        # APPEND, exactly like the real contenteditable.
        self._text = self._text + value
        if self._on_fill is not None:
            self._on_fill(value)

    def press(self, key):
        if self._raises:
            raise PlaywrightError("element detached")
        if key == "ControlOrMeta+a":
            if not self._supports_modifier:
                # Playwright <1.44 throws this from input.ts, server-side.
                raise PlaywrightError("Unknown modifier ControlOrMeta")
            self._selected_all = True
        elif key == "Backspace" and self._selected_all:
            self._text = ""
            self._selected_all = False
        if self._on_press is not None:
            self._on_press(key)


class _CountOverrideLocator:
    """Wraps a REAL locator, optionally forcing ``count()`` to a fixed value
    and/or recording each call — the shape every "models a hydration dip"
    test in ``TestUpdateMaster`` needs.

    Those tests all want the same thing: a locator that reports the truthful
    row count except on the ticks where it should look mid-hydration, with
    ``nth()`` still delegating so a settled read sees the real rows. Before
    this helper each test nested its own 10-line class for that (there were
    seven, four of them byte-identical apart from the name), which made the
    obvious next step "add an eighth variant" rather than "parameterise".

    ``count=None`` delegates to the real locator; ``count=0`` (or any int)
    forces that value. ``on_count`` is called before each ``count()`` so a
    test can count reads or decide the dip's length from outside.
    """

    def __init__(self, real_locator, count=None, on_count=None):
        self._real = real_locator
        self._count = count
        self._on_count = on_count

    def count(self):
        if self._on_count is not None:
            self._on_count()
        return self._real.count() if self._count is None else self._count

    def nth(self, i):
        return self._real.nth(i)


class _FakeLocator:
    """A Locator for one selector — holds every matched handle for that selector."""

    def __init__(self, handles):
        self._handles = handles

    def count(self):
        return len(self._handles)

    def nth(self, i):
        return self._handles[i]

    @property
    def first(self):
        return self._handles[0] if self._handles else _FakeLocatorHandle(raises=True)

    def all_inner_texts(self):
        # Models Locator.all_inner_texts() — used by _read_target_actions
        # (issue #707) to read a target-action row's label off its
        # `[data-testid="Text"]` child (not unique across rows, so scoped by
        # a compound CSS selector rather than `.first`).
        return [handle.inner_text() for handle in self._handles]


class _FakeRequest:
    def __init__(self, post_data=None, headers=None):
        self.post_data = post_data
        self.headers = headers or {"x-csrf-token": "fake"}


class _FakeGridResponse:
    """The subset of Playwright's Response ``_capture_grid_campaigns_request``
    reads off the ``response`` event: ``url``, ``status``,
    ``request.post_data``, ``request.headers``."""

    def __init__(self, url, status=200, post_data=None, headers=None):
        self.url = url
        self.status = status
        self.request = _FakeRequest(post_data, headers)


class _FakeApiRequestContext:
    """Fakes ``page.request`` — the replayed POST used for pagination."""

    def __init__(self, pages=None, ok=True, status=200, raw_body=None):
        # `pages`: list of dict payloads returned on successive .post() calls
        # (one per pagination page); the last one repeats if exhausted.
        self._pages = pages or []
        self._call_count = 0
        self._ok = ok
        self._status = status
        self._raw_body = raw_body
        self.calls = []  # (url, data, headers) for assertions

    def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        idx = min(self._call_count, max(len(self._pages) - 1, 0))
        self._call_count += 1
        payload = self._pages[idx] if self._pages else {}
        return _FakeApiResponse(
            ok=self._ok, status=self._status, payload=payload, raw_body=self._raw_body
        )


class _FakeApiResponse:
    def __init__(self, ok=True, status=200, payload=None, raw_body=None):
        self.ok = ok
        self.status = status
        self._payload = payload
        self._raw_body = raw_body

    def json(self):
        if self._raw_body is not None:
            return json.loads(self._raw_body)  # may raise, on purpose
        return self._payload


class _FakeResponseInfo:
    """Mimics Playwright's ``EventContextManager`` returned by ``expect_response``.

    ``value`` is only resolved lazily (matching real Playwright, where the
    listener started in ``__enter__`` but the wait happens on first access
    to ``.value``, after the wrapped ``with`` block — e.g. ``goto`` — has
    run and had a chance to trigger the response).
    """

    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    @property
    def value(self):
        candidate = self._page._grid_response
        if candidate is not None and self._predicate(candidate):
            return candidate
        # Real Playwright raises its TimeoutError (a PlaywrightError
        # subclass) when the predicate never matches within the timeout.
        raise PlaywrightError("Timeout waiting for response")


class _FakeExpectResponse:
    """Context manager fake for ``page.expect_response(predicate, timeout=...)``."""

    def __init__(self, page, predicate):
        self._page = page
        self._predicate = predicate

    def __enter__(self):
        return _FakeResponseInfo(self._page, self._predicate)

    def __exit__(self, *exc_info):
        return False


class _FakeExpectResponseExitRaises(_FakeExpectResponse):
    """Faithfully mimics real Playwright's ``EventContextManager.__exit__``.

    Real Playwright resolves ``response_info.value`` itself inside
    ``__exit__`` when the wrapped ``with`` block exits without raising — so
    a ``expect_response`` timeout surfaces as an exception from the `with`
    block's own exit, NOT from a later, separate access to
    ``response_info.value`` (see issue #694). ``_FakeExpectResponse``/
    ``_FakeResponseInfo`` above resolve lazily on ``.value`` access instead,
    which cannot reproduce that ordering bug — this subclass raises in
    ``__exit__`` itself when no matching response was ever observed, to
    exercise the real failure mode.
    """

    def __exit__(self, *exc_info):
        if exc_info[0] is not None:
            return False
        candidate = self._page._grid_response
        if candidate is None or not self._predicate(candidate):
            raise PlaywrightError("Timeout waiting for response")
        return False


class _FakeAncestorLocator:
    """Result of ``handle.locator("xpath=ancestor-or-self::button[1]")``.

    ``count()`` is 0 when the matched node has no enclosing ``<button>``,
    in which case ``_click_action_button`` clicks the node itself.
    """

    def __init__(self, button):
        self._button = button

    def count(self):
        return 1 if self._button is not None else 0

    @property
    def first(self):
        return self._button


class _FakeTextLocatorHandle:
    """One matched element for ``get_by_text`` — supports ``is_visible``/``click``.

    ``on_click`` is an optional no-arg callback invoked when ``click()`` is
    called — used to model a suspend/resume click flipping the fake page's
    status text.
    """

    def __init__(
        self,
        visible=True,
        on_click=None,
        raises=False,
        disabled=False,
        aria_disabled=None,
        button_ancestor=None,
    ):
        self._visible = visible
        self._on_click = on_click
        self._raises = raises
        self._disabled = disabled
        self._aria_disabled = aria_disabled
        # Models the `xpath=ancestor-or-self::button[1]` resolution
        # `_click_action_button` performs (issue #766): real Yandex markup
        # matches the <span> inside the button, so the module walks up to the
        # <button> before clicking. `None` models a match with no button
        # ancestor, where the module clicks the matched node itself.
        self._button_ancestor = button_ancestor

    def locator(self, selector):
        if "ancestor-or-self::button" not in selector:
            raise AssertionError(f"unexpected locator selector: {selector!r}")
        return _FakeAncestorLocator(self._button_ancestor)

    def is_visible(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._visible

    def is_disabled(self):
        if self._raises:
            raise PlaywrightError("element detached")
        return self._disabled

    def get_attribute(self, name):
        if name == "disabled":
            return "" if self._disabled else None
        if name == "aria-disabled":
            return self._aria_disabled
        return None

    def click(self):
        if self._raises:
            raise PlaywrightError("element detached")
        if self._on_click is not None:
            self._on_click()


class _FakeGetByTextLocator:
    """Fakes ``page.get_by_text(text, exact=False)`` — one handle list per text."""

    def __init__(self, handles):
        self._handles = handles

    def count(self):
        return len(self._handles)

    def nth(self, i):
        return self._handles[i]

    @property
    def first(self):
        # Mirrors real Playwright's Locator.first (and _FakeLocator.first's
        # own identical fallback) — issue #796's
        # _close_target_actions_search_popup uses it on a get_by_text()
        # result the same way every other locator in this module does. An
        # empty match returns a handle that raises on use, not an
        # IndexError on attribute access, so callers wrapped in
        # contextlib.suppress(PlaywrightError) (as that function is) see
        # the same "best-effort, no-op on absence" behaviour a real empty
        # Locator's timeout would produce.
        return self._handles[0] if self._handles else _FakeLocatorHandle(raises=True)


class FakePage:
    """A Page whose ``locator(selector)`` result is pre-scripted per selector."""

    def __init__(
        self,
        locators=None,
        body_text="",
        html="<html></html>",
        grid_response=None,
        api_request=None,
        text_buttons=None,
        role_elements=None,
        locators_after_navigation=None,
    ):
        self._locators = locators or {}
        # Issue #744 cycle-review: a real navigation REPLACES the DOM, so a
        # fake whose locator map survives goto() cannot distinguish "read
        # the field before navigating" from "read it after". That blindness
        # hid a live defect — _verify_created read the create form's slots
        # off the post-redirect overview page, which does not render them.
        # A test that passes this dict gets the map swapped on the first
        # goto()/url change, modelling the page the caller actually lands on.
        self._locators_after_navigation = locators_after_navigation
        # Armed by the url setter, committed by the url getter — see both.
        self._pending_locators = None
        # Every overview-page test implicitly exercises _goto_overview_page
        # (issue #683), which polls for this exact testid before returning
        # control to the caller — default it present so existing tests that
        # don't care about the wait mechanics aren't all forced to register
        # it explicitly. A test that DOES care (e.g. the DRAFT-shaped
        # "marker never appears" timeout case) removes it from `locators`.
        self._locators.setdefault(
            browser_masters._OVERVIEW_TITLE_SELECTOR,
            _FakeLocator([_FakeLocatorHandle()]),
        )
        self._body_text = body_text
        self._html = html
        self.navigated_to = []
        self.goto_wait_until = None
        self.closed = False
        # Mutated by goto() and settable directly by a test's on_click
        # callback to simulate Yandex's post-click redirect (see
        # TestCopyMaster) — copy_master polls this the same way
        # archive_master polls fetch_masters_list.
        self._url = ""
        # If set, matched by expect_response()'s predicate once goto() has
        # been called inside its `with` block — models the grid firing its
        # GridCampaigns XHR during navigation.
        self._grid_response = grid_response
        self.request = api_request or _FakeApiRequestContext()
        # {text: _FakeGetByTextLocator} for get_by_text() — used by
        # suspend_master/resume_master's action-button click.
        self._text_buttons = text_buttons or {}
        # [(role, accessible_name, handle), ...] for get_by_role() — honors
        # `exact` the same way real Playwright does (substring vs. equality
        # against `accessible_name`), so a fake test can actually catch a
        # get_by_role() call whose `exact`/`name` doesn't match the real
        # element, instead of always matching by selector-string identity
        # (issue #631 cycle-review: the previous get_by_text-based fakes
        # could not distinguish a correct role-scoped match from an
        # accidental ancestor-container match).
        self._role_elements = role_elements or []
        # Callable(arg) -> result for evaluate() -- see evaluate()'s own
        # docstring (issue #791, _scroll_grid_to_row).
        self._evaluate_side_effect = None

    @property
    def url(self):
        """Reading the redirected URL is what commits the DOM swap.

        Issue #744 cycle-review. A property rather than a plain attribute so
        the fake can model the one ordering that matters: in a real SPA the
        URL changes first (history.pushState) and the DOM is replaced
        shortly after, so code that reads the create form BETWEEN the click
        and the redirect wait still finds it, while code that reads it after
        `_wait_for_created_campaign_id` (which polls this property until the
        URL carries a campaign id) finds the page it landed on instead.

        Committing on read rather than on assignment is what makes the fake
        able to tell those two orderings apart — assigning on click swapped
        the map before `create_master` had read anything, which made a
        correctly-ordered implementation look broken.
        """
        if self._pending_locators is not None:
            self._locators = self._pending_locators
            self._pending_locators = None
        return self._url

    @url.setter
    def url(self, value):
        """Arm the DOM swap; the read above commits it.

        A test's on_click callback simulates Yandex's post-click redirect by
        assigning ``page.url`` directly, exactly as goto() does. The initial
        navigation TO the create page is deliberately exempt: that one
        renders the form this fake is scripted with.
        """
        leaving_create_page = (
            self._url == browser_masters.WIZARD_CREATE_URL and value != self._url
        )
        self._url = value
        if leaving_create_page and self._locators_after_navigation is not None:
            self._pending_locators = self._locators_after_navigation

    def goto(self, url, wait_until=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until
        self.url = url

    def close(self):
        self.closed = True

    def expect_response(self, predicate, timeout=None):
        if getattr(self, "_expect_response_exit_raises", False):
            return _FakeExpectResponseExitRaises(self, predicate)
        return _FakeExpectResponse(self, predicate)

    def eval_on_selector_all(self, selector, expression):
        return []

    def evaluate(self, script, arg=None):
        # _scroll_grid_to_row (issue #791) is the only caller: a test wires
        # up ``self._evaluate_side_effect`` (a callable taking the same
        # ``arg`` this method receives) to model the grid's virtual-scroll
        # container being found/not-found, or a test overrides this method
        # entirely for an exception path. Defaults to ``False`` (row never
        # found) so any test that doesn't care about scroll behaviour gets
        # the same "no-op, fall through to the existing retry loop" shape
        # as production code hitting a real page without this call wired.
        if self._evaluate_side_effect is not None:
            return self._evaluate_side_effect(arg)
        return False

    def locator(self, selector):
        return self._locators.get(selector, _FakeLocator([]))

    def get_by_text(self, text, exact=False):
        return self._text_buttons.get(text, _FakeGetByTextLocator([]))

    def get_by_role(self, role, name=None, exact=False):
        matched = []
        for elem_role, elem_name, handle in self._role_elements:
            if elem_role != role:
                continue
            if name is None:
                matched.append(handle)
            elif exact:
                if elem_name == name:
                    matched.append(handle)
            elif name in elem_name:
                matched.append(handle)
        return _FakeGetByTextLocator(matched)

    def inner_text(self, selector=None):
        return self._body_text

    def content(self):
        return self._html

    def wait_for_timeout(self, timeout):
        # Advances the module-wide fake clock instead of really sleeping —
        # see `_advance_fake_clock` (issue #767).
        _advance_fake_clock(timeout)

    @property
    def mouse(self):
        return _FakeMouse()

    @property
    def keyboard(self):
        return _FakeKeyboard()


class _FakeMouse:
    """Minimal ``page.mouse`` stand-in — only ``wheel()`` is used
    (``_click_save``'s scroll-to-bottom-before-searching step)."""

    def wheel(self, delta_x, delta_y):
        pass


class _FakeKeyboard:
    """Minimal ``page.keyboard`` stand-in — only ``press()`` is used
    (``_read_devices``/``_set_devices``/``_add_audience_tag`` closing the
    device or tag-suggestion popup via Escape, issue #681)."""

    def press(self, key):
        pass


def _passport_page(html="<body>Войдите с Яндекс ID</body>", **kwargs):
    """A ``FakePage`` that also carries the Passport DOM marker.

    ``session.py``'s ``login_persistent_session``/``capture_storage_state``
    poll for ``_PASSPORT_PAGE_MARKERS``/``_DIRECT_PAGE_MARKERS`` via
    ``_wait_for_marker`` after every ``wait_until="commit"`` navigation
    (issue #686) — a bare ``FakePage(locators={}, html=...)`` matches neither
    marker, so ``_wait_for_marker`` would poll for real wall-clock seconds
    until timeout. This factory (and ``_direct_page`` below) keeps the fake's
    ``locators`` in sync with whichever page state its ``html`` models.
    """
    from direct_cli.browser import session as session_module

    locators = dict(kwargs.pop("locators", {}) or {})
    for selector in session_module._PASSPORT_PAGE_MARKERS:
        locators.setdefault(selector, _FakeLocator([_FakeLocatorHandle()]))
    return FakePage(locators=locators, html=html, **kwargs)


def _direct_page(html="<body>Кампания остановлена</body>", **kwargs):
    """A ``FakePage`` that also carries the Direct (grid) DOM marker.

    See ``_passport_page``'s docstring — same rationale, opposite page.
    """
    from direct_cli.browser import session as session_module

    locators = dict(kwargs.pop("locators", {}) or {})
    for selector in session_module._DIRECT_PAGE_MARKERS:
        locators.setdefault(selector, _FakeLocator([_FakeLocatorHandle()]))
    return FakePage(locators=locators, html=html, **kwargs)


class TestMastersRegistered(unittest.TestCase):
    """The group and its subcommands must be wired into the root CLI."""

    def setUp(self):
        self.runner = CliRunner()

    def test_masters_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("list", result.output)
        self.assertIn("get", result.output)
        self.assertIn("login", result.output)
        self.assertIn("logout", result.output)

    def test_masters_list_help(self):
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_masters_list_help_documents_chrome_profile_flag(self):
        # session.py's error message tells users with a non-Default Chrome
        # profile to pass --chrome-profile — that flag must actually exist.
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertIn("--chrome-profile", result.output)

    def test_masters_get_help(self):
        result = self.runner.invoke(cli, ["masters", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_masters_list_has_no_login_option(self):
        # #639: --login built a `?ulogin=<own login>` URL, which Yandex
        # rejects with HTTP 401 "Доступ ограничен" — masters only ever reads
        # the logged-in browser session's own account, so the option is gone.
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("--login", result.output)

    def test_masters_get_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "get", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("--login", result.output)

    def test_masters_list_has_status_option(self):
        result = self.runner.invoke(cli, ["masters", "list", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--status", result.output)

    def test_masters_no_credentials_required(self):
        # masters is in cli.py's _NO_CREDENTIALS_GROUPS -- no API token/login
        # is needed to even reach the browser layer's own errors.
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(
                cli,
                ["masters", "list"],
                env={"YANDEX_DIRECT_TOKEN": "", "YANDEX_DIRECT_LOGIN": ""},
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())
        self.assertIn("pip install", result.output)
        self.assertNotIn("token", result.output.lower())

    def test_masters_list_missing_playwright_shows_install_hint(self):
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(cli, ["masters", "list"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())
        self.assertIn("pip install", result.output)

    def test_open_session_catches_errors_raised_inside_the_with_block(self):
        # Regression test for #634: open_chrome_session is a
        # @contextlib.contextmanager, so calling it only builds a generator —
        # anything its body raises only surfaces on `__enter__`. A naive
        # `try: return open_chrome_session(...) except BrowserSessionError`
        # around just the *call* can never catch that (the call itself never
        # raises), so commands/masters.py::_open_session must itself be a
        # contextmanager wrapping the inner `with` statement — see its
        # docstring. This matters once code *inside* the `with` block raises
        # a BrowserSessionError subclass too (e.g. BrowserAuthError from
        # #634's login-page detector), which must be reported the same way.
        import contextlib

        from direct_cli.commands.masters import _open_session, masters

        # A genuine contextmanager generator whose body raises on __enter__,
        # exactly like open_chrome_session — not a mock with side_effect=,
        # which would raise on call and prove nothing about this bug.
        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            raise BrowserSessionError("boom from generator body")
            yield  # pragma: no cover - unreachable, contextmanager shape only

        # A real click.Context (rather than a bare Mock) so
        # ctx.get_parameter_source(...) behaves correctly for tier-1
        # detection inside _open_session. Built from the `list` subcommand
        # (not the `masters` group itself, which is no_args_is_help).
        list_cmd = masters.commands["list"]
        with list_cmd.make_context("list", []) as ctx:
            with (
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
            ):
                with self.assertRaises(click.ClickException) as cm:
                    with _open_session(
                        ctx, headful=False, profile_dir=None, chrome_profile="Default"
                    ):
                        pass
        self.assertIn("boom from generator body", str(cm.exception))


class _FakeContext:
    def __init__(self):
        self.added_cookies = None
        self.closed = False
        self.locale = None

    def add_cookies(self, cookies):
        self.added_cookies = cookies

    def new_page(self):
        return FakePage()

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.contexts_created = []
        self.closed = False
        self.launch_kwargs = None

    def new_context(self, **kwargs):
        ctx = _FakeContext()
        ctx.locale = kwargs.get("locale")
        self.contexts_created.append(ctx)
        return ctx

    def close(self):
        self.closed = True


class _FakePersistentContext:
    """Fakes the context ``launch_persistent_context`` returns directly.

    Unlike ``_FakeBrowser``/``_FakeContext`` (a separate browser + context
    pair for ``chromium.launch()``), a persistent context IS the return
    value — there is no separate ``Browser`` object to close.
    """

    def __init__(self, pages=None):
        self.closed = False
        self.launch_kwargs = None
        self._pages = list(pages or [])

    def new_page(self):
        if self._pages:
            return self._pages.pop(0)
        return FakePage()

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser, persistent_context=None):
        self._browser = browser
        self._persistent_context = persistent_context
        self.launch_kwargs = None
        self.launch_persistent_context_kwargs = None
        self.launch_persistent_context_user_data_dir = None

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return self._browser

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.launch_persistent_context_user_data_dir = user_data_dir
        self.launch_persistent_context_kwargs = kwargs
        return self._persistent_context


class _FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestOpenChromeSession(unittest.TestCase):
    """#634: cookies are decrypted ourselves and injected via add_cookies(),
    rather than relying on a real Chrome launched on a copied profile."""

    def test_injects_decrypted_cookies_without_requesting_real_chrome_channel(self):
        # playwright is the optional `browser` extra, not an offline test
        # dependency — the offline CI job doesn't install it, and this test
        # patches "playwright.sync_api.sync_playwright" by string path, which
        # requires the real import to succeed.
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        fake_browser = _FakeBrowser()
        fake_chromium = _FakeChromium(fake_browser)
        fake_playwright = _FakePlaywright(fake_chromium)
        fake_cookies = [{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}]

        with (
            patch(
                "playwright.sync_api.sync_playwright",
                return_value=fake_playwright,
            ),
            patch(
                "direct_cli.browser._chrome_crypto.load_yandex_cookies",
                return_value=fake_cookies,
            ),
            patch.object(
                session_module,
                "default_chrome_profile_dir",
                return_value=Path("/fake/chrome/profile"),
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            with session_module.open_chrome_session() as page:
                self.assertIsInstance(page, FakePage)

        # Cookies were injected, not left for a real Chrome to decrypt itself.
        ctx = fake_browser.contexts_created[0]
        self.assertEqual(ctx.added_cookies, fake_cookies)
        self.assertEqual(ctx.locale, "ru-RU")
        # channel="chrome" required a real Google Chrome install to be
        # present; bundled Chromium is now sufficient since we no longer
        # depend on the real browser to decrypt cookies for us.
        self.assertNotIn("channel", fake_chromium.launch_kwargs)
        # Both the context and the browser process must be cleaned up.
        self.assertTrue(ctx.closed)
        self.assertTrue(fake_browser.closed)


class TestPersistentSession(unittest.TestCase):
    """direct masters login (issue #635) — CLI-owned persistent Chromium
    profile, no Keychain/real-Chrome-cookie involvement at all.

    Uses real temp directories (rather than fake Path patching) because
    _launch_persistent_context calls profile_dir.mkdir() for real.
    """

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.profile_dir = Path(self._tmpdir.name) / "chrome-profile"
        # A completed login records its profile dir; keep that off the
        # developer's real ~/.direct-cli.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path(self._tmpdir.name) / "chrome-profile-path",
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _make_profile(self):
        """Create a profile dir the way a completed `masters login` leaves it."""
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()

    def test_login_refuses_to_mark_an_existing_unrelated_directory(self):
        """`--profile-dir` at an existing directory must not be claimed.

        Codex review finding on PR #644: the profile dir was created with
        `exist_ok=True` and then unconditionally marked CLI-owned, so
        `masters login --profile-dir ~` planted the ownership marker into the
        user's home directory — and `masters logout` on the same path then
        accepted that marker as authorization to `shutil.rmtree` it. A failed
        login armed it just the same, because the marker was written before
        Chromium even launched.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import (
            PROFILE_MARKER_NAME,
            BrowserSessionError,
        )

        victim = Path(self._tmpdir.name) / "my-documents"
        victim.mkdir()
        (victim / "taxes.pdf").write_text("important")

        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserSessionError) as ctx:
                session_module.login_persistent_session(
                    profile_dir=victim, timeout_ms=1_000
                )

        self.assertFalse(
            (victim / PROFILE_MARKER_NAME).exists(),
            "login planted an ownership marker in a directory it did not create",
        )
        self.assertTrue((victim / "taxes.pdf").exists())
        self.assertIn("already exists", str(ctx.exception).lower())

    def test_aborted_login_does_not_leave_a_profile_that_looks_usable(self):
        """A login that never completed must not register as a usable profile.

        `_launch_persistent_context` creates the directory before Chromium
        starts, so a login the user ctrl-C's out of (or that times out) leaves
        a directory behind with no session in it. If tier 1.5 accepted mere
        directory existence, every later `masters` call would route through
        that empty profile, launch a browser, fail auth, and only then fall
        back — paying a wasted browser launch each time and bypassing the
        user's working saved session.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = _passport_page()
        probe_page = _passport_page()
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError):
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir, timeout_ms=1_000
                )

        self.assertFalse(
            session_module.persistent_profile_is_usable(self.profile_dir),
            "an aborted login left a profile tier 1.5 would route through",
        )

    def test_recorded_profile_dir_is_absolute(self):
        """The login pointer must not make later commands depend on cwd.

        `masters login --profile-dir prof` recorded "prof" verbatim, so
        `masters logout` run from a different directory resolved it against
        *that* cwd — deleting a different profile, or none. The marker check
        still bounded the damage, but which directory a command acts on must
        not depend on where the user happens to be standing.
        """
        from direct_cli.browser import session as session_module

        pointer = Path(self._tmpdir.name) / "chrome-profile-path"
        with patch.object(session_module, "PROFILE_POINTER_PATH", pointer):
            session_module.remember_persistent_profile_dir(Path("relative/profile"))
            recorded = session_module.configured_persistent_profile_dir()

        self.assertTrue(
            recorded.is_absolute(),
            f"recorded a cwd-dependent path: {recorded}",
        )

    def test_open_persistent_session_raises_when_profile_missing(self):
        pytest.importorskip("playwright")
        from direct_cli.browser.session import (
            BrowserSessionMissingError,
            open_persistent_session,
        )

        with self.assertRaises(BrowserSessionMissingError) as ctx:
            with open_persistent_session(profile_dir=self.profile_dir):
                pass
        self.assertIn("masters login", str(ctx.exception))

    def test_open_persistent_session_launches_persistent_context(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        self._make_profile()
        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with session_module.open_persistent_session(
                profile_dir=self.profile_dir
            ) as page:
                self.assertIsInstance(page, FakePage)

        self.assertEqual(
            fake_chromium.launch_persistent_context_user_data_dir,
            str(self.profile_dir),
        )
        self.assertEqual(
            fake_chromium.launch_persistent_context_kwargs["locale"], "ru-RU"
        )
        self.assertTrue(persistent_ctx.closed)

    def test_open_persistent_session_chmods_profile_dir_0700(self):
        # issue #635 risk: the profile holds a live Yandex session in
        # plaintext-readable cookies -- must be 0700, same as
        # direct_cli/browser/store.py's session file directory.
        pytest.importorskip("playwright")
        import stat

        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        # A real profile (marker present) that has somehow ended up
        # world-readable -- reopening it must tighten the mode back to 0700.
        self.profile_dir.mkdir(parents=True, mode=0o755)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()
        persistent_ctx = _FakePersistentContext()
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with session_module.open_persistent_session(profile_dir=self.profile_dir):
                pass

        mode = stat.S_IMODE(self.profile_dir.stat().st_mode)
        self.assertEqual(format(mode, "04o"), "0700")

    def test_login_persistent_session_returns_once_authenticated(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        # Page 1 is the visible Passport tab; page 2 is the poll probe whose
        # HTML decides whether login has completed.
        login_page = _passport_page()
        authed_page = _direct_page()
        persistent_ctx = _FakePersistentContext(pages=[login_page, authed_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            session_module.login_persistent_session(
                profile_dir=self.profile_dir, timeout_ms=5_000
            )

        self.assertTrue(persistent_ctx.closed)
        self.assertTrue(self.profile_dir.exists())

    def test_login_persistent_session_times_out_if_never_authenticated(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = _passport_page()
        probe_page = _passport_page()
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError) as ctx:
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir,
                    timeout_ms=1_000,
                )
        self.assertIn("Timed out", str(ctx.exception))
        self.assertTrue(probe_page.closed, "poll probe page was left open")

    def test_login_polling_does_not_navigate_the_page_the_user_is_typing_into(self):
        """The visible login page must stay on Passport until login succeeds.

        The poll loop checks authentication by driving the *same* page the
        human is typing into. Every interval it navigates that page away to
        the grid, wiping a half-filled login form and any 2FA prompt on it —
        the user cannot finish signing in against a page that resets under
        their hands once a second.
        """
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = _passport_page()
        probe_page = _passport_page()
        persistent_ctx = _FakePersistentContext(pages=[login_page, probe_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError):
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir,
                    timeout_ms=3_000,
                )

        # The page the user interacts with is navigated exactly once: to
        # Passport. Polling must not steer it anywhere else.
        self.assertEqual(
            login_page.navigated_to,
            [session_module._PASSPORT_LOGIN_URL],
            "poll loop navigated the user's login page away from Passport",
        )

    def test_login_navigations_use_commit_not_domcontentloaded(self):
        """Issue #686: both `goto` calls in the login flow (the visible
        Passport tab and the poll probe) must use `wait_until="commit"`, not
        `domcontentloaded` — Passport occasionally timed out on
        `domcontentloaded` during its own slow initial paint. `commit`
        returns as soon as the navigation is committed, and
        `_wait_for_marker` polling for a concrete DOM marker afterwards is
        what actually confirms the page rendered (see `_wait_for_marker`'s
        docstring)."""
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        login_page = _passport_page()
        authed_page = _direct_page()
        persistent_ctx = _FakePersistentContext(pages=[login_page, authed_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            session_module.login_persistent_session(
                profile_dir=self.profile_dir, timeout_ms=5_000
            )

        self.assertEqual(login_page.goto_wait_until, "commit")
        self.assertEqual(authed_page.goto_wait_until, "commit")

    def test_login_fails_closed_when_passport_marker_never_appears(self):
        """Issue #692 cycle-review: `_wait_for_marker`'s `False` return must
        not be discarded. A blank/unrendered Passport page matches neither
        `_PASSPORT_PAGE_MARKERS` nor `_LOGIN_PAGE_MARKERS` — trusting
        `page.content()` regardless would let an unrendered page slip past
        `assert_authenticated` undetected, instead of failing loudly."""
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        blank_page = FakePage(locators={}, html="<html></html>")
        persistent_ctx = _FakePersistentContext(pages=[blank_page])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with (
            patch("playwright.sync_api.sync_playwright", return_value=fake_playwright),
            patch.object(session_module, "_PAGE_MARKER_TIMEOUT_MS", 10),
        ):
            with self.assertRaises(session_module.BrowserSessionError) as ctx:
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir, timeout_ms=5_000
                )
        self.assertIn("Timed out", str(ctx.exception))
        self.assertFalse(
            session_module.PROFILE_POINTER_PATH.exists(),
            "an unrendered login must not be recorded as a usable profile",
        )

    def test_login_poll_treats_unrendered_tick_as_not_yet_authenticated(self):
        """Issue #692 cycle-review: a tick where neither the grid nor
        Passport marker appears must be treated like "not authenticated
        yet" (same as an explicit `BrowserAuthError`), not like a
        successful, verified login — a blank grid response matches neither
        `_LOGIN_PAGE_MARKERS` nor a captcha marker, so `assert_authenticated`
        alone would silently accept it."""
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        login_page = _passport_page()
        blank_probe = FakePage(locators={}, html="<html></html>")
        persistent_ctx = _FakePersistentContext(pages=[login_page, blank_probe])
        fake_chromium = _FakeChromium(_FakeBrowser(), persistent_ctx)
        fake_playwright = _FakePlaywright(fake_chromium)

        with patch("playwright.sync_api.sync_playwright", return_value=fake_playwright):
            with self.assertRaises(BrowserAuthError):
                session_module.login_persistent_session(
                    profile_dir=self.profile_dir,
                    timeout_ms=1_000,
                )

        # The unfinished login must never be recorded as a usable profile.
        self.assertFalse(session_module.PROFILE_POINTER_PATH.exists())


class _FakeVerifyContext(_FakeContext):
    """A ``_FakeContext`` whose ``new_page()`` returns one pre-built page and
    which fakes ``storage_state()`` — needed by ``capture_storage_state``,
    which neither ``_FakeContext`` nor ``_FakePersistentContext`` support.
    """

    def __init__(self, page, storage_state=None):
        super().__init__()
        self._page = page
        self._storage_state = storage_state if storage_state is not None else {}

    def new_page(self):
        return self._page

    def storage_state(self):
        return self._storage_state


class TestCaptureStorageState(unittest.TestCase):
    """``capture_storage_state`` (``direct playwright login``'s verify path)
    — issue #686: the grid ``goto`` must use ``wait_until="commit"`` +
    ``_wait_for_marker`` instead of ``domcontentloaded``.
    """

    def _patch_decrypt(self):
        return patch(
            "direct_cli.browser._chrome_crypto.load_yandex_cookies",
            return_value=[{"name": "Session_id", "value": "x", "domain": ".yandex.ru"}],
        )

    def test_verify_navigation_uses_commit_and_succeeds_against_the_grid(self):
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module

        page = _direct_page()
        fake_browser = _FakeBrowser()
        fake_context = _FakeVerifyContext(page, storage_state={"cookies": []})
        fake_browser.new_context = lambda **kwargs: fake_context
        fake_chromium = _FakeChromium(fake_browser)
        fake_playwright = _FakePlaywright(fake_chromium)

        with (
            patch("playwright.sync_api.sync_playwright", return_value=fake_playwright),
            self._patch_decrypt(),
            patch.object(
                session_module,
                "default_chrome_profile_dir",
                return_value=Path("/fake/chrome/profile"),
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            storage_state, _source_meta = session_module.capture_storage_state()

        self.assertEqual(page.goto_wait_until, "commit")
        self.assertEqual(storage_state, {"cookies": []})

    def test_verify_raises_auth_error_when_grid_redirects_to_passport(self):
        """A bad/expired cookie jar redirects the grid URL to Passport
        instead of rendering the grid — `_wait_for_marker` must accept
        either page's marker (see its docstring) so `assert_authenticated`
        gets a real, rendered page to inspect, not an in-progress shell."""
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        page = _passport_page()
        fake_browser = _FakeBrowser()
        fake_context = _FakeVerifyContext(page)
        fake_browser.new_context = lambda **kwargs: fake_context
        fake_chromium = _FakeChromium(fake_browser)
        fake_playwright = _FakePlaywright(fake_chromium)

        with (
            patch("playwright.sync_api.sync_playwright", return_value=fake_playwright),
            self._patch_decrypt(),
            patch.object(
                session_module,
                "default_chrome_profile_dir",
                return_value=Path("/fake/chrome/profile"),
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            with self.assertRaises(BrowserAuthError):
                session_module.capture_storage_state()

        self.assertEqual(page.goto_wait_until, "commit")

    def test_verify_fails_closed_when_grid_marker_never_appears(self):
        """Issue #692 cycle-review: `_wait_for_marker`'s `False` return must
        not be discarded here either — a blank/unrendered grid response
        matches neither `_LOGIN_PAGE_MARKERS` nor a captcha marker, so
        trusting `page.content()` regardless would let
        ``capture_storage_state(verify=True)`` return unverified cookies as
        if the session had been confirmed."""
        pytest.importorskip("playwright")
        from direct_cli.browser import session as session_module
        from direct_cli.browser.session import BrowserAuthError

        blank_page = FakePage(locators={}, html="<html></html>")
        fake_browser = _FakeBrowser()
        fake_context = _FakeVerifyContext(blank_page, storage_state={"cookies": []})
        fake_browser.new_context = lambda **kwargs: fake_context
        fake_chromium = _FakeChromium(fake_browser)
        fake_playwright = _FakePlaywright(fake_chromium)

        with (
            patch("playwright.sync_api.sync_playwright", return_value=fake_playwright),
            self._patch_decrypt(),
            patch.object(
                session_module,
                "default_chrome_profile_dir",
                return_value=Path("/fake/chrome/profile"),
            ),
            patch.object(Path, "exists", return_value=True),
            patch.object(session_module, "_PAGE_MARKER_TIMEOUT_MS", 10),
        ):
            with self.assertRaises(BrowserAuthError) as ctx:
                session_module.capture_storage_state()

        self.assertIn("Timed out", str(ctx.exception))


class TestOpenSessionTiers(unittest.TestCase):
    """_open_session's tiered resolution: explicit profile / persistent CLI
    profile / saved session / fresh-decrypt fallback (with auth-error
    self-heal retry)."""

    def setUp(self):
        # Every test in this class exercises tiers below 1.5 (persistent CLI
        # profile) unless a test explicitly wants that tier -- patch
        # DEFAULT_PERSISTENT_PROFILE_DIR to a guaranteed-nonexistent Path so
        # these tests don't depend on whether the developer running them has
        # ever run `direct masters login` for real.
        patcher = patch(
            "direct_cli.browser.session.DEFAULT_PERSISTENT_PROFILE_DIR",
            Path("/nonexistent/chrome-profile"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        # Resolution goes through the login pointer -- keep it off the
        # developer's real ~/.direct-cli so these tests never depend on
        # whether `masters login` has been run on this machine.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path("/nonexistent/chrome-profile-path"),
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _list_ctx(self, args=None):
        from direct_cli.commands.masters import masters

        list_cmd = masters.commands["list"]
        return list_cmd.make_context("list", list(args or []))

    def test_custom_login_profile_dir_is_honoured_by_reads(self):
        """A session saved by `login --profile-dir X` must be used by reads.

        Tier 1.5 originally resolved the profile from
        DEFAULT_PERSISTENT_PROFILE_DIR only and passed no profile_dir to
        open_persistent_session, so `masters login --profile-dir X` reported
        "Login confirmed" and then every list/get/suspend/resume ignored X
        entirely -- falling through to the Keychain path the flag exists to
        avoid.
        """
        import tempfile

        from direct_cli.commands.masters import _open_session

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        custom = Path(tmpdir.name) / "custom-profile"
        (custom / "Default").mkdir(parents=True)
        (custom / "Default" / "Cookies").write_bytes(b"")

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.commands.masters._configured_persistent_profile_dir",
                    return_value=custom,
                ),
                patch(
                    "direct_cli.browser.session.open_persistent_session"
                ) as persistent,
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                persistent.return_value.__enter__ = lambda self: "page"
                persistent.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass

        persistent.assert_called_once()
        self.assertEqual(persistent.call_args.kwargs.get("profile_dir"), custom)
        saved.assert_not_called()
        fresh.assert_not_called()

    def test_explicit_profile_dir_bypasses_saved_session(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx(["--profile-dir", "/some/profile"]) as ctx:
            with (
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx,
                    headful=False,
                    profile_dir="/some/profile",
                    chrome_profile="Default",
                ):
                    pass
        saved.assert_not_called()
        fresh.assert_called_once()

    def test_persistent_profile_used_when_present(self):
        """Tier 1.5: when the CLI's own persistent profile holds a session,
        it's preferred over the saved storage_state session and the Keychain
        decrypt path -- neither should be touched."""
        import tempfile

        from direct_cli.commands.masters import _open_session

        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        # A profile a completed login would leave: Chromium's cookie store is
        # what makes it usable, not the directory merely existing.
        profile = Path(tmpdir.name) / "chrome-profile"
        (profile / "Default").mkdir(parents=True)
        (profile / "Default" / "Cookies").write_bytes(b"")

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.commands.masters._configured_persistent_profile_dir",
                    return_value=profile,
                ),
                patch(
                    "direct_cli.browser.session.open_persistent_session"
                ) as persistent,
                patch("direct_cli.browser.store.session_status") as status,
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                persistent.return_value.__enter__ = lambda self: "page"
                persistent.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        persistent.assert_called_once()
        status.assert_not_called()
        saved.assert_not_called()
        fresh.assert_not_called()

    def test_fresh_saved_session_used_without_decrypting(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                saved.return_value.__enter__ = lambda self: "page"
                saved.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        saved.assert_called_once()
        fresh.assert_not_called()

    def test_expired_saved_session_falls_through_to_fresh(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": True},
                ),
                patch("direct_cli.browser.session.open_saved_session") as saved,
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
                patch("direct_cli.commands.masters.print_info"),
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        saved.assert_not_called()
        fresh.assert_called_once()

    def test_no_saved_session_falls_through_to_fresh_with_tip(self):
        from direct_cli.commands.masters import _open_session

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
                patch("direct_cli.commands.masters.print_info") as info,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with _open_session(
                    ctx, headful=False, profile_dir=None, chrome_profile="Default"
                ):
                    pass
        fresh.assert_called_once()
        info.assert_called_once()
        self.assertIn("playwright login", info.call_args[0][0])

    def test_auth_error_from_saved_session_enter_propagates_uncaught(self):
        """_open_session itself no longer catches BrowserAuthError -- the
        retry now lives one level up, in _with_session (see
        TestWithSessionRetry). A BrowserAuthError raised on
        open_saved_session's __enter__ must propagate straight through."""
        import contextlib

        from direct_cli.browser.session import BrowserAuthError
        from direct_cli.commands.masters import _open_session

        @contextlib.contextmanager
        def _fake_open_saved_session(**kwargs):
            raise BrowserAuthError("saved session expired server-side")
            yield  # pragma: no cover - unreachable, contextmanager shape only

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch(
                    "direct_cli.browser.session.open_saved_session",
                    _fake_open_saved_session,
                ),
                patch("direct_cli.browser.session.open_chrome_session") as fresh,
            ):
                fresh.return_value.__enter__ = lambda self: "page"
                fresh.return_value.__exit__ = lambda self, *a: False
                with self.assertRaises(BrowserAuthError):
                    with _open_session(
                        ctx, headful=False, profile_dir=None, chrome_profile="Default"
                    ):
                        pass
        fresh.assert_not_called()


class TestWithSessionRetry(unittest.TestCase):
    """_with_session retries the whole operation on BrowserAuthError.

    Regression coverage for the double-yield bug: a stale saved session is
    NOT caught on open (assert_authenticated runs inside the caller's
    operation, after the session has already been yielded), so the retry
    must re-run the operation against a fresh session rather than trying to
    yield a second time from the same _open_session generator invocation
    (which raises RuntimeError: generator didn't stop after throw()).
    """

    def _list_ctx(self, args=None):
        from direct_cli.commands.masters import masters

        list_cmd = masters.commands["list"]
        return list_cmd.make_context("list", list(args or []))

    def test_auth_error_raised_inside_operation_retries_via_fresh_session(self):
        import contextlib

        from direct_cli.browser.session import BrowserAuthError
        from direct_cli.commands.masters import _with_session

        @contextlib.contextmanager
        def _fake_open_saved_session(**kwargs):
            yield "saved-page"

        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            yield "fresh-page"

        calls = []

        def operation(page):
            calls.append(page)
            if page == "saved-page":
                # Mirrors assert_authenticated raising deep inside
                # fetch_masters_list/fetch_master, after _open_session has
                # already yielded the page to the caller.
                raise BrowserAuthError("stale session, detected mid-body")
            return f"ok:{page}"

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": True, "error": None, "expired": False},
                ),
                patch(
                    "direct_cli.browser.session.open_saved_session",
                    _fake_open_saved_session,
                ),
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
            ):
                result = _with_session(ctx, False, None, "Default", operation)

        self.assertEqual(result, "ok:fresh-page")
        self.assertEqual(calls, ["saved-page", "fresh-page"])

    def test_no_saved_session_runs_operation_once(self):
        import contextlib

        from direct_cli.commands.masters import _with_session

        @contextlib.contextmanager
        def _fake_open_chrome_session(**kwargs):
            yield "fresh-page"

        with self._list_ctx() as ctx:
            with (
                patch(
                    "direct_cli.browser.store.session_status",
                    return_value={"exists": False, "error": None, "expired": None},
                ),
                patch(
                    "direct_cli.browser.session.open_chrome_session",
                    _fake_open_chrome_session,
                ),
                patch("direct_cli.commands.masters.print_info"),
            ):
                result = _with_session(
                    ctx, False, None, "Default", lambda page: f"ok:{page}"
                )

        self.assertEqual(result, "ok:fresh-page")


class TestPollUntil(unittest.TestCase):
    """Issue #715: ``_poll_until``'s ``while time.monotonic() < deadline``
    loop measures real wall-clock time, so on a CPU-loaded CI runner (many
    Python-level iterations execute per real millisecond) the loop can run
    an unbounded number of ticks before ``time.monotonic()`` finally reports
    the deadline has passed — the tick count is not a function of the
    predicate/timeout alone, it also depends on how fast the host CPU
    happens to be at that moment. Injecting a ``clock`` callable (defaulting
    to ``time.monotonic``, so production behaviour is unchanged) lets a test
    supply a fake clock that only advances when ``page.wait_for_timeout`` is
    actually called, making the tick count fully deterministic regardless of
    real CPU speed.
    """

    def test_tick_count_is_deterministic_under_a_fake_clock_that_only_advances_on_wait(
        self,
    ):
        # Simulates a CPU-loaded runner: the predicate loop can spin many
        # times per real millisecond, but the deadline must still be judged
        # in terms of ticks (fake-clock advancement), not raw loop
        # iterations. A fake clock that starts at 0 and only advances by
        # ``tick_ms`` inside ``wait_for_timeout`` proves the loop runs
        # exactly ``timeout_ms // tick_ms`` ticks before giving up, no
        # matter how many times the predicate itself is polled between
        # ticks.
        fake_time = {"now": 0.0}

        class _FakeClockPage(FakePage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tick_count = 0

            def wait_for_timeout(self, timeout):
                self.tick_count += 1
                fake_time["now"] += timeout / 1000

        page = _FakeClockPage(locators={})
        result = browser_masters._poll_until(
            page,
            lambda: False,
            1_000,
            tick_ms=250,
            clock=lambda: fake_time["now"],
        )
        self.assertFalse(result)
        # 1000ms / 250ms == 4 ticks, deterministically -- not a real
        # wall-clock race against however fast the host CPU spins the loop.
        self.assertEqual(page.tick_count, 4)

    def test_poll_until_honours_the_package_clock_without_an_explicit_argument(self):
        # Issue #767: `_poll_until`'s `clock` parameter used to default to
        # `time.monotonic` bound at DEFINITION time, so the ~30 call sites
        # that don't pass `clock` explicitly kept a real wall-clock deadline
        # regardless of what the harness installed. It must resolve
        # `_clock.now` at CALL time instead, or the module-wide fake clock
        # this file installs in `setUpModule` silently stops applying and the
        # whole suite goes back to burning real timeout budgets.
        fake_time = {"now": 0.0}

        class _TickCountingPage(FakePage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tick_count = 0

            def wait_for_timeout(self, timeout):
                self.tick_count += 1
                fake_time["now"] += timeout / 1000

        page = _TickCountingPage(locators={})
        with patch.object(_clock, "_clock", lambda: fake_time["now"]):
            # No `clock=` argument — the deadline must still come from the
            # installed package clock.
            result = browser_masters._poll_until(page, lambda: False, 1_000)
        self.assertFalse(result)
        self.assertEqual(page.tick_count, 4)

    def test_poll_until_terminal_honours_the_package_clock_without_an_argument(self):
        # Same contract as above for the sibling helper (`_edit_form_terminal_state`
        # and friends go through this one).
        fake_time = {"now": 0.0}

        class _TickCountingPage(FakePage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tick_count = 0

            def wait_for_timeout(self, timeout):
                self.tick_count += 1
                fake_time["now"] += timeout / 1000

        page = _TickCountingPage(locators={})
        with patch.object(_clock, "_clock", lambda: fake_time["now"]):
            result = browser_masters._poll_until_terminal(page, lambda: None, 1_000)
        self.assertIsNone(result)
        self.assertEqual(page.tick_count, 4)


# Modules whose callables read a real clock. `_clock.now()` is the package's
# only sanctioned source for a POLL DEADLINE, so rather than denylisting
# individual functions this bans the modules wholesale (see
# `_raw_clock_calls`).
_REAL_CLOCK_MODULES = frozenset({"time", "datetime"})

# Per-module carve-outs for readings that legitimately are NOT deadlines.
# `store.py` stamps `created_at` into the persisted session envelope and
# measures its age: that is calendar time, which must survive a reboot and be
# comparable across processes, so `time.time()` is correct there while
# `_clock.now()` (monotonic, arbitrary epoch) would be actively wrong.
#
# Scoped PER FILE, not package-wide. A blanket `{time, time_ns}` allowance
# reopened the whole bug: `time.time()` is a real clock that a no-op
# `wait_for_timeout` tick cannot advance either, so `deadline = time.time() +
# …` busy-spins exactly like `monotonic` did — measured at 61.89s on this file
# with the guard still reporting clean. No module that owns a poll loop
# appears here, so that spelling stays banned everywhere it could do harm.
_WALL_CLOCK_CARVE_OUTS = {"store.py": frozenset({"time", "time_ns"})}


def _raw_clock_calls(source, allowed=frozenset()):
    """Yield ``(lineno, rendered_call)`` for every real-clock read in `source`.

    Parses rather than greps: the original substring check only recognised the
    literal ``time.monotonic()``, so an aliased import (``import time as _t``
    → ``_t.monotonic()``) or a from-import (``from time import monotonic`` →
    ``monotonic()``) reintroduced a busy-spinning deadline that the guard
    reported as clean — verified at 1.4s → 64s on this file. Because only
    ``ast.Call`` nodes are considered, prose in a docstring is structurally
    excluded rather than filtered by a backtick heuristic (which had also
    exempted any real call sharing a line with a ``…`` comment).

    Bans the clock modules WHOLESALE instead of naming individual functions.
    A ``{monotonic, perf_counter}`` denylist still let every sibling through —
    ``monotonic_ns``, ``perf_counter_ns``, ``time``, ``time_ns``,
    ``process_time``, ``datetime.now()`` — each just as unreachable by a no-op
    ``wait_for_timeout`` tick, and one of them (``time.monotonic_ns()``) was
    measured reintroducing the full regression (1.0s → 62s) while the guard
    reported clean. Enumerating banned functions is a losing game; enumerating
    the two sanctioned ways to read time is not, since a poll deadline in this
    package has exactly one legitimate source.

    Also resolves single-name assignment aliasing (``_t = time`` /
    ``_m = time.monotonic``), which otherwise smuggles a deadline past any
    import-only analysis.

    ``allowed`` names attributes this particular module may still call — see
    ``_WALL_CLOCK_CARVE_OUTS``. It is deliberately per-file: allowing
    ``time.time`` package-wide reopened the original bug, since a wall clock
    is no more tickable by a no-op ``wait_for_timeout`` than a monotonic one.
    """
    tree = ast.parse(source)

    module_aliases = set()  # names bound to a real-clock module
    bare_names = set()  # names bound directly to one of its callables
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _REAL_CLOCK_MODULES:
                    module_aliases.add(alias.asname or root)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[0] in _REAL_CLOCK_MODULES
        ):
            for alias in node.names:
                # `from datetime import datetime` binds the class, whose
                # `.now()` is caught by the attribute branch below.
                if alias.name in _REAL_CLOCK_MODULES:
                    module_aliases.add(alias.asname or alias.name)
                else:
                    bare_names.add(alias.asname or alias.name)

    # Second pass: `_t = time` / `_m = time.monotonic` rebind the same source
    # under a new name, so fold those in before inspecting calls.
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if not isinstance(target, ast.Name):
            continue
        if isinstance(value, ast.Name):
            if value.id in module_aliases:
                module_aliases.add(target.id)
            elif value.id in bare_names:
                bare_names.add(target.id)
        elif (
            isinstance(value, ast.Attribute)
            and isinstance(value.value, ast.Name)
            and value.value.id in module_aliases
        ):
            bare_names.add(target.id)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # `getattr(time, "monotonic")()` — the indirection is the call target.
        if (
            isinstance(func, ast.Call)
            and isinstance(func.func, ast.Name)
            and func.func.id == "getattr"
            and func.args
            and isinstance(func.args[0], ast.Name)
            and func.args[0].id in module_aliases
        ):
            yield node.lineno, f"getattr({func.args[0].id}, …)()"
        elif isinstance(func, ast.Attribute) and func.attr not in allowed:
            # A nested chain (`datetime.datetime.now()`) still bottoms out at
            # the module. Reported once, at the module attribute, so a
            # trailing `.timestamp()` does not double-count.
            root = func.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in module_aliases:
                yield node.lineno, f"{root.id}.{func.attr}()"
        elif isinstance(func, ast.Name) and func.id in bare_names:
            yield node.lineno, f"{func.id}()"


class TestBrowserPackageClock(unittest.TestCase):
    """Issue #767: every poll deadline in ``direct_cli/browser/`` must go
    through ``_clock.now()``.

    These loops pair a deadline with ``page.wait_for_timeout`` as their tick.
    In production the tick is a real in-browser sleep; under this file's fake
    ``Page`` it is a no-op that advances only the fake clock. A deadline read
    from ``time.monotonic()`` directly therefore cannot be reached by ticking
    — the loop busy-spins for the full production timeout in REAL wall-clock
    seconds. Before this guard existed, five such tests in this file burned
    135s between them and the whole file took ~880s sequentially (~1s after
    the fix), so a single reintroduced ``time.monotonic()`` is a multi-minute
    regression that no assertion would otherwise catch.
    """

    def test_no_raw_monotonic_deadlines_in_the_browser_package(self):
        package_dir = Path(browser_masters.__file__).parent
        offenders = []
        for module_path in sorted(package_dir.glob("*.py")):
            if module_path.name == "_clock.py":
                continue  # the one legitimate `time.monotonic` reference
            allowed = _WALL_CLOCK_CARVE_OUTS.get(module_path.name, frozenset())
            offenders.extend(
                f"{module_path.name}:{lineno}: {call}"
                for lineno, call in _raw_clock_calls(
                    module_path.read_text(), allowed=allowed
                )
            )

        self.assertEqual(
            offenders,
            [],
            "These poll deadlines read the real clock instead of "
            "`_clock.now()`, so the offline test harness cannot tick them "
            "past their timeout and each one costs its full production "
            "timeout in real seconds (issue #767):\n" + "\n".join(offenders),
        )

    # The detector needs its own coverage: the guard above passes both when
    # the package is clean and when the detector is blind, so without these
    # the bypasses below could be reintroduced by a "simplification" of
    # `_raw_clock_calls` and nothing would go red.

    def test_detects_a_plain_time_monotonic_deadline(self):
        source = "import time\ndeadline = time.monotonic() + 1\n"
        self.assertEqual([(2, "time.monotonic()")], list(_raw_clock_calls(source)))

    def test_detects_a_deadline_read_through_an_aliased_time_import(self):
        # The substring guard this replaced missed exactly this spelling; a
        # live reintroduction in `session.py::_wait_for_marker` took this file
        # from 1.4s to 64.12s while the guard still reported clean.
        source = "import time as _t\ndeadline = _t.monotonic() + 1\n"
        self.assertEqual([(2, "_t.monotonic()")], list(_raw_clock_calls(source)))

    def test_detects_a_deadline_read_through_a_from_import(self):
        source = "from time import monotonic\ndeadline = monotonic() + 1\n"
        self.assertEqual([(2, "monotonic()")], list(_raw_clock_calls(source)))

    def test_detects_a_renamed_from_import(self):
        source = "from time import monotonic as _m\ndeadline = _m() + 1\n"
        self.assertEqual([(2, "_m()")], list(_raw_clock_calls(source)))

    def test_detects_perf_counter_as_well_as_monotonic(self):
        # Just as unreachable by a no-op `wait_for_timeout` tick, so it is the
        # obvious drop-in once `monotonic` is guarded.
        source = "import time\ndeadline = time.perf_counter() + 1\n"
        self.assertEqual([(2, "time.perf_counter()")], list(_raw_clock_calls(source)))

    def test_detects_every_sibling_of_the_originally_banned_pair(self):
        # A `{monotonic, perf_counter}` denylist let all of these through, and
        # `time.monotonic_ns()` was measured reintroducing the full regression
        # (1.0s -> 62.19s) with the guard still reporting clean. Banning the
        # module wholesale is what closes the family, not a longer denylist.
        for call in (
            "monotonic_ns",
            "perf_counter_ns",
            "process_time",
            "process_time_ns",
            "gmtime",
        ):
            with self.subTest(call=call):
                source = f"import time\ndeadline = time.{call}() + 1\n"
                self.assertEqual(
                    [(2, f"time.{call}()")], list(_raw_clock_calls(source))
                )

    def test_allows_wall_clock_time_only_for_the_carved_out_module(self):
        # `store.py` stamps `created_at` into the persisted session envelope
        # and measures its age. That is calendar time — it must survive a
        # reboot and compare across processes — so `time.time()` is correct
        # and `_clock.now()` (monotonic, arbitrary epoch) would be wrong.
        # Banning it outright would make this guard un-satisfiable for real
        # code, so the allowance exists — but only for that module.
        source = "import time\nenvelope = {'created_at': time.time()}\n"
        self.assertEqual(
            [],
            list(_raw_clock_calls(source, allowed=_WALL_CLOCK_CARVE_OUTS["store.py"])),
        )

    def test_wall_clock_carve_out_does_not_leak_to_other_modules(self):
        # The carve-out was package-wide for one commit, and that reopened the
        # entire bug: `time.time()` is a real clock a no-op `wait_for_timeout`
        # tick cannot advance either, so it backs a busy-spin deadline exactly
        # like `monotonic` — measured at 61.89s on this file with the guard
        # reporting clean. Only modules in _WALL_CLOCK_CARVE_OUTS get the
        # allowance, and no module owning a poll loop is in it.
        source = (
            "import time\n"
            "deadline = time.time() + timeout_ms / 1000\n"
            "while time.time() < deadline:\n"
            "    page.wait_for_timeout(250)\n"
        )
        self.assertEqual(
            [(2, "time.time()"), (3, "time.time()")], list(_raw_clock_calls(source))
        )
        self.assertNotIn("masters.py", _WALL_CLOCK_CARVE_OUTS)
        self.assertNotIn("session.py", _WALL_CLOCK_CARVE_OUTS)

    def test_detects_a_datetime_based_clock_read(self):
        source = "import datetime\nd = datetime.datetime.now().timestamp() + 1\n"
        self.assertEqual([(2, "datetime.now()")], list(_raw_clock_calls(source)))

    def test_detects_a_module_rebound_by_assignment(self):
        source = "import time\n_t = time\ndeadline = _t.monotonic() + 1\n"
        self.assertEqual([(3, "_t.monotonic()")], list(_raw_clock_calls(source)))

    def test_detects_a_function_rebound_by_assignment(self):
        source = "import time\n_m = time.monotonic\ndeadline = _m() + 1\n"
        self.assertEqual([(3, "_m()")], list(_raw_clock_calls(source)))

    def test_detects_a_getattr_indirection(self):
        source = "import time\ndeadline = getattr(time, 'monotonic')() + 1\n"
        self.assertEqual([(2, "getattr(time, …)()")], list(_raw_clock_calls(source)))

    def test_ignores_prose_mentioning_the_banned_call(self):
        # Structurally excluded (not a Call node) rather than filtered by the
        # old backtick heuristic, which also exempted any REAL call that
        # happened to share its line with a ``…`` comment.
        source = '"""Docstring naming ``time.monotonic()`` in prose."""\n'
        self.assertEqual([], list(_raw_clock_calls(source)))

    def test_ignores_a_real_call_sharing_a_line_with_backtick_prose(self):
        source = (
            "import time\n"
            "deadline = time.monotonic() + 1  # unlike ``_clock.now()``\n"
        )
        self.assertEqual([(2, "time.monotonic()")], list(_raw_clock_calls(source)))

    def test_ignores_an_unrelated_monotonic_attribute(self):
        # `self.monotonic()` / `counter.monotonic()` are not the time module.
        source = "import time\nvalue = self.monotonic()\n"
        self.assertEqual([], list(_raw_clock_calls(source)))

    def test_ignores_the_sanctioned_package_clock(self):
        source = "from . import _clock\ndeadline = _clock.now() + 1\n"
        self.assertEqual([], list(_raw_clock_calls(source)))


class TestFetchMastersList(unittest.TestCase):
    """`list` reads the grid's GridCampaigns JSON call, not its DOM (#639):
    the grid is a virtualized SPA and never renders a
    ``a[href*='/wizard/campaigns/']`` anchor (confirmed live)."""

    _GRID_REQUEST_BODY = {
        "operationName": "GridCampaigns",
        "variables": {
            "login": "ksamatadirect",
            "campaignInput": {
                "filter": {},
                "limitOffset": {"offset": 0, "limit": 200},
            },
        },
        "query": "query GridCampaigns { ... }",
    }

    def _grid_response(self, post_data=None, status=200):
        return _FakeGridResponse(
            url=(
                f"{browser_masters.GRID_API_URL}"
                f"?operationName={browser_masters._GRID_CAMPAIGNS_OPERATION}"
            ),
            status=status,
            post_data=post_data or json.dumps(self._GRID_REQUEST_BODY),
        )

    def _page(self, api_pages, grid_status=200, grid_post_data=None):
        return FakePage(
            grid_response=self._grid_response(
                post_data=grid_post_data, status=grid_status
            ),
            api_request=_FakeApiRequestContext(pages=api_pages),
        )

    def test_selects_only_uac_source_rows(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="all")

        ids = {row["CampaignId"] for row in result}
        # 72349978/107707079 (STOPPED), 77501358 (ARCHIVED TEXT), 100571135
        # (ARCHIVED CPM_BANNER) are all source == "UAC" in the fixture.
        self.assertEqual(ids, {72349978, 107707079, 77501358, 100571135})
        # The two non-UAC rows (75071838, 74773845) must never appear.
        self.assertNotIn(75071838, ids)
        self.assertNotIn(74773845, ids)

    def test_stopped_masters_included_by_default_status_filter(self):
        # Regression for #639: the user's two STOPPED Мастера must be found
        # under the *default* status filter, not just an explicit one.
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page)  # default status

        ids = {row["CampaignId"] for row in result}
        self.assertIn(72349978, ids)
        self.assertIn(107707079, ids)
        stopped = next(r for r in result if r["CampaignId"] == 72349978)
        self.assertEqual(stopped["Status"], "SUSPENDED")

    def test_status_archived_returns_only_archived(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="archived")

        ids = {row["CampaignId"] for row in result}
        self.assertEqual(ids, {77501358, 100571135})

    def test_status_all_returns_every_uac_row(self):
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        result = browser_masters.fetch_masters_list(page, status="all")

        self.assertEqual(len(result), 4)

    def _grid_request_body_with_default_filter_status_in(self):
        # Live-captured shape (issue #730): the grid UI's own default view
        # sends this exact filterStatusIn list -- no "ARCHIVED" -- so an
        # archived campaign is excluded server-side, before
        # STATUS_FILTERS ever runs. See _widen_filter_status_for_archived.
        body = dict(self._GRID_REQUEST_BODY)
        body["variables"] = dict(body["variables"])
        body["variables"]["campaignInput"] = dict(body["variables"]["campaignInput"])
        body["variables"]["campaignInput"]["filter"] = {
            "filterStatusIn": [
                "ACTIVE",
                "DRAFT",
                "MODERATION",
                "MODERATION_DENIED",
                "RUN_WARN",
                "STOPPED",
                "TEMPORARILY_PAUSED",
            ]
        }
        return body

    def test_status_archived_widens_filter_status_in_before_replaying(self):
        # Issue #730: without widening, the grid's own default
        # filterStatusIn (captured verbatim from the live UI) excludes
        # ARCHIVED server-side -- the replayed pagination POST must carry
        # "ARCHIVED" or a real archived campaign never appears in rowset at
        # all, regardless of STATUS_FILTERS below.
        fixture = _load_grid_campaigns_fixture()
        body = self._grid_request_body_with_default_filter_status_in()
        page = self._page([fixture], grid_post_data=json.dumps(body))

        browser_masters.fetch_masters_list(page, status="archived")

        self.assertEqual(len(page.request.calls), 1)
        posted_body = json.loads(page.request.calls[0][1])
        status_in = posted_body["variables"]["campaignInput"]["filter"][
            "filterStatusIn"
        ]
        self.assertIn("ARCHIVED", status_in)

    def test_status_all_also_widens_filter_status_in(self):
        fixture = _load_grid_campaigns_fixture()
        body = self._grid_request_body_with_default_filter_status_in()
        page = self._page([fixture], grid_post_data=json.dumps(body))

        browser_masters.fetch_masters_list(page, status="all")

        posted_body = json.loads(page.request.calls[0][1])
        status_in = posted_body["variables"]["campaignInput"]["filter"][
            "filterStatusIn"
        ]
        self.assertIn("ARCHIVED", status_in)

    def test_status_active_does_not_widen_filter_status_in(self):
        # Only archive-including statuses need the widen -- leave the grid's
        # own default filter alone otherwise, matching prior behaviour.
        fixture = _load_grid_campaigns_fixture()
        body = self._grid_request_body_with_default_filter_status_in()
        page = self._page([fixture], grid_post_data=json.dumps(body))

        browser_masters.fetch_masters_list(page, status="active")

        posted_body = json.loads(page.request.calls[0][1])
        status_in = posted_body["variables"]["campaignInput"]["filter"][
            "filterStatusIn"
        ]
        self.assertNotIn("ARCHIVED", status_in)

    def test_paginates_past_the_page_limit(self):
        # totalCount exceeds one page's rowset -> a second request must be
        # made and its rows included, matching the live behaviour that
        # motivated this (a real account's totalCount=224 vs. a 200-row page,
        # see issue #639 diagnosis).
        fixture = _load_grid_campaigns_fixture()
        first_page_rows = fixture["data"]["client"]["campaigns"]["rowset"]
        second_page_rows = [
            {
                "id": "999000001",
                "name": "Мастер со второй страницы",
                "type": "TEXT",
                "metaType": "DEFAULT_",
                "source": "UAC",
                "__typename": "GdTextCampaign",
                "status": {"primaryStatus": "STOPPED"},
                "startDate": "2025-01-01",
            }
        ]
        total_count = len(first_page_rows) + len(second_page_rows)
        first_page = {
            "data": {
                "client": {
                    "campaigns": {
                        "totalCount": total_count,
                        "rowset": first_page_rows,
                    }
                }
            }
        }
        second_page = {
            "data": {
                "client": {
                    "campaigns": {
                        "totalCount": total_count,
                        "rowset": second_page_rows,
                    }
                }
            }
        }
        page = self._page([first_page, second_page])

        result = browser_masters.fetch_masters_list(page, status="all")

        ids = {row["CampaignId"] for row in result}
        self.assertIn(999000001, ids)
        self.assertEqual(len(page.request.calls), 2)

    def test_grid_url_never_contains_ulogin(self):
        # #639: passing our own login as `ulogin` produced HTTP 401 "Доступ
        # ограничен" — list() must never build that URL.
        fixture = _load_grid_campaigns_fixture()
        page = self._page([fixture])

        browser_masters.fetch_masters_list(page, status="all")

        self.assertTrue(page.navigated_to)
        for url in page.navigated_to:
            self.assertNotIn("ulogin", url)

    def test_no_grid_campaigns_request_observed_raises(self):
        # The grid fired no matching response at all (e.g. Yandex renamed the
        # operation) -> a clear BrowserSessionError, not a silent empty list.
        page = FakePage(grid_response=None)

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_expect_response_timeout_from_with_exit_raises_browser_session_error(
        self,
    ):
        # #694: real Playwright's EventContextManager.__exit__ resolves
        # response_info.value itself and raises the TimeoutError there when
        # the `with` block exits cleanly but no matching response ever
        # arrived -- so the timeout must be caught by wrapping the whole
        # `with page.expect_response(...): goto(...); ...` block, not just a
        # later, separate read of response_info.value after the block.
        page = FakePage(grid_response=None)
        page._expect_response_exit_raises = True

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_non_ok_api_response_raises_browser_session_error(self):
        fixture = _load_grid_campaigns_fixture()
        page = FakePage(
            grid_response=self._grid_response(),
            api_request=_FakeApiRequestContext(pages=[fixture], ok=False, status=500),
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_non_json_api_response_raises_browser_session_error(self):
        page = FakePage(
            grid_response=self._grid_response(),
            api_request=_FakeApiRequestContext(raw_body="not json"),
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page, status="all")

    def test_empty_result_prints_warning(self):
        empty = {"data": {"client": {"campaigns": {"totalCount": 0, "rowset": []}}}}
        page = self._page([empty])

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_masters_list(page, status="all")

        self.assertEqual(result, [])
        warn.assert_called_once()

    def test_unknown_status_filter_raises_value_error(self):
        page = self._page([_load_grid_campaigns_fixture()])
        with self.assertRaises(ValueError):
            browser_masters.fetch_masters_list(page, status="bogus")


class TestFetchMaster(unittest.TestCase):
    """Overview-page parsing: title, status, landing URL, stat tiles."""

    _STAT_TILES_SELECTOR = (
        f'[data-testid^="{browser_masters._STAT_TILE_TESTID_PREFIX}"]'
    )

    def _page_for(self, title="Мастер Тест", status_text="Кампания остановлена"):
        return FakePage(
            locators={
                browser_masters._OVERVIEW_TITLE_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text=title)]
                ),
                browser_masters._OVERVIEW_LANDING_LINK_SELECTOR: _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            attrs={
                                "href": (
                                    "https://lp.example.com/x?utm_source=yandex&"
                                    "utm_medium=cpc"
                                )
                            }
                        )
                    ]
                ),
                self._STAT_TILES_SELECTOR: _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            text="281 722",
                            attrs={"data-testid": "ChartSummary.shows"},
                        ),
                        _FakeLocatorHandle(
                            text="2 529",
                            attrs={"data-testid": "ChartSummary.clicks"},
                        ),
                        _FakeLocatorHandle(
                            text="83",
                            attrs={"data-testid": "ChartSummary.conversions"},
                        ),
                        _FakeLocatorHandle(
                            text="272,45 ₽",
                            attrs={"data-testid": "ChartSummary.cpa"},
                        ),
                        _FakeLocatorHandle(
                            text="22 613,58 ₽",
                            attrs={"data-testid": "ChartSummary.cost"},
                        ),
                    ]
                ),
            },
            body_text=status_text,
        )

    def test_parses_full_overview(self):
        page = self._page_for()

        result = browser_masters.fetch_master(page, 72349978)

        self.assertEqual(result["CampaignId"], 72349978)
        self.assertEqual(result["Name"], "Мастер Тест")
        self.assertEqual(result["Status"], "SUSPENDED")
        self.assertEqual(
            result["LandingUrl"],
            "https://lp.example.com/x?utm_source=yandex&utm_medium=cpc",
        )
        self.assertEqual(
            result["Stats"],
            {
                "impressions": "281 722",
                "clicks": "2 529",
                "conversions": "83",
                "cost_per_conversion": "272,45 ₽",
                "cost": "22 613,58 ₽",
            },
        )

    def test_landing_url_ignores_yandex_promo_banner(self):
        # Issue #763: the overview page always also renders a Yandex promo
        # banner ("Yandex Neuro Ads") whose own href carries an unrelated
        # utm_source= tag. The old selector, `a[href*='utm_source=']`, had no
        # way to tell that banner apart from the campaign's own link once the
        # campaign's LandingUrl carried no UTM tail of its own (e.g. right
        # after `update --landing-url` per #761) -- it would then match only
        # the banner and silently report *its* URL as the campaign's
        # LandingUrl. _OVERVIEW_LANDING_LINK_SELECTOR must resolve to the
        # campaign's own link (scoped under CampaignHeader), never the
        # banner, regardless of which anchors happen to carry utm_source=.
        page = FakePage(
            locators={
                browser_masters._OVERVIEW_TITLE_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text="Мастер Тест")]
                ),
                browser_masters._OVERVIEW_LANDING_LINK_SELECTOR: _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            attrs={"href": "https://lp.ksamata.ru/detox_ya"}
                        )
                    ]
                ),
                # A banner-like anchor that an href-content selector would
                # match, but the header-scoped selector above must not.
                "a[href*='utm_source=']": _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            attrs={
                                "href": (
                                    "https://ya.ru/project/yna/?utm_source=yandex"
                                    "&utm_medium=direct&utm_campaign=label"
                                )
                            }
                        )
                    ]
                ),
            },
            body_text="Кампания активна",
        )

        result = browser_masters.fetch_master(page, 713234191)

        self.assertEqual(result["LandingUrl"], "https://lp.ksamata.ru/detox_ya")

    def test_landing_url_reads_utm_tagged_link_in_full(self):
        # When the campaign's own LandingUrl does carry a UTM tail (recorded
        # directly in the link, pre-#761 style), the header-scoped selector
        # must still read the whole href, UTM params included.
        href = (
            "https://lp.ksamata.ru/detox_ya?utm_source=yandex&utm_medium=cpc&"
            "utm_campaign=cid|{campaign_id}|{source_type}&"
            "utm_content=gid|{gbid}|aid|{ad_id}&utm_term={keyword}"
        )
        page = FakePage(
            locators={
                browser_masters._OVERVIEW_TITLE_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text="Мастер Тест")]
                ),
                browser_masters._OVERVIEW_LANDING_LINK_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(attrs={"href": href})]
                ),
            },
            body_text="Кампания активна",
        )

        result = browser_masters.fetch_master(page, 713277109)

        self.assertEqual(result["LandingUrl"], href)

    def test_active_status_recognised(self):
        page = self._page_for(status_text="Кампания активна")
        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Status"], "ACTIVE")

    def test_archived_status_recognised(self):
        # Issue #730: live-confirmed against campaign 713277109 ("Кампания
        # в\xa0архиве", non-breaking space between "в" and "архиве") -- this
        # marker was previously entirely missing, so `masters get` on an
        # archived campaign reported "unrecognised status text" instead.
        page = self._page_for(status_text="Кампания в\xa0архиве")
        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Status"], "ARCHIVED")

    def test_moderation_status_recognised_by_fetch_master(self):
        # _extract_status previously duplicated _read_status_text's marker
        # list but omitted MODERATION -- now both share _read_status_text.
        page = self._page_for(status_text="Кампания на\xa0модерации")
        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Status"], "MODERATION")

    def test_unknown_testid_suffix_is_ignored(self):
        # Live recon (issue #708) confirmed exactly 5 stable suffixes
        # (shows/clicks/conversions/cpa/cost) -- an extra tile Yandex might
        # add later must not raise, only be skipped by the key lookup.
        page = FakePage(
            locators={
                self._STAT_TILES_SELECTOR: _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            text="1",
                            attrs={"data-testid": "ChartSummary.somethingNew"},
                        ),
                        _FakeLocatorHandle(
                            text="281 722",
                            attrs={"data-testid": "ChartSummary.shows"},
                        ),
                    ]
                ),
            },
        )
        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Stats"], {"impressions": "281 722"})

    def test_zero_tiles_returns_without_waiting_out_the_timeout(self):
        # A page with no ChartSummary.* nodes at all (e.g. Yandex changed
        # the markup) must not raise -- the marker-wait predicate
        # (`count() > 0`) is simply never satisfied, _poll_until returns
        # False once the timeout elapses, and _extract_stat_tiles degrades
        # to a warning instead of populating "Stats". A short timeout keeps
        # this test fast in real wall-clock time (FakePage.wait_for_timeout
        # is a no-op, so _poll_until's real `time.monotonic()` deadline is
        # what actually bounds the loop here).
        #
        # body_text carries a recognisable status marker so
        # _is_draft_overview_page's own _poll_until (which runs first, to
        # decide DRAFT vs. non-DRAFT) resolves immediately instead of
        # burning its own real-time _DRAFT_OVERVIEW_DETECT_TIMEOUT_MS budget
        # before _extract_stat_tiles ever gets a chance to run.
        page = FakePage(locators={}, body_text="Кампания активна")
        with patch.object(browser_masters, "_STAT_TILES_TIMEOUT_MS", 200):
            with patch("direct_cli.browser.masters.print_warning") as warn:
                result = browser_masters.fetch_master(page, 1)
        self.assertNotIn("Stats", result)
        warn.assert_any_call("Could not read overview stat tiles for campaign 1.")

    def test_delayed_tile_render_is_waited_for(self):
        # Live recon (issue #708): the marker (any ChartSummary.* node) can
        # take several seconds to appear after the title has rendered, but
        # once it does, all five tiles are present in that same DOM read --
        # no partial/stabilizing state to account for. Models the marker
        # appearing on the 2nd locator() call, not the 1st.
        class _DelayedTilePage(FakePage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tile_scan_count = 0

            def locator(self, selector):
                if selector == TestFetchMaster._STAT_TILES_SELECTOR:
                    self.tile_scan_count += 1
                    if self.tile_scan_count <= 1:
                        return _FakeLocator([])
                    return _FakeLocator(
                        [
                            _FakeLocatorHandle(
                                text="281 722",
                                attrs={"data-testid": "ChartSummary.shows"},
                            )
                        ]
                    )
                return super().locator(selector)

        page = _DelayedTilePage(locators={})
        result = browser_masters.fetch_master(page, 1)

        self.assertEqual(result["Stats"], {"impressions": "281 722"})
        self.assertGreaterEqual(page.tile_scan_count, 2)

    def test_partial_result_on_unrecognised_sections(self):
        # A page whose title element IS present (so _goto_overview_page is
        # satisfied the overview page is ready — see TestGotoOverviewPage
        # for the "never renders at all" case) but whose text can't be read,
        # and whose other sections weren't recognised, must not raise —
        # every extractor degrades to omitting its field plus a warning, per
        # the module's "best-effort" contract (see fetch_master docstring).
        class _PresentButUnreadableTitle(_FakeLocatorHandle):
            def count(self):
                return 1  # matched -> _goto_overview_page's wait is satisfied

            def inner_text(self):
                raise PlaywrightError("element detached")

        page = FakePage(locators={}, body_text="something Yandex changed the markup to")
        page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR] = _FakeLocator(
            [_PresentButUnreadableTitle()]
        )

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_master(page, 999)

        self.assertEqual(result, {"CampaignId": 999})
        self.assertGreaterEqual(warn.call_count, 3)  # name, status, landing, stats


class TestFetchMasterDraft(unittest.TestCase):
    """DRAFT overview-page parsing (issue #660): name/status/weekly budget only.

    See tests/fixtures/masters_wizard_draft_overview.html for the live recon
    this is modeled on — a DRAFT campaign's overview page IS the editable
    wizard form (no status text, no stat tiles, no MenuTrigger), reusing the
    edit page's own CampaignFormControls testids plus its own header ones.
    """

    def _draft_page(
        self,
        title="Мастер ИЖ-1 Сосуды и вены (холодный)",
        budget="80 000",
        landing_url="https://lp.ksamata.ru/",
    ):
        locators = {
            browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR: _FakeLocator(
                [_FakeLocatorHandle(text=browser_masters._DRAFT_STATUS_TEXT)]
            ),
            browser_masters._CAMPAIGN_HEADER_TITLE_NAME_SELECTOR: _FakeLocator(
                [_FakeLocatorHandle(text=title)]
            ),
            browser_masters._BUDGET_INPUT_SELECTOR: _FakeLocator(
                [_FakeLocatorHandle(text=budget)]
            ),
        }
        if landing_url is not None:
            locators[browser_masters._EDIT_URL_INPUT_TESTID] = _FakeLocator(
                [_FakeLocatorHandle(text=landing_url)]
            )
        return FakePage(locators=locators)

    def test_parses_draft_overview(self):
        page = self._draft_page()

        result = browser_masters.fetch_master(page, 713231614)

        self.assertEqual(
            result,
            {
                "CampaignId": 713231614,
                "Status": "DRAFT",
                "Name": "Мастер ИЖ-1 Сосуды и вены (холодный)",
                "WeeklyBudget": "80 000",
                "LandingUrl": "https://lp.ksamata.ru/",
            },
        )

    def test_draft_result_has_no_stats(self):
        result = browser_masters.fetch_master(self._draft_page(), 1)

        self.assertNotIn("Stats", result)

    def test_draft_result_omits_landing_url_when_field_unreadable(self):
        # issue #822: the field genuinely missing/unreadable is reported via
        # print_warning and simply omitted, same convention as name/budget —
        # not a hard failure of the whole `masters get` call.
        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_master(self._draft_page(landing_url=None), 1)

        self.assertNotIn("LandingUrl", result)
        warn.assert_any_call("Could not read landing URL for 1.")

    def test_draft_partial_result_on_missing_name_and_budget(self):
        page = FakePage(
            locators={
                browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text=browser_masters._DRAFT_STATUS_TEXT)]
                ),
            },
        )

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.fetch_master(page, 1)

        self.assertEqual(result, {"CampaignId": 1, "Status": "DRAFT"})
        self.assertEqual(warn.call_count, 3)  # name, budget, landing URL

    def test_non_draft_page_unaffected(self):
        # A page whose CampaignHeader.Status reads something other than
        # "Черновик" must fall through to the normal dashboard extractors,
        # not be misdetected as a draft.
        page = FakePage(
            locators={
                browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text="Активна")]
                ),
                "h1, [role=heading]": _FakeLocator(
                    [_FakeLocatorHandle(text="Обычная")]
                ),
            },
            body_text="Кампания активна",
        )

        result = browser_masters.fetch_master(page, 1)

        self.assertEqual(result["Status"], "ACTIVE")
        self.assertNotIn("WeeklyBudget", result)

    def test_absent_status_node_detected_via_count_not_inner_text(self):
        # Regression: a non-DRAFT overview page has NO CampaignHeader.Status
        # node at all (its status lives in plain body text instead, see
        # _read_status_text) — _is_draft_overview_page must recognise that
        # via .count() == 0 and return False immediately, the same way
        # _is_draft_edit_page does, rather than calling inner_text() on the
        # locator's raising `.first` handle. Real Playwright's inner_text()
        # auto-waits its full actionability timeout (default 30s) for a
        # selector that will never appear before raising — calling it here
        # would silently stall every non-DRAFT masters get/suspend/resume.
        page = FakePage(
            locators={
                "h1, [role=heading]": _FakeLocator(
                    [_FakeLocatorHandle(text="Обычная")]
                ),
            },
            body_text="Кампания активна",
        )

        self.assertFalse(browser_masters._is_draft_overview_page(page))

        result = browser_masters.fetch_master(page, 1)
        self.assertEqual(result["Status"], "ACTIVE")

    def test_draft_detected_after_delayed_hydration(self):
        # Regression: goto(..., wait_until="domcontentloaded") returns before
        # the SPA has necessarily rendered CampaignHeader.Status yet (the
        # same race issue #685 fixed for the create page's step 1 field via
        # _poll_until) — _is_draft_overview_page must not give up on the
        # first, pre-hydration snapshot. Models the status node appearing
        # only after one wait_for_timeout tick.
        ticks = {"count": 0}

        class _DelayedStatusPage(FakePage):
            def locator(self, selector):
                if (
                    selector == browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR
                    and ticks["count"] < 1
                ):
                    return _FakeLocator([])
                return super().locator(selector)

            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedStatusPage(
            locators={
                browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text=browser_masters._DRAFT_STATUS_TEXT)]
                ),
            },
        )

        self.assertTrue(browser_masters._is_draft_overview_page(page))
        self.assertEqual(ticks["count"], 1)

    def test_non_draft_detected_after_delayed_hydration(self):
        # Same race, non-DRAFT side: the status BODY TEXT (not a testid, see
        # _read_status_text) also only settles after the SPA hydrates —
        # the poll must wait for it instead of concluding "no DRAFT marker
        # yet" means DRAFT is ruled out for good.
        ticks = {"count": 0}

        class _DelayedBodyPage(FakePage):
            def inner_text(self, selector=None):
                if selector == "body" and ticks["count"] < 1:
                    return ""
                return "Кампания активна"

            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedBodyPage()

        self.assertFalse(browser_masters._is_draft_overview_page(page))
        self.assertEqual(ticks["count"], 1)

    def test_draft_status_node_mounted_but_empty_is_not_settled(self):
        # Regression (Codex, cycle-review round 3 of PR #700): a framework
        # can mount CampaignHeader.Status before filling in its text — node
        # PRESENCE alone must not be read as "hydration done", or a real
        # DRAFT campaign whose status text arrives late gets misclassified
        # as non-DRAFT. Models the node existing (count() > 0) from the
        # start but its inner_text() staying "" until one polling tick later.
        ticks = {"count": 0}

        class _EmptyThenFilledStatusPage(FakePage):
            def locator(self, selector):
                if selector == browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR:
                    text = (
                        "" if ticks["count"] < 1 else browser_masters._DRAFT_STATUS_TEXT
                    )
                    return _FakeLocator([_FakeLocatorHandle(text=text)])
                return super().locator(selector)

            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _EmptyThenFilledStatusPage()

        self.assertTrue(browser_masters._is_draft_overview_page(page))
        self.assertEqual(ticks["count"], 1)


class TestSuspendResumeMaster(unittest.TestCase):
    """suspend_master/resume_master (issue #630): click + verify, idempotent.

    Both button labels AND their `data-testid`s are live-confirmed as of
    issue #766 (2026-08-06). These tests drive the text-fallback path
    (`FakePage` has no testid-matching locator), which is exactly the
    degradation path the module keeps for a future Yandex testid rename.
    """

    def _page_with_button(
        self, status_text, button_text, next_status_text=None, visible=True
    ):
        state = {"status": status_text}

        def _flip():
            state["status"] = next_status_text

        page = FakePage(
            text_buttons={
                button_text: _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=visible, on_click=_flip)]
                )
            },
        )
        # inner_text("body") must reflect the current (mutable) status, so
        # override the FakePage method rather than passing a fixed body_text.
        page.inner_text = lambda selector=None: state["status"]
        return page

    def test_resume_clicks_confirmed_button_and_verifies(self):
        page = self._page_with_button(
            "Кампания остановлена",
            "Возобновить кампанию",
            next_status_text="Кампания активна",
        )

        result = browser_masters.resume_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "ACTIVE"})
        # resume_master now navigates once itself (issue #758, to check for
        # ARCHIVED) and _suspend_or_resume navigates again -- a harmless
        # repeat visit to the same idempotent overview page, not a regression.
        self.assertEqual(
            page.navigated_to,
            [browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)] * 2,
        )

    def test_suspend_clicks_candidate_button_and_verifies(self):
        page = self._page_with_button(
            "Кампания активна",
            "Остановить кампанию",
            next_status_text="Кампания остановлена",
        )

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})

    def test_resume_idempotent_when_already_active(self):
        page = FakePage(body_text="Кампания активна")

        with patch("direct_cli.browser.masters.print_warning") as warn:
            result = browser_masters.resume_master(page, 7)

        self.assertEqual(result, {"CampaignId": 7, "Status": "ACTIVE"})
        warn.assert_called_once()
        self.assertIn("already", warn.call_args[0][0])

    def test_suspend_idempotent_when_already_suspended(self):
        page = FakePage(body_text="Кампания остановлена")

        with patch("direct_cli.browser.masters.print_warning"):
            result = browser_masters.suspend_master(page, 7)

        self.assertEqual(result, {"CampaignId": 7, "Status": "SUSPENDED"})

    def test_resume_raises_when_no_candidate_button_found(self):
        # None of _RESUME_BUTTON_TEXTS is present -- must not silently no-op.
        page = FakePage(body_text="Кампания остановлена", text_buttons={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 7)
        self.assertIn("--headful", str(ctx.exception))

    def test_suspend_raises_when_click_does_not_change_status(self):
        # The button is found and clicked, but the status text never flips --
        # must not report success on the click alone (module docstring).
        page = self._page_with_button(
            "Кампания активна",
            "Остановить кампанию",
            next_status_text="Кампания активна",  # unchanged after "click"
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 42)
        self.assertIn("never changed", str(ctx.exception))

    def test_suspend_retries_click_when_first_one_is_a_no_op(self):
        """Issue #766: the first click on a freshly rendered overview page
        is frequently a silent no-op — Playwright's actionability checks all
        pass, `.click()` returns without raising, and no request is issued at
        all (React's handler was not yet attached). Confirmed live
        2026-08-06 against campaign 713277109 by capturing every request
        after the click. Waiting longer cannot fix that state; only a second
        click can, which is why the pre-#766 code failed permanently no
        matter how large `_STATUS_CHANGE_TIMEOUT_MS` was set.
        """
        state = {"status": "Кампания активна", "clicks": 0}

        def _click():
            state["clicks"] += 1
            # First click does nothing at all — the no-op.
            if state["clicks"] >= 2:
                state["status"] = "Кампания остановлена"

        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_click)]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(state["clicks"], 2)

    def test_suspend_does_not_click_again_once_status_changed(self):
        """The retry loop must stop as soon as the status changes — a second
        click on an already-effective suspend would toggle it back.
        """
        state = {"status": "Кампания активна", "clicks": 0}

        def _click():
            state["clicks"] += 1
            state["status"] = (
                "Кампания остановлена"
                if state["status"] == "Кампания активна"
                else "Кампания активна"
            )

        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_click)]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(state["clicks"], 1)

    def test_no_second_click_when_the_first_lands_after_the_poll_deadline(self):
        """A click whose status update arrives only after the poll gave up
        must not be clicked again — the retry loop re-reads the status
        immediately before every retry, so the late-but-successful click is
        recognised instead of being undone.

        Without that pre-click re-read the loop would click a second time and
        toggle the campaign straight back to ACTIVE, reporting a failure for
        a mutation that had in fact succeeded.
        """
        state = {"status": "Кампания активна", "clicks": 0, "poll_done": False}

        def _click():
            state["clicks"] += 1
            # Each click toggles: a second one would undo the first.
            state["status"] = (
                "Кампания остановлена"
                if state["status"] == "Кампания активна"
                else "Кампания активна"
            )

        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_click)]
                )
            },
        )

        # Model "the update landed just after the poll's deadline": every read
        # the first attempt's poll makes still reports the OLD status, so the
        # poll times out and the loop goes around for a second attempt. Only
        # then does the real (already-changed) status become visible -- which
        # is exactly what the pre-click re-read must catch.
        # Hide the change for exactly as many reads as the first attempt's
        # poll makes (its full budget, since it never sees a target status),
        # so the poll times out and the loop goes around. The very next read
        # is attempt 2's pre-click re-read -- the one under test.
        poll_reads = int(browser_masters._STATUS_CHANGE_TIMEOUT_MS / 250) + 1
        reads = {"n": 0}

        def _inner_text(selector=None):
            if not state["clicks"]:
                return "Кампания активна"
            reads["n"] += 1
            if reads["n"] <= poll_reads:
                return "Кампания активна"
            return state["status"]

        page.inner_text = _inner_text

        result = browser_masters.suspend_master(page, 42)

        # The button stays present throughout, so the ONLY thing that can stop
        # a second (toggling) click is the pre-click re-read -- this test does
        # not share the vanished-button escape hatch the next one covers.

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(
            state["clicks"],
            1,
            "the late-landing first click must be detected by the pre-retry "
            "re-read, not followed by a second click that toggles it back",
        )

    def test_vanished_button_is_success_when_status_already_changed(self):
        """Once the status flips, the page swaps `.resume` for `.stop` — so a
        button that disappeared between the status read and the click is
        proof the mutation succeeded, not a markup change. It must not be
        reported as "could not find an action button".
        """
        state = {"status": "Кампания активна", "clicks": 0}

        def _click():
            state["clicks"] += 1
            state["status"] = "Кампания остановлена"

        # Visible for the first click, gone afterwards (as the real page does
        # once the status flips and it re-renders the opposite action).
        class _VanishingLocator:
            def count(self):
                return 0 if state["clicks"] else 1

            def nth(self, i):
                return _FakeTextLocatorHandle(visible=True, on_click=_click)

        page = FakePage(
            text_buttons={"Остановить кампанию": _VanishingLocator()},
        )

        # Same late-landing shape as the test above, but here the pre-click
        # re-read is deliberately starved: the status stays hidden until AFTER
        # that read, so the loop reaches `_click_action_button` and finds the
        # button gone. That must resolve to success, not "could not find".
        # Hide the change through the first attempt's whole poll AND through
        # attempt 2's pre-click re-read, so the loop actually reaches
        # `_click_action_button` and hits the vanished button. Only the read
        # inside the resulting rescue path sees the true status -- which is
        # precisely the branch under test.
        poll_reads = int(browser_masters._STATUS_CHANGE_TIMEOUT_MS / 250) + 1
        reads = {"n": 0}

        def _inner_text(selector=None):
            if not state["clicks"]:
                return "Кампания активна"
            reads["n"] += 1
            # +1 for attempt 2's pre-click re-read, which must NOT be the one
            # that rescues this case.
            if reads["n"] <= poll_reads + 1:
                return "Кампания активна"
            return state["status"]

        page.inner_text = _inner_text

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(state["clicks"], 1)

    def test_suspend_prefers_the_stable_testid_over_the_text_fallback(self):
        """Issue #766: the action buttons carry live-confirmed testids
        (`CampaignHeader.ActionButton.stop`/`.resume`); the Russian-label
        candidates are only a fallback. A page offering BOTH must be clicked
        via the testid.
        """
        state = {"status": "Кампания активна", "clicked": []}

        def _by_testid():
            state["clicked"].append("testid")
            state["status"] = "Кампания остановлена"

        def _by_text():
            state["clicked"].append("text")
            state["status"] = "Кампания остановлена"

        page = FakePage(
            locators={
                browser_masters._SUSPEND_BUTTON_SELECTOR: _FakeLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_by_testid)]
                )
            },
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_by_text)]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(state["clicked"], ["testid"])

    def test_text_fallback_clicks_the_enclosing_button_not_the_span(self):
        """Issue #766: `get_by_text` matches the `<span class=
        "dc-Button__text">` INSIDE the button, not the button (confirmed
        live). `_is_button_disabled`'s checks only mean anything against the
        `<button>`, so the fallback resolves the ancestor before clicking.
        """
        state = {"status": "Кампания активна", "clicked": []}

        button = _FakeTextLocatorHandle(
            visible=True,
            on_click=lambda: (
                state["clicked"].append("button"),
                state.__setitem__("status", "Кампания остановлена"),
            ),
        )
        span = _FakeTextLocatorHandle(
            visible=True,
            on_click=lambda: state["clicked"].append("span"),
            button_ancestor=button,
        )

        page = FakePage(
            text_buttons={"Остановить кампанию": _FakeGetByTextLocator([span])},
        )
        page.inner_text = lambda selector=None: state["status"]

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})
        self.assertEqual(state["clicked"], ["button"])

    def test_not_found_error_reports_selector_and_what_the_page_has(self):
        """Issue #766 asked for an error that distinguishes "Yandex renamed
        the button" from "the page rendered a different status" — so it
        names the selector AND the labels searched for, and lists the action
        buttons the page actually has.
        """
        page = FakePage(body_text="Кампания активна")

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 42)

        message = str(ctx.exception)
        self.assertIn(browser_masters._SUSPEND_BUTTON_SELECTOR, message)
        self.assertIn("Остановить кампанию", message)
        self.assertIn("action buttons on the page: none", message)
        self.assertIn("page status reads as 'ACTIVE'", message)

    def test_status_read_is_polled_not_read_once(self):
        """Issue #766: `_goto_overview_page` only guarantees the *title*
        rendered (#683); the status element is a separate render pass that
        routinely still reads as None right after it. A single read here
        live-aborted a real `masters suspend` with "unrecognised status
        text" on a campaign whose status was readable a moment later.
        """
        state = {"reads": 0, "status": "Кампания активна"}

        def _inner_text(selector=None):
            state["reads"] += 1
            # Status element not yet rendered for the first few reads.
            return "" if state["reads"] <= 3 else state["status"]

        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [
                        _FakeTextLocatorHandle(
                            visible=True,
                            on_click=lambda: state.__setitem__(
                                "status", "Кампания остановлена"
                            ),
                        )
                    ]
                )
            },
        )
        page.inner_text = _inner_text

        result = browser_masters.suspend_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "SUSPENDED"})

    def test_resume_raises_when_current_status_unrecognised(self):
        page = FakePage(body_text="something Yandex changed the markup to")

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 7)
        self.assertIn("Could not determine current status", str(ctx.exception))

    def test_suspend_button_invisible_is_skipped(self):
        # An invisible match (e.g. a hidden template) must not be clicked --
        # falls through to the "not found" error since it's the only handle.
        page = self._page_with_button(
            "Кампания активна", "Остановить кампанию", visible=False
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.suspend_master(page, 42)

    def test_suspend_disabled_button_raises_specific_error(self):
        # issue #728: Yandex renders "Остановить кампанию" disabled (not
        # hidden) while some of the campaign's creatives are still on
        # moderation/rejected. Must raise a specific, actionable error
        # instead of the generic "could not find a button" message that
        # implies Yandex changed the markup.
        state = {"status": "Кампания активна"}
        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, disabled=True)]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 42)
        self.assertIn("disabled", str(ctx.exception))
        self.assertIn("moderation", str(ctx.exception))

    def test_suspend_aria_disabled_button_raises_specific_error(self):
        state = {"status": "Кампания активна"}
        page = FakePage(
            text_buttons={
                "Остановить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, aria_disabled="true")]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 42)
        self.assertIn("disabled", str(ctx.exception))

    def _draft_page(self):
        return FakePage(
            locators={
                browser_masters._CAMPAIGN_HEADER_STATUS_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(text=browser_masters._DRAFT_STATUS_TEXT)]
                ),
            },
        )

    def test_suspend_raises_clear_error_on_draft(self):
        # issue #660: a DRAFT campaign has no ACTIVE/SUSPENDED status or
        # action button at all — must refuse with a DRAFT-specific message,
        # not "unrecognised status text" (_read_status_text would return
        # None on this page, which is a different, misleading failure mode).
        page = self._draft_page()

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.suspend_master(page, 713231614)
        self.assertIn("DRAFT", str(ctx.exception))
        self.assertEqual(
            page.navigated_to,
            [browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)],
        )

    def test_resume_raises_clear_error_on_draft(self):
        page = self._draft_page()

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 713231614)
        self.assertIn("DRAFT", str(ctx.exception))

    def _archived_page_with_unarchive(self, next_status_text, resume_button_text=None):
        """An ARCHIVED overview page whose "⋮" menu has only "Разархивировать".

        Models issue #758's live-confirmed shape: no resume button exists on
        an ARCHIVED page at all — clicking the unarchive menu item flips the
        (mutable) status text to ``next_status_text`` (SUSPENDED in the
        success path). ``resume_button_text``, if given, additionally wires
        up a resume button that flips the status again once SUSPENDED is
        reached — modeling the second, ordinary one-click leg of the resume.
        """
        state = {"status": "Кампания в\xa0архиве"}

        def _unarchive():
            state["status"] = next_status_text

        text_buttons = {}
        if resume_button_text is not None:

            def _resume():
                state["status"] = "Кампания активна"

            text_buttons[resume_button_text] = _FakeGetByTextLocator(
                [_FakeTextLocatorHandle(visible=True, on_click=_resume)]
            )

        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._UNARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_unarchive)]
                ),
            },
            text_buttons=text_buttons,
        )
        page.inner_text = lambda selector=None: state["status"]
        return page

    def test_resume_from_archived_unarchives_then_resumes(self):
        # issue #758: ARCHIVED has no resume button at all -- resume_master
        # must click "Разархивировать" first, wait for SUSPENDED, THEN do
        # the ordinary one-click resume to ACTIVE/MODERATION.
        page = self._archived_page_with_unarchive(
            "Кампания остановлена", resume_button_text="Возобновить кампанию"
        )

        result = browser_masters.resume_master(page, 713277109)

        self.assertEqual(result, {"CampaignId": 713277109, "Status": "ACTIVE"})

    def test_resume_from_archived_can_end_in_moderation(self):
        # Yandex may send a resumed campaign to moderation instead of ACTIVE
        # (live-confirmed 2026-08-05) -- this must still be reported as
        # success, with the actual status returned, not normalised to ACTIVE.
        state_holder = {}

        def _resume_to_moderation():
            state_holder["status"] = "Кампания на\xa0модерации"

        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._UNARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_click=lambda: state_holder.__setitem__(
                                "status", "Кампания остановлена"
                            )
                        )
                    ]
                ),
            },
            text_buttons={
                "Возобновить кампанию": _FakeGetByTextLocator(
                    [
                        _FakeTextLocatorHandle(
                            visible=True, on_click=_resume_to_moderation
                        )
                    ]
                )
            },
        )
        state_holder["status"] = "Кампания в\xa0архиве"
        page.inner_text = lambda selector=None: state_holder["status"]

        result = browser_masters.resume_master(page, 713277109)

        self.assertEqual(result, {"CampaignId": 713277109, "Status": "MODERATION"})

    def test_resume_direct_from_suspended_can_end_in_moderation(self):
        # Same MODERATION-as-success behaviour on the ordinary (non-archived)
        # one-click resume path, not just after an unarchive step.
        page = self._page_with_button(
            "Кампания остановлена",
            "Возобновить кампанию",
            next_status_text="Кампания на\xa0модерации",
        )

        result = browser_masters.resume_master(page, 42)

        self.assertEqual(result, {"CampaignId": 42, "Status": "MODERATION"})

    def test_resume_from_archived_raises_when_unarchive_menu_item_missing(self):
        # Menu opens but has no unarchive item -- must fail loudly, not
        # silently skip straight to (futile) resume-button clicking.
        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
            },
            body_text="Кампания в\xa0архиве",
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 713277109)
        self.assertIn("Разархивировать", str(ctx.exception))

    def test_resume_from_archived_raises_when_status_never_becomes_suspended(self):
        # The unarchive click "succeeds" but the status text never flips to
        # SUSPENDED -- must not silently fall through to the resume-button
        # search (which would then fail with a confusing, unrelated error).
        page = self._archived_page_with_unarchive("Кампания в\xa0архиве")

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.resume_master(page, 713277109)
        self.assertIn("Разархивировать", str(ctx.exception))
        self.assertIn("never changed to any of ('SUSPENDED',)", str(ctx.exception))

    def test_resume_from_archived_waits_for_status_to_hydrate(self):
        # issue #758 follow-up: _goto_overview_page only guarantees the
        # title rendered (issue #683) -- the separate status-text element
        # can still read as unrecognised (None) on the very first call right
        # after navigation. resume_master must not silently skip the
        # ARCHIVED/unarchive branch just because that first read raced the
        # page's own hydration -- it must poll for a recognised status
        # before branching, then take the unarchive-then-resume path once
        # the true ARCHIVED status is observed, never falling straight
        # through to a doomed search for a resume button that an ARCHIVED
        # page does not have.
        calls = {"n": 0, "unarchive_clicks": 0}

        def _unarchive():
            calls["unarchive_clicks"] += 1
            calls["status"] = "Кампания остановлена"

        def _resume():
            calls["status"] = "Кампания активна"

        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._UNARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_unarchive)]
                ),
            },
            text_buttons={
                "Возобновить кампанию": _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_resume)]
                )
            },
        )
        calls["status"] = "Кампания в\xa0архиве"

        def fake_inner_text(selector=None):
            calls["n"] += 1
            if calls["n"] == 1:
                # The overview title has rendered but the status element
                # has not hydrated yet -- no recognised marker in the body.
                return ""
            return calls["status"]

        page.inner_text = fake_inner_text

        result = browser_masters.resume_master(page, 713277109)

        self.assertEqual(result, {"CampaignId": 713277109, "Status": "ACTIVE"})
        self.assertEqual(
            calls["unarchive_clicks"],
            1,
            "resume_master must click 'Разархивировать' even when the "
            "first status read after navigation raced the page's own "
            "hydration and came back unrecognised",
        )

    def test_initial_hydration_uses_its_own_budget_not_the_post_click_one(self):
        """The pre-click hydration wait and the post-click status wait are
        two different quantities and must not share a constant.

        Only the post-click latency was ever measured (1.6-2.3s, issue #764);
        `_STATUS_CHANGE_TIMEOUT_MS` was set to 8s from it. The initial
        hydration wait has no measurement behind it, and before #766 it ran
        on the then-current 60s budget. Collapsing the two would silently cut
        it to 8s and, on a slow page, make `resume_master` miss an ARCHIVED
        status, skip the unarchive step and hunt for a resume button that an
        archived page never renders.

        The test above only proves hydration is polled *at all* — it passes
        under any sufficient budget, including a shared one. This asserts the
        separation itself, so a well-meaning "dedupe these two constants"
        change fails here instead of live.
        """
        self.assertGreater(
            browser_masters._STATUS_HYDRATION_TIMEOUT_MS,
            browser_masters._STATUS_CHANGE_TIMEOUT_MS,
            "initial status hydration must keep its own, larger budget — the "
            "8s post-click figure was measured for a different quantity",
        )

        # And the wait must actually poll past a slow first read rather than
        # give up on it -- the behaviour the larger budget buys.
        reads = {"n": 0}

        def fake_read_status_text(page):
            reads["n"] += 1
            return None if reads["n"] < 3 else "ARCHIVED"

        page = FakePage()
        with patch.object(
            browser_masters, "_read_status_text", side_effect=fake_read_status_text
        ):
            status = browser_masters._wait_for_recognised_status(page)

        self.assertEqual(status, "ARCHIVED")
        self.assertEqual(reads["n"], 3)


class TestMastersSuspendResumeCommand(unittest.TestCase):
    """CLI wiring for `masters suspend`/`masters resume`."""

    def setUp(self):
        self.runner = CliRunner()

    def test_suspend_registered(self):
        result = self.runner.invoke(cli, ["masters", "suspend", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_resume_registered(self):
        result = self.runner.invoke(cli, ["masters", "resume", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_suspend_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "suspend", "--help"])
        self.assertNotIn("--login", result.output)

    def test_resume_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "resume", "--help"])
        self.assertNotIn("--login", result.output)

    def test_suspend_calls_suspend_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.suspend_master") as mock_suspend,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "suspend", "1,2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_suspend.call_count, 2)

    def test_resume_calls_resume_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.resume_master") as mock_resume,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "resume", "1"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_resume.call_count, 1)

    def test_suspend_continues_batch_past_a_failing_id(self):
        """Issue #766: a real 8-ID `masters suspend` aborted on the first ID,
        leaving the caller with no idea whether the other seven had even
        been attempted. Every ID must be tried, and every outcome reported.
        """

        def _suspend(page, campaign_id):
            if campaign_id == 2:
                raise BrowserSessionError("boom for 2")
            return {"CampaignId": campaign_id, "Status": "SUSPENDED"}

        with (
            patch("direct_cli.browser.masters.suspend_master", side_effect=_suspend),
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "suspend", "1,2,3"])

        # Non-zero exit, but only AFTER every ID was attempted and reported.
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"CampaignId": 1', result.output)
        self.assertIn('"CampaignId": 3', result.output)
        self.assertIn("boom for 2", result.output)
        self.assertIn("Failed to suspend 1 of 3 campaign(s)", result.output)

    def test_resume_continues_batch_past_a_failing_id(self):
        def _resume(page, campaign_id):
            if campaign_id == 1:
                raise BrowserSessionError("boom for 1")
            return {"CampaignId": campaign_id, "Status": "ACTIVE"}

        with (
            patch("direct_cli.browser.masters.resume_master", side_effect=_resume),
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "resume", "1,2"])

        self.assertNotEqual(result.exit_code, 0)
        # The FIRST id failing must not stop the second one (issue #766's
        # exact reported shape: the error was always about the first ID).
        self.assertIn('"CampaignId": 2', result.output)
        self.assertIn("boom for 1", result.output)
        self.assertIn("Failed to resume 1 of 2 campaign(s)", result.output)


class _FakeHydratingPopupHandle(_FakeLocatorHandle):
    """A popup handle whose ``wait_for`` only succeeds after N total clicks
    of the trigger have happened — models issues #723/#725's hydration race,
    where a click on a visible/enabled trigger sometimes doesn't open its
    popup/portal because React's own handler hasn't finished hydrating yet.
    """

    def __init__(self, *, ready_after_attempt, click_counter, **kwargs):
        super().__init__(**kwargs)
        self._ready_after_attempt = ready_after_attempt
        self._click_counter = click_counter

    def wait_for(self, state="visible", timeout=None):
        if self._click_counter["count"] < self._ready_after_attempt:
            raise PlaywrightError("Timeout waiting for element state")


class TestClickAndWaitForPopup(unittest.TestCase):
    """``_click_and_wait_for_popup`` (issues #723/#725): click a trigger,
    retry if the expected popup doesn't appear, since the click can land on
    a visible/enabled element without its React handler/portal being ready.
    """

    def _page(self, *, trigger_handle, popup_locator):
        return FakePage(
            locators={
                "trigger": _FakeLocator([trigger_handle]),
                "popup": popup_locator,
            }
        )

    def test_succeeds_on_first_click_when_popup_appears_immediately(self):
        page = self._page(
            trigger_handle=_FakeLocatorHandle(),
            popup_locator=_FakeLocator([_FakeLocatorHandle()]),
        )

        browser_masters._click_and_wait_for_popup(
            page,
            trigger_selector="trigger",
            popup_selector="popup",
            description="a test popup",
        )  # must not raise

    def test_retries_click_when_popup_does_not_appear_on_first_attempt(self):
        click_counter = {"count": 0}

        def _on_click():
            click_counter["count"] += 1

        trigger_handle = _FakeLocatorHandle(on_click=_on_click)
        popup_handle = _FakeHydratingPopupHandle(
            ready_after_attempt=2, click_counter=click_counter
        )
        page = self._page(
            trigger_handle=trigger_handle,
            popup_locator=_FakeLocator([popup_handle]),
        )

        browser_masters._click_and_wait_for_popup(
            page,
            trigger_selector="trigger",
            popup_selector="popup",
            description="a test popup",
        )  # must not raise

        self.assertEqual(click_counter["count"], 2)

    def test_raises_after_exhausting_all_attempts(self):
        click_counter = {"count": 0}

        def _on_click():
            click_counter["count"] += 1

        trigger_handle = _FakeLocatorHandle(on_click=_on_click)
        # Never becomes ready within the retry budget.
        popup_handle = _FakeHydratingPopupHandle(
            ready_after_attempt=browser_masters._POPUP_CLICK_MAX_ATTEMPTS + 1,
            click_counter=click_counter,
        )
        page = self._page(
            trigger_handle=trigger_handle,
            popup_locator=_FakeLocator([popup_handle]),
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._click_and_wait_for_popup(
                page,
                trigger_selector="trigger",
                popup_selector="popup",
                description="a test popup",
            )

        self.assertIn("a test popup", str(ctx.exception))
        self.assertEqual(
            click_counter["count"], browser_masters._POPUP_CLICK_MAX_ATTEMPTS
        )

    def test_raises_when_trigger_itself_is_never_clickable(self):
        page = self._page(
            trigger_handle=_FakeLocatorHandle(raises=True),
            popup_locator=_FakeLocator([_FakeLocatorHandle(visible=False)]),
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_and_wait_for_popup(
                page,
                trigger_selector="trigger",
                popup_selector="popup",
                description="a test popup",
            )

    def test_does_not_reclick_a_toggle_trigger_once_popup_is_up(self):
        """A successful-but-slow open must not be undone by a retry.

        The first click genuinely opens the (toggle) menu, but rendering is
        slow enough that the *first* ``wait_for`` call still observes it as
        not-yet-visible and times out — it becomes visible only strictly
        after that. If the loop then blindly re-clicks the trigger on the
        next attempt, it closes the menu that *did* open (a toggle button
        closes on a second click), turning a slow-but-correct open into a
        failure. This must not happen: the loop must re-check for the popup
        (a fresh ``wait_for``) before ever clicking the trigger again, so a
        popup that showed up between attempts is observed without an extra
        click.
        """
        click_counter = {"count": 0}
        popup_state = {"popup_visible": False, "wait_for_calls": 0}

        def _on_click():
            click_counter["count"] += 1
            # A second click on an already-open toggle would close it — the
            # test fails via the final assertion if this ever fires twice.
            popup_state["popup_visible"] = False

        class _ToggleAwarePopupHandle(_FakeLocatorHandle):
            def wait_for(self, state="visible", timeout=None):
                popup_state["wait_for_calls"] += 1
                # Call #1: the loop's pre-check before any click — not up
                # yet. Call #2: right after the first click — still
                # hydrating, times out, but becomes visible immediately
                # after (independently of any further click). Call #3+: the
                # next iteration's pre-check must see it up.
                if popup_state["wait_for_calls"] == 2:
                    popup_state["popup_visible"] = True
                if not popup_state["popup_visible"]:
                    raise PlaywrightError("Timeout waiting for element state")

        popup_handle = _ToggleAwarePopupHandle()
        trigger_handle = _FakeLocatorHandle(on_click=_on_click)
        page = self._page(
            trigger_handle=trigger_handle,
            popup_locator=_FakeLocator([popup_handle]),
        )

        browser_masters._click_and_wait_for_popup(
            page,
            trigger_selector="trigger",
            popup_selector="popup",
            description="a test popup",
        )  # must not raise

        # Only the first click should have happened — the second loop
        # iteration's pre-check must have observed the popup already up and
        # returned instead of clicking (and thereby closing) the toggle
        # again.
        self.assertEqual(click_counter["count"], 1)
        self.assertTrue(popup_state["popup_visible"])


class TestArchiveMaster(unittest.TestCase):
    """archive_master (issue #633): click + verify via the campaigns grid.

    Мастер кампаний has no separate "delete" (live recon, see module
    docstring) — archive is the only destructive/lifecycle action left.
    Unlike suspend/resume's text-matched candidate buttons, the overview
    page's "⋮" menu and its "Архивировать" item are confirmed live via
    stable ``data-testid`` selectors, so these tests exercise exact-selector
    clicks rather than a candidate-list fallback.
    """

    def _row(self, status):
        return {
            "CampaignId": 42,
            "Name": "Мастер тестовый",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }

    def _page_with_menu(
        self, menu_trigger=None, archive_item=None, body_text="Кампания остановлена"
    ):
        locators = {}
        if menu_trigger is not None:
            locators[browser_masters._MENU_TRIGGER_SELECTOR] = _FakeLocator(
                [menu_trigger]
            )
        if archive_item is not None:
            locators[browser_masters._ARCHIVE_MENU_ITEM_SELECTOR] = _FakeLocator(
                [archive_item]
            )
        return FakePage(locators=locators, body_text=body_text)

    def test_archives_and_verifies_via_grid(self):
        # "SUSPENDED" (not the raw grid "STOPPED") -- see the comment on
        # test_raises_when_menu_trigger_not_found for why this must match
        # fetch_masters_list's own normalized value (issue #797's TOCTOU
        # re-check compares against it before the click).
        state = {"status": "SUSPENDED"}

        def _flip():
            state["status"] = "ARCHIVED"

        # The TOCTOU re-check (issue #797) reads the overview page's own
        # status text (_read_status_text), NOT the campaigns grid --
        # navigating to the grid mid-recheck would destroy the "⋮" menu this
        # test's archive_item click depends on (see _reverify_status_or_raise's
        # docstring). "Кампания остановлена" is _read_status_text's own
        # SUSPENDED marker.
        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=_flip),
            body_text="Кампания остановлена",
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [self._row(state["status"])],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(
            page.navigated_to,
            [browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)],
        )

    def test_retries_transient_unrecognised_status_before_archiving(self):
        # Issue #829: on long sequential batch runs, the pre-click TOCTOU
        # re-check (_reverify_status_or_raise) sometimes reads the overview
        # page's status text as unrecognised even after its own internal
        # hydration poll gives up -- not because the campaign actually
        # changed, but because the whole page briefly failed to render on
        # this particular request. Re-navigating to the overview page (a
        # real reload, not just re-polling the same static state) and
        # retrying the open-menu-then-click sequence recovers without
        # treating a rendering hiccup as a hard "another session changed
        # it" abort.
        state = {"status": "", "grid_status": "SUSPENDED"}

        def _flip():
            state["status"] = "ARCHIVED"
            state["grid_status"] = "ARCHIVED"

        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=_flip),
        )

        def _fake_inner_text(selector=None):
            # The status text is unrecognised until the SECOND navigation
            # (the retry's fresh reload) — models a page load that failed to
            # render the status element the first time, recovering the
            # second. `navigated_to` records every goto() the production
            # code has made by the time this read happens.
            if len(page.navigated_to) < 2:
                return ""
            return state["status"] or "Кампания остановлена"

        page.inner_text = _fake_inner_text

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [self._row(state["grid_status"])],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(
            len(page.navigated_to),
            2,
            "archive_master must re-navigate to the overview page and retry "
            "once the pre-click re-check hits an unrecognised status, "
            "instead of aborting on the first hiccup",
        )

    def test_idempotent_when_already_archived(self):
        page = self._page_with_menu()

        with (
            patch(
                "direct_cli.browser.masters.fetch_masters_list",
                return_value=[self._row("ARCHIVED")],
            ),
            patch("direct_cli.browser.masters.print_warning") as warn,
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(page.navigated_to, [])  # not clicking -> no navigation either
        warn.assert_called_once()
        self.assertIn("already archived", warn.call_args[0][0])

    def test_raises_when_campaign_not_found_in_grid(self):
        page = self._page_with_menu()

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Could not find", str(ctx.exception))

    def test_raises_when_menu_trigger_not_found(self):
        page = self._page_with_menu()  # no menu_trigger locator registered

        # "SUSPENDED" (not the raw grid "STOPPED") -- fetch_masters_list
        # itself normalizes STOPPED -> SUSPENDED (_PRIMARY_STATUS_TO_CLI_
        # STATUS) before archive_master ever sees a row, and issue #797's
        # TOCTOU re-check (_reverify_status_or_raise) now compares against
        # that normalized value, so the fixture must match what the real
        # function returns, not the pre-normalization grid string.
        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("SUSPENDED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Could not open the campaign menu", str(ctx.exception))

    def test_raises_when_archive_menu_item_not_found(self):
        page = self._page_with_menu(menu_trigger=_FakeLocatorHandle())

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("SUSPENDED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("Архивировать", str(ctx.exception))

    def test_raises_when_status_never_becomes_archived(self):
        # The click succeeds but the grid keeps reporting SUSPENDED -- must
        # not report success on the click alone.
        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(),
            body_text="Кампания остановлена",
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("SUSPENDED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("did not report it as ARCHIVED", str(ctx.exception))

    def test_raises_clear_error_on_draft_without_navigating(self):
        # issue #660: the grid already reports DRAFT before any navigation
        # happens, and a DRAFT overview page has no "⋮" menu to click at all
        # — refuse immediately with a clear message instead of navigating
        # and hitting "Could not open the campaign menu".
        page = self._page_with_menu()

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("DRAFT", str(ctx.exception))
        self.assertEqual(page.navigated_to, [])

    def _active_page_with_suspend_and_menu(self, suspend_button_text):
        """An ACTIVE/MODERATION overview page: "Остановить кампанию" button
        AND the "⋮" menu with an archive item — models issue #758's
        confirmed shape where the menu has no archive item at all until the
        campaign is SUSPENDED, so archive_master must suspend first."""
        state = {"status": "Кампания активна"}

        def _suspend():
            state["status"] = "Кампания остановлена"

        def _archive():
            state["status"] = "ARCHIVED_VIA_MENU"

        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._ARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_archive)]
                ),
            },
            text_buttons={
                suspend_button_text: _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle(visible=True, on_click=_suspend)]
                )
            },
        )
        page.inner_text = lambda selector=None: state["status"]
        return page, state

    def test_archives_from_active_suspends_first(self):
        # issue #758: an ACTIVE campaign's menu has no "Архивировать" item at
        # all -- archive_master must click "Остановить кампанию" first, wait
        # for SUSPENDED, THEN open the menu and click "Архивировать".
        page, state = self._active_page_with_suspend_and_menu("Остановить кампанию")

        # Grid status by state, mirroring fetch_masters_list's own
        # normalized "SUSPENDED" (issue #797's TOCTOU re-check,
        # _reverify_status_or_raise, requires the grid to actually report
        # SUSPENDED once suspend_master's own poll sees the overview page's
        # "Кампания остановлена" text -- not still ACTIVE).
        def _status_for_grid():
            if state["status"] == "ARCHIVED_VIA_MENU":
                return "ARCHIVED"
            if state["status"] == "Кампания остановлена":
                return "SUSPENDED"
            return "ACTIVE"

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [self._row(_status_for_grid())],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))

    def test_archives_from_moderation_suspends_first(self):
        page, state = self._active_page_with_suspend_and_menu("Остановить кампанию")
        state["status"] = "Кампания на\xa0модерации"

        def _status_for_grid():
            if state["status"] == "ARCHIVED_VIA_MENU":
                return "ARCHIVED"
            if state["status"] == "Кампания остановлена":
                return "SUSPENDED"
            return "MODERATION"

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [self._row(_status_for_grid())],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))

    def test_toctou_aborts_without_clicking_when_status_changed_before_click(self):
        # issue #797 Finding 1 (same TOCTOU shape as delete_master, issue
        # #793 Finding 1): the up-front guard reads SUSPENDED once via
        # fetch_masters_list, but opening the "⋮" menu
        # (_click_and_wait_for_popup's own retry loop) takes real time --
        # another session could move the campaign off SUSPENDED before
        # 'Архивировать' is clicked. The TOCTOU re-check itself reads the
        # overview page's own status text (_read_status_text), not the grid
        # (see _reverify_status_or_raise's docstring for why) -- flip the
        # page's body text to ACTIVE to model that concurrent change.
        archive_clicked = []

        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=lambda: archive_clicked.append(1)),
            body_text="Кампания активна",
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("SUSPENDED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("is now", str(ctx.exception))
        self.assertIn("ACTIVE", str(ctx.exception))
        self.assertIn("Not clicking", str(ctx.exception))
        self.assertEqual(archive_clicked, [])

    def test_toctou_aborts_without_clicking_when_campaign_vanished_before_click(self):
        # Same TOCTOU window, but the overview page no longer shows a
        # recognised status text (e.g. archived or deleted by another
        # session) rather than merely showing a different one.
        archive_clicked = []

        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=lambda: archive_clicked.append(1)),
            body_text="",
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("SUSPENDED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("no longer shows a recognised status", str(ctx.exception))
        self.assertEqual(archive_clicked, [])

    def test_verify_loop_tolerates_transient_error_then_succeeds(self):
        # issue #797 Finding 2 (same tolerant-poll shape as delete_master,
        # issue #793 Finding 2): a transient BrowserSessionError on the
        # FIRST poll after a successful, irreversible click must not
        # propagate -- it must be treated as inconclusive and polling must
        # continue. The TOCTOU re-check (before the click) reads the
        # overview page's own status text, not fetch_masters_list, so every
        # fetch_masters_list call here is a POST-click verify poll.
        state = {"status": "SUSPENDED"}
        poll_calls = {"n": 0}

        def _archive():
            state["status"] = "ARCHIVED"

        def _fetch(page, status="all"):
            poll_calls["n"] += 1
            # Call 1: up-front guard. Call 2: first verify poll -- raise
            # here. Call 3+: verify polls succeed.
            if poll_calls["n"] == 2:
                raise BrowserSessionError("Campaigns grid API returned HTTP 500")
            return [self._row(state["status"])]

        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(on_click=_archive),
            body_text="Кампания остановлена",
        )

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertGreaterEqual(poll_calls["n"], 3)

    def test_verify_loop_reports_click_already_landed_when_every_poll_errors(self):
        # issue #797 Finding 2: if every poll until the deadline errors, the
        # final message must say the click already landed, not just repeat
        # a generic "did not report it as ARCHIVED" (which would falsely
        # suggest the click itself may not have worked).
        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(),
            body_text="Кампания остановлена",
        )

        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            if calls["n"] <= 1:
                # up-front guard sees SUSPENDED (the TOCTOU re-check reads
                # the overview page's own status text, not the grid).
                return [self._row("SUSPENDED")]
            raise BrowserSessionError("Campaigns grid API returned HTTP 500")

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.archive_master(page, 42)

        self.assertIn("landed", str(ctx.exception))
        self.assertIn("HTTP 500", str(ctx.exception))

    def test_verify_loop_reraises_auth_error_for_with_sessions_auto_heal(self):
        # cycle-review finding on issue #797: unlike copy_master (not
        # idempotent -- a retried click would create a SECOND campaign, so
        # it deliberately keeps BrowserAuthError wrapped as a plain
        # BrowserSessionError), archive_master IS idempotent (see the
        # already-ARCHIVED early return). _poll_master_row_tolerant
        # tolerates every BrowserSessionError including BrowserAuthError
        # (issue #797 Finding 2), so without this re-raise a session that
        # expires mid-poll would surface as a generic timeout instead of
        # letting _with_session (direct_cli/commands/masters.py) retry the
        # whole idempotent call under a fresh session.
        page = self._page_with_menu(
            menu_trigger=_FakeLocatorHandle(),
            archive_item=_FakeLocatorHandle(),
            body_text="Кампания остановлена",
        )

        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            if calls["n"] <= 1:
                return [self._row("SUSPENDED")]
            raise BrowserAuthError("stale session, detected mid-poll")

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserAuthError):
                browser_masters.archive_master(page, 42)

    def test_toctou_recheck_tolerates_status_text_hydration_lag(self):
        # cycle-review finding (codex) on issue #797: _goto_overview_page
        # only guarantees the title rendered (issue #683), not the status
        # element -- _wait_for_recognised_status's own docstring documents
        # it as a separate render pass that "routinely reads as None for a
        # moment" right after. A single unguarded _read_status_text at the
        # TOCTOU re-check would misattribute that hydration lag to
        # "another session changed it" and abort a legitimate archive.
        # This page's status text is empty for the first two reads (the
        # lag), then hydrates to the real SUSPENDED marker -- the re-check
        # must tolerate that instead of failing closed on the first read.
        reads = {"n": 0}
        archive_clicked = []

        class _SlowStatusPage(FakePage):
            def inner_text(self, selector=None):
                reads["n"] += 1
                if reads["n"] <= 2:
                    return ""
                return "Кампания остановлена"

        page = _SlowStatusPage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._ARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: archive_clicked.append(1))]
                ),
            }
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._row("ARCHIVED" if archive_clicked else "SUSPENDED")
            ],
        ):
            result = browser_masters.archive_master(page, 42)

        self.assertEqual(result, self._row("ARCHIVED"))
        self.assertEqual(archive_clicked, [1])


class TestMastersArchiveCommand(unittest.TestCase):
    """CLI wiring for `masters archive` (issue #633)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_archive_registered(self):
        result = self.runner.invoke(cli, ["masters", "archive", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_archive_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "archive", "--help"])
        self.assertNotIn("--login", result.output)

    def test_archive_calls_archive_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.archive_master") as mock_archive,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "archive", "1,2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_archive.call_count, 2)

    def test_archive_reports_earlier_successes_when_a_later_id_fails(self):
        # Regression: archive is irreversible (no `masters unarchive`) -- a
        # naive list comprehension that aborts on the first exception would
        # silently lose the report that ids 1/2 were already archived in
        # production before id 3 failed. The per-ID outcome for every ID
        # must reach the user, not just the last error.
        def _fake_archive(page, campaign_id):
            if campaign_id == 3:
                raise BrowserSessionError("boom on id 3")
            return {"CampaignId": campaign_id, "Status": "ARCHIVED"}

        with (
            patch(
                "direct_cli.browser.masters.archive_master", side_effect=_fake_archive
            ) as mock_archive,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "archive", "1,2,3,4"])

        # All four IDs must be attempted -- a failure on id 3 must not skip
        # id 4, and must not discard the already-mutated 1/2 from the report.
        self.assertEqual(mock_archive.call_count, 4)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1", result.output)
        self.assertIn("ARCHIVED", result.output)
        self.assertIn("2", result.output)
        self.assertIn("boom on id 3", result.output)


class TestScrollGridToRow(unittest.TestCase):
    """_scroll_grid_to_row (issue #791): drives the campaigns grid's own
    virtual-scroll container to make a row outside the initial render
    window appear in the DOM. Unit-level tests against page.evaluate()
    directly -- TestDeleteMaster covers the integration (call order,
    best-effort failure handling) within delete_master itself.
    """

    CAMPAIGN_ID = 713356270

    def test_returns_true_and_passes_expected_args_when_row_found(self):
        captured = {}

        def _evaluate(arg):
            captured["arg"] = arg
            return True

        page = FakePage()
        page._evaluate_side_effect = _evaluate

        result = browser_masters._scroll_grid_to_row(page, self.CAMPAIGN_ID)

        self.assertTrue(result)
        self.assertEqual(
            captured["arg"],
            [
                self.CAMPAIGN_ID,
                browser_masters._GRID_SCROLL_MAX_STEPS,
                browser_masters._GRID_SCROLL_STEP_DELAY_MS,
            ],
        )

    def test_returns_false_when_row_never_found(self):
        page = FakePage()
        page._evaluate_side_effect = lambda arg: False

        result = browser_masters._scroll_grid_to_row(page, self.CAMPAIGN_ID)

        self.assertFalse(result)

    def test_returns_false_instead_of_raising_on_playwright_error(self):
        # Mirrors every other best-effort browser primitive in this module
        # (scroll_into_view_if_needed's own try/except) -- a page.evaluate()
        # failure (detached frame, navigation mid-call, etc.) must not
        # propagate; the caller's retry loop is still the authority on
        # success/failure.
        def _raise(arg):
            raise browser_masters.PlaywrightError("evaluate failed")

        page = FakePage()
        page._evaluate_side_effect = _raise

        result = browser_masters._scroll_grid_to_row(page, self.CAMPAIGN_ID)

        self.assertFalse(result)

    def test_coerces_truthy_non_bool_result_to_bool(self):
        # page.evaluate() over CDP can hand back a JS boolean as a Python
        # bool already, but defensively coerce anyway rather than trust
        # the exact type.
        page = FakePage()
        page._evaluate_side_effect = lambda arg: 1

        result = browser_masters._scroll_grid_to_row(page, self.CAMPAIGN_ID)

        self.assertIs(result, True)


class TestDeleteMaster(unittest.TestCase):
    """delete_master (issue #782): DRAFT-only removal via the campaigns
    grid's own row menu — a SEPARATE menu from the overview page's "⋮"
    (see archive_master), confirmed live against DRAFT campaign 713337891.
    """

    CAMPAIGN_ID = 713337891
    ROW_SELECTOR = browser_masters._GRID_ROW_SELECTOR_TEMPLATE.format(
        campaign_id=CAMPAIGN_ID
    )

    def _row(self, status):
        return {
            "CampaignId": self.CAMPAIGN_ID,
            "Name": "ksamata.ru от 06.08.26",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2026-08-06",
        }

    def _page_with_row_menu(self, trigger=None, delete_item=None):
        locators = {}
        if trigger is not None:
            row_handle = _FakeLocatorHandle(
                sub_locators={
                    browser_masters._GRID_ROW_ACTIONS_TRIGGER_SELECTOR: trigger
                }
            )
            locators[self.ROW_SELECTOR] = _FakeLocator([row_handle])
        if delete_item is not None:
            locators[browser_masters._GRID_ROW_DELETE_ITEM_SELECTOR] = _FakeLocator(
                [delete_item]
            )
        return FakePage(locators=locators)

    def test_deletes_and_verifies_via_grid(self):
        state = {"rows": [self._row("DRAFT")]}

        def _remove():
            state["rows"] = []

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(on_click=_remove),
        )
        # The popup itself is portal-rendered on `page`, not inside the row.
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": list(state["rows"]),
        ):
            result = browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(result, {"CampaignId": self.CAMPAIGN_ID, "Deleted": True})

    def test_raises_when_campaign_not_found_in_grid(self):
        page = self._page_with_row_menu()

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("Could not find", str(ctx.exception))

    def test_refuses_non_draft_status_without_clicking(self):
        page = self._page_with_row_menu()

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("ACTIVE")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("not DRAFT", str(ctx.exception))
        self.assertIn("masters archive", str(ctx.exception))

    def test_refuses_archived_status(self):
        # Not just ACTIVE -- every non-DRAFT status is refused the same way.
        page = self._page_with_row_menu()

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("ARCHIVED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("not DRAFT", str(ctx.exception))

    def test_raises_when_row_menu_trigger_not_found(self):
        page = self._page_with_row_menu()  # no trigger registered

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("Could not open the campaigns grid row menu", str(ctx.exception))
        # cycle-review follow-up (#784): the grid is a virtualized SPA
        # (module docstring, #639/#671) -- a row absent from the DOM is
        # indistinguishable, at this call site, from a genuine markup
        # change, so the error must not claim only the latter.
        self.assertIn("virtualized SPA", str(ctx.exception))

    def test_row_is_scrolled_into_view_before_opening_menu(self):
        # cycle-review follow-up (#784, Codex): delete_master is the only
        # function that clicks a specific campaigns-grid ROW's DOM node,
        # and the grid is documented as virtualized -- a best-effort
        # scroll_into_view_if_needed() must run before the trigger click,
        # not just left to Playwright's own actionability wait.
        state = {"rows": [self._row("DRAFT")]}
        scroll_calls = []

        def _remove():
            state["rows"] = []

        trigger_selector = browser_masters._GRID_ROW_ACTIONS_TRIGGER_SELECTOR
        row_handle = _FakeLocatorHandle(
            sub_locators={trigger_selector: _FakeLocatorHandle()}
        )
        row_handle.scroll_into_view_if_needed = (
            lambda timeout=None: scroll_calls.append(timeout)
        )
        page = FakePage(
            locators={
                self.ROW_SELECTOR: _FakeLocator([row_handle]),
                browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._GRID_ROW_DELETE_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_remove)]
                ),
            }
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": list(state["rows"]),
        ):
            browser_masters.delete_master(page, self.CAMPAIGN_ID)

        # ONE scroll_into_view_if_needed call (issue #805/#807 round 2):
        # the TOCTOU re-check now runs BEFORE _open_grid_row_menu, not
        # between an initial open and the click, so the menu is only ever
        # opened once per delete_master call — see delete_master's own
        # docstring for why opening it before the re-check (the original
        # #805 fix's ordering) was wasted work every single call.
        self.assertEqual(len(scroll_calls), 1)

    def test_virtual_scroll_runs_before_scroll_into_view(self):
        # issue #791: _scroll_grid_to_row must run BEFORE
        # scroll_into_view_if_needed(), since it's the one that can
        # actually make a row outside the initial render window exist in
        # the DOM in the first place -- scroll_into_view_if_needed() alone
        # cannot.
        state = {"rows": [self._row("DRAFT")]}
        call_order = []

        def _remove():
            state["rows"] = []

        trigger_selector = browser_masters._GRID_ROW_ACTIONS_TRIGGER_SELECTOR
        row_handle = _FakeLocatorHandle(
            sub_locators={trigger_selector: _FakeLocatorHandle()}
        )
        row_handle.scroll_into_view_if_needed = lambda timeout=None: call_order.append(
            "scroll_into_view"
        )
        page = FakePage(
            locators={
                self.ROW_SELECTOR: _FakeLocator([row_handle]),
                browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._GRID_ROW_DELETE_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_remove)]
                ),
            }
        )

        def _virtual_scroll(arg):
            call_order.append("virtual_scroll")
            return True

        page._evaluate_side_effect = _virtual_scroll

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": list(state["rows"]),
        ):
            browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(call_order, ["virtual_scroll", "scroll_into_view"])

    def test_virtual_scroll_failure_does_not_abort_delete(self):
        # _scroll_grid_to_row swallows its own PlaywrightError (mirrors
        # scroll_into_view_if_needed's existing best-effort contract) --
        # a row genuinely unreachable must still fall through to the
        # existing trigger-click retry loop, not raise here.
        state = {"rows": [self._row("DRAFT")]}

        def _remove():
            state["rows"] = []

        trigger_selector = browser_masters._GRID_ROW_ACTIONS_TRIGGER_SELECTOR
        row_handle = _FakeLocatorHandle(
            sub_locators={trigger_selector: _FakeLocatorHandle()}
        )
        page = FakePage(
            locators={
                self.ROW_SELECTOR: _FakeLocator([row_handle]),
                browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._GRID_ROW_DELETE_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_remove)]
                ),
            }
        )

        def _raise_evaluate(arg):
            raise browser_masters.PlaywrightError("evaluate failed")

        page._evaluate_side_effect = _raise_evaluate

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": list(state["rows"]),
        ):
            result = browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(result, {"CampaignId": self.CAMPAIGN_ID, "Deleted": True})

    def test_scroll_into_view_failure_does_not_abort_delete(self):
        # A row genuinely absent from the DOM (fully virtualized out) makes
        # scroll_into_view_if_needed() itself raise -- must not propagate
        # past the best-effort nudge; the existing trigger-click retry loop
        # is still the one place that decides success/failure.
        state = {"rows": [self._row("DRAFT")]}

        def _remove():
            state["rows"] = []

        trigger_selector = browser_masters._GRID_ROW_ACTIONS_TRIGGER_SELECTOR
        row_handle = _FakeLocatorHandle(
            sub_locators={trigger_selector: _FakeLocatorHandle()}
        )

        def _raise_scroll(timeout=None):
            raise PlaywrightError("element detached")

        row_handle.scroll_into_view_if_needed = _raise_scroll
        page = FakePage(
            locators={
                self.ROW_SELECTOR: _FakeLocator([row_handle]),
                browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._GRID_ROW_DELETE_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_remove)]
                ),
            }
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": list(state["rows"]),
        ):
            result = browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(result, {"CampaignId": self.CAMPAIGN_ID, "Deleted": True})

    def test_raises_when_delete_item_not_found(self):
        page = self._page_with_row_menu(trigger=_FakeLocatorHandle())
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )
        # No DeleteCampaignAction locator registered.

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("Удалить", str(ctx.exception))

    def test_raises_when_campaign_still_present_after_click(self):
        # The click succeeds but the grid still reports the campaign -- must
        # not report success on the click alone (mirrors archive_master's
        # own "never trust the click" convention).
        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("still reports it present", str(ctx.exception))

    def test_toctou_aborts_without_clicking_when_status_changed_before_click(self):
        # issue #793 Finding 1: the up-front guard reads DRAFT once, but the
        # row-menu retry loop takes real time -- another session could move
        # the campaign off DRAFT before DeleteCampaignAction is clicked.
        # _find_master_row is called: once for the up-front guard, once for
        # the TOCTOU re-check right before the click. Flip status on the
        # second call.
        calls = {"n": 0}
        delete_clicked = []

        def _fetch(page, status="all"):
            calls["n"] += 1
            status_now = "DRAFT" if calls["n"] == 1 else "MODERATION"
            return [self._row(status_now)]

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(on_click=lambda: delete_clicked.append(1)),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("is now", str(ctx.exception))
        self.assertIn("MODERATION", str(ctx.exception))
        self.assertIn("Not clicking", str(ctx.exception))
        self.assertEqual(delete_clicked, [])

    def test_toctou_aborts_without_clicking_when_campaign_vanished_before_click(self):
        # Same TOCTOU window, but the row disappeared entirely (e.g. deleted
        # by another session) rather than merely changing status.
        calls = {"n": 0}
        delete_clicked = []

        def _fetch(page, status="all"):
            calls["n"] += 1
            if calls["n"] == 1:
                return [self._row("DRAFT")]
            return []

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(on_click=lambda: delete_clicked.append(1)),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("no longer", str(ctx.exception))
        self.assertEqual(delete_clicked, [])

    def test_toctou_recheck_runs_before_opening_menu_only_once(self):
        # issue #805/#807 round 2 (cycle-review-caught, teammate + Codex +
        # /review independently): the original #805 fix opened the row
        # menu, then ran the TOCTOU re-check (whose own fetch_masters_list
        # call unconditionally navigates via page.goto(GRID_URL) in
        # production, destroying the just-opened menu), then re-opened the
        # menu a second time. That wastes the first open on EVERY call
        # (not just a rare retry path) and reintroduces a delay between
        # the re-check and the click that the "immediately before"
        # guarantee is meant to close. The re-check now runs BEFORE
        # _open_grid_row_menu, so the menu is opened exactly once, right
        # before the click, with nothing able to navigate the page in
        # between.
        #
        # A DOM-click-count assertion can't distinguish "opened once, used
        # correctly" from "opened twice, first one wasted" here: this
        # fake's locators are static dicts with no real page.goto() side
        # effect. Assert on the call COUNT of _open_grid_row_menu itself,
        # and on fetch_masters_list's call ORDER relative to it.
        call_order = []
        delete_clicked = []
        state = {"rows": [self._row("DRAFT")]}

        def _fetch(page, status="all"):
            call_order.append("fetch")
            return list(state["rows"])

        def _remove():
            delete_clicked.append(1)
            state["rows"] = []

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(on_click=_remove),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        def _open_menu_spy(page, campaign_id):
            call_order.append("open_menu")
            return real_open_menu(page, campaign_id)

        real_open_menu = browser_masters._open_grid_row_menu

        with (
            patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch),
            patch.object(
                browser_masters, "_open_grid_row_menu", side_effect=_open_menu_spy
            ) as open_menu_spy,
        ):
            result = browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(result, {"CampaignId": self.CAMPAIGN_ID, "Deleted": True})
        self.assertEqual(delete_clicked, [1])
        # Opened exactly once -- not twice with the first one thrown away.
        self.assertEqual(open_menu_spy.call_count, 1)
        # fetch_masters_list calls: up-front guard, TOCTOU re-check, then
        # (after the click) the post-click verify poll -- BOTH before
        # open_menu, which itself comes right before the click.
        self.assertEqual(call_order, ["fetch", "fetch", "open_menu", "fetch"])

    def test_toctou_recheck_aborts_before_opening_menu_when_status_changed(self):
        # Companion to the above: when the re-check finds the campaign no
        # longer DRAFT, the menu must never be opened at all -- not opened
        # and immediately wasted, as the pre-#807-round-2 ordering did.
        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            status_now = "DRAFT" if calls["n"] == 1 else "MODERATION"
            return [self._row(status_now)]

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with (
            patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch),
            patch.object(browser_masters, "_open_grid_row_menu") as open_menu_mock,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("is now", str(ctx.exception))
        self.assertIn("MODERATION", str(ctx.exception))
        open_menu_mock.assert_not_called()

    def test_verify_loop_tolerates_transient_error_then_succeeds(self):
        # issue #793 Finding 2: a transient BrowserSessionError on the FIRST
        # poll after a successful, irreversible click must not propagate --
        # it must be treated as inconclusive and polling must continue.
        state = {"rows": [self._row("DRAFT")]}
        poll_calls = {"n": 0}

        def _remove():
            state["rows"] = []

        def _fetch(page, status="all"):
            poll_calls["n"] += 1
            # Call 1: up-front guard. Call 2: TOCTOU re-check. Call 3: first
            # verify poll -- raise here. Call 4+: verify polls succeed.
            if poll_calls["n"] == 3:
                raise BrowserSessionError("Campaigns grid API returned HTTP 500")
            return list(state["rows"])

        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(on_click=_remove),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            result = browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertEqual(result, {"CampaignId": self.CAMPAIGN_ID, "Deleted": True})
        self.assertGreaterEqual(poll_calls["n"], 4)

    def test_verify_loop_reports_click_already_landed_when_every_poll_errors(self):
        # issue #793 Finding 2: if every poll until the deadline errors, the
        # final message must say the click already landed, not just repeat
        # a generic "still present" (which would falsely suggest the click
        # itself may not have worked).
        page = self._page_with_row_menu(
            trigger=_FakeLocatorHandle(),
            delete_item=_FakeLocatorHandle(),
        )
        page._locators[browser_masters._GRID_ROW_ACTIONS_POPUP_SELECTOR] = _FakeLocator(
            [_FakeLocatorHandle()]
        )

        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            if calls["n"] <= 2:
                # up-front guard + TOCTOU re-check both see DRAFT.
                return [self._row("DRAFT")]
            raise BrowserSessionError("Campaigns grid API returned HTTP 500")

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.delete_master(page, self.CAMPAIGN_ID)

        self.assertIn("landed", str(ctx.exception))
        self.assertIn("HTTP 500", str(ctx.exception))


class TestMastersDeleteCommand(unittest.TestCase):
    """CLI wiring for `masters delete` (issue #782), including the
    confirmation gate Yandex's own UI does not provide (live-confirmed: no
    dialog appears before DeleteCampaignAction actually deletes)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_delete_registered(self):
        result = self.runner.invoke(cli, ["masters", "delete", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_delete_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "delete", "--help"])
        self.assertNotIn("--login", result.output)

    def test_delete_with_yes_skips_prompt_and_calls_delete_master(self):
        with (
            patch("direct_cli.browser.masters.delete_master") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 713337891, "Deleted": True}
            result = self.runner.invoke(
                cli, ["masters", "delete", "713337891", "--yes"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_delete.assert_called_once()

    def test_delete_without_yes_prompts_and_confirms(self):
        with (
            patch("direct_cli.browser.masters.delete_master") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch(
                "direct_cli.commands.masters._stdin_is_interactive",
                return_value=True,
            ),
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 713337891, "Deleted": True}
            result = self.runner.invoke(
                cli, ["masters", "delete", "713337891"], input="y\n"
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Permanently delete", result.output)
        mock_delete.assert_called_once()

    def test_delete_without_yes_declining_prompt_aborts(self):
        with (
            patch("direct_cli.browser.masters.delete_master") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch(
                "direct_cli.commands.masters._stdin_is_interactive",
                return_value=True,
            ),
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli, ["masters", "delete", "713337891"], input="n\n"
            )

        self.assertNotEqual(result.exit_code, 0)
        mock_delete.assert_not_called()

    def test_delete_without_yes_non_interactive_refuses(self):
        # No TTY to answer a prompt that would otherwise hang forever.
        with (
            patch("direct_cli.browser.masters.delete_master") as mock_delete,
            patch(
                "direct_cli.commands.masters._stdin_is_interactive",
                return_value=False,
            ),
        ):
            result = self.runner.invoke(cli, ["masters", "delete", "713337891"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--yes", result.output)
        mock_delete.assert_not_called()


class TestClickDraftTerminalButton(unittest.TestCase):
    """``_click_draft_terminal_button`` (issue #668): clicks exactly once,
    no time-based retry.

    Cycle-review PR #711 regression: an earlier version retried the click
    once, purely on elapsed time, if no redirect had happened yet by some
    threshold. Codex proved this structurally double-submits the
    no-rollback save/launch click — ANY threshold shorter than the full
    redirect-wait window is still reachable by a healthy click whose
    redirect simply lands a bit later than usual (shown live for both a
    4s and a 12s threshold). A time-only retry cannot tell "stuck" from
    "still in flight" without a positive failure signal this page doesn't
    expose, so the retry was removed entirely: click once, wait out the
    full timeout, fail loudly if Yandex never redirects.
    """

    def _edit_page_with_delayed_redirect(self, *, redirect_at_s, launch=False):
        """A DRAFT edit page whose terminal button redirects away from
        ``/edit/`` only once simulated wall-clock time reaches
        ``redirect_at_s`` — models a healthy click whose redirect simply
        hasn't landed yet, not a stuck one.
        """
        clock = {"now": 0.0}
        click_count = {"n": 0}

        def _on_click():
            click_count["n"] += 1

        testid = (
            browser_masters._DRAFT_LAUNCH_BUTTON_TESTID
            if launch
            else browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID
        )
        page = FakePage(
            locators={testid: _FakeLocator([_FakeLocatorHandle(on_click=_on_click)])}
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)

        def _wait_for_timeout(timeout):
            clock["now"] += timeout / 1000
            if clock["now"] >= redirect_at_s and "/edit/" in page.url:
                page.url = browser_masters.WIZARD_OVERVIEW_URL.format(
                    campaign_id=713231614
                )

        page.wait_for_timeout = _wait_for_timeout
        return page, click_count, clock

    def test_never_double_clicks_within_the_accepted_redirect_window(self):
        # Regression (cycle-review PR #711, Codex round 1 + round 2
        # findings): must click exactly once for ANY redirect delay inside
        # the full accepted window (_DRAFT_SAVE_REDIRECT_TIMEOUT_MS =
        # 20s) -- not just the ~5s this file documents as typical. Round 1
        # proved a 4s retry threshold fires on a 5s redirect; round 2
        # proved a 12s threshold fires on a 15s redirect. A time-based
        # retry threshold can never close this for every point in the
        # window, so there is no retry left to trigger.
        for redirect_at_s in (0.1, 5.0, 15.0, 19.0):
            with self.subTest(redirect_at_s=redirect_at_s):
                page, click_count, clock = self._edit_page_with_delayed_redirect(
                    redirect_at_s=redirect_at_s
                )
                with patch.object(_clock, "_clock", lambda clock=clock: clock["now"]):
                    browser_masters._click_draft_terminal_button(
                        page, 713231614, launch=False
                    )
                self.assertEqual(click_count["n"], 1)

    def test_raises_when_redirect_never_happens(self):
        # No positive failure signal exists on this page to retry against
        # -- a click that never redirects must fail loudly (issue #704
        # recon's hydration race now surfaces here instead of being
        # silently papered over by a second click).
        page, click_count, clock = self._edit_page_with_delayed_redirect(
            redirect_at_s=1_000_000.0
        )

        with patch.object(_clock, "_clock", lambda: clock["now"]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._click_draft_terminal_button(
                    page, 713231614, launch=False
                )

        self.assertEqual(click_count["n"], 1)
        self.assertIn("did not redirect", str(ctx.exception))

    def test_raises_specific_goal_error_when_target_actions_table_is_empty(self):
        # Issue #823: an empty "Целевые действия" table is a KNOWN, silent
        # cause of the click never redirecting (same widget/failure mode as
        # create_master's #777 finding) — the timeout must surface that
        # specific diagnosis, not the generic "may not have saved" message.
        page = _FakeTargetActionsPage(
            {},
            locators={
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713469085)

        clock = {"now": 0.0}

        def _wait_for_timeout(timeout):
            clock["now"] += timeout / 1000

        page.wait_for_timeout = _wait_for_timeout

        with patch.object(_clock, "_clock", lambda: clock["now"]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._click_draft_terminal_button(
                    page, 713469085, launch=True
                )

        self.assertIn("Целевые действия", str(ctx.exception))
        self.assertIn("conversion goal", str(ctx.exception))

    def test_generic_error_when_target_actions_table_has_rows(self):
        # A stuck redirect with goals PRESENT must keep the generic message
        # — the specific goal diagnosis only fires when the table is
        # genuinely empty, not for every timeout.
        page = _FakeTargetActionsPage(
            {159614149: {"name": "Регистрация", "price": "150"}},
            locators={
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713469085)

        clock = {"now": 0.0}

        def _wait_for_timeout(timeout):
            clock["now"] += timeout / 1000

        page.wait_for_timeout = _wait_for_timeout

        with patch.object(_clock, "_clock", lambda: clock["now"]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._click_draft_terminal_button(
                    page, 713469085, launch=True
                )

        self.assertIn("did not redirect", str(ctx.exception))
        self.assertNotIn("Целевые действия", str(ctx.exception))

    def test_returns_normally_when_redirect_lands_during_empty_table_diagnosis(self):
        # Cycle-review PR #826 (Codex, HIGH): the empty-table diagnosis itself
        # polls for up to _TARGET_ACTION_SETTLE_TIMEOUT_MS after the original
        # redirect deadline already elapsed — plenty of time for a merely-
        # slow (not stuck) redirect to land DURING the diagnosis. Raising the
        # goal-specific error in that case would report failure on an
        # actually-successful, no-rollback launch/save. The table reads
        # empty (the settle-poll's row count never moves off 0), but once
        # the redirect is observed the function must return normally instead
        # of raising.
        page = _FakeTargetActionsPage(
            {},
            locators={
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713469085)

        clock = {"now": 0.0}
        ticks = {"n": 0}

        def _wait_for_timeout(timeout):
            clock["now"] += timeout / 1000
            ticks["n"] += 1
            # Let the redirect-deadline loop time out normally (that part
            # ticks in 250ms steps — well under the settle poll's 400ms
            # ticks), then land the redirect partway through the settle
            # poll that follows, exactly like a merely-slow Yandex redirect
            # completing while this function is busy diagnosing.
            if ticks["n"] == 90:
                page.url = "https://direct.yandex.ru/wizard/campaigns/713469085"

        page.wait_for_timeout = _wait_for_timeout

        with patch.object(_clock, "_clock", lambda: clock["now"]):
            # Must NOT raise — the late redirect means the click actually
            # succeeded.
            browser_masters._click_draft_terminal_button(page, 713469085, launch=True)

    def test_returns_normally_when_redirect_lands_during_settle_wait_timeout(self):
        # Same late-redirect race, but hitting the *second* url re-check
        # (after a settle-wait timeout / non-empty table) rather than the
        # one inside the empty-table branch.
        page = _FakeTargetActionsPage(
            {159614149: {"name": "Регистрация", "price": "150"}},
            locators={
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713469085)

        clock = {"now": 0.0}
        ticks = {"n": 0}

        def _wait_for_timeout(timeout):
            clock["now"] += timeout / 1000
            ticks["n"] += 1
            if ticks["n"] == 90:
                page.url = "https://direct.yandex.ru/wizard/campaigns/713469085"

        page.wait_for_timeout = _wait_for_timeout

        with patch.object(_clock, "_clock", lambda: clock["now"]):
            browser_masters._click_draft_terminal_button(page, 713469085, launch=True)


class TestLaunchMaster(unittest.TestCase):
    """``launch_master`` (issue #704): publish a DRAFT via the edit page's
    launch button, then verify via the overview page's own status text —
    NOT the campaigns grid (issue #704 live recon: the grid's primaryStatus
    lagged the real DRAFT->MODERATION transition by 45+ seconds, while the
    overview page reflected it immediately — see launch_master's
    docstring). Contract otherwise mirrors ``archive_master``: idempotent
    no-op on a non-DRAFT campaign, never trusts the click alone.
    """

    def _row(self, status):
        return {
            "CampaignId": 713231614,
            "Name": "Мастер тестовый",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }

    def _draft_edit_page(self, *, on_click=None):
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        # _OVERVIEW_TITLE_SELECTOR (the marker launch_master's post-redirect
        # _goto_overview_page call polls for) is defaulted present by
        # FakePage itself -- see its own docstring note -- so it does not
        # need to be registered here.
        locators = {
            browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                [_FakeLocatorHandle()]
            ),
            edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
        }
        if on_click is not None:
            locators[browser_masters._DRAFT_LAUNCH_BUTTON_TESTID] = _FakeLocator(
                [_FakeLocatorHandle(on_click=on_click)]
            )
        page = FakePage(locators=locators)
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        return page

    def test_launches_and_verifies_via_overview_status_text(self):
        state = {"status_text": "Черновик"}

        def _flip():
            # Regression: the space between "на" and "модерации" is a
            # non-breaking space (U+00A0), not ASCII -- this cost a full
            # live-debugging pass (issue #704) when the constant used a
            # plain space and silently never matched real page text.
            state["status_text"] = "Кампания на\xa0модерации"
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = self._draft_edit_page(on_click=_flip)
        page.inner_text = lambda selector=None: state["status_text"]

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            result = browser_masters.launch_master(page, 713231614)

        self.assertEqual(result, {"CampaignId": 713231614, "Status": "MODERATION"})

    def test_idempotent_when_not_draft(self):
        page = FakePage(locators={})

        with (
            patch(
                "direct_cli.browser.masters.fetch_masters_list",
                return_value=[self._row("ACTIVE")],
            ),
            patch("direct_cli.browser.masters.print_warning") as warn,
        ):
            result = browser_masters.launch_master(page, 713231614)

        self.assertEqual(result, self._row("ACTIVE"))
        self.assertEqual(page.navigated_to, [])  # not clicking -> no navigation
        warn.assert_called_once()
        self.assertIn("not a DRAFT", warn.call_args[0][0])

    def test_raises_when_campaign_not_found_in_grid(self):
        page = FakePage(locators={})

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.launch_master(page, 713231614)

        self.assertIn("Could not find", str(ctx.exception))

    def test_raises_when_edit_page_is_not_draft_after_all(self):
        # The grid said DRAFT, but the edit page itself disagrees -- must not
        # click blind.
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()])}
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.launch_master(page, 713231614)

        self.assertIn("does not show the DRAFT", str(ctx.exception))

    def test_raises_when_status_never_becomes_moderation(self):
        # The click succeeds (and redirects away from /edit/, like the real
        # button) but the overview page keeps reporting the DRAFT text --
        # must not report success on the click alone.
        def _redirect_only():
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = self._draft_edit_page(on_click=_redirect_only)
        page.inner_text = lambda selector=None: "Черновик"

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._row("DRAFT")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.launch_master(page, 713231614)

        self.assertIn("did not report MODERATION", str(ctx.exception))


class TestMastersLaunchCommand(unittest.TestCase):
    """CLI wiring for `masters launch` (issue #704)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_launch_registered(self):
        result = self.runner.invoke(cli, ["masters", "launch", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_launch_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "launch", "--help"])
        self.assertNotIn("--login", result.output)

    def test_launch_calls_launch_master_per_id(self):
        with (
            patch("direct_cli.browser.masters.launch_master") as mock_launch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "launch", "1,2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_launch.call_count, 2)

    def test_launch_reports_earlier_successes_when_a_later_id_fails(self):
        def _fake_launch(page, campaign_id):
            if campaign_id == 3:
                raise BrowserSessionError("boom on id 3")
            return {"CampaignId": campaign_id, "Status": "MODERATION"}

        with (
            patch(
                "direct_cli.browser.masters.launch_master", side_effect=_fake_launch
            ) as mock_launch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(cli, ["masters", "launch", "1,2,3,4"])

        self.assertEqual(mock_launch.call_count, 4)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1", result.output)
        self.assertIn("MODERATION", result.output)
        self.assertIn("2", result.output)
        self.assertIn("boom on id 3", result.output)


class TestCopyMaster(unittest.TestCase):
    """``copy_master`` (issue #659): click Клонировать, then the clone form's

    terminal button, verified via both the post-click URL redirect and the
    campaigns grid — live-verified end to end (see module docstring, campaign
    107707079 -> draft copy 713231614).
    """

    SOURCE_ID = 42
    NEW_ID = 4200

    def _source_row(self, status="SUSPENDED"):
        return {
            "CampaignId": self.SOURCE_ID,
            "Name": "Мастер тестовый",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }

    def _new_row(self, status="DRAFT"):
        return {
            "CampaignId": self.NEW_ID,
            "Name": "Мастер тестовый — 2",
            "Status": status,
            "Type": "TEXT",
            "StartDate": "2026-08-02",
        }

    def _page(
        self,
        menu_trigger=None,
        clone_item=None,
        step2_ready=True,
        terminal_button_text=None,
        redirect_on_click=True,
        body_text="Кампания остановлена",
        page_class=FakePage,
    ):
        locators = {}
        if menu_trigger is not None:
            locators[browser_masters._MENU_TRIGGER_SELECTOR] = _FakeLocator(
                [menu_trigger]
            )
        if clone_item is not None:
            locators[browser_masters._CLONE_MENU_ITEM_SELECTOR] = _FakeLocator(
                [clone_item]
            )
        if step2_ready:
            locators[f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'] = (
                _FakeLocator([_FakeLocatorHandle()])
            )

        # The TOCTOU re-check (issue #797) reads the overview page's own
        # status text (_read_status_text), NOT the campaigns grid -- see
        # _reverify_status_or_raise's docstring. Defaults to SOURCE_ID's
        # default "STOPPED" grid status normalized to SUSPENDED's own
        # _read_status_text marker. page_class lets a test model the
        # overview status text changing between the up-front read and the
        # re-check's own read (both now come from the overview page).
        page = page_class(locators=locators, body_text=body_text)

        if terminal_button_text is not None:

            def _on_terminal_click():
                if redirect_on_click:
                    page.url = browser_masters.WIZARD_OVERVIEW_URL.format(
                        campaign_id=self.NEW_ID
                    )

            page._role_elements = [
                (
                    "button",
                    terminal_button_text,
                    _FakeTextLocatorHandle(visible=True, on_click=_on_terminal_click),
                )
            ]
        return page

    def test_copies_saves_as_draft_by_default_and_verifies(self):
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._source_row(),
                self._new_row(),
            ],
        ):
            result = browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertEqual(result["SourceCampaignId"], self.SOURCE_ID)
        self.assertEqual(result["CampaignId"], self.NEW_ID)
        self.assertEqual(result["Status"], "DRAFT")
        self.assertFalse(result["Launched"])
        self.assertEqual(
            page.navigated_to[0],
            browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=self.SOURCE_ID),
        )

    def test_toctou_recheck_does_not_false_abort_on_grid_overview_status_mismatch(
        self,
    ):
        # cycle-review finding (codex) on issue #797: the grid's
        # primaryStatus vocabulary is broader than and can lag
        # _read_status_text's four recognised values (module docstring
        # documents a 45+s DRAFT->MODERATION lag) -- comparing the up-front
        # grid-derived status against the re-check's overview-derived
        # status would false-abort a legitimate, unchanged clone whenever
        # the two sources disagree. Model that disagreement directly: the
        # grid reports a status _read_status_text can't recognise at all
        # (e.g. TEMPORARILY_PAUSED), while the overview page's own status
        # text is a perfectly valid, UNCHANGING "Кампания остановлена". The
        # re-check must compare against the overview's own up-front read
        # (also "Кампания остановлена"), not the grid's, so it must NOT
        # abort here.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
            body_text="Кампания остановлена",
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._source_row(status="TEMPORARILY_PAUSED"),
                self._new_row(),
            ],
        ):
            result = browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertEqual(result["CampaignId"], self.NEW_ID)

    def test_launch_true_clicks_launch_button(self):
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._LAUNCH_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=lambda page, status="all": [
                self._source_row(),
                self._new_row(status="ACTIVE"),
            ],
        ):
            result = browser_masters.copy_master(page, self.SOURCE_ID, launch=True)

        self.assertTrue(result["Launched"])
        self.assertEqual(result["Status"], "ACTIVE")

    def test_raises_when_source_campaign_not_found(self):
        page = self._page()

        with patch("direct_cli.browser.masters.fetch_masters_list", return_value=[]):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Could not find", str(ctx.exception))

    def test_raises_when_menu_trigger_not_found(self):
        page = self._page()  # no menu_trigger locator registered

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Could not open the campaign menu", str(ctx.exception))

    def test_raises_when_clone_menu_item_not_found(self):
        page = self._page(menu_trigger=_FakeLocatorHandle())

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("Клонировать", str(ctx.exception))

    def test_raises_when_no_redirect_after_terminal_click(self):
        # The terminal button is clicked but Yandex never redirects -- must
        # not report success on the click alone (not idempotent, so a false
        # success here is expensive to clean up).
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
            redirect_on_click=False,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("did not redirect", str(ctx.exception))

    def test_raises_when_new_campaign_never_appears_in_grid(self):
        # The redirect happens (page.url changes) but the grid never reports
        # the new campaign -- must not trust the URL alone either.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row()],  # never includes NEW_ID
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("did not appear in the campaigns grid", str(ctx.exception))

    def test_auth_error_during_post_click_verification_is_not_retried(self):
        # The clone/terminal-button click has ALREADY happened (irreversible,
        # not idempotent) by the time verification runs. If the saved session
        # is invalidated exactly in that window, fetch_masters_list's own
        # assert_authenticated raises BrowserAuthError -- which _with_session
        # (direct_cli/commands/masters.py) would otherwise catch and retry
        # the WHOLE copy_master call under a fresh session, re-clicking
        # Клонировать and the terminal button and creating a SECOND copy (or,
        # with --launch, a second live campaign spending real budget). This
        # must surface as a plain BrowserSessionError (not BrowserAuthError),
        # so _with_session's retry-on-BrowserAuthError does not fire, and the
        # error message must reference NEW_ID so the caller can check
        # manually instead of losing track of the clone that already exists.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        calls = []

        def _fetch_masters_list(page, status="all"):
            # Call 1: the up-front source-campaign lookup (the TOCTOU
            # re-check reads the overview page's own status text, not
            # fetch_masters_list -- see _reverify_status_or_raise's
            # docstring). Only the post-click lookup (finding new_id), call
            # 2+, hits the invalidated session.
            calls.append(status)
            if len(calls) <= 1:
                return [self._source_row()]
            raise BrowserAuthError("stale session, detected mid-body")

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=_fetch_masters_list,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertIn(str(self.NEW_ID), str(ctx.exception))

    def test_toctou_aborts_without_clicking_when_status_changed_before_click(self):
        # issue #797 Finding 1 (same TOCTOU shape as delete_master, issue
        # #793 Finding 1): the up-front status read (_wait_for_recognised_
        # status, right after _goto_overview_page -- cycle-review finding:
        # this must come from the SAME overview-page source the re-check
        # itself reads, not the up-front grid guard) happens once, but
        # opening the "⋮" menu (_click_and_wait_for_popup's own retry loop)
        # takes real time -- another session could change the campaign
        # before 'Клонировать' is clicked. Flip the page's body text to
        # ARCHIVED on the SECOND read (the re-check) to model that
        # concurrent change; the first read (up-front) still sees SUSPENDED.
        # copy_master has no single required status, so ANY change from
        # what was first read is what this re-check refuses to click
        # through.
        clone_clicked = []
        reads = {"n": 0}

        class _StatusChangesPage(FakePage):
            def inner_text(self, selector=None):
                reads["n"] += 1
                return (
                    "Кампания остановлена"
                    if reads["n"] == 1
                    else "Кампания в\xa0архиве"
                )

        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(on_click=lambda: clone_clicked.append(1)),
            page_class=_StatusChangesPage,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row(status="STOPPED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("is now", str(ctx.exception))
        self.assertIn("ARCHIVED", str(ctx.exception))
        self.assertIn("Not clicking", str(ctx.exception))
        self.assertEqual(clone_clicked, [])

    def test_toctou_aborts_without_clicking_when_campaign_vanished_before_click(self):
        # Same TOCTOU window, but the overview page no longer shows a
        # recognised status text (e.g. deleted or archived-and-purged by
        # another session) rather than merely showing a different one. The
        # up-front read still sees SUSPENDED; only the re-check's read goes
        # unrecognised.
        clone_clicked = []
        reads = {"n": 0}

        class _StatusVanishesPage(FakePage):
            def inner_text(self, selector=None):
                reads["n"] += 1
                return "Кампания остановлена" if reads["n"] == 1 else ""

        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(on_click=lambda: clone_clicked.append(1)),
            page_class=_StatusVanishesPage,
        )

        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            return_value=[self._source_row(status="STOPPED")],
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertIn("no longer shows a recognised status", str(ctx.exception))
        self.assertEqual(clone_clicked, [])

    def test_new_campaign_verify_loop_tolerates_transient_error_then_succeeds(self):
        # issue #797 Finding 2 (same tolerant-poll shape as delete_master,
        # issue #793 Finding 2, and the same fix this module's own
        # test_auth_error_during_post_click_verification_is_not_retried
        # already covers for BrowserAuthError specifically): a transient
        # plain BrowserSessionError on the FIRST post-click poll must not
        # propagate -- it must be treated as inconclusive and polling must
        # continue, unlike the pre-#797 code which only tolerated
        # BrowserAuthError here.
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            # Call 1: up-front guard (the TOCTOU re-check reads the
            # overview page's own status text, not fetch_masters_list).
            # Call 2: first post-click poll for NEW_ID -- raise here
            # (transient, NOT an auth error). Call 3+: succeeds.
            if calls["n"] == 2:
                raise BrowserSessionError("Campaigns grid API returned HTTP 500")
            return [self._source_row(), self._new_row()]

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            result = browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertEqual(result["CampaignId"], self.NEW_ID)
        self.assertGreaterEqual(calls["n"], 3)

    def test_new_campaign_verify_loop_reports_click_already_landed_when_every_poll_errors(  # noqa: E501
        self,
    ):
        # issue #797 Finding 2: if every post-click poll until the deadline
        # errors with a plain (non-auth) BrowserSessionError, the final
        # message must say the clone was likely created, not just repeat a
        # generic "did not appear in the campaigns grid" (which would
        # falsely suggest cloning itself may not have worked).
        page = self._page(
            menu_trigger=_FakeLocatorHandle(),
            clone_item=_FakeLocatorHandle(),
            terminal_button_text=browser_masters._SAVE_DRAFT_BUTTON_TEXT,
        )

        calls = {"n": 0}

        def _fetch(page, status="all"):
            calls["n"] += 1
            if calls["n"] <= 1:
                # up-front guard succeeds (the TOCTOU re-check reads the
                # overview page's own status text, not fetch_masters_list).
                return [self._source_row()]
            raise BrowserSessionError("Campaigns grid API returned HTTP 500")

        with patch("direct_cli.browser.masters.fetch_masters_list", side_effect=_fetch):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.copy_master(page, self.SOURCE_ID)

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertIn("likely created", str(ctx.exception))
        self.assertIn(str(self.NEW_ID), str(ctx.exception))
        self.assertIn("HTTP 500", str(ctx.exception))


class TestMastersCopyCommand(unittest.TestCase):
    """CLI wiring for `masters copy` (issue #659)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_copy_registered(self):
        result = self.runner.invoke(cli, ["masters", "copy", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_copy_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "copy", "--help"])
        self.assertNotIn("--login", result.output)

    def test_copy_defaults_to_draft(self):
        with (
            patch("direct_cli.browser.masters.copy_master") as mock_copy,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_copy.return_value = {"CampaignId": 99, "SourceCampaignId": 42}
            result = self.runner.invoke(cli, ["masters", "copy", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_copy.assert_called_once_with(mock_copy.call_args[0][0], 42, launch=False)

    def test_copy_launch_flag_passes_through(self):
        with (
            patch("direct_cli.browser.masters.copy_master") as mock_copy,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_copy.return_value = {"CampaignId": 99, "SourceCampaignId": 42}
            result = self.runner.invoke(cli, ["masters", "copy", "42", "--launch"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_copy.assert_called_once_with(mock_copy.call_args[0][0], 42, launch=True)


class TestSetWeeklyBudget(unittest.TestCase):
    """``_set_weekly_budget`` (issue #631, Этап A) — fills the budget input."""

    def test_fills_field_with_bare_integer(self):
        state = {}
        handle = _FakeLocatorHandle(
            text="80 000", on_fill=lambda v: state.__setitem__("value", v)
        )
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_weekly_budget(page, 95000)

        self.assertEqual(state["value"], "95000")

    def test_raises_browser_session_error_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_weekly_budget(page, 95000)


def _directs_helps_page(initial_checked, on_toggle=None):
    """Build a FakePage modeling the label/toggle-div pair (issue #724).

    The real toggle's underlying ``<input>`` is visually-hidden — Yandex's
    clickable element is a sibling ``.label``, and state is read from the
    toggle div's ``data-checked`` attribute, not the input. ``attrs`` is a
    single shared dict so the label's click handler and the div's
    ``get_attribute("data-checked")`` observe the same mutable state, mirroring
    how the real DOM's label click flips the sibling div's attribute.
    """
    attrs = {"data-checked": "true" if initial_checked else "false"}

    def _toggle():
        attrs["data-checked"] = "false" if attrs["data-checked"] == "true" else "true"
        if on_toggle is not None:
            on_toggle(attrs["data-checked"] == "true")

    label_handle = _FakeLocatorHandle(on_click=_toggle)
    div_handle = _FakeLocatorHandle(attrs=attrs)
    return FakePage(
        locators={
            browser_masters._DIRECT_HELPS_TOGGLE_LABEL_SELECTOR: _FakeLocator(
                [label_handle]
            ),
            browser_masters._DIRECT_HELPS_TOGGLE_DIV_SELECTOR: _FakeLocator(
                [div_handle]
            ),
        }
    )


class TestSetDirectsHelps(unittest.TestCase):
    """``_set_directs_helps`` (issue #631, Этап A; issue #724 label/data-checked
    rewrite) — click the visible label, idempotent no-op when already matching."""

    def test_enables_checkbox(self):
        state = {}
        page = _directs_helps_page(
            False, on_toggle=lambda v: state.__setitem__("checked", v)
        )

        browser_masters._set_directs_helps(page, True)

        self.assertTrue(state["checked"])

    def test_disables_checkbox(self):
        state = {}
        page = _directs_helps_page(
            True, on_toggle=lambda v: state.__setitem__("checked", v)
        )

        browser_masters._set_directs_helps(page, False)

        self.assertFalse(state["checked"])

    def test_is_noop_when_already_in_requested_state(self):
        state = {"toggled": False}
        page = _directs_helps_page(
            True, on_toggle=lambda v: state.__setitem__("toggled", True)
        )

        browser_masters._set_directs_helps(page, True)

        self.assertFalse(state["toggled"])

    def test_raises_browser_session_error_when_checkbox_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_directs_helps(page, True)

    def test_waits_out_hydration_before_deciding_to_click(self):
        # Regression (Codex, cycle-review round 1 of PR #731): a one-shot
        # _read_directs_helps() can catch data-checked mid-hydration —
        # absent/unset, read as None — while the toggle is ALREADY in the
        # requested state. Treating that None as "opposite of enabled" would
        # click the label and actually INVERT the real (already-correct)
        # state. Models data-checked missing for one tick, then settling to
        # "true" (already matches enabled=True) — must poll via
        # _read_until_matches and end up NOT clicking.
        ticks = {"count": 0}
        state = {"toggled": False}

        def _toggle():
            state["toggled"] = True

        def _get_attrs():
            if ticks["count"] < 1:
                return {}
            return {"data-checked": "true"}

        label_handle = _FakeLocatorHandle(on_click=_toggle)
        div_handle = _DynamicAttrsLocatorHandle(get_attrs=_get_attrs)

        class _DelayedHydrationPage(FakePage):
            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedHydrationPage(
            locators={
                browser_masters._DIRECT_HELPS_TOGGLE_LABEL_SELECTOR: _FakeLocator(
                    [label_handle]
                ),
                browser_masters._DIRECT_HELPS_TOGGLE_DIV_SELECTOR: _FakeLocator(
                    [div_handle]
                ),
            }
        )

        browser_masters._set_directs_helps(page, True)

        self.assertFalse(state["toggled"])
        self.assertGreaterEqual(ticks["count"], 1)

    def test_does_not_poll_out_the_full_timeout_on_a_real_change(self):
        # Regression (Codex, cycle-review round 2 of PR #731 — cloud
        # fallback, inline finding P2): a genuine state CHANGE has
        # _read_directs_helps stably reporting the opposite of `enabled`
        # until the label click below actually flips it — nothing makes it
        # converge to `enabled` on its own. Polling via _read_until_matches
        # against `enabled` (the round-1 fix's first attempt) would burn the
        # full _VERIFY_FIELD_READ_TIMEOUT_MS on every real toggle. The fix
        # polls only while the read is inconclusive (None); a settled,
        # stable, non-None read (even if it's the opposite of `enabled`)
        # must be accepted immediately — zero wait_for_timeout ticks.
        ticks = {"count": 0}
        state = {"toggled": False}
        page = _directs_helps_page(
            False, on_toggle=lambda v: state.__setitem__("toggled", True)
        )
        page.wait_for_timeout = lambda timeout: ticks.__setitem__(
            "count", ticks["count"] + 1
        )

        browser_masters._set_directs_helps(page, True)

        self.assertTrue(state["toggled"])
        self.assertEqual(ticks["count"], 0)

    def test_raises_instead_of_clicking_blind_when_state_never_resolves(self):
        # Regression (issue #736, Codex round-3 finding on PR #731): if
        # data-checked stays unreadable/absent (None) for the WHOLE poll
        # timeout — not just a transient hydration tick — _set_directs_helps
        # must never click the label with an unknown pre-click state, since
        # that click could invert an already-correct toggle and commit that
        # on a live Yandex account. It must raise BrowserSessionError and
        # leave the label untouched instead.
        state = {"toggled": False}

        def _toggle():
            state["toggled"] = True

        def _get_attrs():
            return {}

        label_handle = _FakeLocatorHandle(on_click=_toggle)
        div_handle = _DynamicAttrsLocatorHandle(get_attrs=_get_attrs)

        page = FakePage(
            locators={
                browser_masters._DIRECT_HELPS_TOGGLE_LABEL_SELECTOR: _FakeLocator(
                    [label_handle]
                ),
                browser_masters._DIRECT_HELPS_TOGGLE_DIV_SELECTOR: _FakeLocator(
                    [div_handle]
                ),
            }
        )

        # Keeps the test fast: _read_until_matches's timeout_ms default is
        # bound to _VERIFY_FIELD_READ_TIMEOUT_MS at function-definition time,
        # so patching the module constant alone would not shrink it — jumping
        # the clock it polls against past that budget on every read does.
        # (Overrides the module-wide fake clock of issue #767, which advances
        # only per `wait_for_timeout` tick; this test wants the deadline blown
        # on the FIRST read, so it drives the hook itself.)
        fake_now = {"value": 0.0}

        def _fake_monotonic():
            fake_now["value"] += browser_masters._VERIFY_FIELD_READ_TIMEOUT_MS
            return fake_now["value"]

        with patch.object(_clock, "_clock", _fake_monotonic):
            with self.assertRaises(BrowserSessionError):
                browser_masters._set_directs_helps(page, True)

        self.assertFalse(state["toggled"])


class TestSetPromotionGoal(unittest.TestCase):
    """``_set_promotion_goal`` (issue #631, Этап A) — open dropdown, click, verify.

    Options are modeled via ``locators`` keyed by the option row's
    data-testid selector, NOT ``role_elements`` (issue #696
    re-investigation, 2026-08-04): Yandex now appends a description
    sentence and, for some rows, a "Рекомендуем" badge to each option's
    accessible name, which broke the previous
    ``get_by_role("option", name=label, exact=True)`` match entirely on
    live pages. ``_set_promotion_goal`` now matches by the option's stable
    data-testid (``PROMOTION_GOAL_INTERNAL_VALUES``) instead.

    The trigger's ``inner_text()`` is modeled as TWO lines (static section
    label, then the current selection) — confirmed live 2026-08-01 (see
    ``tests/fixtures/masters_wizard_edit_stage_a.html``). A single-line fake
    would not have caught the regression where the verification code
    compared the WHOLE two-line ``inner_text()`` for exact equality against
    the bare one-line label (always false) instead of just its last line.
    """

    _TRIGGER_LABEL = "Цель продвижения"

    def _option_testid(self, goal):
        return browser_masters._PROMOTION_GOAL_OPTION_TESTID_TEMPLATE.format(
            value=browser_masters.PROMOTION_GOAL_INTERNAL_VALUES[goal]
        )

    def _page_for_goal_selection(
        self, goal, selected_line_after_click, *, visible=True
    ):
        state = {"selected_line": "Максимум целевых действий"}

        def _select():
            state["selected_line"] = selected_line_after_click

        trigger = _FakeLocatorHandle(text=self._TRIGGER_LABEL)
        # inner_text() must reflect the mutable state set by clicking the
        # option — two lines, matching the live-confirmed shape.
        trigger.inner_text = lambda: f"{self._TRIGGER_LABEL}\n{state['selected_line']}"

        option = _FakeLocatorHandle(visible=visible, on_click=_select)
        option_selector = f'[data-testid="{self._option_testid(goal)}"]'

        return FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger]),
                option_selector: _FakeLocator([option]),
            },
        )

    def test_selects_option_and_verifies(self):
        page = self._page_for_goal_selection("max-clicks", "Максимум переходов")

        browser_masters._set_promotion_goal(page, "max-clicks")

        trigger = page.locator(browser_masters._PROMOTION_GOAL_BUTTON_XPATH).first
        self.assertEqual(trigger.inner_text(), "Цель продвижения\nМаксимум переходов")

    def test_raises_on_unknown_goal_key(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters._set_promotion_goal(page, "not-a-real-goal")

    def test_raises_when_dropdown_trigger_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")

    def test_raises_when_option_not_found(self):
        trigger = _FakeLocatorHandle(text="Цель продвижения")
        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger])
            },
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")

    def test_raises_when_option_not_visible(self):
        page = self._page_for_goal_selection(
            "max-clicks", "Максимум переходов", visible=False
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_promotion_goal(page, "max-clicks")

    def test_does_not_raise_when_option_is_still_hydrating(self):
        # Regression test (issue #696 cycle-review finding): the option row
        # can still be hydrating/animating in immediately after
        # trigger.click() opens the dropdown — is_visible() reports False on
        # the very first check even though the element becomes visible and
        # clickable moments later, exactly the class of race _set_goal_price/
        # _read_goal_price were fixed for elsewhere in this same module. A
        # one-shot is_visible() gate (with no actionability wait) treats this
        # transient state as "option not found" and raises — even though
        # click() itself would have waited for and hit the element fine.
        state = {"selected_line": "Максимум целевых действий", "visible_checks": 0}

        def _select():
            state["selected_line"] = "Максимум переходов"

        trigger = _FakeLocatorHandle(text=self._TRIGGER_LABEL)
        trigger.inner_text = lambda: f"{self._TRIGGER_LABEL}\n{state['selected_line']}"

        option = _FakeLocatorHandle(visible=True, on_click=_select)

        def _is_visible_after_hydration():
            # False on the first check (still hydrating), True from then on —
            # models the option becoming visible moments after the dropdown
            # opens. click() (unlike a one-shot is_visible() gate) would wait
            # for and hit this element without issue.
            state["visible_checks"] += 1
            return state["visible_checks"] > 1

        option.is_visible = _is_visible_after_hydration
        option_selector = f'[data-testid="{self._option_testid("max-clicks")}"]'

        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger]),
                option_selector: _FakeLocator([option]),
            },
        )

        browser_masters._set_promotion_goal(page, "max-clicks")

        self.assertEqual(state["selected_line"], "Максимум переходов")

    def test_raises_when_click_does_not_change_trigger_text(self):
        # Option is clicked but the trigger's selected line never changes.
        page = self._page_for_goal_selection(
            "max-clicks",
            "Максимум целевых действий",  # unchanged
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_promotion_goal(page, "max-clicks")
        self.assertIn("does not show it", str(ctx.exception))

    def test_retries_open_when_first_trigger_click_is_swallowed(self):
        # Regression test for issue #840, reproduced live on campaign
        # 74736436: the trigger matches (count=1) while React has not yet
        # attached its click handler, so Playwright's actionability check
        # passes, the click lands on the un-hydrated node and NOTHING
        # happens — instrumenting a real failing run showed the trigger
        # still reporting aria-expanded=None with an empty inner_text() at
        # click time, hydrating to 'false' 2s later. Because the option
        # rows only exist in the DOM while the dropdown is open, the old
        # single-click code then reported "Could not find the ... option
        # ... Yandex may have changed the page's markup" — a misdiagnosis,
        # since the markup was verified byte-identical. The open must
        # therefore be retried (via _click_and_wait_for_popup) rather than
        # trusted once.
        state = {"selected_line": "Максимум переходов", "trigger_clicks": 0}

        def _select():
            state["selected_line"] = "Максимум целевых действий"

        option = _FakeLocatorHandle(visible=False, on_click=_select)
        option_selector = f'[data-testid="{self._option_testid("max-conversions")}"]'

        def _on_trigger_click():
            # The FIRST click is swallowed by the hydration race and leaves
            # the listbox unmounted; only a later one actually opens it.
            state["trigger_clicks"] += 1
            if state["trigger_clicks"] > 1:
                option._visible = True

        trigger = _FakeLocatorHandle(
            text=self._TRIGGER_LABEL, on_click=_on_trigger_click
        )
        trigger.inner_text = lambda: f"{self._TRIGGER_LABEL}\n{state['selected_line']}"

        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger]),
                option_selector: _FakeLocator([option]),
            },
        )

        browser_masters._set_promotion_goal(page, "max-conversions")

        self.assertGreater(state["trigger_clicks"], 1)
        self.assertEqual(state["selected_line"], "Максимум целевых действий")


class TestReadSaveValidationErrors(unittest.TestCase):
    """``_read_save_validation_errors`` (issue #840).

    Yandex's client-side validation can refuse a save outright — confirmed
    live on campaign 74736436, where ``--promotion-goal max-conversions``
    never reaches the server because the campaign has no Metrika goals.
    Before this the operator only saw "it did not save"; the reason is now
    quoted back.
    """

    def test_reads_and_normalises_messages(self):
        goal_required_raw = (
            "Добавьте хотя\xa0бы одну цель для сайта,\n"
            "чтобы создать и\xa0запустить кампанию."
        )
        goal_required = (
            "Добавьте хотя бы одну цель для сайта, "
            "чтобы создать и запустить кампанию."
        )
        page = FakePage()
        page.eval_on_selector_all = lambda selector, script: [
            # NBSP + newlines, exactly as the live page renders them.
            "Вы\xa0добавили 200 ключевых фраз\xa0— это пока максимум",
            goal_required_raw,
        ]

        self.assertEqual(
            browser_masters._read_save_validation_errors(page),
            [
                "Вы добавили 200 ключевых фраз — это пока максимум",
                goal_required,
            ],
        )

    def test_deduplicates_and_caps(self):
        page = FakePage()
        page.eval_on_selector_all = lambda selector, script: ["же самое"] * 3 + [
            f"ошибка {i}" for i in range(10)
        ]

        result = browser_masters._read_save_validation_errors(page)

        self.assertEqual(result[0], "же самое")
        self.assertEqual(len(result), browser_masters._SAVE_VALIDATION_ERROR_LIMIT)

    def test_returns_empty_on_read_failure(self):
        # Best-effort by design: this only enriches an error that is already
        # being raised, so a selector miss must never mask the real mismatch.
        page = FakePage()

        def _raise(selector, script):
            raise PlaywrightError("no such selector")

        page.eval_on_selector_all = _raise

        self.assertEqual(browser_masters._read_save_validation_errors(page), [])


class TestSetGoalPrice(unittest.TestCase):
    """``_set_goal_price``/``_read_goal_price`` (issue #696).

    ``CampaignTargetSelect.PriceInput`` only exists on the page when the
    campaign's promotion goal is 'max-clicks' (confirmed live, see module
    docstring above ``_GOAL_PRICE_INPUT_TESTID``) — so the field-missing
    case (goal is 'max-conversions', or the strategy isn't AVG_PRICE) is
    modeled the same way as every other optional-field helper in this
    module: an empty/invisible ``_FakeLocator``, not a special code path.
    """

    def _page_with_price_field(self, *, visible=True, initial_value=""):
        state = {"value": initial_value}
        field = _FakeLocatorHandle(visible=visible)
        field.fill = lambda value: state.__setitem__("value", value)
        field.input_value = lambda: state["value"]
        page = FakePage(
            locators={browser_masters._GOAL_PRICE_INPUT_TESTID: _FakeLocator([field])},
        )
        return page, state

    def test_fills_price_field(self):
        page, state = self._page_with_price_field()

        browser_masters._set_goal_price(page, 500)

        self.assertEqual(state["value"], "500")

    def test_fills_non_integer_price_as_is(self):
        page, state = self._page_with_price_field()

        browser_masters._set_goal_price(page, 12.5)

        self.assertEqual(state["value"], "12.5")

    def test_raises_when_field_not_present(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_goal_price(page, 500)
        self.assertIn("max-clicks", str(ctx.exception))

    def test_raises_when_field_click_fails(self):
        # click() (not a one-shot is_visible() snapshot) is what locates
        # the field before filling — see _set_goal_price's docstring for
        # why (the section can still be hydrating when this runs). Modeled
        # via raises=True, the same "element not found/detached" fake
        # every other click()-based helper in this module uses.
        field = _FakeLocatorHandle(raises=True)
        page = FakePage(
            locators={browser_masters._GOAL_PRICE_INPUT_TESTID: _FakeLocator([field])},
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_goal_price(page, 500)

    def test_reads_current_value(self):
        page, _ = self._page_with_price_field(initial_value="500")

        self.assertEqual(browser_masters._read_goal_price(page), "500")

    def test_read_returns_none_when_field_not_visible(self):
        page, _ = self._page_with_price_field(visible=False, initial_value="500")

        self.assertIsNone(browser_masters._read_goal_price(page))

    def test_read_returns_none_when_field_missing(self):
        page = FakePage(locators={})

        self.assertIsNone(browser_masters._read_goal_price(page))


class TestGoalPriceMatches(unittest.TestCase):
    """``_goal_price_matches`` — numeric comparison tolerant of Yandex's
    own comma-decimal / whitespace formatting on read-back."""

    def test_matches_identical_string(self):
        self.assertTrue(browser_masters._goal_price_matches(500, "500"))

    def test_matches_comma_decimal(self):
        self.assertTrue(browser_masters._goal_price_matches(12.5, "12,5"))

    def test_matches_with_nbsp_thousands_separator(self):
        self.assertTrue(browser_masters._goal_price_matches(1500, "1\xa0500"))

    def test_does_not_match_different_value(self):
        self.assertFalse(browser_masters._goal_price_matches(500, "600"))

    def test_does_not_match_none(self):
        self.assertFalse(browser_masters._goal_price_matches(500, None))

    def test_does_not_match_unparseable_value(self):
        self.assertFalse(browser_masters._goal_price_matches(500, "not-a-number"))


class _FakeTargetActionsPage(FakePage):
    """Models the "Целевые действия" table (issue #707).

    ``rows``: ``{goal_id: {"name": str, "price": str}}`` — one existing row
    per key. Mirrors ``_FakeImagesPage``'s "one shared dict both the reader
    and any mutation act on" shape, but keyed by Yandex Metrika goal id
    rather than a positional list (there is no fixed slot count here
    either, same reasoning as images).
    """

    def __init__(self, rows, *, section_present=True, **kwargs):
        super().__init__(**kwargs)
        self.rows = dict(rows)
        self.section_present = section_present

    def locator(self, selector):
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        if selector == edit_form_ready_selector:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._TARGET_ACTIONS_SECTION_TESTID:
            return _FakeLocator([_FakeLocatorHandle()] if self.section_present else [])
        row_prefix = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        if selector == row_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(attrs={"data-testid": self._row_testid(gid)})
                    for gid in self.rows
                ]
            )
        for goal_id, row in self.rows.items():
            name_selector = (
                f'[data-testid="{self._row_testid(goal_id)}"] ' '[data-testid="Text"]'
            )
            if selector == name_selector:
                return _FakeLocator([_FakeLocatorHandle(text=row["name"])])
            price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
                category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
            )
            if selector == f'[data-testid="{price_testid}"]':
                return _FakeLocator([_FakeLocatorHandle(text=row["price"])])
        return super().locator(selector)

    def _row_testid(self, goal_id):
        return browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )


class TestReadTargetActions(unittest.TestCase):
    """``_read_target_actions`` (issue #707)."""

    def test_reads_one_row(self):
        page = _FakeTargetActionsPage(
            {159614149: {"name": "Регистрация", "price": "150"}}
        )

        self.assertEqual(
            browser_masters._read_target_actions(page),
            [{"GoalId": 159614149, "Name": "Регистрация", "Price": 150.0}],
        )

    def test_reads_multiple_rows(self):
        page = _FakeTargetActionsPage(
            {
                159614149: {"name": "Регистрация", "price": "150"},
                281285474: {"name": "Заказ", "price": "500"},
            }
        )

        results = browser_masters._read_target_actions(page)

        self.assertEqual(len(results), 2)
        self.assertEqual({r["GoalId"] for r in results}, {159614149, 281285474})

    def test_row_with_no_price_yet_reads_none(self):
        page = _FakeTargetActionsPage({159614149: {"name": "Регистрация", "price": ""}})

        self.assertEqual(
            browser_masters._read_target_actions(page),
            [{"GoalId": 159614149, "Name": "Регистрация", "Price": None}],
        )

    def test_empty_table_is_not_an_error(self):
        page = _FakeTargetActionsPage({})

        self.assertEqual(browser_masters._read_target_actions(page), [])

    def test_section_absent_returns_empty_list(self):
        # e.g. promotion goal is 'max-clicks', not 'max-conversions' — the
        # table doesn't exist on the page at all, same "absent, not an
        # error" convention as _read_goal_price under the opposite goal.
        page = _FakeTargetActionsPage(
            {159614149: {"name": "Регистрация", "price": "150"}},
            section_present=False,
        )

        self.assertEqual(browser_masters._read_target_actions(page), [])


class TestParseTargetActionPrice(unittest.TestCase):
    """``_parse_target_action_price`` — same tolerant numeric parsing as
    ``_goal_price_matches``, but returning the parsed value (or ``None``)
    rather than a boolean match."""

    def test_parses_plain_integer_string(self):
        self.assertEqual(browser_masters._parse_target_action_price("150"), 150.0)

    def test_parses_comma_decimal(self):
        self.assertEqual(browser_masters._parse_target_action_price("12,5"), 12.5)

    def test_parses_nbsp_thousands_separator(self):
        self.assertEqual(browser_masters._parse_target_action_price("1\xa0500"), 1500.0)

    def test_empty_string_is_none_not_zero(self):
        self.assertIsNone(browser_masters._parse_target_action_price(""))

    def test_whitespace_only_is_none(self):
        self.assertIsNone(browser_masters._parse_target_action_price("   "))

    def test_unparseable_value_is_none(self):
        self.assertIsNone(browser_masters._parse_target_action_price("not-a-number"))


class TestTargetActionPriceMatches(unittest.TestCase):
    """``_target_action_price_matches`` — mirrors ``_goal_price_matches``,
    but compares already-parsed floats (the caller parses via
    ``_parse_target_action_price`` first)."""

    def test_matches_identical_value(self):
        self.assertTrue(browser_masters._target_action_price_matches(150.0, 150.0))

    def test_does_not_match_different_value(self):
        self.assertFalse(browser_masters._target_action_price_matches(150.0, 200.0))

    def test_does_not_match_none(self):
        self.assertFalse(browser_masters._target_action_price_matches(150.0, None))


class TestSetTargetActionPrice(unittest.TestCase):
    """``_set_target_action_price`` (issue #707)."""

    def test_fills_existing_row(self):
        state = {"value": ""}
        field = _FakeLocatorHandle()
        field.fill = lambda value: state.__setitem__("value", value)
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        page = FakePage(
            locators={f'[data-testid="{price_testid}"]': _FakeLocator([field])}
        )

        browser_masters._set_target_action_price(page, 159614149, 200)

        self.assertEqual(state["value"], "200")

    def test_closes_leftover_search_popup_after_filling(self):
        # issue #796: clicking the price field leaves a separate search
        # combobox open, which silently blocks the create/save page's
        # terminal click. This must be closed before returning.
        field = _FakeLocatorHandle()
        field.fill = lambda value: None
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        heading_clicks = []
        heading = _FakeLocatorHandle(on_click=lambda: heading_clicks.append(1))
        page = FakePage(
            locators={f'[data-testid="{price_testid}"]': _FakeLocator([field])},
            text_buttons={
                browser_masters._TARGET_ACTIONS_HEADING_TEXT: _FakeGetByTextLocator(
                    [heading]
                )
            },
        )

        browser_masters._set_target_action_price(page, 159614149, 200)

        self.assertEqual(heading_clicks, [1])

    def test_missing_heading_does_not_raise(self):
        # _close_target_actions_search_popup is best-effort (issue #796) --
        # a page/fixture with no matching heading (e.g. Yandex changed the
        # markup, or a test that doesn't care about this) must not turn
        # _set_target_action_price itself into a failure.
        field = _FakeLocatorHandle()
        field.fill = lambda value: None
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        page = FakePage(
            locators={f'[data-testid="{price_testid}"]': _FakeLocator([field])}
        )

        browser_masters._set_target_action_price(page, 159614149, 200)  # must not raise

    def test_skips_click_when_heading_text_matches_more_than_once(self):
        # cycle-review of #796: the heading-text match is page-wide, not
        # scoped to the "Целевые действия" section's own container, on the
        # empirical (live-recon, not structural) assumption that it's the
        # ONLY exact match on the page. If that assumption ever breaks
        # (e.g. a second nav item/breadcrumb/tooltip with the same exact
        # text), .first would click an unverified — possibly interactive —
        # element instead of the section heading, and a successful click
        # on the wrong element is not a PlaywrightError, so
        # contextlib.suppress would not catch it. Must skip the click
        # outright on ANY count other than exactly 1, not guess.
        field = _FakeLocatorHandle()
        field.fill = lambda value: None
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        heading_clicks = []
        heading_a = _FakeLocatorHandle(on_click=lambda: heading_clicks.append("a"))
        heading_b = _FakeLocatorHandle(on_click=lambda: heading_clicks.append("b"))
        page = FakePage(
            locators={f'[data-testid="{price_testid}"]': _FakeLocator([field])},
            text_buttons={
                browser_masters._TARGET_ACTIONS_HEADING_TEXT: _FakeGetByTextLocator(
                    [heading_a, heading_b]
                )
            },
        )

        browser_masters._set_target_action_price(page, 159614149, 200)  # must not raise

        self.assertEqual(heading_clicks, [])

    def test_raises_when_row_not_present(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_target_action_price(page, 159614149, 200)
        self.assertIn("159614149", str(ctx.exception))
        self.assertIn("max-conversions", str(ctx.exception))

    def test_raises_when_field_click_fails(self):
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        page = FakePage(
            locators={
                f'[data-testid="{price_testid}"]': _FakeLocator(
                    [_FakeLocatorHandle(raises=True)]
                )
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_target_action_price(page, 159614149, 200)


class TestAddTargetAction(unittest.TestCase):
    """``_add_target_action`` (issue #717): open the "Добавить" popup, click
    the goal's option, then fill its price via ``_set_target_action_price``.
    """

    def _add_button_testid(self):
        testid = browser_masters._TARGET_ACTION_ADD_BUTTON_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY
        )
        return f'[data-testid="{testid}"]'

    def _option_testid(self, goal_id):
        testid = browser_masters._TARGET_ACTION_ADD_OPTION_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )
        return f'[data-testid="{testid}"]'

    def _price_testid(self, goal_id):
        testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )
        return f'[data-testid="{testid}"]'

    def test_clicks_add_button_then_option_then_fills_price(self):
        add_clicks = {"count": 0}
        add_button = _FakeLocatorHandle(
            on_click=lambda: add_clicks.__setitem__("count", add_clicks["count"] + 1)
        )
        option_clicked = {"clicked": False}
        option = _FakeLocatorHandle(
            on_click=lambda: option_clicked.__setitem__("clicked", True)
        )
        price_state = {"value": ""}
        price_field = _FakeLocatorHandle()
        price_field.fill = lambda value: price_state.__setitem__("value", value)

        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator([option]),
                self._price_testid(226158067): _FakeLocator([price_field]),
            }
        )

        browser_masters._add_target_action(page, 226158067, 77)

        self.assertEqual(add_clicks["count"], 1)
        self.assertTrue(option_clicked["clicked"])
        self.assertEqual(price_state["value"], "77")

    def test_retries_add_button_click_when_option_not_yet_visible(self):
        add_clicks = {"count": 0}

        def _on_add_click():
            add_clicks["count"] += 1

        add_button = _FakeLocatorHandle(on_click=_on_add_click)
        option = _FakeHydratingPopupHandle(
            ready_after_attempt=2, click_counter=add_clicks
        )
        price_field = _FakeLocatorHandle()
        price_field.fill = lambda value: None

        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator([option]),
                self._price_testid(226158067): _FakeLocator([price_field]),
            }
        )

        browser_masters._add_target_action(page, 226158067, 77)  # must not raise

        self.assertEqual(add_clicks["count"], 2)

    def test_raises_when_option_never_appears(self):
        add_button = _FakeLocatorHandle()
        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator(
                    [_FakeLocatorHandle(visible=False)]
                ),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_target_action(page, 226158067, 77)
        self.assertIn("226158067", str(ctx.exception))
        self.assertIn("max-conversions", str(ctx.exception))

    def _empty_add_button_testid(self):
        testid = browser_masters._TARGET_ACTION_ADD_BUTTON_EMPTY_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY
        )
        return f'[data-testid="{testid}"]'

    def test_bounds_the_click_on_a_trigger_that_is_not_on_the_page(self):
        """Every candidate trigger must be clicked with an EXPLICIT short
        ``timeout=`` (issue #779 review, found independently by both
        reviewers).

        ``_add_target_action`` tries both trigger testids because only one
        of them exists on any given render — so a click against the absent
        one is the EXPECTED path, not an edge case, and it runs on every
        single ``masters add``: the create page's table always starts
        empty, so the ``MiniGrid.AddButton`` variant tried first is never
        there for the first goal. With no explicit ``timeout=``, Playwright
        applies its 30s default action timeout (nothing in ``direct_cli/``
        calls ``set_default_timeout``), so that expected miss costs ~30s of
        auto-wait before falling through to the trigger that does exist —
        and the documented no-Metrika-counter failure case multiplies it by
        ``_TARGET_ACTION_ADD_OPTION_MAX_ATTEMPTS``.

        This is unobservable through the fake's timing: ``_FakeLocator.first``
        raises INSTANTLY for an absent selector, so the production cost
        never shows up as a slow test — the same structural blind spot
        ``_clock.py`` documents for poll deadlines. The argument passed to
        ``click()`` is therefore the only thing an offline test can assert
        on, which is why the fake records it.
        """
        # Create-page shape: only the empty-table trigger exists, so the
        # MiniGrid one tried first is absent.
        missing_trigger = _FakeLocatorHandle(raises=True)
        present_trigger = _FakeLocatorHandle()
        option = _FakeLocatorHandle()
        price_field = _FakeLocatorHandle()
        price_field.fill = lambda value: None

        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([missing_trigger]),
                self._empty_add_button_testid(): _FakeLocator([present_trigger]),
                self._option_testid(226158067): _FakeLocator([option]),
                self._price_testid(226158067): _FakeLocator([price_field]),
            }
        )

        browser_masters._add_target_action(page, 226158067, 77)

        # An empty table must go STRAIGHT to the trigger that exists there,
        # never paying for the MiniGrid variant at all.
        self.assertEqual(
            missing_trigger.click_timeouts,
            [],
            "an empty table clicked the populated-table trigger — the "
            "ordering that keeps `masters add`'s first goal from paying "
            "for a known-absent trigger has regressed",
        )
        self.assertTrue(present_trigger.click_timeouts)

        # And every trigger click, whichever is tried, stays bounded: the
        # ordering is a hint, so the OTHER trigger is still attempted
        # whenever the hint is wrong (a non-empty table on the create page,
        # a mid-hydration row count), and that attempt must not fall back
        # to Playwright's 30s default.
        for timeout in present_trigger.click_timeouts:
            self.assertIsNotNone(
                timeout,
                "click() was called with no explicit timeout, so Playwright's "
                "30s default applies to a trigger that may be absent",
            )
            self.assertLessEqual(
                timeout,
                browser_masters._POPUP_APPEAR_TIMEOUT_MS,
                "the trigger click's timeout must stay short — a present "
                "trigger is present immediately",
            )

    def test_bounds_the_click_when_the_row_count_hint_is_wrong(self):
        """The row-count hint only reorders the attempts — when it points at
        the wrong trigger the other is still tried, and THAT click is the
        one whose missing ``timeout=`` would cost Playwright's 30s default
        (issue #779 review).

        Modelled here as a populated table (so the hint picks
        ``MiniGrid.AddButton`` first) on which only the empty-table trigger
        actually renders — the create page's state mid-hydration, and the
        reason the ordering must stay a hint rather than a branch.
        """
        missing_trigger = _FakeLocatorHandle(raises=True)
        present_trigger = _FakeLocatorHandle()
        option = _FakeLocatorHandle()
        price_field = _FakeLocatorHandle()
        price_field.fill = lambda value: None

        row_testid = browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=111222333
        )
        prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )

        page = FakePage(
            locators={
                # A row already in the table — the hint therefore says
                # "populated", so MiniGrid.AddButton is tried first...
                prefix_selector: _FakeLocator(
                    [_FakeLocatorHandle(attrs={"data-testid": row_testid})]
                ),
                # ...but only the empty-table trigger is actually present.
                self._add_button_testid(): _FakeLocator([missing_trigger]),
                self._empty_add_button_testid(): _FakeLocator([present_trigger]),
                self._option_testid(226158067): _FakeLocator([option]),
                self._price_testid(226158067): _FakeLocator([price_field]),
            }
        )

        browser_masters._add_target_action(page, 226158067, 77)

        self.assertTrue(
            missing_trigger.click_timeouts,
            "the wrong-hint fall-through was never exercised — this test no "
            "longer covers the click it is meant to bound",
        )
        for timeout in missing_trigger.click_timeouts + present_trigger.click_timeouts:
            self.assertIsNotNone(
                timeout,
                "click() was called with no explicit timeout, so Playwright's "
                "30s default applies to a trigger known to be absent",
            )
            self.assertLessEqual(
                timeout,
                browser_masters._POPUP_APPEAR_TIMEOUT_MS,
                "the trigger click's timeout must stay short — a present "
                "trigger is present immediately",
            )

    def test_names_the_click_bound_when_no_trigger_ever_became_clickable(self):
        """Bounding the trigger click made "present but not actionable in
        time" a NEWLY reachable way into the exhausted-retry branch, and the
        error must say so (issue #779 review round 2).

        Before the bound, that branch was only reachable after Playwright's
        30s-per-click default, so attributing it to the Metrika counter /
        promotion goal / changed markup was fair. With a
        ``_POPUP_APPEAR_TIMEOUT_MS`` bound it is also reachable on a slow
        render — and this section is documented to hydrate for seconds
        (``_TARGET_ACTION_SETTLE_TIMEOUT_MS`` is 10s, and
        ``_wait_for_target_actions_settled`` exists precisely because its
        reads are unreliable for over a second). Playwright's ``TimeoutError``
        cannot tell "absent" from "present but not actionable", so the code
        cannot distinguish them — but the message can name both, instead of
        sending the user to audit counter setup that is fine.

        Issue #783 round 3: a positive ``count()`` read ALSO cannot prove
        the trigger is genuinely actionable — a disabled "Добавить" (e.g.
        the linked Metrika counter has no goals on offer) satisfies
        ``count() > 0`` too. So this branch must no longer claim a single
        cause; it must carry BOTH the hydration-race explanation and the
        counter/promotion-goal audit steps inline, since a dangling
        cross-reference to an unreachable branch left the counter-audit
        diagnosis unreachable from here entirely.
        """
        # Both triggers time out on every attempt — the shape a still-
        # hydrating page presents.
        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator(
                    [_FakeLocatorHandle(visible=False)]
                ),
                self._empty_add_button_testid(): _FakeLocator(
                    [_FakeLocatorHandle(visible=False)]
                ),
                self._option_testid(226158067): _FakeLocator([_FakeLocatorHandle()]),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_target_action(page, 226158067, 77)

        message = str(ctx.exception)
        self.assertIn("226158067", message)
        self.assertRegex(
            message,
            r"(?i)hydrat|clickable|did not become",
            "the exhausted-retry error never mentions that the 'Добавить' "
            "trigger may simply not have become clickable within the short "
            "bound — on a slow page this sends the user to audit a Metrika "
            "counter that is fine",
        )
        # The counter/promotion-goal audit steps must be reachable from
        # THIS message directly — no dangling "(see below)" cross-reference
        # to an unreachable branch (issue #783 finding 1).
        self.assertIn(
            "max-conversions",
            message,
            "a genuinely-stuck disabled trigger (count()>0 but never "
            "actionable) must still surface actionable counter/"
            "promotion-goal audit steps, not just a 're-run' suggestion "
            "pointing nowhere",
        )
        self.assertIn(
            "targetactions get",
            message,
            "the counter-audit command must be named inline, not left "
            "behind a dangling cross-reference",
        )

    def test_still_blames_the_counter_when_no_trigger_is_on_the_page_at_all(self):
        """The counter/promotion-goal diagnosis must survive for the case it
        was written for — a genuinely absent trigger (issue #779 review
        round 2). The new hydration branch above must not swallow it."""
        page = FakePage(
            locators={
                # Neither trigger registered at all — the section really
                # isn't there.
                self._option_testid(226158067): _FakeLocator([_FakeLocatorHandle()]),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_target_action(page, 226158067, 77)

        message = str(ctx.exception)
        self.assertIn("226158067", message)
        self.assertIn("max-conversions", message)
        self.assertIn("targetactions get", message)

    def test_raises_with_context_when_price_fill_fails_after_add(self):
        add_button = _FakeLocatorHandle()
        option = _FakeLocatorHandle()
        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator([option]),
                # No price input registered — _set_target_action_price raises.
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_target_action(page, 226158067, 77)
        self.assertIn("Added goal 226158067", str(ctx.exception))

    def test_does_not_hedge_the_counter_diagnosis_once_the_section_has_settled(
        self,
    ):
        """The counterpart to the two tests below: when the trigger WAS
        clicked (``ever_clicked=True``) and the "Целевые действия" row count
        has genuinely settled before the option-wait gives up, the exhausted
        popup read is a trustworthy observation — the message may keep its
        confident counter/promotion-goal diagnosis, with no hydration hedge
        appended (issue #783). Unregistered row-prefix locator here reads a
        stable 0 on every poll, so ``_wait_for_target_actions_settled``
        settles immediately."""
        add_button = _FakeLocatorHandle()
        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator(
                    [_FakeLocatorHandle(visible=False)]
                ),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_target_action(page, 226158067, 77)

        message = str(ctx.exception)
        self.assertIn("226158067", message)
        self.assertIn("max-conversions", message)
        self.assertNotIn(
            "had not finished settling",
            message,
            "a settled section still got the hydration hedge appended, so "
            "a confident-and-correct diagnosis now reads as uncertain",
        )

    def test_hedges_the_counter_diagnosis_when_clicked_but_section_never_settled(
        self,
    ):
        """Issue #783 finding 2: ``ever_clicked=True`` observes only that
        the option did not become visible WITHIN the bound
        (``_TARGET_ACTION_ADD_OPTION_MAX_ATTEMPTS *
        _POPUP_APPEAR_TIMEOUT_MS`` = 7500ms), which is shorter than the
        section's documented hydration bound
        (``_TARGET_ACTION_SETTLE_TIMEOUT_MS``). If the row count never even
        settles within that longer bound either, the popup may simply have
        been slow — the message must not assert the counter/promotion-goal
        cause alone; it must also carry the hydration-race possibility.

        Models a row-prefix locator whose ``.count()`` never repeats the
        same value twice in a row, so ``_wait_for_target_actions_settled``
        can never accumulate a streak and returns ``False``."""
        add_button = _FakeLocatorHandle()
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )

        class _NeverStableLocator:
            def __init__(self):
                self._n = 0

            def count(self):
                self._n += 1
                return self._n % 2

            def nth(self, i):
                # Only `_target_action_row_count`'s trigger-order hint reads
                # this (via `.count()` above, always 0 or 1); it is unrelated
                # to the settling gate under test, so a harmless empty
                # handle is enough to keep that unrelated call from raising.
                return _FakeLocatorHandle(attrs={"data-testid": ""})

        page = FakePage(
            locators={
                self._add_button_testid(): _FakeLocator([add_button]),
                self._option_testid(226158067): _FakeLocator(
                    [_FakeLocatorHandle(visible=False)]
                ),
            }
        )
        original_locator = page.locator
        never_stable = _NeverStableLocator()

        def _stub_locator(selector):
            if selector == row_prefix_selector:
                return never_stable
            return original_locator(selector)

        page.locator = _stub_locator

        with (
            patch.object(browser_masters, "_TARGET_ACTION_SETTLE_TIMEOUT_MS", 50),
            patch.object(browser_masters, "_TARGET_ACTION_STABLE_TICK_MS", 5),
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._add_target_action(page, 226158067, 77)

        message = str(ctx.exception)
        self.assertIn("226158067", message)
        # Still names the counter/promotion-goal audit steps — they remain
        # a real possibility, just no longer the SOLE claimed cause.
        self.assertIn("max-conversions", message)
        self.assertRegex(
            message,
            r"(?i)had not finished settling|slow to render",
            "an unsettled section after a clicked trigger must hedge the "
            "counter/promotion-goal diagnosis with the hydration-race "
            "possibility, not assert the counter cause alone",
        )


class TestRemoveTargetAction(unittest.TestCase):
    """``_remove_target_action`` (issue #717): click an existing row's close
    button."""

    def _close_testid(self, goal_id):
        testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
        )
        return f'[data-testid="{testid}"]'

    def test_clicks_close_button_of_existing_row(self):
        clicked = {"value": False}
        close_button = _FakeLocatorHandle(
            on_click=lambda: clicked.__setitem__("value", True)
        )
        page = FakePage(
            locators={self._close_testid(159614149): _FakeLocator([close_button])}
        )

        browser_masters._remove_target_action(page, 159614149)

        self.assertTrue(clicked["value"])

    def test_raises_when_row_not_present(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._remove_target_action(page, 159614149)
        self.assertIn("159614149", str(ctx.exception))
        self.assertIn("max-conversions", str(ctx.exception))

    def test_raises_when_close_click_fails(self):
        page = FakePage(
            locators={
                self._close_testid(159614149): _FakeLocator(
                    [_FakeLocatorHandle(raises=True)]
                )
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._remove_target_action(page, 159614149)


class TestFetchMasterTargetActions(unittest.TestCase):
    """``fetch_master_target_actions`` (issue #707) — ``masters targetactions
    get``'s browser layer, read-only."""

    def test_returns_target_actions_and_count(self):
        page = _FakeTargetActionsPage(
            {159614149: {"name": "Регистрация", "price": "150"}}
        )

        result = browser_masters.fetch_master_target_actions(page, 713234191)

        self.assertEqual(
            result,
            {
                "CampaignId": 713234191,
                "TargetActions": [
                    {"GoalId": 159614149, "Name": "Регистрация", "Price": 150.0}
                ],
                "Count": 1,
            },
        )

    def test_empty_table_is_a_valid_result(self):
        page = _FakeTargetActionsPage({})

        result = browser_masters.fetch_master_target_actions(page, 713234191)

        self.assertEqual(
            result, {"CampaignId": 713234191, "TargetActions": [], "Count": 0}
        )


class TestClickSave(unittest.TestCase):
    """``_click_save`` (issue #631, Этап A) — role-scoped, exact-name button match.

    ``_click_save`` uses ``get_by_role("button", name=_SAVE_BUTTON_TEXT,
    exact=True)`` (cycle-review fix: the previous ``get_by_text(exact=False)``
    risked matching an ancestor container instead of the button itself).
    """

    def test_does_not_click_a_decoy_whose_name_only_contains_the_button_text(self):
        # A decoy element whose accessible name merely CONTAINS
        # _SAVE_BUTTON_TEXT (e.g. an ancestor wrapper with extra text) must
        # NOT be treated as a match — exact=True requires exact equality.
        decoy_clicked = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    f"{browser_masters._SAVE_BUTTON_TEXT} и отмена",
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: decoy_clicked.append(True)
                    ),
                )
            ],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_save(page, 42, is_draft=False)
        self.assertEqual(decoy_clicked, [])

    def test_clicks_the_exact_match_button(self):
        clicks = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    browser_masters._SAVE_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: clicks.append(True)
                    ),
                )
            ],
        )

        browser_masters._click_save(page, 42, is_draft=False)

        self.assertEqual(clicks, [True])


class TestDraftEditPageSave(unittest.TestCase):
    """``_is_draft_edit_page``/``_click_save`` DRAFT path (issue #668).

    A DRAFT campaign's edit page has NO "Сохранить кампанию" button at all
    — only ``CampaignFormControls.saveDraft.button``/``.save.button``, the
    latter labelled "Запустить кампанию" (publishes) here, unlike the
    non-DRAFT page's "Сохранить кампанию" — live-confirmed against campaign
    713231614, see the module docstring's "DRAFT support" note.
    """

    def test_is_draft_edit_page_true_when_save_draft_button_present(self):
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            }
        )

        self.assertTrue(browser_masters._is_draft_edit_page(page))

    def test_is_draft_edit_page_false_when_absent(self):
        page = FakePage(locators={})

        self.assertFalse(browser_masters._is_draft_edit_page(page))

    def test_click_save_on_draft_clicks_save_draft_button_by_default(self):
        clicks = []
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            }
        )

        browser_masters._click_save(page, 713231614, is_draft=True)

        # The publish button must never be touched unless --launch was
        # explicitly requested.
        self.assertEqual(clicks, ["draft"])

    def test_click_save_on_draft_clicks_launch_button_when_requested(self):
        clicks = []
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            }
        )

        browser_masters._click_save(page, 713231614, is_draft=True, launch=True)

        self.assertEqual(clicks, ["launch"])

    def test_click_save_on_draft_raises_when_button_missing(self):
        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
                # _DRAFT_LAUNCH_BUTTON_TESTID deliberately absent.
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_save(page, 713231614, is_draft=True, launch=True)

    def test_click_save_prefers_non_draft_path_when_save_draft_button_absent(self):
        # Regression guard: a non-DRAFT page must keep using the plain
        # "Сохранить кампанию" role-scoped match, not the DRAFT testid path.
        clicks = []
        page = FakePage(
            locators={},
            role_elements=[
                (
                    "button",
                    browser_masters._SAVE_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: clicks.append(True)
                    ),
                )
            ],
        )

        browser_masters._click_save(page, 42, is_draft=False)

        self.assertEqual(clicks, [True])

    def test_click_save_uses_caller_supplied_is_draft_despite_dom_flap(self):
        # Regression for #726: is_draft=True must force the DRAFT branch
        # even when the DOM has no draft testid (simulates the marker
        # flapping away mid-hydration) and no "Сохранить кампанию" role
        # element either, since a real DRAFT page never has one.
        page = FakePage(locators={}, role_elements=[])

        # The failure must come from the DRAFT-terminal-button lookup
        # (proves it took the DRAFT branch), not the non-DRAFT "Сохранить
        # кампанию" lookup — which would raise a differently-worded error.
        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._click_save(page, 713231614, is_draft=True)
        self.assertIn(browser_masters._SAVE_DRAFT_BUTTON_TEXT, str(ctx.exception))

    def test_open_images_editor_reads_is_draft_before_returning(self):
        # Regression for #726 on the images path: _open_images_editor must
        # read is_draft right after _wait_for_edit_form (i.e. as part of
        # this call), NOT leave it for a caller to re-derive later after
        # _apply_image_operations has run — that would reopen the same
        # DOM-flap race _click_save's is_draft contract exists to close.
        page = _FakeImagesPage(
            ["a"],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )

        _content_ids, is_draft = browser_masters._open_images_editor(page, 42)

        self.assertTrue(is_draft)

    def test_open_images_editor_is_draft_false_when_marker_absent(self):
        page = _FakeImagesPage(["a"])

        _content_ids, is_draft = browser_masters._open_images_editor(page, 42)

        self.assertFalse(is_draft)

    def test_add_master_images_uses_is_draft_captured_before_apply_operations(self):
        # End-to-end regression for #726 on add_master_images: the DRAFT
        # branch must be taken based on the marker's state at
        # _open_images_editor time, not re-queried after
        # _apply_image_operations (uploads) has run and the marker may have
        # flapped away.
        draft_clicks = []

        def _on_draft_click():
            draft_clicks.append(True)
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)

        page = _FakeImagesPage(
            [],
            upload_ids=["new1"],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_draft_click)]
                )
            },
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=42)

        browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertEqual(draft_clicks, [True])


class TestWaitForDraftStatus(unittest.TestCase):
    """``_wait_for_draft_status`` (issue #726, cycle-review round 2 —
    Codex-caught gap): polls for either terminal save control instead of
    trusting a single point-in-time read taken right after
    ``_wait_for_edit_form``, which only guarantees the headline slot has
    rendered, not either terminal button.
    """

    def test_returns_true_once_draft_marker_mounts_after_a_delay(self):
        # The headline slot (what _wait_for_edit_form waits for) can render
        # before CampaignFormControls.saveDraft.button mounts — a straight
        # post-_wait_for_edit_form read would misclassify this DRAFT page
        # as non-DRAFT. The poll must wait it out instead.
        ticks = {"count": 0}

        class _DelayedDraftMarkerPage(FakePage):
            def locator(self, selector):
                if (
                    selector == browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID
                    and ticks["count"] < 2
                ):
                    return _FakeLocator([])
                return super().locator(selector)

            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedDraftMarkerPage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
            role_elements=[],
        )

        self.assertTrue(browser_masters._wait_for_draft_status(page, 713231614))
        self.assertEqual(ticks["count"], 2)

    def test_returns_false_once_non_draft_button_mounts_after_a_delay(self):
        ticks = {"count": 0}
        save_handle = _FakeTextLocatorHandle(visible=True)

        class _DelayedSaveButtonPage(FakePage):
            def get_by_role(self, role, name=None, exact=False):
                if ticks["count"] < 2:
                    return _FakeGetByTextLocator([])
                return super().get_by_role(role, name=name, exact=exact)

            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedSaveButtonPage(
            locators={},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        self.assertFalse(browser_masters._wait_for_draft_status(page, 42))
        self.assertEqual(ticks["count"], 2)

    def test_raises_if_neither_marker_ever_appears(self):
        page = FakePage(locators={}, role_elements=[])

        with patch.object(browser_masters, "_EDIT_FORM_READY_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_draft_status(page, 42)

        self.assertIn("42", str(ctx.exception))

    def test_names_archived_when_status_text_confirms_it(self):
        # cycle-review round 2 (issue #761 fixup, Codex-confirmed): a
        # dedicated pre-mutation Clear-button "is this campaign ARCHIVED"
        # guard was removed from update_master — it false-positived on any
        # unfocused OR empty landing-URL field on an otherwise ordinary
        # campaign, which would have blocked every masters update. An
        # ARCHIVED campaign already has no reliable escape from THIS
        # timeout (neither terminal marker below ever appears for one), so
        # the timeout message is upgraded with a status-text hint —
        # best-effort only, never a pre-mutation gate — instead of a
        # separate field-shaped pre-check.
        page = FakePage(
            locators={},
            role_elements=[],
            body_text="Кампания в\xa0архиве",
        )

        with patch.object(browser_masters, "_EDIT_FORM_READY_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_draft_status(page, 42)

        self.assertIn("42", str(ctx.exception))
        self.assertIn("ARCHIVED", str(ctx.exception))

    def test_does_not_name_archived_when_status_text_is_inconclusive(self):
        # Companion to the above: when the status-text hint can't confirm
        # ARCHIVED (absent/unreadable/some other status), the generic
        # "neither button appeared" message is unchanged — no false
        # ARCHIVED claim from an inconclusive read.
        page = FakePage(locators={}, role_elements=[], body_text="")

        with patch.object(browser_masters, "_EDIT_FORM_READY_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_draft_status(page, 42)

        self.assertIn("42", str(ctx.exception))
        self.assertNotIn("ARCHIVED", str(ctx.exception))


class TestUpdateMasterDraftSupport(unittest.TestCase):
    """``update_master`` end to end on a DRAFT campaign (issue #668)."""

    def _draft_page_with_headline_slot(self, *, saved_text_after_save):
        # _verify_saved re-navigates to the SAME edit URL after saving —
        # FakePage's goto() is a no-op that just records the URL, so the
        # same locator objects (and their mutable state) are seen both
        # before and after the "reload", exactly like the non-DRAFT
        # TestUpdateMaster fakes above.
        #
        # _click_draft_terminal_button (issue #668 live-recon fix) polls
        # page.url until it leaves "/edit/" before returning, mirroring the
        # click's real ~5s redirect to the overview page — on_click here
        # mutates page.url the same way TestCopyMaster's fakes do, so the
        # poll resolves immediately instead of burning the real timeout.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        draft_clicks = []
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )

        def _on_draft_click():
            draft_clicks.append(True)
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_draft_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        return page, slot, draft_clicks

    def test_updates_headline_on_draft_campaign_saving_as_draft(self):
        page, slot, draft_clicks = self._draft_page_with_headline_slot(
            saved_text_after_save="Новый заголовок"
        )

        result = browser_masters.update_master(
            page, 713231614, headlines={0: "Новый заголовок"}
        )

        self.assertEqual(slot.inner_text(), "Новый заголовок")
        self.assertEqual(len(draft_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 713231614, "Headlines": {0: "Новый заголовок"}}
        )

    def test_launch_true_on_draft_campaign_adds_launched_key(self):
        # Issue #704/#721: update --launch still needs to report it actually
        # published the DRAFT, not just that the field was saved — the
        # overview page's status text must explicitly read MODERATION (see
        # TestLaunchMaster._draft_edit_page's own on_click convention).
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )
        state = {"status_text": "Черновик"}

        def _on_launch_click():
            state["status_text"] = "Кампания на\xa0модерации"
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_launch_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        page.inner_text = lambda selector=None: state["status_text"]

        result = browser_masters.update_master(
            page, 713231614, headlines={0: "Новый заголовок"}, launch=True
        )

        self.assertEqual(
            result,
            {
                "CampaignId": 713231614,
                "Headlines": {0: "Новый заголовок"},
                "Launched": True,
            },
        )

    def test_launch_true_raises_when_status_stays_draft(self):
        # Regression (issue #721): fields saved and the click redirected away
        # from /edit/, but the overview page's status text never actually
        # became MODERATION — must not report "Launched": True on the
        # redirect alone.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )

        def _on_launch_click():
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_launch_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        page.inner_text = lambda selector=None: "Черновик"

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 713231614, headlines={0: "Новый заголовок"}, launch=True
            )

        self.assertIn("did not report MODERATION", str(ctx.exception))
        self.assertEqual(slot.inner_text(), "Новый заголовок")

    def test_auth_error_during_post_launch_moderation_check_is_not_retried(self):
        # Found via adversarial review (Codex) in cycle-review round 1 of
        # PR #727. Mirrors
        # test_auth_error_during_post_save_image_verification_is_not_retried's
        # pattern: the launch click has ALREADY happened (irreversible), and
        # if --image was also passed, any image replacement is NOT
        # idempotent either. If the session is invalidated while
        # _goto_overview_page/_verify_launched_to_moderation confirm
        # MODERATION, letting BrowserAuthError propagate bare would make
        # _with_session retry the ENTIRE update_master call under a fresh
        # session, re-mutating already-applied changes.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )
        state = {"status_text": "Черновик"}
        launch_clicks = []

        def _on_launch_click():
            launch_clicks.append(True)
            state["status_text"] = "Кампания на\xa0модерации"
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_launch_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)
        page.inner_text = lambda selector=None: state["status_text"]

        original_assert_authenticated = browser_masters.assert_authenticated
        calls_after_click = {"n": 0}

        def _assert_authenticated(content):
            if launch_clicks:
                calls_after_click["n"] += 1
                # Let the FIRST post-click call (inside the existing
                # _verify_saved guard) succeed; fail on the SECOND (inside
                # _goto_overview_page, called from the launch-moderation
                # check added by issue #721).
                if calls_after_click["n"] >= 2:
                    raise BrowserAuthError("stale session, detected mid-body")
            return original_assert_authenticated(content)

        with patch.object(
            browser_masters,
            "assert_authenticated",
            side_effect=_assert_authenticated,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.update_master(
                    page, 713231614, headlines={0: "Новый заголовок"}, launch=True
                )

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)

    def test_error_message_on_draft_mismatch_names_the_draft_button_not_save(self):
        # The mismatch error text must reflect the button THIS run actually
        # clicked, not a hard-coded "Сохранить кампанию" that was never on
        # the page.
        slot = _FakeContentEditableHandle(text="Старый заголовок")
        slot.type = lambda value, delay=None: None  # write silently rejected
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )

        def _on_draft_click():
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=713231614)

        page = FakePage(
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_draft_click)]
                ),
                selector: _FakeLocator([slot]),
            }
        )
        page.url = browser_masters.WIZARD_EDIT_URL.format(campaign_id=713231614)

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 713231614, headlines={0: "Новый заголовок"}
            )

        self.assertIn(
            f"'{browser_masters._SAVE_DRAFT_BUTTON_TEXT}'", str(ctx.exception)
        )
        self.assertNotIn(browser_masters._SAVE_BUTTON_TEXT, str(ctx.exception))


class TestUpdateMaster(unittest.TestCase):
    """``update_master`` (issue #631, Этап A) — partial updates, one whole-form save.

    ``update_master`` now re-navigates and re-reads every requested field
    after clicking save (``_verify_saved``, cycle-review fix for "reports
    success without confirming the save actually took") — so these fakes
    model persistent mutable state (``budget_state``/``checkbox_state``)
    that BOTH the fill/check handles AND the post-reload read-back handles
    share, via ``get_value``/``get_checked`` callables. A test that wants to
    simulate "Yandex silently rejected the value" sets that shared state to
    something OTHER than what was requested, independent of what ``fill``
    was called with.
    """

    def _page_with_save_button(
        self,
        extra_locators=None,
        weekly_budget_state=None,
        directs_helps_state=None,
        name_state=None,
        landing_url_state=None,
        landing_url_read_only=False,
        utm_input_state=None,
        headlines_state=None,
        texts_state=None,
        goal_price_state=None,
        target_action_prices_state=None,
    ):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        locators = dict(extra_locators or {})
        headline_handles = {}
        text_handles = {}

        def _add_repeating_slot_locators(state, testid_template, slot_count, out):
            # ``state`` maps 0-based index -> starting text, pre-populated
            # by the test with whatever the fake edit page starts showing
            # (a real slot is either filled or empty; ``_set_repeating_value``
            # refuses to write to an empty one, mirroring the live page).
            #
            # FakePage reuses the SAME handle object across both goto()
            # calls inside one update_master() run (save, then the
            # post-save reload), just like the real page keeps rendering
            # the same slot — so a plain _FakeContentEditableHandle's own
            # mutable ``_text`` already carries the mutation
            # ``_set_repeating_value`` made into ``_verify_saved``'s re-read.
            # ``out`` hands the handles back to the caller so a test can
            # assert on ``handle.inner_text()`` directly.
            for index in range(slot_count):
                selector = f'[data-testid="{testid_template.format(index=index)}"]'
                handle = _FakeContentEditableHandle(text=state.get(index, ""))
                locators[selector] = _FakeLocator([handle])
                out[index] = handle

        if headlines_state is not None:
            _add_repeating_slot_locators(
                headlines_state,
                browser_masters._HEADLINES_TESTID_TEMPLATE,
                browser_masters._HEADLINES_SLOT_COUNT,
                headline_handles,
            )
        if texts_state is not None:
            _add_repeating_slot_locators(
                texts_state,
                browser_masters._TEXTS_TESTID_TEMPLATE,
                browser_masters._TEXTS_SLOT_COUNT,
                text_handles,
            )

        if weekly_budget_state is not None:
            budget_handle = _FakeLocatorHandle(
                on_fill=lambda v: weekly_budget_state.__setitem__("value", v),
                get_value=lambda: weekly_budget_state.get("value", ""),
            )
            locators[browser_masters._WEEKLY_BUDGET_INPUT_XPATH] = _FakeLocator(
                [budget_handle]
            )
        if directs_helps_state is not None:
            # Issue #724: the toggle's real clickable element is the label,
            # and state lives in the sibling div's `data-checked` attribute —
            # so the label's on_click and the div's get_attribute must read/
            # write the SAME shared `directs_helps_state`, mirroring the real
            # DOM's label-click-flips-sibling-attribute behavior.
            def _directs_helps_attrs():
                return {
                    "data-checked": (
                        "true" if directs_helps_state.get("checked", False) else "false"
                    )
                }

            def _toggle_directs_helps():
                directs_helps_state["checked"] = not directs_helps_state.get(
                    "checked", False
                )

            label_handle = _FakeLocatorHandle(on_click=_toggle_directs_helps)
            div_handle = _DynamicAttrsLocatorHandle(get_attrs=_directs_helps_attrs)
            locators[browser_masters._DIRECT_HELPS_TOGGLE_LABEL_SELECTOR] = (
                _FakeLocator([label_handle])
            )
            locators[browser_masters._DIRECT_HELPS_TOGGLE_DIV_SELECTOR] = _FakeLocator(
                [div_handle]
            )
        if name_state is not None:
            # The rename modal's "Применить" only updates the header's
            # optimistic state on click -- the header handle's own text is
            # what _read_campaign_name reads back after a reload, so
            # on_fill here writes to the SAME state _read_campaign_name's
            # get_value reads, mirroring the budget/checkbox pattern above.
            edit_button_handle = _FakeLocatorHandle()
            name_input_handle = _FakeLocatorHandle(
                on_fill=lambda v: name_state.__setitem__("value", v),
                get_value=lambda: name_state.get("value", ""),
            )
            accept_handle = _FakeLocatorHandle()
            header_handle = _FakeLocatorHandle()
            header_handle.inner_text = lambda: name_state.get("value", "")
            locators[browser_masters._EDIT_NAME_BUTTON_SELECTOR] = _FakeLocator(
                [edit_button_handle]
            )
            locators[browser_masters._NAME_MODAL_INPUT_SELECTOR] = _FakeLocator(
                [name_input_handle]
            )
            locators[browser_masters._NAME_MODAL_ACCEPT_SELECTOR] = _FakeLocator(
                [accept_handle]
            )
            locators[browser_masters._NAME_HEADER_SELECTOR] = _FakeLocator(
                [header_handle]
            )

        landing_url_handle = None
        if landing_url_state is not None:
            # Same "shared mutable state" pattern as name_state above, but
            # via a _FakeContentEditableHandle (the real field is a
            # contenteditable widget, not a plain <input> — issue #757, same
            # widget family as the create page's own URL field).
            #
            # landing_url_read_only (issue #761 cycle-review round 2,
            # Codex): _set_landing_url no longer infers ARCHIVED from the
            # Clear button's disabled state (legitimately disabled on an
            # ordinary campaign too — unfocused field, or nothing to clear
            # — see the function's own docstring), so this fixture no
            # longer models that button at all. A genuinely read-only
            # (ARCHIVED) field is instead modeled as one whose
            # press("Backspace") is a no-op — ``_clear_text_field`` then
            # reports failure exactly like a real read-only contenteditable
            # that ignores keystrokes.
            class _ReadOnlyAwareContentEditableHandle(_FakeContentEditableHandle):
                def press(self, key):
                    if landing_url_read_only:
                        return  # Read-only: keystrokes are silently ignored.
                    super().press(key)

            landing_url_handle = _ReadOnlyAwareContentEditableHandle(
                text=landing_url_state.get("value", "")
            )
            locators[browser_masters._EDIT_URL_INPUT_TESTID] = _FakeLocator(
                [landing_url_handle]
            )

        # UTM spoiler and UTM input field (issue #761) — mounted only when a
        # test actually exercises --tracking-params. _set_landing_url/
        # _read_landing_url are independent of this field and never touch it.
        utm_input_handle = None
        spoiler_expanded = False
        if utm_input_state is not None:
            # _expand_utm_spoiler only ever clicks to OPEN and polls for
            # "true" — it never collapses the spoiler — so the fake only
            # needs to model a one-way flip, not a toggle.
            def _open_spoiler():
                nonlocal spoiler_expanded
                spoiler_expanded = True

            def _spoiler_attrs():
                return {"aria-expanded": "true" if spoiler_expanded else "false"}

            spoiler_handle = _DynamicAttrsLocatorHandle(
                get_attrs=_spoiler_attrs,
                on_click=_open_spoiler,
            )
            locators[browser_masters._EDIT_UTM_SPOILER_BUTTON_TESTID] = _FakeLocator(
                [spoiler_handle]
            )

            utm_input_handle = _FakeContentEditableHandle(
                text=utm_input_state.get("value", "") if utm_input_state else ""
            )
            locators[browser_masters._EDIT_UTM_INPUT_TESTID] = _FakeLocator(
                [utm_input_handle]
            )
            # landing_url_handle's own ._text is the state actually mutated
            # by type()/Backspace and read back by _read_landing_url on the
            # post-save reload (same object reused across both goto() calls,
            # mirroring headline_handles/text_handles above) — tests must
            # assert against page.landing_url_handle.text_content(), NOT the
            # landing_url_state dict passed in, which is only a starting
            # value and is never written back to.

        if goal_price_state is not None:
            price_handle = _FakeLocatorHandle(
                on_fill=lambda v: goal_price_state.__setitem__("value", v),
                get_value=lambda: goal_price_state.get("value", ""),
            )
            locators[browser_masters._GOAL_PRICE_INPUT_TESTID] = _FakeLocator(
                [price_handle]
            )

        if target_action_prices_state is not None:
            # ``target_action_prices_state``: {goal_id: starting price string}
            # — one existing row per key, mirroring goal_price_state's single
            # field but keyed by goal id (issue #707).
            section_selector = browser_masters._TARGET_ACTIONS_SECTION_TESTID
            locators[section_selector] = _FakeLocator([_FakeLocatorHandle()])
            row_prefix_selector = (
                f'[data-testid^="TargetActions.'
                f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
            )
            row_handles = []
            for goal_id in target_action_prices_state:
                row_testid = browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
                    category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=goal_id
                )
                row_handles.append(
                    _FakeLocatorHandle(attrs={"data-testid": row_testid})
                )

                def _make_state_writer(goal_id=goal_id):
                    return lambda v: target_action_prices_state.__setitem__(goal_id, v)

                price_testid = (
                    browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
                        category=browser_masters._TARGET_ACTIONS_CATEGORY,
                        goal_id=goal_id,
                    )
                )
                locators[f'[data-testid="{price_testid}"]'] = _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_fill=_make_state_writer(),
                            get_value=(
                                lambda goal_id=goal_id: target_action_prices_state[
                                    goal_id
                                ]
                            ),
                        )
                    ]
                )
            locators[row_prefix_selector] = _FakeLocator(row_handles)

        # Issue #684: every WIZARD_EDIT_URL goto() now polls
        # _wait_for_edit_form for the first headline slot before trusting
        # the page. headlines_state already adds a real handle for slot 0
        # when a test cares about headline content; otherwise stand in with
        # a bare present handle, mirroring _FakeImagesPage's treatment of
        # _IMAGES_EDITOR_SELECTOR as "always present once the page renders".
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        locators.setdefault(
            edit_form_ready_selector, _FakeLocator([_FakeLocatorHandle()])
        )

        page = FakePage(
            locators=locators,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        # Attached rather than returned as extra tuple elements, so the
        # many existing ``page, save_clicks = ...`` two-value call sites
        # above don't all need updating for this one new capability.
        page.headline_handles = headline_handles
        page.text_handles = text_handles
        page.landing_url_handle = landing_url_handle
        page.utm_input_handle = utm_input_handle
        return page, save_clicks

    def test_updates_only_weekly_budget(self):
        budget_state = {}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state
        )

        result = browser_masters.update_master(page, 107707079, weekly_budget=95000)

        self.assertEqual(budget_state["value"], "95000")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 107707079, "WeeklyBudget": 95000})
        self.assertEqual(
            page.navigated_to,
            [
                browser_masters.WIZARD_EDIT_URL.format(campaign_id=107707079),
                browser_masters.WIZARD_EDIT_URL.format(campaign_id=107707079),
            ],
        )

    def test_updates_only_directs_helps(self):
        checkbox_state = {"checked": False}
        page, save_clicks = self._page_with_save_button(
            directs_helps_state=checkbox_state
        )

        result = browser_masters.update_master(page, 42, directs_helps=True)

        self.assertTrue(checkbox_state["checked"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "DirectsHelps": True})

    def test_updates_only_goal_price(self):
        price_state = {}
        page, save_clicks = self._page_with_save_button(goal_price_state=price_state)

        result = browser_masters.update_master(page, 42, goal_price=500)

        self.assertEqual(price_state["value"], "500")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "GoalPrice": 500})

    def test_raises_when_saved_goal_price_does_not_match_requested(self):
        # The field fills fine, but the post-save reload shows a DIFFERENT
        # value than what was requested (Yandex rejected it client-side) —
        # _verify_saved must catch this the same way it catches every
        # other silently-rejected field.
        price_state = {"value": "999"}
        price_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # fill() is a no-op — value never changes
            get_value=lambda: price_state["value"],
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                browser_masters._GOAL_PRICE_INPUT_TESTID: _FakeLocator([price_handle]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, goal_price=500)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_verify_saved_survives_delayed_weekly_budget_hydration(self):
        # Issue #706: _wait_for_edit_form's poll only waits for the FIRST
        # HEADLINE slot (_EDIT_FORM_READY_TESTID) to appear — a different,
        # earlier-in-the-DOM section than the weekly-budget input further
        # down the page. _read_weekly_budget reads input_value() exactly
        # once, right after that wait returns, with no poll/retry of its
        # own (unlike _read_goal_price, which was already hardened for this
        # in issue #696 via wait_for(state="visible")). Models the budget
        # input's value still showing the PRE-save figure for one tick after
        # the reload, settling to the actually-saved value only afterwards
        # — the same class of hydration race #700 fixed for
        # _is_draft_overview_page, just on a different field.
        ticks = {"count": 0}
        budget_state = {"value": "95000"}

        def _get_budget_value():
            if ticks["count"] < 1:
                return "80000"  # stale pre-save snapshot
            return budget_state["value"]

        budget_handle = _FakeLocatorHandle(
            on_fill=lambda v: budget_state.__setitem__("value", v),
            get_value=_get_budget_value,
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )

        class _DelayedBudgetPage(FakePage):
            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedBudgetPage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, weekly_budget=95000)

        self.assertEqual(result, {"CampaignId": 42, "WeeklyBudget": 95000})

    def test_verify_saved_survives_delayed_goal_price_hydration(self):
        # Issue #716: goal_price's one-shot _read_goal_price() call in
        # _verify_saved wasn't wrapped in _read_until_matches (unlike the
        # four fields #706 hardened) — same hydration race, different
        # field. Models the target-price input still showing the PRE-save
        # figure for one tick after reload, settling to the actually-saved
        # value only afterwards.
        ticks = {"count": 0}
        price_state = {"value": "500"}

        def _get_price_value():
            if ticks["count"] < 1:
                return "999"  # stale pre-save snapshot
            return price_state["value"]

        price_handle = _FakeLocatorHandle(
            on_fill=lambda v: price_state.__setitem__("value", v),
            get_value=_get_price_value,
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )

        class _DelayedPricePage(FakePage):
            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedPricePage(
            locators={
                browser_masters._GOAL_PRICE_INPUT_TESTID: _FakeLocator([price_handle]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, goal_price=500)

        self.assertEqual(result, {"CampaignId": 42, "GoalPrice": 500})

    def test_verify_saved_survives_delayed_target_action_price_hydration(self):
        # Issue #716: target_action_prices' one-shot _read_target_actions()
        # call in _verify_saved wasn't wrapped in _read_until_matches either
        # — the "Целевые действия" table sits even lower on the edit page
        # (per _set_target_action_price's own docstring) so it is at least
        # as exposed to this hydration race as weekly_budget/goal_price.
        ticks = {"count": 0}
        price_state = {"value": "200"}

        def _get_price_value():
            if ticks["count"] < 1:
                return "150"  # stale pre-save snapshot
            return price_state["value"]

        price_handle = _FakeLocatorHandle(
            on_fill=lambda v: price_state.__setitem__("value", v),
            get_value=_get_price_value,
        )
        row_testid = browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )

        class _DelayedTargetActionPage(FakePage):
            def wait_for_timeout(self, timeout):
                ticks["count"] += 1
                super().wait_for_timeout(timeout)

        page = _DelayedTargetActionPage(
            locators={
                browser_masters._TARGET_ACTIONS_SECTION_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                row_prefix_selector: _FakeLocator(
                    [_FakeLocatorHandle(attrs={"data-testid": row_testid})]
                ),
                f'[data-testid="{price_testid}"]': _FakeLocator([price_handle]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(
            page, 42, target_action_prices={159614149: 200}
        )

        self.assertEqual(
            result, {"CampaignId": 42, "TargetActionPrices": {159614149: 200}}
        )

    def test_updates_only_target_action_price(self):
        prices_state = {159614149: "150"}
        page, save_clicks = self._page_with_save_button(
            target_action_prices_state=prices_state
        )

        result = browser_masters.update_master(
            page, 42, target_action_prices={159614149: 200}
        )

        self.assertEqual(prices_state[159614149], "200")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 42, "TargetActionPrices": {159614149: 200}}
        )

    def test_updates_multiple_target_action_prices_in_one_call(self):
        prices_state = {159614149: "150", 281285474: "50"}
        page, save_clicks = self._page_with_save_button(
            target_action_prices_state=prices_state
        )

        browser_masters.update_master(
            page, 42, target_action_prices={159614149: 200, 281285474: 75}
        )

        self.assertEqual(prices_state[159614149], "200")
        self.assertEqual(prices_state[281285474], "75")
        self.assertEqual(len(save_clicks), 1)

    def test_raises_when_target_action_goal_not_in_table(self):
        page, _ = self._page_with_save_button(
            target_action_prices_state={159614149: "150"}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, target_action_prices={999999999: 100}
            )
        self.assertIn("999999999", str(ctx.exception))
        self.assertIn("max-conversions", str(ctx.exception))

    def test_raises_when_saved_target_action_price_does_not_match_requested(self):
        # Fills fine, but the post-save reload shows a DIFFERENT value than
        # requested (Yandex rejected it client-side) — mirrors
        # test_raises_when_saved_goal_price_does_not_match_requested.
        price_state = {"value": "999"}
        price_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # fill() is a no-op — value never changes
            get_value=lambda: price_state["value"],
        )
        row_testid = browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        price_testid = browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                browser_masters._TARGET_ACTIONS_SECTION_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                row_prefix_selector: _FakeLocator(
                    [_FakeLocatorHandle(attrs={"data-testid": row_testid})]
                ),
                f'[data-testid="{price_testid}"]': _FakeLocator([price_handle]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, target_action_prices={159614149: 500}
            )
        self.assertIn("did not save as requested", str(ctx.exception))

    def _dynamic_target_actions_page(self, rows):
        """A page whose "Целевые действия" table's ROW SET itself mutates —
        needed for add/remove (issue #717), unlike ``target_action_prices_state``
        above which only ever mutates an EXISTING row's price. ``rows``:
        ``{goal_id: price_string}``, mutated in place by add/remove/save
        clicks; the row-prefix locator and each row's own locators are
        computed FRESH on every ``page.locator()`` call (mirroring
        ``_FakeTargetActionsPage``) so a later read sees whatever the
        earlier click did.
        """
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        add_button_testid_raw = (
            browser_masters._TARGET_ACTION_ADD_BUTTON_TESTID_TEMPLATE.format(
                category=browser_masters._TARGET_ACTIONS_CATEGORY
            )
        )
        add_button_testid = f'[data-testid="{add_button_testid_raw}"]'
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        save_handle = _FakeTextLocatorHandle(visible=True)

        class _DynamicTargetActionsPage(FakePage):
            def locator(self, selector):
                if selector == edit_form_ready_selector:
                    return _FakeLocator([_FakeLocatorHandle()])
                if selector == browser_masters._TARGET_ACTIONS_SECTION_TESTID:
                    return _FakeLocator([_FakeLocatorHandle()])
                if selector == add_button_testid:
                    return _FakeLocator([_FakeLocatorHandle()])
                if selector == row_prefix_selector:
                    row_testid_template = (
                        browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE
                    )
                    category = browser_masters._TARGET_ACTIONS_CATEGORY
                    return _FakeLocator(
                        [
                            _FakeLocatorHandle(
                                attrs={
                                    "data-testid": row_testid_template.format(
                                        category=category,
                                        goal_id=goal_id,
                                    )
                                }
                            )
                            for goal_id in rows
                        ]
                    )
                for goal_id in list(rows):
                    price_testid = (
                        browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
                            category=browser_masters._TARGET_ACTIONS_CATEGORY,
                            goal_id=goal_id,
                        )
                    )
                    if selector == f'[data-testid="{price_testid}"]':
                        handle = _FakeLocatorHandle(
                            on_fill=(lambda v, gid=goal_id: rows.__setitem__(gid, v)),
                            get_value=(lambda gid=goal_id: rows.get(gid, "")),
                        )
                        return _FakeLocator([handle])
                    close_testid = (
                        browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
                            category=browser_masters._TARGET_ACTIONS_CATEGORY,
                            goal_id=goal_id,
                        )
                    )
                    if selector == f'[data-testid="{close_testid}"]':
                        return _FakeLocator(
                            [
                                _FakeLocatorHandle(
                                    on_click=(lambda gid=goal_id: rows.pop(gid, None))
                                )
                            ]
                        )
                # An "add" option: matches ANY goal id, not just those
                # currently in `rows` — clicking it inserts a fresh empty row,
                # mirroring the real page's freshly-added-row-has-empty-price
                # behaviour (see _add_target_action's docstring).
                option_prefix = (
                    f"AddTargetAction.{browser_masters._TARGET_ACTIONS_CATEGORY}."
                )
                if selector.startswith(
                    f'[data-testid="{option_prefix}'
                ) and selector.endswith('"]'):
                    goal_id = int(selector[len(f'[data-testid="{option_prefix}') : -2])
                    return _FakeLocator(
                        [
                            _FakeLocatorHandle(
                                on_click=(lambda gid=goal_id: rows.setdefault(gid, ""))
                            )
                        ]
                    )
                return super().locator(selector)

        return _DynamicTargetActionsPage(
            locators={edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()])},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

    def test_adds_new_target_action_with_price(self):
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)

        result = browser_masters.update_master(
            page, 42, add_target_actions={226158067: 77}
        )

        self.assertEqual(rows, {159614149: "150", 226158067: "77"})
        self.assertEqual(
            result, {"CampaignId": 42, "AddedTargetActions": {226158067: 77}}
        )

    def test_removes_existing_target_action(self):
        rows = {159614149: "150", 226158067: "77"}
        page = self._dynamic_target_actions_page(rows)

        result = browser_masters.update_master(
            page, 42, remove_target_action_goal_ids=[226158067]
        )

        self.assertEqual(rows, {159614149: "150"})
        self.assertEqual(
            result, {"CampaignId": 42, "RemovedTargetActionGoalIds": [226158067]}
        )

    def test_adds_and_removes_in_the_same_call(self):
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)

        browser_masters.update_master(
            page,
            42,
            add_target_actions={226158067: 77},
            remove_target_action_goal_ids=[159614149],
        )

        self.assertEqual(rows, {226158067: "77"})

    def test_raises_when_added_goal_still_absent_after_save(self):
        # The option click + price fill both "succeed" (rows gains the goal
        # during the mutation phase), but the POST-SAVE RELOAD shows it
        # still absent (Yandex rejected it server-side) — _verify_saved must
        # catch this. Modeled by dropping the goal back out of `rows` right
        # as the SECOND goto() (the one _verify_saved issues after the
        # mutation phase has already run) starts — the first goto() (initial
        # edit-page load, before any mutation) is a no-op here.
        rows = {}
        page = self._dynamic_target_actions_page(rows)
        original_goto = page.goto

        def _goto_and_drop_on_second_call(url, wait_until=None):
            if len(page.navigated_to) == 1:
                rows.pop(226158067, None)
            original_goto(url, wait_until=wait_until)

        page.goto = _goto_and_drop_on_second_call

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, add_target_actions={226158067: 77})
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_removed_goal_still_present_after_save(self):
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator

        def _stub_locator(selector):
            close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
                category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
            )
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_removal_verify_hits_transient_row_scan_failure(self):
        """Codex adversarial review of #717: the section-visibility retry
        (test above) is NOT enough — a transient failure can also occur
        INSIDE ``_read_target_actions`` itself (enumerating the row
        elements) even though the section is visible. Without a matching
        ``None`` propagation there, that mid-scan hiccup collapses to `[]`,
        and `_add_remove_match` reads a genuinely-still-present goal as
        removed. Models: close-button click is a no-op (goal stays in
        `rows`), section is always visible, but the row-prefix locator's
        own ``.count()`` raises on its first call after the verify reload,
        succeeding on every later call."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_scan_calls = {"count": 0}

        close_testid_raw = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        close_testid = f'[data-testid="{close_testid_raw}"]'
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )

        class _FlakyOnceCountLocator:
            """Wraps the REAL row-prefix locator (reflecting the current,
            unchanged `rows` state) but makes its FIRST `.count()` raise —
            models a transient mid-scan failure, not a genuinely-empty
            table. Delegating to the real locator on success (rather than
            hardcoding an empty result) is essential: a hardcoded `count()
            == 0` would make the retry look like a real, correct removal
            confirmation instead of the FALSE one this test exists to catch.
            """

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                row_scan_calls["count"] += 1
                if row_scan_calls["count"] == 1:
                    raise PlaywrightError("Timeout waiting for element state")
                return self._real.count()

            def nth(self, i):
                return self._real.nth(i)

        def _stub_locator(selector):
            if selector == close_testid:
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                return _FlakyOnceCountLocator(original_locator(selector))
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))
        # Confirms the retry actually happened past the transient failure —
        # a false "removed_ok" on the first empty scan would never get here.
        self.assertGreater(row_scan_calls["count"], 1)

    def test_raises_when_removal_verify_hits_transient_get_attribute_failure(self):
        """Codex adversarial review of #717, round 2: the FIRST fix attempt
        (test above) only made ``.count()`` itself failure-safe — it still
        delegated the actual per-element read to ``_read_testid_suffixes``,
        which does its OWN independent ``page.locator(...).count()`` call
        and swallows ANY failure in that second enumeration (including a
        raise from ``.nth(i).get_attribute(...)``, not just from
        ``.count()``) into ``[]``. Reproduced on that version: a no-op
        removal was reported as successful because the probe ``count()``
        succeeded while the delegated enumeration's ``get_attribute()``
        raised once. This test targets exactly that: ``.count()`` NEVER
        raises, but ``.nth(0).get_attribute(...)`` raises on its first call,
        succeeding on every later call — the fixed version must enumerate
        rows inline (no second, independently-failing locator call) so this
        is caught too."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        get_attribute_calls = {"count": 0}

        close_testid_raw = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        close_testid = f'[data-testid="{close_testid_raw}"]'
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )

        class _FlakyAttributeHandle:
            def __init__(self, real_handle):
                self._real = real_handle

            def get_attribute(self, name):
                get_attribute_calls["count"] += 1
                if get_attribute_calls["count"] == 1:
                    raise PlaywrightError("element detached")
                return self._real.get_attribute(name)

        class _CountNeverFailsLocator:
            """``.count()`` always succeeds (unlike the sibling test above)
            — only the PER-ELEMENT read that follows ever raises. A
            probe-then-delegate fix (round 2's actual bug) never sees this
            failure at all, since its own probe only calls ``.count()``."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                return self._real.count()

            def nth(self, i):
                return _FlakyAttributeHandle(self._real.nth(i))

        def _stub_locator(selector):
            if selector == close_testid:
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                return _CountNeverFailsLocator(original_locator(selector))
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))
        self.assertGreater(get_attribute_calls["count"], 1)

    def test_raises_when_removal_verify_read_hits_transient_hydration_failure(
        self,
    ):
        """A single transient hydration failure on the FIRST post-save read
        of the "Целевые действия" section must not be read as "table is
        empty, so the removed goal is gone" — that is indistinguishable from
        a genuinely empty table unless _verify_saved treats an unreadable
        section as its own inconclusive state (not as an empty `{}`) and
        retries past it. Models: close-button click is a no-op (goal stays
        in `rows`, mirroring a save Yandex silently rejected), AND the
        section's own visibility check raises PlaywrightError on its first
        call after the verify reload, succeeding on every later call."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        section_wait_for_calls = {"count": 0}

        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )

        class _FlakyOnceSectionHandle(_FakeLocatorHandle):
            def wait_for(self, state="visible", timeout=None):
                section_wait_for_calls["count"] += 1
                if section_wait_for_calls["count"] == 1:
                    raise PlaywrightError("Timeout waiting for element state")

        flaky_section = _FlakyOnceSectionHandle()

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == browser_masters._TARGET_ACTIONS_SECTION_TESTID:
                return _FakeLocator([flaky_section])
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))
        # Confirms the retry actually happened past the transient failure —
        # a false "removed_ok" on the first empty read would never get here.
        self.assertGreater(section_wait_for_calls["count"], 1)

    def test_raises_when_removal_verify_first_read_is_incomplete_not_failed(
        self,
    ):
        """Issue #750 (Codex round-3 finding on #749, NOT fixed by rounds
        1-2 above): a successful-but-INCOMPLETE first read must not be
        trusted either — this is the gap those two raise-based tests don't
        cover. Unlike them, nothing here ever raises ``PlaywrightError``:
        the row-prefix locator's ``.count()`` genuinely, truthfully returns
        ``0`` for the first several polls (the goal row hasn't mounted
        yet — live-confirmed on campaign 713277109, see
        ``_wait_for_target_actions_settled``'s docstring), then flips back
        to ``1`` and stays there — the goal was never actually removed
        server-side. Without a completeness signal gating the very first
        read the retry loop trusts, ``_add_remove_match`` would see ``{}``
        on attempt 1, treat "goal absent" as "removal confirmed", and
        return success despite the goal still being present in every read
        from attempt 2 onward. Models: close-button click is a no-op (goal
        stays in `rows`, mirroring a save Yandex silently rejected)."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        row_scan_calls = {"count": 0}

        class _IncompleteThenRealLocator:
            """Wraps the REAL row-prefix locator (reflecting `rows`, which
            still has the "removed" goal in it) but makes the first several
            ``.count()`` calls report ``0`` — a truthful read of a table
            that has not finished hydrating, never an exception. Delegates
            to the real locator afterward so the eventually-settled state
            still correctly shows the goal as present (removal genuinely
            did not happen), the same way
            ``_FlakyOnceCountLocator``/``_CountNeverFailsLocator`` above
            delegate to the real locator on their own non-flaky path."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                row_scan_calls["count"] += 1
                if row_scan_calls["count"] <= 3:
                    return 0
                return self._real.count()

            def nth(self, i):
                return self._real.nth(i)

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                return _IncompleteThenRealLocator(original_locator(selector))
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))
        # Confirms the settling loop actually polled past the incomplete
        # reads — a premature "removed_ok" on attempt 1 would never
        # observe more than a couple of `.count()` calls total.
        self.assertGreater(row_scan_calls["count"], 3)

    def test_page_fallback_gate_waits_out_the_marker_before_settling(self):
        """Issue #756 follow-up live recon: the page-level React Suspense
        ``PageFallback`` node is present for the WHOLE hydration dip
        (confirmed live: it also gates ``CampaignTitles0.textarea``, not
        just this section). ``_wait_for_target_actions_ready`` must wait
        for it to clear BEFORE running the row-count settling streak,
        rather than letting the streak absorb the dip on its own.

        Models the marker present for the first few polls, then gone —
        and asserts the row-count read that follows sees the REAL
        (post-dip) row set rather than a mid-dip empty one, which only
        holds if the fallback wait actually blocked first."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        fallback_polls = {"count": 0}
        fallback_gone_after = 3

        def _stub_locator(selector):
            if selector == browser_masters._PAGE_FALLBACK_SELECTOR:
                fallback_polls["count"] += 1
                still_present = fallback_polls["count"] <= fallback_gone_after
                return _FakeLocator([_FakeLocatorHandle()] if still_present else [])
            return original_locator(selector)

        page.locator = _stub_locator

        with patch.object(browser_masters, "_PAGE_FALLBACK_GONE_TIMEOUT_MS", 1000):
            ready = browser_masters._wait_for_target_actions_ready(page)

        self.assertTrue(ready)
        # The gate must have actually polled the marker more than once —
        # a single check would defeat the purpose of waiting it out.
        self.assertGreater(fallback_polls["count"], 1)

    def test_page_fallback_gate_is_a_no_op_when_no_marker_ever_appears(self):
        """The common case (recon: 3 of 8 fresh loads showed no dip at
        all) must not be slowed down — ``_wait_for_page_fallback_gone``
        finds the selector absent on its very first poll and returns
        immediately, so ``_wait_for_target_actions_ready`` proceeds
        straight to the row-count streak without extra delay."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)

        ready = browser_masters._wait_for_target_actions_ready(page)

        self.assertTrue(ready)

    def test_page_fallback_gate_timeout_falls_through_to_the_streak_anyway(self):
        """A ``PageFallback`` node that never clears within
        ``_PAGE_FALLBACK_GONE_TIMEOUT_MS`` (an unusually long dip, or a
        drifted class name making the selector always match something)
        must not abort verification — ``_wait_for_target_actions_ready``
        falls through to the row-count streak regardless, since a timed-
        out fallback wait is a best-effort optimization, not a
        precondition. The row-count streak below still succeeds because
        it is checking a genuinely stable table, independent of the
        fallback node's fate."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator

        def _stub_locator(selector):
            if selector == browser_masters._PAGE_FALLBACK_SELECTOR:
                # Always "present" — the gate can never see it clear.
                return _FakeLocator([_FakeLocatorHandle()])
            return original_locator(selector)

        page.locator = _stub_locator

        with (patch.object(browser_masters, "_PAGE_FALLBACK_GONE_TIMEOUT_MS", 20),):
            ready = browser_masters._wait_for_target_actions_ready(page)

        # The fallback wait itself timed out (returns False), but the
        # overall ready-gate must still report the table as settled since
        # the row count itself never moved.
        self.assertTrue(ready)

    def test_raises_when_target_actions_row_count_never_settles(self):
        """Codex adversarial review of this PR (#753): the settling wait's
        return value must not be discarded. Models a row-prefix locator
        whose ``.count()`` NEVER reports the same value twice in a row for
        the settling wait's whole timeout window — it keeps flipping
        between the real count (1, goal still present) and 0, so
        ``_wait_for_target_actions_settled`` can never accumulate
        ``_TARGET_ACTION_STABLE_STREAK`` consecutive equal reads and times
        out. Before the fix, a discarded timeout would fall straight into
        the retry loop below, whose first read could easily land on one of
        the flipped-to-0 values and be trusted as "goal removed" — a false
        success despite the goal never actually leaving `rows`. The fixed
        behavior must report this as a mismatch (raising, not returning
        success) instead of ever reaching the retry loop at all."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        row_scan_calls = {"count": 0}

        class _NeverStableLocator:
            """Wraps the REAL row-prefix locator but alternates its
            ``.count()`` result between the real count and 0 on every call,
            so consecutive reads are never equal — settling can never
            accumulate a streak and must time out."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                row_scan_calls["count"] += 1
                return self._real.count() if row_scan_calls["count"] % 2 else 0

            def nth(self, i):
                return self._real.nth(i)

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                return _NeverStableLocator(original_locator(selector))
            return original_locator(selector)

        page.locator = _stub_locator

        with (
            patch.object(browser_masters, "_TARGET_ACTION_SETTLE_TIMEOUT_MS", 50),
            patch.object(browser_masters, "_TARGET_ACTION_STABLE_TICK_MS", 5),
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.update_master(
                    page, 42, remove_target_action_goal_ids=[159614149]
                )
        self.assertIn("did not save as requested", str(ctx.exception))
        self.assertIn("never settled", str(ctx.exception))
        # Confirms settling actually polled repeatedly rather than trusting
        # a single early read.
        self.assertGreater(row_scan_calls["count"], 3)

    def test_raises_when_post_settle_read_hits_a_single_transient_empty_dip(
        self,
    ):
        """Codex adversarial review of this PR (#753), round 2: settling
        successfully confirming a stable row count does NOT certify the
        SEPARATE read the retry loop performs right after —
        ``_wait_for_target_actions_settled`` calls ``page.locator(...)``
        exactly ONCE and polls that single locator's ``.count()``
        repeatedly, while ``_read_target_actions_or_none`` (the retry
        loop's own reader) calls ``page.locator(...)`` AGAIN on every
        attempt — genuinely independent locator acquisitions, not a
        shared cached one. This models the dip on the SECOND-ever
        ``page.locator(row_prefix_selector)`` acquisition (settling's is
        the first) — i.e. the retry loop's very first read — reporting an
        empty table once before reverting to the real, still-present row
        on every read from then on (the close-button click is a no-op;
        the goal never actually left `rows`). Without a stability
        requirement on the retry loop's own match (not just on the
        settling pre-check), this single post-settle empty read would be
        trusted immediately as "goal removed" and ``update_master`` would
        report success despite the goal never actually leaving `rows`."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        locator_acquisitions = {"count": 0}
        read_attempts = {"count": 0}

        class _RealCountLocator:
            """Wraps the REAL row-prefix locator, always reporting the
            true, stable count — used for every settling tick (settling
            acquires this wrapper once and polls it repeatedly)."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                return self._real.count()

            def nth(self, i):
                return self._real.nth(i)

        class _RealCountLocatorAfterDip:
            """Wraps the REAL row-prefix locator, always reporting the
            true, stable count — used for every retry-loop acquisition
            AFTER the single dip has already been consumed."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                read_attempts["count"] += 1
                return self._real.count()

            def nth(self, i):
                return self._real.nth(i)

        class _OnceEmptyLocator:
            """Wraps the REAL row-prefix locator but reports 0 on its
            ``.count()`` call — used for exactly the retry loop's FIRST,
            independent post-settle acquisition, globally once."""

            def __init__(self, real_locator):
                self._real = real_locator

            def count(self):
                read_attempts["count"] += 1
                return 0

            def nth(self, i):
                return self._real.nth(i)

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                locator_acquisitions["count"] += 1
                real = original_locator(selector)
                if locator_acquisitions["count"] == 1:
                    # Settling's single locator acquisition: always the
                    # real, stable count.
                    return _RealCountLocator(real)
                if locator_acquisitions["count"] == 2:
                    # The retry loop's first, independent acquisition:
                    # empty exactly once, globally.
                    return _OnceEmptyLocator(real)
                # Every later retry-loop acquisition: back to the real,
                # still-present row (the goal was never actually removed).
                return _RealCountLocatorAfterDip(real)
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        self.assertIn("did not save as requested", str(ctx.exception))
        self.assertIn(
            "still present in the 'Целевые действия' table", str(ctx.exception)
        )
        # Confirms the retry loop kept reading past the single post-settle
        # dip rather than trusting it immediately.
        self.assertGreater(read_attempts["count"], 1)

    def test_raises_when_removal_verify_dip_outlasts_the_whole_streak(self):
        """Issue #756 (round-3 finding on #750): the round-2 fix required
        ``_TARGET_ACTION_STABLE_STREAK`` CONSECUTIVE matching reads, but a
        streak is a TIMED proxy for completeness — a hydration dip lasting
        at least as long as the streak defeats it outright, and Codex
        reproduced exactly that: hold the table empty for the streak's full
        duration and a no-op removal is reported as successful.

        This models a dip LONGER than the whole streak: EVERY post-save
        retry-loop read reports an empty table for more reads than
        ``_TARGET_ACTION_STABLE_STREAK``, while the goal is still genuinely
        present server-side (the close-button click is a no-op, so it never
        leaves ``rows``). Under a streak-only predicate this is a false
        success — ``removed_ok`` is trivially true on ``{}``, so every one
        of those empty reads matches and the streak completes on empty.

        What must save it is the structural fix: ``update_master`` snapshots
        the goal-id set BEFORE the mutation, ``_verify_saved`` derives the
        expected post-save set (``{}`` here would only be correct if the
        removal had actually happened AND nothing else remained), and the
        set comparison rejects a snapshot that is missing rows nobody asked
        to remove. Here the pre-mutation table holds a SECOND goal that was
        never touched, so the expected set is non-empty and an empty dip can
        never match it — verification fails closed no matter how long the
        dip lasts."""
        rows = {159614149: "150", 159614150: "200"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )
        locator_acquisitions = {"count": 0}
        empty_reads = {"count": 0}
        # Strictly MORE empty reads than the streak needs, so a
        # streak-of-matching-reads predicate would complete entirely
        # inside the dip.
        dip_reads = browser_masters._TARGET_ACTION_STABLE_STREAK + 5

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                return _FakeLocator([_FakeLocatorHandle()])  # click is a no-op
            if selector == row_prefix_selector:
                locator_acquisitions["count"] += 1
                real = original_locator(selector)
                # Acquisitions 1-3 are the PRE-mutation snapshot's own
                # settle + read (issue #756) — they must see the real table
                # or there would be no baseline to compare against. The
                # dip models the POST-save reads only, reporting 0 for the
                # first `dip_reads` of them (longer than the whole streak).
                if (
                    locator_acquisitions["count"] > 3
                    and empty_reads["count"] < dip_reads
                ):
                    return _CountOverrideLocator(
                        real,
                        count=0,
                        on_count=lambda: empty_reads.__setitem__(
                            "count", empty_reads["count"] + 1
                        ),
                    )
                return _CountOverrideLocator(real)
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )
        # Asserts the OUTCOME (verification failed closed), not which of the
        # two independent defences phrased it — the predicate's set check
        # rejects the dip mid-loop, and the post-loop set comparison catches
        # it if the loop times out having only ever seen dips. Either is a
        # correct report; silently succeeding is the bug.
        self.assertIn("did not save as requested", str(ctx.exception))
        self.assertIn("Целевые действия", str(ctx.exception))
        # The dip really did outlast the streak — otherwise this test would
        # be re-proving the round-2 fix rather than the round-3 one.
        self.assertGreater(empty_reads["count"], 0)
        self.assertGreaterEqual(dip_reads, browser_masters._TARGET_ACTION_STABLE_STREAK)

    def test_a_dipped_pre_mutation_baseline_does_not_fail_a_good_save(self):
        """Issue #756, adversarial review of the fix itself: the baseline
        snapshot is guarded only by the same probabilistic settling wait,
        and a dip that outlasts the streak settles at count 0 — at which
        point ``_read_target_actions_or_none`` returns a well-formed ``[]``,
        NOT ``None``. An ``is not None`` guard accepts that empty read, and
        the derived expected set (``{} - removed`` = ``{}``) is a bar the
        real table can never clear: the removal genuinely succeeds and
        ``update_master`` reports failure anyway. That is not harmless —
        the mutation has already committed and a retry is not idempotent
        (``_remove_target_action`` raises on an already-absent row).

        The baseline is therefore additionally required to CONTAIN every
        goal about to be removed, which those rows provably do (their close
        buttons are about to be clicked). Here the baseline read dips
        empty, the table hydrates before the click, and the removal really
        happens — verification must SUCCEED."""
        rows = {159614149: "150", 159614150: "200"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        acquisitions = {"count": 0}

        def _stub_locator(selector):
            if selector == row_prefix_selector:
                acquisitions["count"] += 1
                real = original_locator(selector)
                # Acquisition 1 = the baseline's settling wait, 2 = the
                # baseline's own read. Both dip empty; everything after
                # (the close click and all post-save reads) sees the real,
                # fully hydrated table.
                if acquisitions["count"] <= 2:
                    return _CountOverrideLocator(real, count=0)
                return _CountOverrideLocator(real)
            return original_locator(selector)

        page.locator = _stub_locator

        # Must NOT raise: the removal genuinely took effect.
        result = browser_masters.update_master(
            page, 42, remove_target_action_goal_ids=[159614149]
        )

        self.assertEqual(result["RemovedTargetActionGoalIds"], [159614149])
        self.assertEqual(set(rows), {159614150})

    def test_stability_constants_leave_room_for_a_full_streak(self):
        """Issue #756/#752: widening a streak without widening the window
        that has to contain it turns a settle-poll into one that can never
        succeed — it would time out mid-streak on every single run, which
        surfaces as a hard failure on every update rather than as a race.
        Guards the arithmetic on both pairs, plus the verification retry
        budget that has to fit a full streak of matching reads at
        ``_read_until_matches``'s own 250ms poll interval even after a dip
        has consumed the settle timeout."""
        target_action_span_ms = (
            browser_masters._TARGET_ACTION_STABLE_STREAK
            * browser_masters._TARGET_ACTION_STABLE_TICK_MS
        )
        self.assertGreater(
            browser_masters._TARGET_ACTION_SETTLE_TIMEOUT_MS,
            target_action_span_ms,
            "the settle timeout must fit at least one full streak",
        )

        verify_budget_ms = (
            browser_masters._VERIFY_FIELD_READ_TIMEOUT_MS
            + browser_masters._TARGET_ACTION_SETTLE_TIMEOUT_MS
        )
        streak_at_retry_tick_ms = browser_masters._TARGET_ACTION_STABLE_STREAK * 250
        self.assertGreater(
            verify_budget_ms - browser_masters._TARGET_ACTION_SETTLE_TIMEOUT_MS,
            streak_at_retry_tick_ms,
            "after a worst-case dip consumes the settle timeout, the retry "
            "budget must still fit a full streak of matching reads",
        )

    def test_removal_verification_rejects_a_snapshot_missing_untouched_rows(self):
        """Issue #756: a post-save snapshot in which the REQUESTED removal
        looks correct but an UNTOUCHED row has vanished must be rejected.
        Both per-goal checks (added present / removed absent) pass on such
        a snapshot — only the full expected-set comparison catches it, and
        it is precisely the shape a partial hydration read takes.

        Drives the real path: the close-button click removes BOTH the
        requested goal and an untouched one (modelling a save that dropped
        more than asked, or a snapshot that never showed the survivor)."""
        rows = {159614149: "150", 159614150: "200"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        close_testid = browser_masters._TARGET_ACTION_CLOSE_TESTID_TEMPLATE.format(
            category=browser_masters._TARGET_ACTIONS_CATEGORY, goal_id=159614149
        )

        def _stub_locator(selector):
            if selector == f'[data-testid="{close_testid}"]':
                # Clicking the requested goal's close button ALSO drops the
                # untouched row — the requested removal looks correct, but
                # the surviving goal is gone.
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: rows.clear())])
            return original_locator(selector)

        page.locator = _stub_locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )

        self.assertIn("did not save as requested", str(ctx.exception))
        self.assertIn("159614150", str(ctx.exception))

    def test_pre_mutation_snapshot_lets_a_successful_removal_still_verify(self):
        """Issue #756's expected-set check must not make a GENUINE removal
        fail: with a real close-button click, the post-save table equals
        ``before - removed``, which is exactly the derived expected set."""
        rows = {159614149: "150", 159614150: "200"}
        page = self._dynamic_target_actions_page(rows)

        result = browser_masters.update_master(
            page, 42, remove_target_action_goal_ids=[159614149]
        )

        self.assertEqual(result["RemovedTargetActionGoalIds"], [159614149])
        self.assertEqual(set(rows), {159614150})

    def test_baseline_requires_two_independent_settled_reads_to_agree(self):
        """Codex adversarial review of this PR (#756): the certification
        that gates ``target_action_goal_ids_before`` used to check only
        that the to-be-removed goal was PRESENT in the settled baseline —
        it never confirmed the baseline was COMPLETE with respect to an
        UNTOUCHED survivor. A settle streak only stabilizes a row *count*;
        a partial-but-stable read (missing a survivor row that never
        mounted during the streak's window) passes it just as easily as a
        genuinely complete one, so the derived expected set silently omits
        the survivor and a real, successful save is reported as failed.

        This models exactly that: the FIRST settled read of the baseline
        (survivor 159614150 never mounts) is missing it, but the SECOND
        independent settled read (later in wall-clock time) sees the full,
        correct baseline. Two independent reads disagreeing on the id set
        must refuse to certify — the removal must still verify correctly
        (via the round-2 streak-only fallback), proving the fix narrows the
        false-failure window without breaking the genuine-success path."""
        rows = {159614149: "150", 159614150: "200"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        acquisitions = {"count": 0}

        def _stub_locator(selector):
            if selector == row_prefix_selector:
                acquisitions["count"] += 1
                real = original_locator(selector)
                # Acquisitions 1-2 = the FIRST settled read (settle poll +
                # its own row read): missing the untouched survivor.
                # Acquisitions 3-4 = the SECOND independent settled read:
                # sees the real, complete baseline. Everything after (the
                # close click and all post-save reads) sees the real table.
                if acquisitions["count"] <= 2:
                    survivor_testid = (
                        browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE.format(
                            category=browser_masters._TARGET_ACTIONS_CATEGORY,
                            goal_id=159614150,
                        )
                    )
                    return _CountOverrideLocator(
                        _FakeLocator(
                            [
                                h
                                for h in real._handles
                                if h.get_attribute("data-testid") != survivor_testid
                            ]
                        )
                    )
                return _CountOverrideLocator(real)
            return original_locator(selector)

        page.locator = _stub_locator

        with patch.object(browser_masters, "print_warning") as mock_warning:
            result = browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )

        # The removal genuinely succeeded — must NOT be reported as failed.
        self.assertEqual(result["RemovedTargetActionGoalIds"], [159614149])
        self.assertEqual(set(rows), {159614150})
        # The two reads disagreeing means certification could not complete,
        # so the degradation must be surfaced (Codex's observability gap).
        mock_warning.assert_called_once()
        self.assertIn(
            "could not certify a pre-mutation baseline",
            mock_warning.call_args[0][0],
        )

    def test_warns_when_baseline_certification_never_succeeds(self):
        """Codex adversarial review of this PR (#756): when the baseline
        cannot be certified at all (e.g. the table never settles), the PR's
        own design deliberately degrades verification to the weaker
        round-2 streak-only predicate rather than aborting a save whose
        mutations are otherwise fine — but that degradation used to be
        completely silent. Models a baseline read that never settles (the
        row count keeps changing every tick), confirming the operator is
        warned that the stronger structural guarantee did not run, while
        the update itself still succeeds via the weaker fallback."""
        rows = {159614149: "150"}
        page = self._dynamic_target_actions_page(rows)
        original_locator = page.locator
        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        # ``_wait_for_target_actions_settled`` acquires the locator ONCE per
        # call and polls ``.count()`` on it repeatedly, so unsettling only
        # the BASELINE's settle poll (and letting every later acquisition —
        # the post-save settle plus its own reads — see the real, stable
        # table) requires counting ``.locator()`` acquisitions, not ticks.
        acquisitions = {"count": 0}

        def _stub_locator(selector):
            if selector == row_prefix_selector:
                acquisitions["count"] += 1
                real = original_locator(selector)
                if acquisitions["count"] == 1:
                    # The baseline's one-and-only settle-poll acquisition:
                    # alternate 0/1 on every .count() call so the streak
                    # never accumulates and the poll times out.
                    ticks = {"n": 0}

                    class _NeverSettles:
                        def count(self):
                            ticks["n"] += 1
                            return ticks["n"] % 2

                        def nth(self, i):
                            return real.nth(i)

                    return _NeverSettles()
                return _CountOverrideLocator(real)
            return original_locator(selector)

        page.locator = _stub_locator

        with (
            patch.object(browser_masters, "_TARGET_ACTION_SETTLE_TIMEOUT_MS", 50),
            patch.object(browser_masters, "_TARGET_ACTION_STABLE_TICK_MS", 5),
            patch.object(browser_masters, "_TARGET_ACTION_STABLE_STREAK", 3),
            patch.object(browser_masters, "print_warning") as mock_warning,
        ):
            result = browser_masters.update_master(
                page, 42, remove_target_action_goal_ids=[159614149]
            )

        # The removal still succeeds via the round-2 fallback — degrading
        # must not abort an update whose mutations are otherwise fine.
        self.assertEqual(result["RemovedTargetActionGoalIds"], [159614149])
        mock_warning.assert_called_once()
        self.assertIn(
            "could not certify a pre-mutation baseline",
            mock_warning.call_args[0][0],
        )

    def test_updates_multiple_fields_in_one_call(self):
        budget_state = {}
        checkbox_state = {"checked": False}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state, directs_helps_state=checkbox_state
        )

        result = browser_masters.update_master(
            page, 42, weekly_budget=50000, directs_helps=False
        )

        self.assertEqual(budget_state["value"], "50000")
        self.assertFalse(checkbox_state["checked"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {"CampaignId": 42, "WeeklyBudget": 50000, "DirectsHelps": False},
        )

    def test_updates_only_name(self):
        name_state = {}
        page, save_clicks = self._page_with_save_button(name_state=name_state)

        result = browser_masters.update_master(page, 42, name="Новое имя")

        self.assertEqual(name_state["value"], "Новое имя")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Name": "Новое имя"})

    def test_updates_landing_url(self):
        landing_url_state = {"value": "https://lp.example.ru/old?utm_source=old"}
        page, save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state
        )

        result = browser_masters.update_master(
            page, 42, landing_url="https://lp.example.ru/new?utm_source=new"
        )

        self.assertEqual(
            page.landing_url_handle.text_content(),
            "https://lp.example.ru/new?utm_source=new",
        )
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "LandingUrl": "https://lp.example.ru/new?utm_source=new",
            },
        )

    def test_clears_landing_url_entirely_with_empty_string(self):
        landing_url_state = {"value": "https://lp.example.ru/page"}
        page, save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state
        )

        result = browser_masters.update_master(page, 42, landing_url="")

        self.assertEqual(page.landing_url_handle.text_content(), "")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "LandingUrl": ""})

    def test_updates_tracking_params(self):
        # Issue #761: --tracking-params is a SEPARATE field (UTMInput,
        # under the "Дополнительные параметры" spoiler) — independent of
        # --landing-url/LinkInput.
        utm_input_state = {"value": "utm_source=old&utm_medium=cpc"}
        page, save_clicks = self._page_with_save_button(utm_input_state=utm_input_state)

        result = browser_masters.update_master(
            page, 42, tracking_params="utm_source=yandex&utm_medium=cpc"
        )

        self.assertEqual(
            page.utm_input_handle.text_content(),
            "utm_source=yandex&utm_medium=cpc",
        )
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "TrackingParams": "utm_source=yandex&utm_medium=cpc",
            },
        )

    def test_clears_tracking_params_with_empty_string(self):
        utm_input_state = {"value": "utm_source=yandex"}
        page, save_clicks = self._page_with_save_button(utm_input_state=utm_input_state)

        result = browser_masters.update_master(page, 42, tracking_params="")

        self.assertEqual(page.utm_input_handle.text_content(), "")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "TrackingParams": ""})

    def test_retries_transient_contenteditable_clear_failure(self):
        # Issue #829: the edit widget can be present before its keyboard
        # handler is ready.  A one-shot select-all/Backspace reports a false
        # "could not clear" error; retrying the idempotent clear is safe.
        class _FlakyClearHandle(_FakeContentEditableHandle):
            def __init__(self):
                super().__init__(text="utm_source=old")
                self.attempts = 0

            def press(self, key):
                if key == "ControlOrMeta+a" and self.attempts == 0:
                    self.attempts += 1
                    raise PlaywrightError("keyboard handler not ready")
                return super().press(key)

        field = _FlakyClearHandle()
        page = FakePage(
            locators={browser_masters._EDIT_URL_INPUT_TESTID: _FakeLocator([field])}
        )

        browser_masters._set_contenteditable_field(
            page, browser_masters._EDIT_URL_INPUT_TESTID, "", label="landing-page URL"
        )

        self.assertEqual(field.text_content(), "")
        self.assertEqual(field.attempts, 1)

    def test_updates_landing_url_and_tracking_params_together(self):
        landing_url_state = {"value": "https://lp.example.ru/old"}
        utm_input_state = {"value": "utm_source=old"}
        page, save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state,
            utm_input_state=utm_input_state,
        )

        result = browser_masters.update_master(
            page,
            42,
            landing_url="https://lp.example.ru/new",
            tracking_params="utm_source=new",
        )

        self.assertEqual(
            page.landing_url_handle.text_content(), "https://lp.example.ru/new"
        )
        self.assertEqual(page.utm_input_handle.text_content(), "utm_source=new")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "LandingUrl": "https://lp.example.ru/new",
                "TrackingParams": "utm_source=new",
            },
        )

    def test_sets_tracking_params_before_landing_url_when_combined(self):
        """Issue #830: UTM expansion must not invalidate the URL edit."""
        page, _save_clicks = self._page_with_save_button(
            landing_url_state={"value": "https://lp.example.ru/old"},
            utm_input_state={"value": "utm_source=old"},
        )
        calls = []
        original_set_tracking_params = browser_masters._set_tracking_params
        original_set_landing_url = browser_masters._set_landing_url

        def set_tracking_params(_page, value):
            calls.append(("tracking_params", value))
            original_set_tracking_params(_page, value)

        def set_landing_url(_page, value):
            calls.append(("landing_url", value))
            original_set_landing_url(_page, value)

        with (
            patch.object(browser_masters, "_set_tracking_params", set_tracking_params),
            patch.object(browser_masters, "_set_landing_url", set_landing_url),
        ):
            browser_masters.update_master(
                page,
                42,
                landing_url="https://lp.example.ru/new",
                tracking_params="utm_source=new",
            )

        self.assertEqual(
            calls,
            [
                ("tracking_params", "utm_source=new"),
                ("landing_url", "https://lp.example.ru/new"),
            ],
        )

    def test_raises_when_landing_url_field_is_read_only_archived(self):
        # cycle-review round 2 (issue #761 fixup, Codex-confirmed):
        # _set_landing_url no longer pre-checks the Clear button's disabled
        # state (that button is ALSO legitimately disabled on an ordinary
        # campaign whenever unfocused or whenever the URL is already empty
        # — see the function's own docstring) — it just attempts the write
        # and lets _set_contenteditable_field's own "could not clear the
        # field" error surface a genuinely read-only ARCHIVED field,
        # upgraded with a status-text hint when _read_status_text confirms
        # ARCHIVED.
        landing_url_state = {"value": "https://lp.example.ru/page"}
        page, _save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state,
            landing_url_read_only=True,
        )
        page._body_text = "Кампания в\xa0архиве"

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, landing_url="https://lp.example.ru/new"
            )
        self.assertIn("ARCHIVED", str(ctx.exception))
        # The field was never touched — Yandex's own state is unchanged.
        self.assertEqual(
            page.landing_url_handle.text_content(), "https://lp.example.ru/page"
        )

    def test_raises_generic_error_when_landing_url_field_is_read_only_but_status_unclear(  # noqa: E501
        self,
    ):
        # Companion: when the field can't be cleared but _read_status_text
        # can't confirm ARCHIVED (e.g. the marker text isn't on this page,
        # or reading it fails) — the original "could not clear" error
        # surfaces unchanged, with no unverified ARCHIVED claim tacked on.
        landing_url_state = {"value": "https://lp.example.ru/page"}
        page, _save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state,
            landing_url_read_only=True,
        )
        page._body_text = ""

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, landing_url="https://lp.example.ru/new"
            )
        self.assertNotIn("ARCHIVED", str(ctx.exception))
        self.assertIn("could not clear", str(ctx.exception).lower())

    def test_does_not_touch_landing_url_when_updating_an_unrelated_field(self):
        # cycle-review round 2 (issue #761 fixup, Codex-confirmed): the
        # removed pre-mutation campaign-wide ARCHIVED guard used to read the
        # landing-URL Clear button before ANY mutation, regardless of which
        # field was actually being changed — false-positiving on an
        # ordinary campaign's unfocused/empty URL field and blocking every
        # update. update_master no longer touches the landing-URL field at
        # all unless the caller actually requests it.
        landing_url_state = {"value": "https://lp.example.ru/page"}
        budget_state = {}
        page, save_clicks = self._page_with_save_button(
            landing_url_state=landing_url_state,
            weekly_budget_state=budget_state,
        )

        result = browser_masters.update_master(page, 42, weekly_budget=50000)

        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result["WeeklyBudget"], 50000)
        self.assertEqual(
            page.landing_url_handle.text_content(), "https://lp.example.ru/page"
        )

    def test_raises_when_saved_landing_url_does_not_match_requested(self):
        # The field accepts the new text (so the in-flight type-and-verify
        # loop inside _type_landing_url is satisfied), but the post-save
        # RELOAD reads back the OLD value — Yandex silently rejected the
        # save (or it didn't persist), same "never trust the click alone"
        # convention as name. Modeled by a handle whose text_content()
        # reports live (mutated) state up through the save, then reverts to
        # the original once _verify_saved's own goto() has fired — a second,
        # separate _FakeContentEditableHandle can't model this because
        # FakePage.locator() keeps returning the SAME handle object across
        # both goto() calls (see _page_with_save_button's landing_url_state
        # comment).
        original_value = "https://lp.example.ru/old"

        class _RevertsOnReloadHandle(_FakeContentEditableHandle):
            def text_content(self):
                if len(page.navigated_to) > 1:
                    return original_value
                return super().text_content()

        url_handle = _RevertsOnReloadHandle(text=original_value)
        clear_handle = _FakeLocatorHandle()
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        page = FakePage(
            locators={
                browser_masters._EDIT_URL_INPUT_TESTID: _FakeLocator([url_handle]),
                browser_masters._EDIT_URL_CLEAR_BUTTON_TESTID: _FakeLocator(
                    [clear_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, landing_url="https://lp.example.ru/new"
            )
        self.assertIn("landing_url", str(ctx.exception))

    def test_a_stale_landing_url_reload_is_recovered_by_re_navigating(self):
        # Issue #790: live-reproduced 15/15 against real Мастер кампаний —
        # `masters update --landing-url` on a URL whose CURRENT value already
        # carries a query string reported a mismatch (the old query tail
        # showing as "extra") even though the save genuinely took effect. The
        # immediate post-save reload served a stale render (same class of
        # race as #769/#774's tracking_params staleness, confirmed PAGE-level
        # not field-specific); a fresh navigation moments later showed the
        # correct new value. `_verify_saved` must re-navigate on a
        # `landing_url` mismatch instead of only re-polling the same stale
        # page — this must succeed, not raise.
        original_value = "https://lp.example.ru/old?utm_source=old"
        new_value = "https://lp.example.ru/new?utm_source=new"

        class _RecoversOnReNavigationHandle(_FakeContentEditableHandle):
            def text_content(self):
                # The first post-save reload (one goto beyond the initial
                # edit-page open) is stale; the second goto (the re-
                # navigation retry) sees the real, saved value.
                if len(page.navigated_to) > 2:
                    return new_value
                if len(page.navigated_to) > 1:
                    return original_value
                return super().text_content()

        url_handle = _RecoversOnReNavigationHandle(text=original_value)
        clear_handle = _FakeLocatorHandle()
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        page = FakePage(
            locators={
                browser_masters._EDIT_URL_INPUT_TESTID: _FakeLocator([url_handle]),
                browser_masters._EDIT_URL_CLEAR_BUTTON_TESTID: _FakeLocator(
                    [clear_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, landing_url=new_value)

        self.assertEqual(result["LandingUrl"], new_value)

    def test_updates_name_together_with_weekly_budget(self):
        budget_state = {}
        name_state = {}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state, name_state=name_state
        )

        result = browser_masters.update_master(
            page, 42, weekly_budget=50000, name="Новое имя"
        )

        self.assertEqual(budget_state["value"], "50000")
        self.assertEqual(name_state["value"], "Новое имя")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 42, "WeeklyBudget": 50000, "Name": "Новое имя"}
        )

    def test_raises_when_saved_name_does_not_match_requested(self):
        # The modal's "Применить" click "succeeds", but the state backing
        # the header text never actually changes (Yandex silently rejected
        # the rename, or the terminal save didn't persist it).
        name_state = {"value": "Старое имя"}
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_button_handle = _FakeLocatorHandle()
        name_input_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # the fill "succeeds" but doesn't persist
            get_value=lambda: name_state["value"],
        )
        accept_handle = _FakeLocatorHandle()
        header_handle = _FakeLocatorHandle()
        header_handle.inner_text = lambda: name_state["value"]
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                browser_masters._EDIT_NAME_BUTTON_SELECTOR: _FakeLocator(
                    [edit_button_handle]
                ),
                browser_masters._NAME_MODAL_INPUT_SELECTOR: _FakeLocator(
                    [name_input_handle]
                ),
                browser_masters._NAME_MODAL_ACCEPT_SELECTOR: _FakeLocator(
                    [accept_handle]
                ),
                browser_masters._NAME_HEADER_SELECTOR: _FakeLocator([header_handle]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, name="Новое имя")
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_does_not_click_save_when_name_edit_button_missing(self):
        page = FakePage(role_elements=[])

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, name="Новое имя")

    def test_raises_value_error_when_no_field_provided(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42)

    def test_does_not_click_save_when_field_setter_fails(self):
        # No locator registered for the budget field -> _set_weekly_budget
        # raises before _click_save is ever reached.
        page, save_clicks = self._page_with_save_button()

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, weekly_budget=1000)

        self.assertEqual(save_clicks, [])

    def test_raises_when_save_button_missing(self):
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [_FakeLocatorHandle(get_value=lambda: "1000")]
                )
            },
            role_elements=[],
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, weekly_budget=1000)

    def test_raises_when_saved_value_does_not_match_requested(self):
        # Save button is clicked, but the reload shows the OLD budget still
        # in place (e.g. Yandex silently rejected the value) — this must be
        # reported as a hard error, not a false success.
        budget_state = {"value": "80000"}  # never actually updated to 95000
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        budget_handle = _FakeLocatorHandle(
            on_fill=lambda v: None,  # the fill "succeeds" but doesn't persist
            get_value=lambda: budget_state["value"],
        )
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, weekly_budget=95000)

        self.assertEqual(len(save_clicks), 1)  # save WAS clicked
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_saved_directs_helps_does_not_match_requested(self):
        save_handle = _FakeTextLocatorHandle(visible=True)
        # Label click is a no-op — models "Yandex silently rejected the
        # toggle": data-checked never actually flips to true (issue #724).
        label_handle = _FakeLocatorHandle(on_click=lambda: None)
        div_handle = _FakeLocatorHandle(attrs={"data-checked": "false"})
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                browser_masters._DIRECT_HELPS_TOGGLE_LABEL_SELECTOR: _FakeLocator(
                    [label_handle]
                ),
                browser_masters._DIRECT_HELPS_TOGGLE_DIV_SELECTOR: _FakeLocator(
                    [div_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, directs_helps=True)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_raises_when_saved_promotion_goal_does_not_match_requested(self):
        # The goal setter's own post-click check passes (trigger text
        # updates immediately), but the post-save reload shows the OLD
        # goal still selected -- _verify_saved must still catch this. The
        # trigger's inner_text() is modeled as two lines (static label +
        # selection), matching the live-confirmed shape.
        trigger_texts = iter(
            [
                "Цель продвижения\nМаксимум переходов",
                "Цель продвижения\nМаксимум целевых действий",
            ]
        )
        # _read_until_matches (issue #706) retries the reader until it
        # settles or times out — the fake models a real page's stable value
        # by repeating the LAST scripted line once the iterator is
        # exhausted, instead of raising StopIteration on a second read.
        import contextlib

        last_text = {"value": None}

        def _next_trigger_text():
            with contextlib.suppress(StopIteration):
                last_text["value"] = next(trigger_texts)
            return last_text["value"]

        trigger = _FakeLocatorHandle(text="Цель продвижения")
        trigger.inner_text = _next_trigger_text
        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        option_testid = browser_masters._PROMOTION_GOAL_OPTION_TESTID_TEMPLATE.format(
            value=browser_masters.PROMOTION_GOAL_INTERNAL_VALUES["max-clicks"]
        )
        option_selector = f'[data-testid="{option_testid}"]'
        page = FakePage(
            locators={
                browser_masters._PROMOTION_GOAL_BUTTON_XPATH: _FakeLocator([trigger]),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
                option_selector: _FakeLocator([_FakeLocatorHandle(visible=True)]),
            },
            role_elements=[
                ("button", browser_masters._SAVE_BUTTON_TEXT, save_handle),
            ],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, promotion_goal="max-clicks")
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_updates_only_one_headline_slot(self):
        headlines_state = {0: "Старый заголовок", 1: "Другой заголовок"}
        page, save_clicks = self._page_with_save_button(headlines_state=headlines_state)

        result = browser_masters.update_master(
            page, 42, headlines={0: "Новый заголовок"}
        )

        self.assertEqual(page.headline_handles[0].inner_text(), "Новый заголовок")
        # Slot 1 must be left exactly as it was.
        self.assertEqual(page.headline_handles[1].inner_text(), "Другой заголовок")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result, {"CampaignId": 42, "Headlines": {0: "Новый заголовок"}}
        )

    def test_updates_headline_and_text_together_with_weekly_budget(self):
        budget_state = {}
        headlines_state = {0: "Старый заголовок"}
        texts_state = {0: "Старый текст"}
        page, save_clicks = self._page_with_save_button(
            weekly_budget_state=budget_state,
            headlines_state=headlines_state,
            texts_state=texts_state,
        )

        result = browser_masters.update_master(
            page,
            42,
            weekly_budget=60000,
            headlines={0: "Новый заголовок"},
            texts={0: "Новый текст"},
        )

        self.assertEqual(budget_state["value"], "60000")
        self.assertEqual(page.headline_handles[0].inner_text(), "Новый заголовок")
        self.assertEqual(page.text_handles[0].inner_text(), "Новый текст")
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "WeeklyBudget": 60000,
                "Headlines": {0: "Новый заголовок"},
                "Texts": {0: "Новый текст"},
            },
        )

    def test_raises_when_saved_headline_does_not_match_requested(self):
        # The setter's write "succeeds", but the post-save reload shows the
        # OLD value still in the slot (mirrors the budget/goal equivalents
        # above) — must be a hard error, not a false success.
        headlines_state = {0: "Старый заголовок"}
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        slot = _FakeContentEditableHandle(text=headlines_state[0])
        # Detach the write from the shared state entirely, unlike the
        # normal helper wiring, to simulate Yandex silently rejecting it.
        slot.type = lambda value, delay=None: None
        selector = (
            f"[data-testid="
            f'"{browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)}"]'
        )
        page = FakePage(
            locators={selector: _FakeLocator([slot])},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, headlines={0: "Новый заголовок"})

        self.assertEqual(len(save_clicks), 1)  # save WAS clicked
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_does_not_click_save_when_headline_slot_is_empty(self):
        headlines_state = {0: ""}  # empty slot -> _set_repeating_value refuses
        page, save_clicks = self._page_with_save_button(headlines_state=headlines_state)

        with self.assertRaises(BrowserSessionError):
            browser_masters.update_master(page, 42, headlines={0: "Новый заголовок"})

        self.assertEqual(save_clicks, [])

    def test_raises_value_error_when_only_empty_headlines_dict_provided(self):
        # An empty dict is falsy — same "nothing to update" guard as every
        # other field, not treated as "update with zero slots".
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42, headlines={})

    def test_raises_value_error_when_only_empty_images_dict_provided(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42, images={})

    def test_update_master_replaces_an_image(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c"],
            upload_ids=["new"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, images={1: "/tmp/fake.png"})

        self.assertEqual(page.ids, ["a", "c", "new"])
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Images": {1: "/tmp/fake.png"}})

    def test_update_master_replaces_multiple_images_by_original_position(self):
        """Two ``--image`` flags in one call must resolve BOTH positions
        against the ORIGINAL (pre-mutation) set, not the live, already
        reordered one.

        Found independently by both reviewers in cycle-review round 1 of
        PR #672: ``_set_image`` re-reads the live page on every call, and
        the image manager appends replacements to the END of the set
        (confirmed live), so a naive per-position loop resolves the second
        ``--image`` against a set that has already shifted because of the
        first. Replacing positions 1 and 2 of ``[a, b, c, d]`` must remove
        exactly ``a`` and ``b`` — never a third, untouched image like
        ``c`` — regardless of set reordering in between.
        """
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c", "d"],
            upload_ids=["new1", "new2"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(
            page, 42, images={0: "/tmp/one.png", 1: "/tmp/two.png"}
        )

        self.assertEqual(set(page.ids), {"c", "d", "new1", "new2"})
        self.assertNotIn("a", page.ids)
        self.assertNotIn("b", page.ids)
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(
            result,
            {
                "CampaignId": 42,
                "Images": {0: "/tmp/one.png", 1: "/tmp/two.png"},
            },
        )

    def test_update_master_raises_when_saved_image_set_does_not_match(self):
        """Mirrors the headline "silently rejected" test — the page-level
        save WAS clicked, but the post-reload re-read still shows the image
        that was supposed to be gone."""
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c"],
            upload_ids=["new"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        # Sabotage AFTER _set_image runs but BEFORE _verify_saved's reload —
        # models Yandex accepting the modal's own Save but the page-level
        # terminal save silently not persisting the change.
        original_click = save_handle._on_click

        def _click():
            original_click()
            page.ids = ["a", "b", "c"]  # revert, as if nothing was saved

        save_handle._on_click = _click

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, images={1: "/tmp/fake.png"})

        self.assertEqual(len(page_save_clicks), 1)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_auth_error_during_post_save_image_verification_is_not_retried(self):
        """Mirrors ``copy_master``'s
        ``test_auth_error_during_post_click_verification_is_not_retried``.

        By the time ``_verify_saved`` reloads the edit page, every requested
        image replacement has ALREADY been committed via its own modal Save
        — irreversible from here, and NOT idempotent for images the way
        ``_set_repeating_value`` is for headlines/texts (replacement always
        appends to the end of the set — see ``_set_image``'s docstring), so
        a positional re-application on retry would replace DIFFERENT images
        than the ones the caller named. If the saved session is invalidated
        in exactly this window, ``_verify_saved``'s own
        ``assert_authenticated`` raises ``BrowserAuthError`` — letting that
        propagate as-is would make ``_with_session``
        (``direct_cli/commands/masters.py``) retry this ENTIRE
        ``update_master`` call under a fresh session, re-snapshotting the
        now-already-mutated image set and removing further, untouched
        images. This must surface as a plain ``BrowserSessionError`` (not
        ``BrowserAuthError``), so ``_with_session``'s retry-on-auth-error
        does not fire — found via adversarial review (Codex) in
        cycle-review round 2 of PR #672.
        """
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ["a", "b", "c", "d"],
            upload_ids=["new1", "new2"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        original_assert_authenticated = browser_masters.assert_authenticated

        def _assert_authenticated(content):
            # The terminal save click is irreversible and NOT idempotent for
            # images (see this test's own docstring) — only an auth failure
            # AFTER that click (i.e. during _verify_saved's post-save
            # reload) is the dangerous case this test guards. Gating on
            # page_save_clicks rather than a raw call count keeps this
            # correct regardless of how many assert_authenticated calls
            # precede the save (e.g. _wait_for_edit_form's own poll-loop
            # check, added in cycle-review round 1 of PR #689).
            if page_save_clicks:
                raise BrowserAuthError("stale session, detected mid-body")
            return original_assert_authenticated(content)

        with patch.object(
            browser_masters,
            "assert_authenticated",
            side_effect=_assert_authenticated,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.update_master(
                    page, 42, images={0: "/tmp/one.png", 1: "/tmp/two.png"}
                )

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertEqual(len(page_save_clicks), 1)
        # The images WERE already replaced (irreversibly) before the auth
        # error surfaced -- the error message must say so rather than
        # implying nothing happened.
        self.assertIn("42", str(ctx.exception))

    def test_raises_value_error_when_only_empty_remove_videos_list_provided(self):
        page = FakePage()

        with self.assertRaises(ValueError):
            browser_masters.update_master(page, 42, remove_videos=[])

    def test_update_master_adds_a_video(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeVideosPage(
            ["https://a.test/1.mp4"],
            upload_urls=["https://a.test/new.mp4"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(page, 42, add_video="/tmp/fake.mp4")

        self.assertEqual(page.urls, ["https://a.test/1.mp4", "https://a.test/new.mp4"])
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "AddedVideo": "/tmp/fake.mp4"})

    def test_update_master_removes_a_video(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeVideosPage(
            ["https://a.test/1.mp4", "https://a.test/2.mp4"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        result = browser_masters.update_master(
            page, 42, remove_videos=["https://a.test/1.mp4"]
        )

        self.assertEqual(page.urls, ["https://a.test/2.mp4"])
        self.assertEqual(len(page_save_clicks), 1)
        self.assertEqual(
            result,
            {"CampaignId": 42, "RemovedVideos": ["https://a.test/1.mp4"]},
        )

    def test_update_master_raises_when_removing_a_video_not_present(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page, 42, remove_videos=["https://nonexistent.test/x.mp4"]
            )

        self.assertIn("not present", str(ctx.exception).lower())

    def test_update_master_raises_before_mutating_when_a_later_remove_url_is_invalid(
        self,
    ):
        # Preflight: with two --remove-video URLs where the first is valid
        # and the second is not, nothing on the page should be clicked —
        # the whole batch is validated against the pre-mutation snapshot
        # before any _remove_video call, mirroring _set_image's "resolve
        # every target up front" pattern for identity-based (not
        # position-based) removal.
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page,
                42,
                remove_videos=[
                    "https://a.test/1.mp4",
                    "https://nonexistent.test/x.mp4",
                ],
            )

        self.assertIn("not present", str(ctx.exception).lower())
        self.assertEqual(page.urls, ["https://a.test/1.mp4", "https://a.test/2.mp4"])

    def test_update_master_raises_when_remove_videos_has_a_duplicate_url(self):
        # A duplicate URL in --remove-video must not be treated as "still
        # present" by a stale snapshot re-check — it must be rejected
        # up front as a caller error, the same way _set_image treats a
        # content ID that already disappeared earlier in the same batch.
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page,
                42,
                remove_videos=["https://a.test/1.mp4", "https://a.test/1.mp4"],
            )

        self.assertIn("duplicate", str(ctx.exception).lower())
        self.assertEqual(page.urls, ["https://a.test/1.mp4", "https://a.test/2.mp4"])

    def test_add_video_failure_after_a_prior_remove_does_not_claim_no_change(self):
        # A --remove-video is committed directly on the page, with no Save
        # gate of its own (see _remove_video's docstring) — so if a
        # following --add-video then fails, the error must not claim "the
        # video set has NOT been changed": the removal already ran.
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._VIDEOS_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(raises=True)])
            return original_locator(selector)

        page.locator = _locator

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(
                page,
                42,
                remove_videos=["https://a.test/1.mp4"],
                add_video="/tmp/fake.mp4",
            )

        message = str(ctx.exception)
        self.assertNotIn("has NOT been changed", message)
        self.assertIn("1 --remove-video removal(s)", message)
        self.assertEqual(page.urls, ["https://a.test/2.mp4"])

    def test_update_master_raises_when_saved_video_set_does_not_match(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeVideosPage(
            ["https://a.test/1.mp4"],
            upload_urls=["https://a.test/new.mp4"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        original_click = save_handle._on_click

        def _click():
            original_click()
            page.urls = ["https://a.test/1.mp4"]  # revert, as if not saved

        save_handle._on_click = _click

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, add_video="/tmp/fake.mp4")

        self.assertEqual(len(page_save_clicks), 1)
        self.assertIn("did not save as requested", str(ctx.exception))

    def test_auth_error_during_post_save_video_verification_is_not_retried(self):
        page_save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: page_save_clicks.append(True)
        )
        page = _FakeVideosPage(
            ["https://a.test/1.mp4"],
            upload_urls=["https://a.test/new.mp4"],
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        original_assert_authenticated = browser_masters.assert_authenticated

        def _assert_authenticated(content):
            if page_save_clicks:
                raise BrowserAuthError("stale session, detected mid-body")
            return original_assert_authenticated(content)

        with patch.object(
            browser_masters,
            "assert_authenticated",
            side_effect=_assert_authenticated,
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.update_master(page, 42, add_video="/tmp/fake.mp4")

        self.assertNotIsInstance(ctx.exception, BrowserAuthError)
        self.assertEqual(len(page_save_clicks), 1)
        self.assertIn("42", str(ctx.exception))


class TestMastersUpdateCommand(unittest.TestCase):
    """CLI wiring for `masters update` (issue #631, Этап A)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_registered(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertNotIn("--login", result.output)

    def test_documents_stage_a_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--weekly-budget", result.output)
        self.assertIn("--promotion-goal", result.output)
        self.assertIn("--directs-helps", result.output)
        self.assertIn("--name", result.output)

    def test_calls_update_master_with_given_fields(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "WeeklyBudget": 95000}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--weekly-budget", "95000"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_update.assert_called_once()
        args, kwargs = mock_update.call_args
        self.assertEqual(args[1], 42)
        self.assertEqual(kwargs["weekly_budget"], 95000)
        self.assertIsNone(kwargs["promotion_goal"])
        self.assertIsNone(kwargs["directs_helps"])
        self.assertIsNone(kwargs["name"])

    def test_passes_name_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "Name": "Новое имя"}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--name", "Новое имя"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["name"], "Новое имя")

    def test_passes_landing_url_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {
                "CampaignId": 42,
                "LandingUrl": "https://lp.example.ru/new?utm_source=new",
            }
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--landing-url",
                    "https://lp.example.ru/new?utm_source=new",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["landing_url"],
            "https://lp.example.ru/new?utm_source=new",
        )

    def test_passes_empty_landing_url_flag_to_clear_it(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "LandingUrl": ""}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--landing-url", ""]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["landing_url"], "")

    def test_documents_landing_url_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--landing-url", result.output)

    def test_passes_tracking_params_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {
                "CampaignId": 42,
                "TrackingParams": "utm_source=yandex&utm_medium=cpc",
            }
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--tracking-params",
                    "utm_source=yandex&utm_medium=cpc",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["tracking_params"],
            "utm_source=yandex&utm_medium=cpc",
        )

    def test_passes_empty_tracking_params_flag_to_clear_it(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42, "TrackingParams": ""}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--tracking-params", ""]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["tracking_params"], "")

    def test_documents_tracking_params_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--tracking-params", result.output)

    def test_passes_promotion_goal_choice(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--promotion-goal", "max-clicks"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["promotion_goal"], "max-clicks")

    def test_rejects_unknown_promotion_goal(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--promotion-goal", "bogus"]
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_passes_goal_price(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--promotion-goal",
                    "max-clicks",
                    "--goal-price",
                    "500",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["goal_price"], 500.0)
        self.assertEqual(mock_update.call_args.kwargs["promotion_goal"], "max-clicks")

    def test_goal_price_alone_is_a_valid_field(self):
        # --goal-price on its own (no --promotion-goal) is accepted by the
        # CLI's "at least one field" guard — whether it actually works
        # depends on the campaign's CURRENT saved goal already being
        # 'max-clicks', which update_master (not this guard) determines.
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--goal-price", "300"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["goal_price"], 300.0)
        self.assertIsNone(mock_update.call_args.kwargs["promotion_goal"])

    def test_rejects_goal_price_with_max_conversions(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--promotion-goal",
                "max-conversions",
                "--goal-price",
                "500",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max-conversions", result.output)

    def test_does_not_call_update_master_when_goal_price_rejected(self):
        with patch("direct_cli.browser.masters.update_master") as mock_update:
            self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--promotion-goal",
                    "max-conversions",
                    "--goal-price",
                    "500",
                ],
            )
        mock_update.assert_not_called()

    def test_documents_target_action_price_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--target-action-price", result.output)

    def test_passes_target_action_price(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--promotion-goal",
                    "max-conversions",
                    "--target-action-price",
                    "159614149=200",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["target_action_prices"], {159614149: 200.0}
        )
        self.assertEqual(
            mock_update.call_args.kwargs["promotion_goal"], "max-conversions"
        )

    def test_passes_multiple_target_action_prices(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--target-action-price",
                    "159614149=200",
                    "--target-action-price",
                    "281285474=75",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["target_action_prices"],
            {159614149: 200.0, 281285474: 75.0},
        )

    def test_target_action_price_alone_is_a_valid_field(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--target-action-price", "159614149=200"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(mock_update.call_args.kwargs["promotion_goal"])

    def test_rejects_target_action_price_with_max_clicks(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--promotion-goal",
                "max-clicks",
                "--target-action-price",
                "159614149=200",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max-clicks", result.output)

    def test_does_not_call_update_master_when_target_action_price_rejected(self):
        with patch("direct_cli.browser.masters.update_master") as mock_update:
            self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--promotion-goal",
                    "max-clicks",
                    "--target-action-price",
                    "159614149=200",
                ],
            )
        mock_update.assert_not_called()

    def test_rejects_malformed_target_action_price_value(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--target-action-price", "not-valid"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_non_integer_target_action_goal_id(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--target-action-price", "abc=200"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_non_numeric_target_action_price(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--target-action-price",
                "159614149=abc",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_duplicate_target_action_goal(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--target-action-price",
                "159614149=200",
                "--target-action-price",
                "159614149=300",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_documents_add_and_remove_target_action_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--add-target-action", result.output)
        self.assertIn("--remove-target-action", result.output)

    def test_passes_add_target_action(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--add-target-action",
                    "226158067=77",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["add_target_actions"], {226158067: 77.0}
        )

    def test_passes_multiple_add_target_actions(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--add-target-action",
                    "226158067=77",
                    "--add-target-action",
                    "267672143=50",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["add_target_actions"],
            {226158067: 77.0, 267672143: 50.0},
        )

    def test_passes_remove_target_action(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--remove-target-action", "159614149"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["remove_target_action_goal_ids"],
            [159614149],
        )

    def test_passes_multiple_remove_target_actions(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--remove-target-action",
                    "159614149",
                    "--remove-target-action",
                    "226158067",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["remove_target_action_goal_ids"],
            [159614149, 226158067],
        )

    def test_add_target_action_alone_is_a_valid_field(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--add-target-action", "226158067=77"],
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_remove_target_action_alone_is_a_valid_field(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--remove-target-action", "159614149"],
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_rejects_add_target_action_with_max_clicks(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--promotion-goal",
                "max-clicks",
                "--add-target-action",
                "226158067=77",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max-clicks", result.output)

    def test_rejects_remove_target_action_with_max_clicks(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--promotion-goal",
                "max-clicks",
                "--remove-target-action",
                "159614149",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max-clicks", result.output)

    def test_rejects_add_target_action_without_price(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--add-target-action", "226158067"],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("price is required", result.output)

    def test_rejects_non_integer_add_target_action_goal_id(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--add-target-action", "abc=77"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_non_numeric_add_target_action_price(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--add-target-action", "226158067=abc"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_non_integer_remove_target_action_goal_id(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--remove-target-action", "abc"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_duplicate_add_target_action_goal(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--add-target-action",
                "226158067=77",
                "--add-target-action",
                "226158067=88",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_duplicate_remove_target_action_goal(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--remove-target-action",
                "159614149",
                "--remove-target-action",
                "159614149",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_same_goal_in_target_action_price_and_add(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--target-action-price",
                "159614149=200",
                "--add-target-action",
                "159614149=77",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("159614149", result.output)

    def test_rejects_same_goal_in_add_and_remove(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--add-target-action",
                "159614149=77",
                "--remove-target-action",
                "159614149",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("159614149", result.output)

    def test_rejects_same_goal_in_target_action_price_and_remove(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--target-action-price",
                "159614149=200",
                "--remove-target-action",
                "159614149",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("159614149", result.output)

    def test_does_not_call_update_master_when_add_target_action_rejected(self):
        with patch("direct_cli.browser.masters.update_master") as mock_update:
            self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--promotion-goal",
                    "max-clicks",
                    "--add-target-action",
                    "226158067=77",
                ],
            )
        mock_update.assert_not_called()

    def test_passes_directs_helps_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--directs-helps"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(mock_update.call_args.kwargs["directs_helps"])

    def test_passes_no_directs_helps_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--no-directs-helps"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(mock_update.call_args.kwargs["directs_helps"])

    def test_errors_when_no_field_given(self):
        result = self.runner.invoke(cli, ["masters", "update", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at least one", result.output)

    def test_does_not_call_update_master_when_no_field_given(self):
        with patch("direct_cli.browser.masters.update_master") as mock_update:
            self.runner.invoke(cli, ["masters", "update", "42"])
        mock_update.assert_not_called()

    def test_documents_headline_and_text_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--headline", result.output)
        self.assertIn("--text", result.output)

    def test_passes_headline_slot_as_zero_based_index(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "2=Новый заголовок"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        # User-facing slot 2 (1-based) -> browser layer's 0-based index 1.
        self.assertEqual(
            mock_update.call_args.kwargs["headlines"], {1: "Новый заголовок"}
        )

    def test_passes_multiple_headline_and_text_slots(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--headline",
                    "1=Заголовок один",
                    "--headline",
                    "3=Заголовок три",
                    "--text",
                    "2=Текст два",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["headlines"],
            {0: "Заголовок один", 2: "Заголовок три"},
        )
        self.assertEqual(mock_update.call_args.kwargs["texts"], {1: "Текст два"})

    def test_headline_value_containing_equals_sign_splits_on_first_only(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--headline", "1=x=y=z"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["headlines"], {0: "x=y=z"})

    def test_rejects_headline_without_equals_sign(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=text"', result.output)

    def test_rejects_non_numeric_slot_number(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "abc=Текст"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("integer", result.output)

    def test_rejects_slot_number_below_one(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "0=Текст"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1 or greater", result.output)

    def test_rejects_duplicate_slot_number(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--headline",
                "1=Первый",
                "--headline",
                "1=Второй",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output)

    def test_format_errors_do_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "bogus"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_rejects_an_out_of_range_headline_slot(self):
        """``--headline "6=x"`` names a slot the edit page does not have.

        The edit page renders a FIXED 5 headline / 3 text slots, so an
        oversized slot number is a purely invalid CLI argument — it must be
        refused here, as a UsageError, not carried into a browser session
        only for ``_set_repeating_value`` to reject it as a
        BrowserSessionError after a Chromium launch and possible auth prompt.
        """
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "6=x"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-5", result.output)

    def test_rejects_an_out_of_range_text_slot(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--text", "4=x"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-3", result.output)

    def test_accepts_the_last_valid_slot_of_each_field(self):
        """The upper bound is inclusive — 5 headlines and 3 texts are valid."""
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--headline", "5=a", "--text", "3=b"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["headlines"], {4: "a"})
        self.assertEqual(mock_update.call_args.kwargs["texts"], {2: "b"})

    def test_out_of_range_slot_does_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "6=x"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_rejects_an_empty_headline_replacement(self):
        """``--headline "1="`` would DELETE variant 1, not replace it.

        Deleting a variant is explicitly out of scope for Этап B (issue
        #665), and the failure mode is silent: the slot gets cleared, the
        empty string typed, the form saved, and the post-save check compares
        the re-read slot against the requested value — both empty, so it
        matches and the delete is reported as a successful update.
        """
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "1="]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())

    def test_rejects_a_whitespace_only_text_replacement(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--text", "2=   "])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())

    def test_empty_replacement_does_not_open_a_browser_session(self):
        """The refusal must land before any live page is touched — an
        already-open edit page is a live, no-rollback mutation surface."""
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "1="]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_headline_flag_alone_satisfies_the_at_least_one_field_guard(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--headline", "1=Текст"]
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_documents_clear_headline_and_clear_text_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--clear-headline", result.output)
        self.assertIn("--clear-text", result.output)

    def test_passes_clear_headline_slot_as_zero_based_index(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--clear-headline", "2"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        # User-facing slot 2 (1-based) -> browser layer's 0-based index 1.
        self.assertEqual(mock_update.call_args.kwargs["clear_headlines"], [1])

    def test_passes_multiple_clear_headline_and_clear_text_slots(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--clear-headline",
                    "1",
                    "--clear-headline",
                    "3",
                    "--clear-text",
                    "2",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_update.call_args.kwargs["clear_headlines"], [0, 2])
        self.assertEqual(mock_update.call_args.kwargs["clear_texts"], [1])

    def test_rejects_non_numeric_clear_headline_slot(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--clear-headline", "abc"]
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_clear_headline_slot_below_one(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--clear-headline", "0"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1 or greater", result.output)

    def test_rejects_an_out_of_range_clear_headline_slot(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--clear-headline", "6"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-5", result.output)

    def test_rejects_an_out_of_range_clear_text_slot(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--clear-text", "4"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-3", result.output)

    def test_rejects_duplicate_clear_headline_slot(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--clear-headline",
                "1",
                "--clear-headline",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output)

    def test_rejects_same_slot_in_both_headline_and_clear_headline(self):
        """A slot cannot be both set and cleared in the same call — Yandex's
        edit page has no "set then clear" concept, and picking an order
        silently would make behaviour depend on an implementation detail."""
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--headline",
                "2=Новый заголовок",
                "--clear-headline",
                "2",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--headline", result.output)
        self.assertIn("--clear-headline", result.output)

    def test_rejects_same_slot_in_both_text_and_clear_text(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--text",
                "1=Новый текст",
                "--clear-text",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--text", result.output)
        self.assertIn("--clear-text", result.output)

    def test_clear_headline_flag_alone_satisfies_the_at_least_one_field_guard(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--clear-headline", "1"]
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_out_of_range_clear_slot_does_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--clear-headline", "6"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_omitted_clear_flags_pass_none_not_empty_list(self):
        """``clear_headlines``/``clear_texts`` must be ``None`` when not
        requested — ``update_master``'s own guard distinguishes "nothing
        passed" (falsy None/[]) consistently with every other optional
        list-shaped field here (e.g. ``add_audience_tags``)."""
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--weekly-budget", "1000"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(mock_update.call_args.kwargs["clear_headlines"])
        self.assertIsNone(mock_update.call_args.kwargs["clear_texts"])

    def test_documents_launch_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--launch", result.output)

    def test_launch_flag_defaults_to_false(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--weekly-budget", "1000"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(mock_update.call_args.kwargs["launch"])

    def test_passes_launch_flag(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                ["masters", "update", "42", "--weekly-budget", "1000", "--launch"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(mock_update.call_args.kwargs["launch"])

    def test_documents_image_flag(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--image", result.output)

    def test_image_uses_path_not_text_in_format_error(self):
        """--image must show its OWN vocabulary ("N=path"), not Этап B's
        "N=text" — regression guard for the shared parser's parameterization
        (issue #670): the two option's defaults must never bleed into each
        other."""
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--image", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=path"', result.output)
        self.assertNotIn('"N=text"', result.output)

    def test_headline_format_error_still_says_text_after_image_added(self):
        """The Этап B regression anchor itself, byte-for-byte — proves
        adding --image's overrides did not change --headline's defaults."""
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--headline", "no equals here"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('"N=text"', result.output)

    def test_rejects_a_nonexistent_image_path(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--image", "1=/no/such/file.png"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output.lower())

    def test_rejects_an_unsupported_image_extension(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", f"1={f.name}"]
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("unsupported extension", result.output.lower())

    def test_rejects_an_out_of_range_image_slot(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", f"6={f.name}"]
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("1-5", result.output)

    def test_rejects_an_empty_image_replacement(self):
        result = self.runner.invoke(cli, ["masters", "update", "42", "--image", "1="])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("empty", result.output.lower())
        self.assertNotIn("ad variant", result.output.lower())

    def test_image_format_errors_do_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", "bogus"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_nonexistent_image_path_does_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--image", "1=/no/such/file.png"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_image_flag_alone_satisfies_the_at_least_one_field_guard(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".png") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--image", f"1={f.name}"]
                )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_calls_update_master_with_parsed_images(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--image", f"2={f.name}"]
                )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(mock_update.call_args.kwargs["images"], {1: f.name})

    def test_documents_add_video_and_remove_video_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--add-video", result.output)
        self.assertIn("--remove-video", result.output)

    def test_rejects_a_nonexistent_video_path(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--add-video", "/no/such/file.mp4"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output.lower())

    def test_rejects_an_unsupported_video_extension(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--add-video", f.name]
            )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("unsupported extension", result.output.lower())

    def test_video_format_errors_do_not_open_a_browser_session(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--add-video", "/no/such/file.mp4"]
            )
        self.assertNotEqual(result.exit_code, 0)
        mock_with_session.assert_not_called()

    def test_add_video_flag_alone_satisfies_the_at_least_one_field_guard(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--add-video", f.name]
                )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_remove_video_flag_alone_satisfies_the_at_least_one_field_guard(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--remove-video",
                    "https://a.test/1.mp4",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)

    def test_calls_update_master_with_add_video_path(self):
        import tempfile

        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            with tempfile.NamedTemporaryFile(suffix=".mov") as f:
                result = self.runner.invoke(
                    cli, ["masters", "update", "42", "--add-video", f.name]
                )

                self.assertEqual(result.exit_code, 0, result.output)
                self.assertEqual(mock_update.call_args.kwargs["add_video"], f.name)
                self.assertIsNone(mock_update.call_args.kwargs["remove_videos"])

    def test_calls_update_master_with_remove_video_urls(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--remove-video",
                    "https://a.test/1.mp4",
                    "--remove-video",
                    "https://a.test/2.mp4",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            mock_update.call_args.kwargs["remove_videos"],
            ["https://a.test/1.mp4", "https://a.test/2.mp4"],
        )
        self.assertIsNone(mock_update.call_args.kwargs["add_video"])


class TestMastersAdimagesCommand(unittest.TestCase):
    """CLI wiring for `masters adimages get/add/delete/set`."""

    def setUp(self):
        self.runner = CliRunner()

    def test_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "--help"])
        self.assertEqual(result.exit_code, 0)
        for leaf in ("get", "add", "delete", "set"):
            self.assertIn(leaf, result.output)

    def test_get_help_registered(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_add_help_documents_image_file_and_launch(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "add", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--image-file", result.output)
        self.assertIn("--launch", result.output)

    def test_delete_help_documents_addressing_flags(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "delete", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--position", result.output)
        self.assertIn("--content-id", result.output)
        self.assertIn("--all", result.output)

    def test_set_help_documents_allow_empty(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "set", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--image-file", result.output)
        self.assertIn("--allow-empty", result.output)

    def test_get_calls_fetch_master_images(self):
        with (
            patch("direct_cli.browser.masters.fetch_master_images") as mock_fetch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_fetch.return_value = {"CampaignId": 42, "Images": [], "Count": 0}
            result = self.runner.invoke(cli, ["masters", "adimages", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.args[1], 42)

    def test_add_rejects_missing_file_before_any_session_opens(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "adimages",
                    "add",
                    "42",
                    "--image-file",
                    "/tmp/does-not-exist-xyz-123.png",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("does not exist", result.output)
        mock_with_session.assert_not_called()

    def test_add_rejects_unsupported_extension_before_any_session_opens(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".webp") as f,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            result = self.runner.invoke(
                cli, ["masters", "adimages", "add", "42", "--image-file", f.name]
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("unsupported extension", result.output)
        mock_with_session.assert_not_called()

    def test_add_rejects_more_files_than_the_cap_before_any_session_opens(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            args = ["masters", "adimages", "add", "42"]
            for i in range(6):
                args += ["--image-file", f"/tmp/{i}.png"]
            result = self.runner.invoke(cli, args)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cap", result.output.lower())
        mock_with_session.assert_not_called()

    def test_add_calls_add_master_images_with_paths_and_launch(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".jpg") as f,
            patch("direct_cli.browser.masters.add_master_images") as mock_add,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_add.return_value = {"CampaignId": 42, "Added": 1, "Count": 1}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "adimages",
                    "add",
                    "42",
                    "--image-file",
                    f.name,
                    "--launch",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_add.assert_called_once()
        args, kwargs = mock_add.call_args
        self.assertEqual(args[1], 42)
        self.assertEqual(kwargs["paths"], [f.name])
        self.assertTrue(kwargs["launch"])

    def test_delete_rejects_when_no_addressing_flag_given(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "delete", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at least one", result.output.lower())

    def test_delete_rejects_all_combined_with_position(self):
        result = self.runner.invoke(
            cli, ["masters", "adimages", "delete", "42", "--all", "--position", "1"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cannot be combined", result.output.lower())

    def test_delete_rejects_position_zero(self):
        result = self.runner.invoke(
            cli, ["masters", "adimages", "delete", "42", "--position", "0"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("out of range", result.output.lower())

    def test_delete_rejects_duplicate_positions(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "adimages",
                "delete",
                "42",
                "--position",
                "1",
                "--position",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output.lower())

    def test_delete_calls_delete_master_images_with_zero_based_positions(self):
        with (
            patch("direct_cli.browser.masters.delete_master_images") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 42, "Deleted": 1, "Count": 1}
            result = self.runner.invoke(
                cli,
                ["masters", "adimages", "delete", "42", "--position", "2"],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = mock_delete.call_args.kwargs
        self.assertEqual(kwargs["positions"], [1])
        self.assertIsNone(kwargs["content_ids"])
        self.assertFalse(kwargs["all_images"])

    def test_delete_calls_delete_master_images_with_all(self):
        with (
            patch("direct_cli.browser.masters.delete_master_images") as mock_delete,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_delete.return_value = {"CampaignId": 42, "Deleted": 3, "Count": 0}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "delete", "42", "--all"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = mock_delete.call_args.kwargs
        self.assertTrue(kwargs["all_images"])

    def test_set_rejects_no_files_without_allow_empty(self):
        result = self.runner.invoke(cli, ["masters", "adimages", "set", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("allow-empty", result.output.lower())
        self.assertIn("delete --all", result.output)

    def test_set_with_allow_empty_calls_set_master_images_with_no_paths(self):
        with (
            patch("direct_cli.browser.masters.set_master_images") as mock_set,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_set.return_value = {"CampaignId": 42, "Count": 0}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "set", "42", "--allow-empty"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_set.call_args.kwargs["paths"], [])

    def test_set_calls_set_master_images_with_paths(self):
        import tempfile

        with (
            tempfile.NamedTemporaryFile(suffix=".png") as f,
            patch("direct_cli.browser.masters.set_master_images") as mock_set,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_set.return_value = {"CampaignId": 42, "Count": 1}
            result = self.runner.invoke(
                cli, ["masters", "adimages", "set", "42", "--image-file", f.name]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_set.call_args.kwargs["paths"], [f.name])

    def test_set_rejects_more_files_than_the_cap(self):
        with patch("direct_cli.commands.masters._with_session") as mock_with_session:
            args = ["masters", "adimages", "set", "42"]
            for i in range(6):
                args += ["--image-file", f"/tmp/{i}.png"]
            result = self.runner.invoke(cli, args)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("cap", result.output.lower())
        mock_with_session.assert_not_called()


class TestMastersTargetActionsCommand(unittest.TestCase):
    """CLI wiring for `masters targetactions get` (issue #707)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "targetactions", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("get", result.output)

    def test_get_help_registered(self):
        result = self.runner.invoke(cli, ["masters", "targetactions", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_get_calls_fetch_master_target_actions(self):
        with (
            patch(
                "direct_cli.browser.masters.fetch_master_target_actions"
            ) as mock_fetch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_fetch.return_value = {
                "CampaignId": 42,
                "TargetActions": [],
                "Count": 0,
            }
            result = self.runner.invoke(cli, ["masters", "targetactions", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.args[1], 42)


class TestMastersCountersCommand(unittest.TestCase):
    """CLI wiring for `masters counters get` (issue #842)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_group_registered(self):
        result = self.runner.invoke(cli, ["masters", "counters", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("get", result.output)

    def test_get_help_registered(self):
        result = self.runner.invoke(cli, ["masters", "counters", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_get_calls_fetch_master_metrika_counters(self):
        with (
            patch(
                "direct_cli.browser.masters.fetch_master_metrika_counters"
            ) as mock_fetch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_fetch.return_value = {
                "CampaignId": 42,
                "SectionPresent": True,
                "Counters": [],
                "Count": 0,
            }
            result = self.runner.invoke(cli, ["masters", "counters", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_fetch.assert_called_once()
        self.assertEqual(mock_fetch.call_args.args[1], 42)


class TestParseMetrikaCounterTag(unittest.TestCase):
    """``_parse_metrika_counter_tag`` (issue #842).

    Live-confirmed tag shape (campaign 713234204): two lines,
    ``"gc.ksamata.ru • 72112213\\n30 целей"``. Note this is NOT the
    autocomplete shape ``--add-metrika-counter`` matches, which also
    carries a leading label.
    """

    def test_parses_live_confirmed_shape(self):
        parsed = browser_masters._parse_metrika_counter_tag(
            "gc.ksamata.ru • 72112213\n30 целей"
        )

        self.assertEqual(parsed["CounterId"], 72112213)
        self.assertEqual(parsed["Domain"], "gc.ksamata.ru")
        self.assertEqual(parsed["Text"], "gc.ksamata.ru • 72112213\n30 целей")

    def test_unparsed_tag_still_returns_text(self):
        # The pre-hydration value is a bare id with no separator (measured
        # at t+0ms). Parsing must degrade, never raise — the raw text is
        # still useful output.
        parsed = browser_masters._parse_metrika_counter_tag("72112213")

        self.assertIsNone(parsed["CounterId"])
        self.assertIsNone(parsed["Domain"])
        self.assertEqual(parsed["Text"], "72112213")

    def test_handles_autocomplete_style_three_part_text(self):
        parsed = browser_masters._parse_metrika_counter_tag(
            "Ксамата Директ • gc.ksamata.ru • 72112213"
        )

        self.assertEqual(parsed["CounterId"], 72112213)
        self.assertEqual(parsed["Domain"], "gc.ksamata.ru")


class TestMastersLoginCommand(unittest.TestCase):
    """CLI wiring for `masters login` (issue #635)."""

    def setUp(self):
        self.runner = CliRunner()
        # CliRunner supplies a non-tty stdin, so `login` would refuse to run
        # (it needs a human). Every test here exercises the interactive path;
        # the non-interactive refusal has its own test that overrides this.
        tty = patch(
            "direct_cli.commands.masters._stdin_is_interactive", return_value=True
        )
        tty.start()
        self.addCleanup(tty.stop)

    def test_login_registered(self):
        result = self.runner.invoke(cli, ["masters", "login", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_login_fails_fast_in_a_non_interactive_environment(self):
        """In CI/a script, fail immediately instead of blocking for the timeout.

        Issue #635 (Риски → Интерактивность): the command waits for a human, so
        run non-interactively it must "падать сразу с понятным текстом, а не
        висеть" — otherwise CI hangs for the full --timeout on a browser window
        nobody can see.
        """
        with patch("direct_cli.browser.session.login_persistent_session") as login_fn:
            with patch(
                "direct_cli.commands.masters._stdin_is_interactive",
                return_value=False,
            ):
                result = self.runner.invoke(cli, ["masters", "login"])

        login_fn.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertIn("interactive", result.output.lower())

    def test_login_has_no_output_format_options(self):
        # login is interactive/side-effecting, not a data-fetching command --
        # it has no --format/--output, unlike list/get/suspend/resume.
        result = self.runner.invoke(cli, ["masters", "login", "--help"])
        self.assertNotIn("--format", result.output)

    def test_login_calls_login_persistent_session(self):
        with patch("direct_cli.browser.session.login_persistent_session") as mock_login:
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_login.assert_called_once()
        _, kwargs = mock_login.call_args
        self.assertEqual(kwargs["timeout_ms"], 300_000)
        self.assertIsNone(kwargs["profile_dir"])

    def test_login_passes_explicit_profile_dir_and_timeout(self):
        with patch("direct_cli.browser.session.login_persistent_session") as mock_login:
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "login",
                    "--profile-dir",
                    "/custom/profile",
                    "--timeout",
                    "30",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_login.call_args
        self.assertEqual(kwargs["profile_dir"], Path("/custom/profile"))
        self.assertEqual(kwargs["timeout_ms"], 30_000)

    def test_login_converts_browser_session_error_to_click_exception(self):
        from direct_cli.browser.session import BrowserAuthError

        with patch(
            "direct_cli.browser.session.login_persistent_session",
            side_effect=BrowserAuthError("timed out"),
        ):
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("timed out", result.output)

    def test_login_missing_playwright_raises_usage_error(self):
        with patch.dict(
            "sys.modules", {"playwright": None, "playwright.sync_api": None}
        ):
            result = self.runner.invoke(cli, ["masters", "login"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("playwright", result.output.lower())


class TestMastersLogoutCommand(unittest.TestCase):
    """CLI wiring for `masters logout` (issue #635 risk: revocation)."""

    def setUp(self):
        self.runner = CliRunner()
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.profile_dir = Path(self._tmpdir.name) / "chrome-profile"

        # Keep the login pointer off the developer's real ~/.direct-cli.
        pointer = patch(
            "direct_cli.browser.session.PROFILE_POINTER_PATH",
            Path(self._tmpdir.name) / "chrome-profile-path",
        )
        pointer.start()
        self.addCleanup(pointer.stop)

    def _make_profile(self):
        """Create a profile dir the way `masters login` does — marker included."""
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        self.profile_dir.mkdir(parents=True)
        (self.profile_dir / PROFILE_MARKER_NAME).touch()

    def test_logout_registered(self):
        result = self.runner.invoke(cli, ["masters", "logout", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_logout_deletes_existing_profile(self):
        self._make_profile()
        (self.profile_dir / "Cookies").write_text("fake")

        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(self.profile_dir)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_is_a_noop_warning_when_no_profile_exists(self):
        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(self.profile_dir)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_uses_default_persistent_profile_dir_when_unset(self):
        with patch(
            "direct_cli.browser.session.DEFAULT_PERSISTENT_PROFILE_DIR",
            self.profile_dir,
        ):
            self._make_profile()
            result = self.runner.invoke(cli, ["masters", "logout"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(self.profile_dir.exists())

    def test_logout_refuses_a_directory_it_did_not_create(self):
        """`--profile-dir` pointing at an unrelated directory must not be deleted.

        Codex review finding on PR #644: `logout` passes whatever `--profile-dir`
        resolves to straight into `shutil.rmtree`, with no check that the target
        is actually a profile this CLI created. A typo or a shell-expanded `.`
        therefore recursively deletes an arbitrary tree.

        `shutil.rmtree` is patched, so this test never deletes anything for real —
        it only records the path the command *would* have destroyed.
        """
        victim = Path(self._tmpdir.name) / "not-a-profile"
        victim.mkdir(parents=True)
        (victim / "important.txt").write_text("user data")

        with patch("shutil.rmtree") as rmtree:
            result = self.runner.invoke(
                cli, ["masters", "logout", "--profile-dir", str(victim)]
            )

        rmtree.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertTrue(victim.exists())

    def test_logout_refuses_a_symlinked_profile_dir(self):
        """A symlink would let rmtree escape the directory the user named."""
        self._make_profile()
        link = Path(self._tmpdir.name) / "link-to-profile"
        link.symlink_to(self.profile_dir, target_is_directory=True)

        with patch("shutil.rmtree") as rmtree:
            result = self.runner.invoke(
                cli, ["masters", "logout", "--profile-dir", str(link)]
            )

        rmtree.assert_not_called()
        self.assertNotEqual(result.exit_code, 0, result.output)
        self.assertTrue(self.profile_dir.exists())

    def test_logout_explicit_profile_dir_does_not_clear_pointer_to_a_different_profile(
        self,
    ):
        """`logout --profile-dir A` must not wipe the pointer to a live profile B.

        `logout` unconditionally unlinks PROFILE_POINTER_PATH after deleting
        whatever `--profile-dir` resolved to. If the user logged into profile B
        (recorded by the pointer) after an older profile A, then deletes A by
        explicit path, the pointer to B — still on disk and in use — is wiped
        too. The next read then falls back to the default location instead of B.
        """
        from direct_cli.browser.session import PROFILE_MARKER_NAME

        old_profile = self.profile_dir  # profile A: about to be deleted
        self._make_profile()

        live_profile = Path(self._tmpdir.name) / "chrome-profile-b"
        live_profile.mkdir(parents=True)
        (live_profile / PROFILE_MARKER_NAME).touch()

        from direct_cli.browser import session as session_module

        session_module.remember_persistent_profile_dir(live_profile)

        result = self.runner.invoke(
            cli, ["masters", "logout", "--profile-dir", str(old_profile)]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertFalse(old_profile.exists())
        self.assertTrue(live_profile.exists(), "unrelated live profile was deleted")
        self.assertEqual(
            session_module.configured_persistent_profile_dir(),
            live_profile.resolve(),
            "logout on an unrelated profile cleared the pointer to the live one",
        )


class TestCaptchaDetection(unittest.TestCase):
    def test_assert_not_captcha_raises_on_gate_markers(self):
        from direct_cli.browser.session import assert_not_captcha

        for marker_html in (
            "<html>showCaptcha(...)</html>",
            "<script>smartCaptcha.render()</script>",
            "<title>Captcha</title>",
        ):
            with self.assertRaises(BrowserCaptchaError):
                assert_not_captcha(marker_html)

    def test_assert_not_captcha_passes_on_real_content(self):
        from direct_cli.browser.session import assert_not_captcha

        # Must not raise.
        assert_not_captcha("<html><body>Кампания остановлена</body></html>")

    def test_fetch_masters_list_raises_on_captcha_page(self):
        # A live SmartCaptcha gate is served as an ordinary 200 HTML page, so
        # page.goto() itself never raises — fetch_masters_list must check the
        # rendered content and surface BrowserCaptchaError explicitly, per
        # issue #628 risk item 5 ("не молча падать" — never fail silently).
        page = FakePage(locators={}, html="<title>Captcha</title>")

        with self.assertRaises(BrowserCaptchaError):
            browser_masters.fetch_masters_list(page)

    def test_fetch_master_raises_on_captcha_page(self):
        page = FakePage(locators={}, html="<script>smartCaptcha.render()</script>")

        with self.assertRaises(BrowserCaptchaError):
            browser_masters.fetch_master(page, 1)


class TestAuthDetection(unittest.TestCase):
    """#634: decrypted cookies can still represent an expired/wrong session —
    detect Yandex's login page explicitly instead of relying on a timeout."""

    def test_assert_authenticated_raises_on_login_page(self):
        from direct_cli.browser.session import BrowserAuthError, assert_authenticated

        for marker_html in (
            "<html>redirecting to passport.yandex.ru/auth?...</html>",
            "<body>Войдите с Яндекс ID</body>",
        ):
            with self.assertRaises(BrowserAuthError):
                assert_authenticated(marker_html)

    def test_assert_authenticated_raises_on_current_pwl_yandex_login_page(self):
        # Live re-recon 2026-08-02 (issue #666): Yandex Passport's login page
        # has migrated from /auth to /pwl-yandex, and no longer renders the
        # "Войдите с Яндекс ID" text anywhere in the HTML — confirmed via a
        # real open_saved_session() + goto(GRID_URL) against an actual
        # expired/invalid saved session. Both #634 markers went stale at the
        # same time, so assert_authenticated silently passed a real login
        # page through as "authenticated", turning an expired session into
        # an opaque `masters list` timeout ("waiting for event 'response'")
        # instead of a clear BrowserAuthError.
        from direct_cli.browser.session import BrowserAuthError, assert_authenticated

        html = (
            "<title>Авторизация</title>"
            "<script>window.__CONSTANTS__ = {'baseUrl':'/pwl-yandex',"
            "'authUrl':'https://passport.yandex.ru/pwl-yandex?retpath=..."
            "&origin=direct', ...};</script>"
        )
        with self.assertRaises(BrowserAuthError):
            assert_authenticated(html)

    def test_assert_authenticated_passes_on_real_content(self):
        from direct_cli.browser.session import assert_authenticated

        # Must not raise.
        assert_authenticated("<html><body>Кампания остановлена</body></html>")

    def test_fetch_masters_list_raises_on_login_page(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with self.assertRaises(BrowserAuthError):
            browser_masters.fetch_masters_list(page)

    def test_fetch_master_raises_on_login_page(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with self.assertRaises(BrowserAuthError):
            browser_masters.fetch_master(page, 1)

    def test_fetch_masters_list_login_page_not_masked_without_playwright(self):
        # CI's "quality" job runs the offline suite without the playwright
        # package installed, so PlaywrightError falls back to bare Exception
        # (see the import fallback in direct_cli/browser/masters.py). Once
        # _capture_grid_campaigns_request's whole `with page.expect_response`
        # block (goto/assert_* included) moved inside one try/except
        # PlaywrightError (issue #694 fix), that broad except-Exception
        # fallback started swallowing assert_authenticated's BrowserAuthError
        # too, relabelling it as the generic "could not observe the grid's
        # data request" timeout error instead of letting it propagate --
        # confirmed live on CI (PR #698). Simulate the no-playwright fallback
        # here directly so this regression is caught locally too, regardless
        # of whether playwright happens to be installed in the dev env.
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        from direct_cli.browser.session import BrowserAuthError

        with patch.object(browser_masters, "PlaywrightError", Exception):
            with self.assertRaises(BrowserAuthError):
                browser_masters.fetch_masters_list(page)

    def test_fetch_masters_list_waits_for_commit_not_networkidle(self):
        # #634: networkidle never settles on Yandex's login page (it holds
        # long-poll connections), which is what turned an auth failure into
        # an opaque 30s timeout instead of a clear error. #682: the grid's
        # own document.readyState never advances past "interactive" either,
        # so domcontentloaded itself was timing out — commit is the
        # earliest wait_until that still lets expect_response observe the
        # navigation. Guard against a silent regression back to
        # networkidle/domcontentloaded. (No captured grid response here ->
        # raises BrowserSessionError right after the goto assertion, which
        # is all this test needs to observe.)
        page = FakePage(locators={})
        with self.assertRaises(BrowserSessionError):
            browser_masters.fetch_masters_list(page)
        self.assertEqual(page.goto_wait_until, "commit")

    def test_fetch_master_uses_commit_not_domcontentloaded(self):
        # #683: domcontentloaded raced the overview page's client-rendered
        # header (live-confirmed intermittent "Could not read campaign name"
        # against campaign 72349978) -- _goto_overview_page now uses
        # wait_until="commit" and polls for the header marker itself instead
        # of trusting an implicit DOM-ready signal. fetch_master navigates to
        # the wizard overview page, not the grid
        # (_capture_grid_campaigns_request) — out of scope for #682, which
        # only touches the grid's own goto.
        page = FakePage(locators={})
        browser_masters.fetch_master(page, 1)
        self.assertEqual(page.goto_wait_until, "commit")


class TestGotoOverviewPage(unittest.TestCase):
    """_goto_overview_page (issue #683): the shared wait every wizard
    overview entry point (get/suspend/resume/archive/copy) now goes through.

    domcontentloaded raced the overview page's client-rendered header --
    live-confirmed intermittent "Could not read campaign name" against
    campaign 72349978 while status/landing-URL/stats all read back fine.
    wait_until="commit" plus an explicit poll for
    _OVERVIEW_TITLE_SELECTOR (the "<h2 data-testid=CampaignHeader.Title>"
    element, confirmed live present on BOTH DRAFT and non-DRAFT overview
    pages, unlike _MENU_TRIGGER_SELECTOR which #660 found absent on DRAFT)
    replaces it.
    """

    def test_every_overview_entry_point_uses_commit(self):
        # fetch_master (get), _suspend_or_resume (suspend/resume),
        # archive_master, and copy_master all navigate through
        # _goto_overview_page -- each must request wait_until="commit", not
        # domcontentloaded (#683).
        page = FakePage(locators={})
        browser_masters.fetch_master(page, 1)
        self.assertEqual(page.goto_wait_until, "commit")

        page = FakePage(body_text="Кампания активна")
        browser_masters.resume_master(page, 1)
        self.assertEqual(page.goto_wait_until, "commit")

        page = FakePage(
            locators={
                browser_masters._MENU_TRIGGER_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._ARCHIVE_MENU_ITEM_SELECTOR: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
            },
            # The TOCTOU re-check (issue #797) reads the overview page's own
            # status text (_read_status_text), not fetch_masters_list -- see
            # _reverify_status_or_raise's docstring.
            body_text="Кампания остановлена",
        )
        # "SUSPENDED" (not the raw grid "STOPPED") -- fetch_masters_list
        # itself normalizes STOPPED -> SUSPENDED before archive_master ever
        # sees a row (_PRIMARY_STATUS_TO_CLI_STATUS), so the fixture must
        # match what the real function returns. Two entries: the up-front
        # guard, and the post-click verify poll (the TOCTOU re-check itself
        # reads the overview page's body text above, not this mock).
        _row = {
            "CampaignId": 1,
            "Name": "x",
            "Status": "SUSPENDED",
            "Type": "TEXT",
            "StartDate": "2025-01-01",
        }
        with patch(
            "direct_cli.browser.masters.fetch_masters_list",
            side_effect=[
                [_row],
                [{**_row, "Status": "ARCHIVED"}],
            ],
        ):
            browser_masters.archive_master(page, 1)
        self.assertEqual(page.goto_wait_until, "commit")

    def test_waits_for_title_marker_before_returning(self):
        # A page whose header hasn't rendered yet on the first poll tick
        # must not be treated as ready -- mirrors _wait_for_images_editor's
        # own "stub state" guard (#670).
        remaining = {"ticks": 2}
        title_selector = browser_masters._OVERVIEW_TITLE_SELECTOR

        class _SlowHeaderPage(FakePage):
            def locator(self, selector):
                if selector == title_selector:
                    if remaining["ticks"] > 0:
                        remaining["ticks"] -= 1
                        return _FakeLocator([])
                    return _FakeLocator([_FakeLocatorHandle()])
                return super().locator(selector)

        page = _SlowHeaderPage(locators={})

        browser_masters.fetch_master(page, 1)  # must not raise

        self.assertEqual(remaining["ticks"], 0)

    def test_raises_when_title_marker_never_appears(self):
        # A DRAFT campaign's overview page has no _MENU_TRIGGER_SELECTOR
        # (issue #660, not fixed here) -- archive_master/copy_master still
        # fail on it, but as a clear bounded timeout, not an indefinite
        # hang. Simulated here via a header that never renders at all.
        page = FakePage(locators={})
        del page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR]

        with patch.object(browser_masters, "_OVERVIEW_LOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._goto_overview_page(page, 999)

        self.assertIn("did not render within", str(ctx.exception))
        self.assertIn("999", str(ctx.exception))

    def test_reports_captcha_immediately_without_waiting_out_the_timeout(self):
        # A captcha gate is reported via its own specific error as soon as
        # it's detected, rather than only after burning the full
        # _OVERVIEW_LOAD_TIMEOUT_MS waiting for a header a captcha page will
        # never render.
        page = FakePage(
            locators={},
            html="<script>smartCaptcha.render()</script>",
        )
        del page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR]

        with self.assertRaises(BrowserCaptchaError):
            browser_masters._goto_overview_page(page, 1)

    def test_reports_auth_failure_immediately_without_waiting_out_the_timeout(self):
        page = FakePage(locators={}, html="<body>Войдите с Яндекс ID</body>")
        del page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR]

        with self.assertRaises(BrowserAuthError):
            browser_masters._goto_overview_page(page, 1)

    def test_captcha_appearing_mid_poll_raises_not_swallowed_as_timeout(self):
        # cycle-review #697 finding (claude/review): a captcha gate that
        # appears AFTER the upfront check (e.g. the session expires while
        # waiting) must still surface as BrowserCaptchaError, not be
        # swallowed as "not yet ready" and reported as a generic render
        # timeout. Mirrors _wait_for_edit_form's own
        # _edit_form_terminal_state pattern (#689): the captcha/auth check
        # must live outside _poll_until's suppressed predicate.
        #
        # PlaywrightError is patched to the real playwright.sync_api.Error
        # here to exercise the exact runtime configuration where the bug
        # bites: with playwright installed, BrowserCaptchaError/
        # BrowserAuthError are NOT subclasses of PlaywrightError, so
        # contextlib.suppress(PlaywrightError) can't hide them regardless
        # of where the check lives -- the swallow only happens when
        # PlaywrightError is aliased to the bare Exception (the
        # no-playwright offline fallback, masters.py's own import
        # try/except), which every raise is a subclass of.
        html_sequence = iter(
            ["<html></html>", "<script>smartCaptcha.render()</script>"]
        )

        class _CaptchaAfterFirstTickPage(FakePage):
            def content(self):
                return next(html_sequence, "<script>smartCaptcha.render()</script>")

        page = _CaptchaAfterFirstTickPage(locators={})
        del page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR]

        with patch.object(browser_masters, "PlaywrightError", Exception):
            with self.assertRaises(BrowserCaptchaError):
                browser_masters._goto_overview_page(page, 1)

    def test_auth_failure_appearing_mid_poll_raises_not_swallowed_as_timeout(self):
        # Same fix, auth-error variant (cycle-review #697 finding). See the
        # sibling captcha test above for why PlaywrightError is patched to
        # the bare Exception.
        html_sequence = iter(["<html></html>", "<body>Войдите с Яндекс ID</body>"])

        class _AuthFailureAfterFirstTickPage(FakePage):
            def content(self):
                return next(html_sequence, "<body>Войдите с Яндекс ID</body>")

        page = _AuthFailureAfterFirstTickPage(locators={})
        del page._locators[browser_masters._OVERVIEW_TITLE_SELECTOR]

        with patch.object(browser_masters, "PlaywrightError", Exception):
            with self.assertRaises(BrowserAuthError):
                browser_masters._goto_overview_page(page, 1)


class TestBrowserSessionErrors(unittest.TestCase):
    def test_browser_captcha_error_is_a_browser_session_error(self):
        self.assertTrue(issubclass(BrowserCaptchaError, BrowserSessionError))

    def test_browser_auth_error_is_a_browser_session_error(self):
        from direct_cli.browser.session import BrowserAuthError

        self.assertTrue(issubclass(BrowserAuthError, BrowserSessionError))

    def test_chrome_cookie_error_is_a_browser_session_error(self):
        from direct_cli.browser.session import ChromeCookieError

        self.assertTrue(issubclass(ChromeCookieError, BrowserSessionError))


class TestFillLandingUrl(unittest.TestCase):
    """``_fill_landing_url`` (issue #632, re-recon issues #650/#690) — step
    1's URL field, then either a matching suggestion or "Далее".

    The URL field and the "Далее" button are located via ``page.locator(...)``
    on their ``data-testid`` (issue #650 re-recon, 2026-08-02) — Yandex
    replaced the plain ``<input placeholder="...">`` with a Combobox whose
    text control is a ``contenteditable`` ``<div role="textbox">`` that
    ``get_by_placeholder()``/``get_by_role()`` can no longer find the same
    way.

    Issue #690 re-recon (2026-08-04, live): typing a URL Yandex recognises
    from the account's own suggestion history renders a
    ``CampaignFormUrl.listBox.<url>`` option INSTEAD of enabling the "Далее"
    button (whose ``data-testid`` is then absent from the DOM entirely) —
    clicking that option is enough to advance, no "Далее" click needed. A
    URL with no such match only ever gets the button.
    """

    def _page(
        self,
        url_state=None,
        next_clicks=None,
        error_visible=False,
        matching_option=None,
        option_clicks=None,
        field_handle=None,
        unrelated_option=None,
    ):
        url_state = url_state if url_state is not None else {}
        next_clicks = next_clicks if next_clicks is not None else []
        option_clicks = option_clicks if option_clicks is not None else []
        field = field_handle or _FakeContentEditableHandle(
            on_fill=lambda v: url_state.__setitem__("url", v)
        )
        next_button = _FakeLocatorHandle(on_click=lambda: next_clicks.append(True))
        locators = {
            browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator([field]),
            browser_masters._CREATE_NEXT_BUTTON_TESTID: _FakeLocator(
                [] if matching_option else [next_button]
            ),
        }
        if matching_option:
            option_handle = _FakeLocatorHandle(
                on_click=lambda: option_clicks.append(True)
            )
            locators[f'[data-testid="CampaignFormUrl.listBox.{matching_option}"]'] = (
                _FakeLocator([option_handle])
            )
        if unrelated_option:
            # Confirmed live: a URL with no EXACT suggestion match still
            # renders the popup (unrelated history) while "Далее" is also
            # present and enabled — see _fill_landing_url's docstring.
            locators[f'[data-testid="CampaignFormUrl.listBox.{unrelated_option}"]'] = (
                _FakeLocator([_FakeLocatorHandle()])
            )
        return FakePage(
            locators=locators,
            text_buttons={
                browser_masters._CREATE_INVALID_URL_TEXT: _FakeGetByTextLocator(
                    [_FakeTextLocatorHandle()] if error_visible else []
                ),
            },
        )

    def test_fills_field_and_clicks_next_when_no_suggestion_matches(self):
        url_state = {}
        next_clicks = []
        page = self._page(url_state=url_state, next_clicks=next_clicks)

        browser_masters._fill_landing_url(page, "https://ksamata.ru/")

        self.assertEqual(url_state["url"], "https://ksamata.ru/")
        self.assertEqual(len(next_clicks), 1)

    def test_clicks_matching_suggestion_instead_of_next_button(self):
        """Issue #690: a history match renders a listBox option and the
        "Далее" button's own data-testid is absent — clicking the option is
        the only way to advance, and "Далее" must never be clicked."""
        url_state = {}
        next_clicks = []
        option_clicks = []
        page = self._page(
            url_state=url_state,
            next_clicks=next_clicks,
            matching_option="https://ksamata.ru",
            option_clicks=option_clicks,
        )

        browser_masters._fill_landing_url(page, "https://ksamata.ru/")

        self.assertEqual(len(option_clicks), 1)
        self.assertEqual(len(next_clicks), 0)

    def test_clicks_matching_suggestion_ignoring_trailing_slash(self):
        """Confirmed live: Yandex stores the suggestion WITHOUT the trailing
        slash the campaign's real URL has — the typed URL (with slash) must
        still match it."""
        option_clicks = []
        page = self._page(
            matching_option="https://ksamata.ru",  # no trailing slash
            option_clicks=option_clicks,
        )

        browser_masters._fill_landing_url(page, "https://ksamata.ru/")

        self.assertEqual(len(option_clicks), 1)

    def test_does_not_match_suggestion_by_stripping_a_path_trailing_slash(self):
        """A suggestion for a DIFFERENT path (``/sale`` without the slash)
        must never be treated as a match for ``/sale/`` — only the bare
        domain-root case (confirmed live) drops the trailing slash. Matching
        on path/query would risk launching against an unintended destination
        (Codex review, PR #703 round 1)."""
        next_clicks = []
        page = self._page(
            next_clicks=next_clicks,
            unrelated_option="https://site.ru/sale",  # no trailing slash
        )

        browser_masters._fill_landing_url(page, "https://site.ru/sale/")

        self.assertEqual(len(next_clicks), 1)

    def test_does_not_match_suggestion_by_stripping_a_query_trailing_slash(self):
        """Same risk as the path case, but for a query value ending in "/":
        ``urlsplit(url).path`` alone is "/" here even though the URL is NOT
        a bare domain root — the query must also be empty before stripping
        (Codex review, PR #703 round 2)."""
        next_clicks = []
        page = self._page(
            next_clicks=next_clicks,
            unrelated_option="https://site.ru/?next=",  # no trailing slash
        )

        browser_masters._fill_landing_url(page, "https://site.ru/?next=/")

        self.assertEqual(len(next_clicks), 1)

    def test_raises_when_url_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._fill_landing_url(page, "https://ksamata.ru/")

    def test_raises_when_neither_suggestion_nor_button_appears(self):
        page = FakePage(
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator(
                    [_FakeContentEditableHandle()]
                ),
            },
        )

        with (
            patch.object(browser_masters, "_CREATE_URL_RESPONSE_TIMEOUT_MS", 1),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._fill_landing_url(page, "https://ksamata.ru/")

    def test_raises_on_invalid_url_format_error(self):
        page = self._page(error_visible=True)

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._fill_landing_url(page, "not-a-valid-url")
        self.assertIn("malformed", str(ctx.exception))

    def test_retries_typing_when_widget_drops_characters(self):
        """Issue #690: the real Combobox intermittently drops characters
        from the typed URL — this asserts _fill_landing_url actually
        notices via a text_content() mismatch and retries rather than
        silently proceeding with a mangled value."""
        field = _FakeContentEditableHandle(supports_modifier=True)
        # First type() call is deliberately mangled (drops "ksamata"); the
        # SECOND call (after _clear_text_field) types correctly - modelled
        # by overriding .type() to mangle only the first invocation.
        original_type = field.type
        call_count = {"n": 0}

        def _flaky_type(value, delay=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                original_type(value.replace("ksamata", ""), delay=delay)
            else:
                original_type(value, delay=delay)

        field.type = _flaky_type
        page = self._page(field_handle=field)

        browser_masters._fill_landing_url(page, "https://ksamata.ru/")

        self.assertEqual(call_count["n"], 2)
        self.assertEqual(field.text_content(), "https://ksamata.ru/")

    def test_raises_when_widget_never_stops_dropping_characters(self):
        field = _FakeContentEditableHandle()
        original_type = field.type
        field.type = lambda value, delay=None: original_type("garbled", delay=delay)
        page = self._page(field_handle=field)

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._fill_landing_url(page, "https://ksamata.ru/")
        self.assertIn("dropping keystrokes", str(ctx.exception))


class TestWaitForStep2(unittest.TestCase):
    """``_wait_for_step2`` (issue #632, re-recon #690) — polls for the first
    headline slot (``CampaignTitles0.textarea``), not the "Регион показов"
    heading this used before: issue #690 re-recon (2026-08-04) found the
    region picker no longer renders at all on a fully-loaded step 2 in the
    account tested — its data-testids and heading text were both completely
    absent.
    """

    def _step2_ready_selector(self):
        return f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'

    def test_returns_once_first_headline_slot_present(self):
        page = FakePage(
            locators={
                self._step2_ready_selector(): _FakeLocator([_FakeLocatorHandle()])
            }
        )

        browser_masters._wait_for_step2(page)  # must not raise

    def test_raises_when_marker_never_appears(self):
        page = FakePage(locators={})

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._wait_for_step2(page)

    def test_timeout_message_says_the_page_is_still_on_step_1(self):
        # Issue #653: which step the page is stuck on changes the diagnosis
        # entirely, and re-running --headful just to find out is expensive on
        # a page with no sandbox — so the error must say it. Step 1's URL
        # field still being in the DOM means the form never advanced.
        page = FakePage(
            locators={
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                )
            },
        )

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._wait_for_step2(page)
        self.assertIn("still showing step 1", str(ctx.exception))

    def test_timeout_message_says_the_page_left_step_1(self):
        # The other branch: step 1's URL field is gone, so step 2 rendered but
        # without the expected first headline slot — that points at a markup
        # change.
        page = FakePage(locators={})

        with (
            patch.object(browser_masters, "_CREATE_STEP2_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._wait_for_step2(page)
        self.assertIn("has left step 1", str(ctx.exception))


class TestAddRepeatingValues(unittest.TestCase):
    """``_add_repeating_values`` (issue #632, re-recon #653) — headline/text
    fixed-slot entry.

    Issue #653 re-recon (2026-08-02): Yandex replaced the old "single
    current-variant input, fill + Enter" flow with a FIXED set of
    pre-rendered contenteditable ``<div role="textbox">`` slots, each its
    own ``data-testid`` (``CampaignTitles{N}.textarea`` etc.) — so the fake
    now keys ``page._locators`` by per-slot selector, and the function
    types via ``.click()`` + ``.type()`` (contenteditable divs have no
    ``.fill()``/Enter-to-submit semantics) instead of pressing Enter.
    """

    def test_types_into_each_slot_by_index(self):
        typed = []
        handles = {
            0: _FakeLocatorHandle(on_fill=lambda v: typed.append((0, v))),
            1: _FakeLocatorHandle(on_fill=lambda v: typed.append((1, v))),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 2, ["Заголовок 1", "Заголовок 2"]
        )

        self.assertEqual(typed, [(0, "Заголовок 1"), (1, "Заголовок 2")])

    def test_clears_each_slot_before_typing(self):
        """Slots arrive PRE-FILLED with Yandex's AI copy (issue #653).

        ``.type()`` appends from wherever the click left the caret, so
        without an explicit clear the caller's value is spliced into the
        middle of Yandex's text — confirmed live as
        ``'Центр оздоровления и китайско<typed>й гимнастики цигун!'``.
        """
        events = []
        field = _FakeLocatorHandle(
            text="Центр оздоровления и китайской гимнастики цигун!",
            on_press=lambda key: events.append(("press", key)),
            on_fill=lambda v: events.append(("type", v)),
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 1, ["Тест фикса 653"]
        )

        # The clear must happen BEFORE the type, not after.
        self.assertEqual(
            events,
            [
                ("press", "ControlOrMeta+a"),
                ("press", "Backspace"),
                ("type", "Тест фикса 653"),
            ],
        )

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["x"]
            )

    def test_raises_when_more_values_than_slots(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["a", "b"]
            )
        self.assertIn("only renders 1 slots", str(ctx.exception))

    def test_clears_every_slot_not_just_the_ones_being_filled(self):
        """Unused slots must not keep Yandex's AI copy (issue #655 review).

        The page renders a FIXED set of slots, most pre-filled by Yandex's
        AI scan. Filling only the first ``len(values)`` of them leaves the
        rest populated, and every non-empty slot is a published ad variant —
        so a single ``--headline`` would launch that headline PLUS four
        AI-written ones the caller never reviewed. That directly violates
        this module's stated contract ("refuses to silently launch
        AI-generated ad copy the caller never reviewed", see create_master's
        docstring) on a page with no sandbox and no rollback.
        """
        slots = {
            0: _FakeContentEditableHandle(text=""),
            1: _FakeContentEditableHandle(
                text="Центр оздоровления и китайской гимнастики!"
            ),
            2: _FakeContentEditableHandle(text="Цигун в Москве — записаться"),
        }
        page = FakePage(
            locators={
                f'[data-testid="fake{i}.textarea"]': _FakeLocator([handle])
                for i, handle in slots.items()
            }
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 3, ["Мой заголовок"]
        )

        self.assertEqual(slots[0].inner_text(), "Мой заголовок")
        # The AI-generated leftovers must be GONE, not merely un-touched.
        self.assertEqual(slots[1].inner_text(), "")
        self.assertEqual(slots[2].inner_text(), "")

    def test_aborts_when_a_slot_cannot_be_cleared(self):
        """A failed clear must abort BEFORE anything is typed (issue #655).

        ``pyproject.toml`` permits ``playwright>=1.40``, but ``ControlOrMeta``
        only exists from 1.44 — on 1.40-1.43 the modifier press throws
        ``Unknown modifier`` server-side. Silently swallowing that leaves the
        slot pre-filled and ``.type()`` then splices the caller's value into
        Yandex's copy; ``create_master`` clicks Launch before it re-reads
        anything, so the mangled variant ships. Failing loudly is the only
        safe outcome on a page with no rollback.
        """
        slot = _FakeContentEditableHandle(
            text="Центр оздоровления и китайской гимнастики!",
            supports_modifier=False,
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([slot])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 1, ["Мой заголовок"]
            )

        # The pre-filled copy must be left untouched rather than spliced into.
        self.assertEqual(
            slot.inner_text(), "Центр оздоровления и китайской гимнастики!"
        )
        self.assertIn("clear", str(ctx.exception).lower())

    def test_aborts_when_an_unused_slot_cannot_be_clicked(self):
        """A click failure on an UNUSED slot must not be a soft skip
        (issue #655 round-2 review, Codex).

        The previous fix treated ``value is None`` (a trailing slot with no
        caller-supplied value) as safe to skip on a click failure, reasoning
        the slot "may simply not be rendered". But a click can also fail on
        a slot that IS rendered and IS still holding Yandex's AI copy — an
        overlay, a transient obstruction, anything short of "truly absent".
        ``create_master`` clicks the terminal LAUNCH button before
        ``_verify_created`` ever re-reads the page, so skipping here risks
        publishing unreviewed copy from a live, no-rollback campaign and
        only discovering it after the fact. Must fail before any click.
        """
        slot0 = _FakeContentEditableHandle(text="")
        slot1 = _FakeLocatorHandle(text="Центр оздоровления и китайской гимнастики!")
        slot1.click = lambda timeout=None: (_ for _ in ()).throw(
            PlaywrightError("intercepted: element obscured")
        )
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([slot0]),
                '[data-testid="fake1.textarea"]': _FakeLocator([slot1]),
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 2, ["Мой заголовок"]
            )

        # slot1's AI copy must survive untouched — the whole point is that
        # this must fail loudly instead of silently leaving it live.
        self.assertEqual(
            slot1.inner_text(), "Центр оздоровления и китайской гимнастики!"
        )

    def test_skips_a_trailing_slot_that_yandex_collapsed_away(self):
        """Issue #744 live recon: the slot list SHRINKS as it is emptied.

        Confirmed live on the create page — clearing the last pre-filled
        headline slot drops the rendered set from 5 slots to 1 in a single
        re-render, so the trailing testids are gone from the DOM by the time
        the loop reaches them. Aborting there (the pre-#744 behaviour) made
        `masters add` fail outright on a form that was in fact filled
        correctly. A slot that does not exist cannot be holding Yandex's AI
        copy, so with no value to write it is safe to skip — which is
        materially different from the obstructed-but-present slot in the
        test above, and that distinction is the whole fix.
        """
        slot0 = _FakeContentEditableHandle(text="Старый заголовок")
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([slot0]),
                # slot1 registered as genuinely ABSENT (zero matches), the
                # way a collapsed slot resolves on the real page.
                '[data-testid="fake1.textarea"]': _FakeLocator([]),
            }
        )

        browser_masters._add_repeating_values(
            page, "fake{index}.textarea", 2, ["Мой заголовок"]
        )  # must not raise

        self.assertEqual(slot0.inner_text(), "Мой заголовок")

    def test_still_aborts_when_a_slot_with_a_value_is_absent(self):
        """The collapse skip must never swallow a caller's OWN value.

        Skipping an absent slot is only safe when there is nothing to write
        into it. If the caller supplied a value for a slot that is gone,
        that value would be silently dropped — the exact "never silently
        drop a caller's value" guarantee issue #655 established — so this
        still has to fail loudly.
        """
        slot0 = _FakeContentEditableHandle(text="")
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([slot0]),
                '[data-testid="fake1.textarea"]': _FakeLocator([]),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_repeating_values(
                page, "fake{index}.textarea", 2, ["Первый", "Второй"]
            )
        self.assertIn("Второй", str(ctx.exception))


class TestReadRepeatingValues(unittest.TestCase):
    """``_read_repeating_values`` (issue #632, re-recon #653) — post-add
    read-back used by ``_verify_created``.

    Reads each slot's contenteditable div via ``inner_text()``, not
    ``input_value()`` (a contenteditable div has no ``value`` attribute).
    """

    def test_reads_inner_text_of_every_slot(self):
        handles = {
            0: _FakeLocatorHandle(text="Заголовок 1"),
            1: _FakeLocatorHandle(text="Заголовок 2"),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["Заголовок 1", "Заголовок 2"])

    def test_missing_slot_reads_as_empty_string(self):
        page = FakePage(locators={})

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["", ""])

    def test_unreadable_slot_reads_as_empty_string_not_a_hard_failure(self):
        handles = {
            0: _FakeLocatorHandle(text="ok"),
            1: _FakeLocatorHandle(raises=True),
        }
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([handles[0]]),
                '[data-testid="fake1.textarea"]': _FakeLocator([handles[1]]),
            }
        )

        values = browser_masters._read_repeating_values(page, "fake{index}.textarea", 2)

        self.assertEqual(values, ["ok", ""])


class TestSetRepeatingValue(unittest.TestCase):
    """``_set_repeating_value`` (issue #665, Этап B) — point replacement of
    ONE existing headline/text slot on the edit page.

    Unlike ``_add_repeating_values`` (the create-page setter, which clears
    and rewrites every slot unconditionally), this only ever touches the
    one requested slot — the rest of the fakes' slots must stay untouched
    across every scenario, mirroring the module's own docstring contract.
    """

    def test_replaces_a_filled_slot(self):
        events = []
        field = _FakeContentEditableHandle(
            text="Старый заголовок",
            on_press=lambda key: events.append(("press", key)),
            on_fill=lambda v: events.append(("type", v)),
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        browser_masters._set_repeating_value(
            page, "fake{index}.textarea", 5, 0, "Новый заголовок"
        )

        self.assertEqual(field.inner_text(), "Новый заголовок")
        # Clear must happen before typing, same convention as
        # _add_repeating_values.
        self.assertEqual(
            events,
            [
                ("press", "ControlOrMeta+a"),
                ("press", "Backspace"),
                ("type", "Новый заголовок"),
            ],
        )

    def test_other_slots_are_never_touched(self):
        untouched = _FakeContentEditableHandle(text="Не трогать")
        target = _FakeContentEditableHandle(text="Старый текст")
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([untouched]),
                '[data-testid="fake1.textarea"]': _FakeLocator([target]),
            }
        )

        browser_masters._set_repeating_value(
            page, "fake{index}.textarea", 2, 1, "Новый текст"
        )

        self.assertEqual(untouched.inner_text(), "Не трогать")
        self.assertEqual(target.inner_text(), "Новый текст")

    def test_raises_when_slot_is_empty(self):
        """Writing to an empty slot would add a new variant, not replace one
        — refused rather than silently treated as "add" (issue #665)."""
        field = _FakeContentEditableHandle(text="")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

        self.assertIn("empty", str(ctx.exception).lower())
        # Nothing should have been typed into the empty slot.
        self.assertEqual(field.inner_text(), "")

    def test_raises_when_index_out_of_range(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 3, 5, "x"
            )

        self.assertIn("out of range", str(ctx.exception).lower())

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 1, 0, "x"
            )

    def test_aborts_when_slot_cannot_be_cleared(self):
        """Same ``supports_modifier=False`` (Playwright <1.44) guard as
        ``_add_repeating_values`` — must fail loudly, not splice text."""
        field = _FakeContentEditableHandle(
            text="Старый заголовок", supports_modifier=False
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("clear", str(ctx.exception).lower())

    def test_click_failure_raises_browser_session_error(self):
        field = _FakeContentEditableHandle(text="Старый заголовок")
        field.click = lambda timeout=None: (_ for _ in ()).throw(
            PlaywrightError("element detached")
        )
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "Новый заголовок"
            )

    def test_refuses_to_blank_a_slot_with_an_empty_value(self):
        """An empty replacement would DELETE a live ad variant.

        Deleting a variant is explicitly out of scope for Этап B (issue #665
        lists it under "Явно вне объёма"), and the damage is silent: the slot
        is cleared, the empty string is typed, the form is saved, and
        ``_verify_repeating_value_mismatches`` then compares the re-read slot
        against the REQUESTED value — ``"" == ""`` matches, so the delete is
        reported as a successful update. On an active campaign that is a live
        ad mutation with no rollback (and with ``--launch`` on a DRAFT, it is
        published immediately). Guarded here as well as at the CLI boundary
        so the browser layer is safe for any caller, not just the CLI.
        """
        field = _FakeContentEditableHandle(text="Старый заголовок")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(page, "fake{index}.textarea", 5, 0, "")

        # The existing variant must survive untouched — not cleared-then-failed.
        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_refuses_to_blank_a_slot_with_a_whitespace_only_value(self):
        """Whitespace-only is the same delete wearing a disguise."""
        field = _FakeContentEditableHandle(text="Старый заголовок")
        page = FakePage(
            locators={'[data-testid="fake0.textarea"]': _FakeLocator([field])}
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_repeating_value(
                page, "fake{index}.textarea", 5, 0, "   "
            )

        self.assertEqual(field.inner_text(), "Старый заголовок")
        self.assertIn("empty", str(ctx.exception).lower())


class TestClearRepeatingValue(unittest.TestCase):
    """``_clear_repeating_value`` (issue #786, Этап B follow-up) — deletes
    ONE existing headline/text slot via its per-slot ``.clear`` button.
    """

    def test_clicks_the_clear_button_of_a_filled_slot(self):
        clicked = []
        textarea = _FakeLocatorHandle(text="Старый заголовок")

        def _on_click():
            clicked.append(True)
            # Models the real `.clear` button synchronously emptying the
            # textarea — the post-click commit check (cycle-review, Codex,
            # this PR) requires this, unlike the pre-fix fake which only
            # recorded the click without mutating state.
            textarea._text = ""

        clear_button = _FakeLocatorHandle(on_click=_on_click)
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )

        browser_masters._clear_repeating_value(
            page, "fake{index}.textarea", "fake{index}.clear", 5, 0
        )

        self.assertEqual(clicked, [True])

    def test_other_slots_are_never_touched(self):
        untouched_textarea = _FakeLocatorHandle(text="Не трогать")
        untouched_clear_clicked = []
        untouched_clear = _FakeLocatorHandle(
            on_click=lambda: untouched_clear_clicked.append(True)
        )
        target_textarea = _FakeLocatorHandle(text="Удалить меня")

        def _clear_target():
            target_textarea._text = ""

        target_clear = _FakeLocatorHandle(on_click=_clear_target)
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([untouched_textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([untouched_clear]),
                '[data-testid="fake1.textarea"]': _FakeLocator([target_textarea]),
                '[data-testid="fake1.clear"]': _FakeLocator([target_clear]),
            }
        )

        browser_masters._clear_repeating_value(
            page, "fake{index}.textarea", "fake{index}.clear", 2, 1
        )

        self.assertEqual(untouched_clear_clicked, [])

    def test_raises_when_slot_is_already_empty(self):
        textarea = _FakeLocatorHandle(text="")
        clear_button = _FakeLocatorHandle()
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 5, 0
            )

        self.assertIn("already empty", str(ctx.exception).lower())

    def test_raises_when_index_out_of_range(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 3, 5
            )

        self.assertIn("out of range", str(ctx.exception).lower())

    def test_raises_when_textarea_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 1, 0
            )

    def test_raises_when_clear_button_click_fails(self):
        textarea = _FakeLocatorHandle(text="Старый заголовок")
        clear_button = _FakeLocatorHandle(raises=True)
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 5, 0
            )

    def test_raises_when_clear_click_never_commits_to_the_dom(self):
        # cycle-review (Codex, this PR): `.clear` is a button whose handler
        # runs async, exactly like the audience-tag close button that taught
        # this module (issue #681) "click alone isn't proof" — a save
        # immediately after a click that hadn't actually committed yet
        # reloaded with the value still present. Without a post-click commit
        # check, a non-committing click here would sail straight through to
        # the caller's `_click_save`, which is irreversible. Models "the
        # click fires with no error, but the textarea keeps reporting its
        # old value forever" — the fake never mutates `_text`, since this
        # `_FakeLocatorHandle` has no `on_click` wired to empty it.
        textarea = _FakeLocatorHandle(text="Старый заголовок")
        clear_button = _FakeLocatorHandle()
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 5, 0
            )

        self.assertIn("may not have committed", str(ctx.exception).lower())
        # The click itself must still have fired — this guards the
        # post-click state, not a refusal to click.
        self.assertEqual(clear_button.click_timeouts, [None])

    def test_does_not_raise_when_clear_click_commits_after_a_few_ticks(self):
        # The commit check must tolerate a DOM update that lands a beat
        # after the click resolves (the normal case), not just an
        # instantaneous one — mirrors the audience-tag poll loop's
        # tolerance for the same async-commit lag.
        textarea = _FakeLocatorHandle(text="Старый заголовок")
        remaining_ticks = [2]

        def _commit_after_delay():
            if remaining_ticks[0] <= 0:
                textarea._text = ""
            else:
                remaining_ticks[0] -= 1

        clear_button = _FakeLocatorHandle(on_click=lambda: None)
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )
        # `inner_text` re-reads must observe the delayed commit — patch the
        # handle's read to tick the countdown, since `_FakeLocatorHandle`
        # has no first-class "value changes over successive reads" hook.
        original_inner_text = textarea.inner_text

        def _ticking_inner_text(timeout=None):
            _commit_after_delay()
            return original_inner_text(timeout=timeout)

        textarea.inner_text = _ticking_inner_text

        browser_masters._clear_repeating_value(
            page, "fake{index}.textarea", "fake{index}.clear", 5, 0
        )

        self.assertEqual(textarea.inner_text(), "")

    def test_raises_browser_session_error_when_commit_check_read_detaches(self):
        # cycle-review (Codex, round 2 of this PR): the post-click
        # commit-check reads must be guarded exactly like the initial
        # pre-click read — a transient DOM detach mid-poll (Yandex
        # re-rendering the slot row after the `.clear` handler runs) must
        # surface this function's own BrowserSessionError, not a raw
        # PlaywrightError traceback out of the mechanism meant to make a
        # non-committing click legible.
        textarea = _FakeLocatorHandle(text="Старый заголовок")
        clear_button = _FakeLocatorHandle(on_click=lambda: None)
        page = FakePage(
            locators={
                '[data-testid="fake0.textarea"]': _FakeLocator([textarea]),
                '[data-testid="fake0.clear"]': _FakeLocator([clear_button]),
            }
        )

        # The FIRST call is the pre-click "is it already empty?" read
        # (must still succeed with the original value, exactly as every
        # other test in this class exercises). Only calls AFTER that —
        # the post-click commit-check reads — must detach, isolating the
        # gap to the unguarded code path this test targets.
        call_count = [0]

        def _detaches_after_first_read(timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return "Старый заголовок"
            raise PlaywrightError("element detached mid-poll")

        textarea.inner_text = _detaches_after_first_read

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._clear_repeating_value(
                page, "fake{index}.textarea", "fake{index}.clear", 5, 0
            )

        # `assertRaises(BrowserSessionError)` above already proves the raised
        # exception IS a BrowserSessionError. The stronger claim this test
        # exists to make is that it is EXACTLY that (not some subclass, and
        # not the raw detach propagating unconverted) — checked by exact
        # type rather than `assertNotIsInstance(..., PlaywrightError)`,
        # since `PlaywrightError` itself falls back to bare `Exception` when
        # the `playwright` package isn't installed (masters.py's ImportError
        # guard), which would make that assertion vacuously true/false
        # depending on the test environment rather than on this function's
        # actual behavior — exactly what broke CI (playwright absent there).
        self.assertIs(type(ctx.exception), BrowserSessionError)


class _FakeImagesPage(FakePage):
    """Models the image set + image manager modal (issue #670, Этап D).

    Unlike headlines/texts, there is no fixed slot count — the page and the
    modal's "Выбранные изображения" panel each render a variable-length list
    of cards. This fake keeps ONE shared ``ids`` list (content IDs, standing
    in 1:1 for thumb URLs too, since ``_set_image`` never needs to tell them
    apart — see ``_read_modal_selected_thumb_urls``'s docstring) that both
    ``_read_image_content_ids`` (via the page-level ``ContentImage.*``
    locator) and ``_read_modal_selected_thumb_urls``/the remove buttons (via
    the modal-level ``SelectedImage.*`` locators) read/mutate — mirroring
    how ``_page_with_save_button``'s ``budget_state``/``headline_handles``
    share mutable state between the "edit" and "post-save reload" phases of
    one ``update_master`` call.

    ``open_images_modal`` toggles whether ``ImageSuggestionsEditorModal`` is
    present at all — real Playwright only renders it after the "Выбрать
    другие изображения" click (confirmed live), and ``_open_images_modal``'s
    polling loop depends on that transition being observable.
    """

    def __init__(self, ids, *, save_clicks=None, upload_ids=None, **kwargs):
        # _wait_for_draft_status (issue #726, cycle-review round 2) polls
        # for a visible non-DRAFT save button as its "definitely not DRAFT"
        # terminal marker, in addition to the DRAFT testid — so every fake
        # images page needs ONE of the two present, same as a real edit
        # page always has exactly one. Defaults to non-DRAFT (matching this
        # fake's pre-existing behavior, where no test ever registered the
        # DRAFT testid); a DRAFT-path test overrides `role_elements=[]` and
        # supplies the DRAFT testid via `locators` instead.
        kwargs.setdefault(
            "role_elements",
            [
                (
                    "button",
                    browser_masters._SAVE_BUTTON_TEXT,
                    _FakeTextLocatorHandle(visible=True),
                )
            ],
        )
        super().__init__(**kwargs)
        self.ids = list(ids)
        self.modal_open = False
        self.save_clicks = save_clicks if save_clicks is not None else []
        # Content IDs assigned to successive set_input_files() uploads, one
        # per call, in order — mirrors a test wanting deterministic new IDs
        # without depending on upload ordering internals.
        self._upload_ids = list(upload_ids or [])
        self._upload_call = 0
        # Every path passed to set_input_files(), in call order — lets
        # ``masters adimages set``/``add`` tests assert upload sequencing
        # (e.g. "removed everything, then uploaded in the order given").
        self.upload_paths = []

    def locator(self, selector):
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        if selector == edit_form_ready_selector:
            # Issue #684: _wait_for_edit_form's marker — headlines always
            # render on the edit page regardless of the images fake's own
            # state, same "present as soon as the page has rendered"
            # treatment as _IMAGES_EDITOR_SELECTOR just below.
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
            # The images section itself — present as soon as the (fake) page
            # has rendered, which is what `_wait_for_images_editor` polls for
            # before trusting an empty read as "this campaign has no images".
            return _FakeLocator([_FakeLocatorHandle()])
        if not self.modal_open and selector == browser_masters._IMAGES_MODAL_SELECTOR:
            return _FakeLocator([])
        if self.modal_open and selector == browser_masters._IMAGES_MODAL_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._IMAGES_OPEN_MODAL_SELECTOR:
            return _FakeLocator(
                [_FakeLocatorHandle(on_click=lambda: setattr(self, "modal_open", True))]
            )
        if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle(on_upload=self._upload)])
        if selector == browser_masters._IMAGES_MODAL_SAVE_SELECTOR:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(
                        on_click=lambda: (
                            self.save_clicks.append(True),
                            setattr(self, "modal_open", False),
                        )
                    )
                ]
            )
        selector_prefix = (
            f'[data-testid^="{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}"]'
        )
        if selector == selector_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(attrs={"data-testid": self._content_testid(cid)})
                    for cid in self.ids
                ]
            )
        modal_prefix = (
            f'[data-testid^="{browser_masters._IMAGES_MODAL_SELECTED_PREFIX}"]'
        )
        if selector == modal_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(
                        attrs={"data-testid": self._selected_testid(cid)}
                    )
                    for cid in self.ids
                ]
            )
        for cid in self.ids:
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url=cid
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                bound_cid = cid
                return _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_click=lambda bound_cid=bound_cid: self.ids.remove(
                                bound_cid
                            )
                        )
                    ]
                )
        return super().locator(selector)

    def _content_testid(self, content_id):
        return f"{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}{content_id}"

    def _selected_testid(self, content_id):
        return f"{browser_masters._IMAGES_MODAL_SELECTED_PREFIX}{content_id}"

    def _upload(self, path):
        self.upload_paths.append(path)
        if self._upload_call < len(self._upload_ids):
            new_id = self._upload_ids[self._upload_call]
        else:
            new_id = f"uploaded-{self._upload_call}"
        self._upload_call += 1
        self.ids.append(new_id)


class _FakeVideosPage(FakePage):
    """Models the "Варианты видео" section + its (assumed) modal (issue
    #648, Этап D).

    Modeled directly on ``_FakeImagesPage``, with the same caveat the
    production code carries: only the section/open-button/close-button
    shape is grounded in a live recon (2026-08-06, campaign 713277109); the
    modal internals (file input, Save button) are pure analogy with
    images' fake, not a confirmed shape. ``urls`` doubles as both the
    page-level video list AND (once open) the modal's own state — real
    Playwright behaviour for the modal was never observed, so there is
    nothing to model differently there yet.

    Unlike ``_FakeImagesPage``, the close button lives on ``page`` itself,
    not gated behind ``modal_open`` — mirrors the recon finding that
    removal needs no modal at all.
    """

    def __init__(self, urls, *, save_clicks=None, upload_urls=None, **kwargs):
        kwargs.setdefault(
            "role_elements",
            [
                (
                    "button",
                    browser_masters._SAVE_BUTTON_TEXT,
                    _FakeTextLocatorHandle(visible=True),
                )
            ],
        )
        super().__init__(**kwargs)
        self.urls = list(urls)
        self.modal_open = False
        self.save_clicks = save_clicks if save_clicks is not None else []
        # URLs assigned to successive set_input_files() uploads, one per
        # call, in order.
        self._upload_urls = list(upload_urls or [])
        self._upload_call = 0
        self.upload_paths = []

    def locator(self, selector):
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        if selector == edit_form_ready_selector:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._VIDEOS_EDITOR_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle()])
        if not self.modal_open and selector == browser_masters._VIDEOS_MODAL_SELECTOR:
            return _FakeLocator([])
        if self.modal_open and selector == browser_masters._VIDEOS_MODAL_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._VIDEOS_OPEN_MODAL_SELECTOR:
            return _FakeLocator(
                [_FakeLocatorHandle(on_click=lambda: setattr(self, "modal_open", True))]
            )
        if selector == browser_masters._VIDEOS_MODAL_FILE_INPUT_SELECTOR:
            return _FakeLocator([_FakeLocatorHandle(on_upload=self._upload)])
        if selector == browser_masters._VIDEOS_MODAL_SAVE_SELECTOR:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(
                        on_click=lambda: (
                            self.save_clicks.append(True),
                            setattr(self, "modal_open", False),
                        )
                    )
                ]
            )
        content_prefix = (
            f'[data-testid^="{browser_masters._VIDEOS_CONTENT_TESTID_PREFIX}"]'
        )
        if selector == content_prefix:
            return _FakeLocator(
                [
                    _FakeLocatorHandle(attrs={"data-testid": self._content_testid(url)})
                    for url in self.urls
                ]
            )
        for url in self.urls:
            close_testid = browser_masters._VIDEOS_CLOSE_BUTTON_TESTID_TEMPLATE.format(
                video_url=url
            )
            close_selector = f'[data-testid="{close_testid}"]'
            if selector == close_selector:
                bound_url = url
                return _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_click=lambda bound_url=bound_url: self.urls.remove(
                                bound_url
                            )
                        )
                    ]
                )
        return super().locator(selector)

    def _content_testid(self, url):
        return f"{browser_masters._VIDEOS_CONTENT_TESTID_PREFIX}{url}"

    def _upload(self, path):
        self.upload_paths.append(path)
        if self._upload_call < len(self._upload_urls):
            new_url = self._upload_urls[self._upload_call]
        else:
            new_url = f"https://example.test/uploaded-{self._upload_call}.mp4"
        self._upload_call += 1
        self.urls.append(new_url)


class TestReadVideos(unittest.TestCase):
    """``_read_videos`` (issue #648, Этап D)."""

    def test_reads_urls_in_dom_order(self):
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])

        self.assertEqual(
            browser_masters._read_videos(page),
            ["https://a.test/1.mp4", "https://a.test/2.mp4"],
        )

    def test_empty_set_reads_as_empty_list(self):
        page = _FakeVideosPage([])

        self.assertEqual(browser_masters._read_videos(page), [])

    def test_ignores_nested_videothumb_and_closebutton_suffixes(self):
        """A real page also renders VideoThumb.<url>[.Content/.VideoElement/
        .PlayButton] and CloseButton.<url> under the same prefix — only the
        bare <url> entry should count as one video (see _read_videos'
        docstring)."""
        url = "https://a.test/1.mp4"
        page = FakePage()
        prefix = browser_masters._VIDEOS_CONTENT_TESTID_PREFIX

        def _locator(selector):
            if selector == f'[data-testid^="{prefix}"]':
                testids = [
                    f"{prefix}{url}",
                    f"{prefix}VideoThumb.{url}",
                    f"{prefix}VideoThumb.{url}.Content",
                    f"{prefix}VideoThumb.{url}.VideoElement",
                    f"{prefix}VideoThumb.{url}.PlayButton",
                    f"{prefix}CloseButton.{url}",
                ]
                return _FakeLocator(
                    [_FakeLocatorHandle(attrs={"data-testid": t}) for t in testids]
                )
            return _FakeLocator([])

        page.locator = _locator

        self.assertEqual(browser_masters._read_videos(page), [url])


class TestWaitForVideosEditor(unittest.TestCase):
    """``_wait_for_videos_editor`` (issue #648, Этап D)."""

    def test_returns_once_section_present(self):
        page = _FakeVideosPage([])
        browser_masters._wait_for_videos_editor(page)  # must not raise

    def test_raises_when_section_never_appears(self):
        page = FakePage()  # no _VIDEOS_EDITOR_SELECTOR registered
        with patch.object(browser_masters, "_VIDEOS_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_videos_editor(page)
        self.assertIn("варианты видео", str(ctx.exception).lower())


class TestOpenVideosModal(unittest.TestCase):
    """``_open_videos_modal`` (issue #648, Этап D) — NOT LIVE-VERIFIED, see
    its own docstring."""

    def test_opens_modal_on_click(self):
        page = _FakeVideosPage([])
        browser_masters._open_videos_modal(page)
        self.assertTrue(page.modal_open)

    def test_raises_when_modal_never_appears(self):
        page = _FakeVideosPage([])
        # Sabotage: clicking Open never actually sets modal_open.
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._VIDEOS_OPEN_MODAL_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_VIDEO_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._open_videos_modal(page)
        self.assertIn("did not appear", str(ctx.exception))


class TestAddVideo(unittest.TestCase):
    """``_add_video`` (issue #648, Этап D) — NOT LIVE-VERIFIED, see module
    comments above ``_VIDEOS_SLOT_COUNT``."""

    def test_uploads_and_appends_to_the_set(self):
        page = _FakeVideosPage(
            ["https://a.test/1.mp4"], upload_urls=["https://a.test/new.mp4"]
        )

        browser_masters._add_video(page, "/tmp/fake.mp4")

        self.assertEqual(page.urls, ["https://a.test/1.mp4", "https://a.test/new.mp4"])
        self.assertEqual(len(page.save_clicks), 1)
        self.assertFalse(page.modal_open)
        self.assertEqual(page.upload_paths, ["/tmp/fake.mp4"])

    def test_refuses_when_already_at_slot_count(self):
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_video(page, "/tmp/fake.mp4")

        self.assertIn("already has 2", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])
        self.assertFalse(page.modal_open)

    def test_does_not_save_when_upload_never_appears(self):
        page = _FakeVideosPage([], upload_urls=[])
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._VIDEOS_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_upload=lambda path: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_VIDEO_UPLOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._add_video(page, "/tmp/fake.mp4")

        self.assertIn("no new", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])


class TestRemoveVideo(unittest.TestCase):
    """``_remove_video`` (issue #648, Этап D) — the close-button-testid
    presence is confirmed live; the click's EFFECT is NOT (see
    ``_remove_video``'s docstring)."""

    def test_removes_the_named_video(self):
        page = _FakeVideosPage(["https://a.test/1.mp4", "https://a.test/2.mp4"])

        browser_masters._remove_video(page, "https://a.test/1.mp4")

        self.assertEqual(page.urls, ["https://a.test/2.mp4"])

    def test_does_not_open_a_modal(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])

        browser_masters._remove_video(page, "https://a.test/1.mp4")

        self.assertFalse(page.modal_open)
        self.assertEqual(page.save_clicks, [])

    def test_raises_when_close_button_missing(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._remove_video(page, "https://nonexistent.test/x.mp4")

        self.assertIn("could not find", str(ctx.exception).lower())

    def test_raises_when_click_does_not_actually_remove_it(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])
        original_locator = page.locator

        def _locator(selector):
            close_testid = browser_masters._VIDEOS_CLOSE_BUTTON_TESTID_TEMPLATE.format(
                video_url="https://a.test/1.mp4"
            )
            close_selector = f'[data-testid="{close_testid}"]'
            if selector == close_selector:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_VIDEO_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._remove_video(page, "https://a.test/1.mp4")

        self.assertIn("still shown", str(ctx.exception).lower())


class TestVerifyVideoMismatches(unittest.TestCase):
    """``_verify_video_mismatches`` (issue #648, Этап D)."""

    def test_no_op_when_nothing_touched(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])

        result = browser_masters._verify_video_mismatches(
            page, before_urls=["https://a.test/1.mp4"], added=False, removed_urls=[]
        )

        self.assertEqual(result, [])

    def test_flags_a_still_present_removed_video(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])  # removal didn't take

        result = browser_masters._verify_video_mismatches(
            page,
            before_urls=["https://a.test/1.mp4"],
            added=False,
            removed_urls=["https://a.test/1.mp4"],
        )

        self.assertTrue(any("still present" in m for m in result))

    def test_flags_a_missing_kept_video(self):
        # An untouched video (position 0) vanished even though only
        # position 1 was requested for removal.
        page = _FakeVideosPage([])
        result = browser_masters._verify_video_mismatches(
            page,
            before_urls=["https://a.test/1.mp4", "https://a.test/2.mp4"],
            added=False,
            removed_urls=["https://a.test/2.mp4"],
        )

        self.assertTrue(any("missing" in m for m in result))

    def test_flags_a_size_mismatch_when_add_did_not_take(self):
        page = _FakeVideosPage(["https://a.test/1.mp4"])  # no new video appeared

        result = browser_masters._verify_video_mismatches(
            page, before_urls=["https://a.test/1.mp4"], added=True, removed_urls=[]
        )

        self.assertTrue(any("expected 2" in m for m in result))

    def test_passes_when_add_and_remove_both_took_effect(self):
        page = _FakeVideosPage(["https://a.test/2.mp4", "https://a.test/new.mp4"])

        result = browser_masters._verify_video_mismatches(
            page,
            before_urls=["https://a.test/1.mp4", "https://a.test/2.mp4"],
            added=True,
            removed_urls=["https://a.test/1.mp4"],
        )

        self.assertEqual(result, [])


class TestReadImageContentIds(unittest.TestCase):
    """``_read_image_content_ids`` (issue #670, Этап D)."""

    def test_reads_ids_in_dom_order(self):
        page = _FakeImagesPage(["a", "b", "c"])

        self.assertEqual(browser_masters._read_image_content_ids(page), ["a", "b", "c"])

    def test_empty_set_is_not_an_error(self):
        """Unlike headlines/texts, zero images is a legitimate campaign state."""
        page = _FakeImagesPage([])

        self.assertEqual(browser_masters._read_image_content_ids(page), [])


class TestWaitForImagesEditor(unittest.TestCase):
    """``_wait_for_images_editor`` (issue #670) — regression guard for a bug
    found during live verification.

    The edit page is an SPA: ``goto(wait_until="domcontentloaded")`` returns
    while the images section is still absent, so reading the set straight
    away yields ``[]`` — indistinguishable from "this campaign genuinely has
    no images". Live-confirmed: four consecutive DRAFT campaigns were
    rejected with "no images" by ``masters update --image`` while their edit
    pages demonstrably rendered four images each.
    """

    def test_returns_once_the_section_is_present(self):
        """The base fixture renders content immediately with no ``StubN``
        tick at all — the "campaign has no images" shape the ghost-pass gate
        (issue #687) must NOT mistake for the ghost pass, since here
        ``ContentImage`` elements are present from tick one, unlike the
        ghost pass which never has any."""
        page = _FakeImagesPage(["a"])

        browser_masters._wait_for_images_editor(page)  # must not raise

    def test_raises_rather_than_reporting_no_images(self):
        """A section that never renders is a hard error, NOT an empty set."""

        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_images_editor(page)

        self.assertIn("did not finish rendering", str(ctx.exception))

    def test_set_image_does_not_claim_no_images_before_the_section_renders(self):
        """The end-to-end shape of the live bug: `_set_image` must not
        report "no images" for a page whose section has not rendered yet."""

        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertNotIn("no images", str(ctx.exception).lower())

    def test_waits_out_the_loading_stub_state_before_returning(self):
        """Live-confirmed 2026-08-03 regression (campaigns 713234191 and
        713234204, both with 4 real images): ``ImageSuggestionsEditor``
        itself renders FIRST with four ``...CampaignContents.StubN``
        loading placeholders, and NEITHER ``ContentImage.*`` nor ``.Open``
        exist yet — only ~3s later do the stubs get replaced by the real
        content. Waiting on ``_IMAGES_EDITOR_SELECTOR`` alone (the original
        implementation) returned during this stub window, so
        ``masters adimages get`` reported ``Count: 0`` for a campaign that
        demonstrably had 4 images, and a subsequent ``adimages add`` then
        uploaded into what it believed was an empty set and timed out.
        """

        class _StubThenContentPage(_FakeImagesPage):
            def __init__(self, *args, stub_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._stub_ticks_remaining = stub_ticks

            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    if self._stub_ticks_remaining > 0:
                        self._stub_ticks_remaining -= 1
                        return _FakeLocator([_FakeLocatorHandle() for _ in range(4)])
                    return _FakeLocator([])
                return super().locator(selector)

        page = _StubThenContentPage(["a", "b", "c", "d"], stub_ticks=2)

        browser_masters._wait_for_images_editor(page)  # must not raise

        # Confirms the wait actually consumed the stub ticks rather than
        # returning on the very first (still-stubbed) poll.
        self.assertEqual(page._stub_ticks_remaining, 0)
        self.assertEqual(
            browser_masters._read_image_content_ids(page), ["a", "b", "c", "d"]
        )

    def test_raises_if_stubs_never_clear(self):
        """A section stuck showing loading placeholders forever must be a
        hard error, not silently treated as an empty (or populated) set."""

        class _StuckStubPage(_FakeImagesPage):
            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    return _FakeLocator([_FakeLocatorHandle() for _ in range(4)])
                return super().locator(selector)

        page = _StuckStubPage(["a", "b", "c", "d"])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_images_editor(page)

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertIn("loading placeholders", str(ctx.exception))

    def test_does_not_settle_on_the_ghost_pass_before_stubs_appear(self):
        """Issue #687, root-caused live 2026-08-03: BEFORE the ``StubN``
        round even begins, ``ImageSuggestionsEditor`` briefly mounts with
        ZERO ``StubN`` and ZERO ``ContentImage`` elements — a ghost render
        that looks identical, by DOM shape alone, to a genuine settle
        (``editor`` present, no ``StubN``). The pre-#687 guard (editor
        present AND no ``StubN``) returned during this ghost pass on 3/3
        live repeats, reading ``[]`` for a campaign confirmed to have 5
        images. The fix requires having actually observed at least one
        ``StubN`` tick before trusting "no ``StubN``" as a settle."""

        class _GhostThenStubThenContentPage(_FakeImagesPage):
            def __init__(self, *args, ghost_ticks=3, stub_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._ghost_ticks_remaining = ghost_ticks
                self._stub_ticks_remaining = stub_ticks

            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    if self._ghost_ticks_remaining > 0:
                        self._ghost_ticks_remaining -= 1
                        return _FakeLocator([])
                    if self._stub_ticks_remaining > 0:
                        self._stub_ticks_remaining -= 1
                        return _FakeLocator([_FakeLocatorHandle() for _ in range(4)])
                    return _FakeLocator([])
                content_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}"]'
                )
                if selector == content_prefix and (
                    self._ghost_ticks_remaining > 0 or self._stub_ticks_remaining > 0
                ):
                    return _FakeLocator([])
                return super().locator(selector)

        page = _GhostThenStubThenContentPage(
            ["a", "b", "c", "d"], ghost_ticks=3, stub_ticks=2
        )

        # The module-wide grace-period patch (see setUpModule) would let the
        # ghost pass settle instantly on its own; force it back up so this
        # test exercises the StubN-gate path specifically, not the grace
        # period's separate fallback (covered by its own tests below).
        with patch.object(browser_masters, "_IMAGES_GHOST_GRACE_S", 9999.0):
            browser_masters._wait_for_images_editor(page)  # must not raise

        # Settling must have consumed BOTH the ghost pass and the real stub
        # round, not returned during the ghost pass's "no StubN" window.
        self.assertEqual(page._ghost_ticks_remaining, 0)
        self.assertEqual(page._stub_ticks_remaining, 0)
        self.assertEqual(
            browser_masters._read_image_content_ids(page), ["a", "b", "c", "d"]
        )

    def test_raises_if_stuck_in_the_ghost_pass_forever(self):
        """A page stuck showing the ghost pass (no StubN ever observed) must
        be a hard error, not a false "settle" on the pre-#687 guard's logic
        nor a false "no images"."""

        class _StuckGhostPage(_FakeImagesPage):
            def locator(self, selector):
                stub_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_STUB_TESTID_PREFIX}"]'
                )
                if selector == stub_prefix:
                    return _FakeLocator([])
                content_prefix = (
                    f'[data-testid^="{browser_masters._IMAGES_CONTENT_TESTID_PREFIX}"]'
                )
                if selector == content_prefix:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _StuckGhostPage(["a", "b", "c", "d"])
        with (
            patch.object(browser_masters, "_IMAGES_GHOST_GRACE_S", 9999.0),
            patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1),
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_images_editor(page)

        self.assertIn("did not finish rendering", str(ctx.exception))

    def test_settles_a_genuinely_empty_set_after_the_grace_period_with_no_stub_round(
        self,
    ):
        """A campaign with zero images can settle into "editor present, no
        StubN, no ContentImage" straight away with no stub round at all —
        the module-wide grace-period patch (see setUpModule) makes this
        instant for every OTHER test in this file, so this test explicitly
        restores a real, non-zero grace period to prove the fallback itself
        works, not just that patching it to 0 short-circuits it."""

        page = _FakeImagesPage([])  # base fixture: no stubs, no content, ever

        with patch.object(browser_masters, "_IMAGES_GHOST_GRACE_S", 0.05):
            browser_masters._wait_for_images_editor(page)  # must not raise

        self.assertEqual(browser_masters._read_image_content_ids(page), [])


class TestWaitForEditForm(unittest.TestCase):
    """``_wait_for_edit_form`` (issue #684) — regression guard for the
    ``domcontentloaded`` navigation timeout.

    Every ``WIZARD_EDIT_URL`` ``goto()`` now uses ``wait_until="commit"``
    (never hangs on the SPA's own long-poll connections) instead of
    ``domcontentloaded``, which was observed to time out. ``commit``
    guarantees nothing about the DOM, so every call site polls this
    function for the first headline slot before trusting the page.
    """

    def _edit_form_ready_selector(self):
        return f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'

    def test_returns_once_the_first_headline_slot_is_present(self):
        page = FakePage(
            locators={
                self._edit_form_ready_selector(): _FakeLocator([_FakeLocatorHandle()])
            }
        )

        browser_masters._wait_for_edit_form(page, 42)  # must not raise

    def test_raises_if_the_marker_never_appears(self):
        page = FakePage(locators={})
        with patch.object(browser_masters, "_EDIT_FORM_READY_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._wait_for_edit_form(page, 42)

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertIn("42", str(ctx.exception))
        self.assertIn(browser_masters._EDIT_FORM_READY_TESTID, str(ctx.exception))

    def test_polls_rather_than_failing_on_the_first_absence(self):
        """Mirrors ``_wait_for_images_editor``'s stub-window test: the
        marker appearing on a LATER poll (not the first) must still be
        accepted, not just an immediately-present one."""

        class _AppearsAfterTicksPage(FakePage):
            def __init__(self, *args, absent_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._absent_ticks_remaining = absent_ticks

            def locator(self, selector):
                if (
                    selector == self._edit_form_ready_selector_str
                    and self._absent_ticks_remaining > 0
                ):
                    self._absent_ticks_remaining -= 1
                    return _FakeLocator([])
                return super().locator(selector)

        _AppearsAfterTicksPage._edit_form_ready_selector_str = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = _AppearsAfterTicksPage(
            locators={
                self._edit_form_ready_selector(): _FakeLocator([_FakeLocatorHandle()])
            },
            absent_ticks=2,
        )

        browser_masters._wait_for_edit_form(page, 42)  # must not raise

        self.assertEqual(page._absent_ticks_remaining, 0)

    def test_raises_browser_captcha_error_if_captcha_appears_mid_poll(self):
        """Issue #684 cycle-review: ``wait_until="commit"`` returns before
        the SPA's own JS has redirected to a captcha/login page, so a
        SmartCaptcha gate served AFTER the initial commit response must
        still be caught by ``_wait_for_edit_form``'s poll loop — not just
        missed by the one-shot ``assert_not_captcha``/``assert_authenticated``
        checks that ran immediately after ``goto()``, before this function
        was even called."""

        class _CaptchaAppearsAfterTicksPage(FakePage):
            def __init__(self, *args, clean_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._clean_ticks_remaining = clean_ticks

            def content(self):
                if self._clean_ticks_remaining > 0:
                    self._clean_ticks_remaining -= 1
                    return "<html></html>"
                return "<html>showCaptcha marker here</html>"

        page = _CaptchaAppearsAfterTicksPage(locators={}, clean_ticks=2)

        with self.assertRaises(BrowserCaptchaError):
            browser_masters._wait_for_edit_form(page, 42)

    def test_raises_browser_auth_error_if_login_page_appears_mid_poll(self):
        """Same race as the captcha case above, but for an expired/wrong
        session redirecting to Yandex Passport instead."""

        class _LoginAppearsAfterTicksPage(FakePage):
            def __init__(self, *args, clean_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._clean_ticks_remaining = clean_ticks

            def content(self):
                if self._clean_ticks_remaining > 0:
                    self._clean_ticks_remaining -= 1
                    return "<html></html>"
                return "<html>Войдите с Яндекс ID</html>"

        page = _LoginAppearsAfterTicksPage(locators={}, clean_ticks=2)

        with self.assertRaises(BrowserAuthError):
            browser_masters._wait_for_edit_form(page, 42)

    def test_raises_browser_captcha_error_even_when_playwright_error_is_broad_exception(
        self,
    ):
        """Regression guard for the CI failure this fix caused before this
        commit: ``PlaywrightError`` falls back to the broad ``Exception``
        (module top, ``ImportError`` branch) when Playwright isn't
        installed — the case for this repo's offline unit-test CI job.
        ``_poll_until``/``_poll_until_terminal`` suppress ``PlaywrightError``
        inside their loop, so if the captcha/auth check were allowed to
        *raise* from inside the polled predicate (as an earlier version of
        this fix did), that broad alias would silently swallow
        ``BrowserCaptchaError``/``BrowserAuthError`` too in this
        environment, and the poll would run out the clock and report a
        generic ``BrowserSessionError`` instead — exactly what broke CI.
        This test patches ``PlaywrightError`` to ``Exception`` directly
        (rather than relying on a real Playwright-absent environment) so
        the regression is caught locally too, not just in CI."""

        class _CaptchaAppearsAfterTicksPage(FakePage):
            def __init__(self, *args, clean_ticks=2, **kwargs):
                super().__init__(*args, **kwargs)
                self._clean_ticks_remaining = clean_ticks

            def content(self):
                if self._clean_ticks_remaining > 0:
                    self._clean_ticks_remaining -= 1
                    return "<html></html>"
                return "<html>showCaptcha marker here</html>"

        page = _CaptchaAppearsAfterTicksPage(locators={}, clean_ticks=2)

        with patch.object(browser_masters, "PlaywrightError", Exception):
            with self.assertRaises(BrowserCaptchaError):
                browser_masters._wait_for_edit_form(page, 42)


class TestWizardEditNavigationUsesCommit(unittest.TestCase):
    """Issue #684: all four ``WIZARD_EDIT_URL`` navigation sites must use
    ``wait_until="commit"`` (never hangs on the SPA's long-poll
    connections) and wait for ``_wait_for_edit_form`` before touching the
    page — regression guard against reintroducing
    ``wait_until="domcontentloaded"``, which was observed to time out.
    """

    def test_verify_saved_uses_commit_and_waits_for_the_form(self):
        page, save_clicks = TestUpdateMaster()._page_with_save_button(
            weekly_budget_state={"value": "80000"}
        )

        browser_masters.update_master(page, 42, weekly_budget=80000)

        self.assertEqual(page.goto_wait_until, "commit")

    def test_update_master_uses_commit_for_the_initial_navigation(self):
        navigated_wait_untils = []

        class _RecordingPage(FakePage):
            def goto(self, url, wait_until=None):
                navigated_wait_untils.append(wait_until)
                super().goto(url, wait_until=wait_until)

        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        budget_state = {"value": "80000"}
        budget_handle = _FakeLocatorHandle(
            on_fill=lambda v: budget_state.__setitem__("value", v),
            get_value=lambda: budget_state["value"],
        )
        save_handle = _FakeTextLocatorHandle(visible=True)
        page = _RecordingPage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_handle]
                ),
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        browser_masters.update_master(page, 42, weekly_budget=95000)

        # Both the initial edit and _verify_saved's post-save reload.
        self.assertEqual(navigated_wait_untils, ["commit", "commit"])

    def test_open_images_editor_uses_commit(self):
        page = _FakeImagesPage(["a"])

        browser_masters._open_images_editor(page, 42)

        self.assertEqual(page.goto_wait_until, "commit")

    def test_verify_saved_images_uses_commit(self):
        page = _FakeImagesPage(["a"])

        browser_masters._verify_saved_images(
            page,
            42,
            expected_kept_ids=["a"],
            removed_ids=set(),
            expected_added_count=0,
            clicked_button_label="Сохранить кампанию",
        )

        self.assertEqual(page.goto_wait_until, "commit")


class TestSetImage(unittest.TestCase):
    """``_set_image`` (issue #670, Этап D) — synthetic point-replacement
    composed from the image manager modal's remove+upload+save.
    """

    def test_replaces_the_requested_position_only(self):
        page = _FakeImagesPage(["a", "b", "c"], upload_ids=["new"])

        browser_masters._set_image(page, 1, "/tmp/fake.png", target_content_id="b")

        # Confirmed-live behaviour: the new image lands at the END of the
        # set, not back at position 1 — see _set_image's own docstring.
        self.assertEqual(page.ids, ["a", "c", "new"])
        self.assertEqual(len(page.save_clicks), 1)
        self.assertFalse(page.modal_open)

    def test_raises_when_image_set_is_empty(self):
        page = _FakeImagesPage([])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(page, 0, "/tmp/fake.png", target_content_id="a")

        self.assertIn("no images", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])

    def test_raises_when_position_out_of_range(self):
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(
                page, 5, "/tmp/fake.png", target_content_id="nonexistent"
            )

        self.assertIn("out of range", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_raises_when_target_content_id_already_gone(self):
        """Models the caller-contract violation this signature exists to
        prevent: a second ``_set_image`` in the same batch naming a content
        ID an earlier call in the SAME batch already removed. A live page
        race is not the scenario here — ``update_master`` always resolves
        ``target_content_id`` from its own pre-batch snapshot, so this can
        only happen if a caller passes a stale/already-consumed ID."""
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_image(
                page, 0, "/tmp/fake.png", target_content_id="already-removed"
            )

        self.assertIn("no longer present", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_does_not_save_when_upload_never_appears(self):
        """A stalled/failed async upload must not be committed via Save."""
        page = _FakeImagesPage(["a", "b"], upload_ids=[])
        # Sabotage the upload: the file input exists but never actually adds
        # a new card to the selected panel.
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_upload=lambda path: None)])
            return original_locator(selector)

        page.locator = _locator
        # Keep the test fast — patch.object restores the real value even on
        # failure, and never hardcodes it (a `finally:` assignment would).
        with patch.object(browser_masters, "_IMAGE_UPLOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("no new", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])
        # The removed image must NOT still be missing from the caller's
        # perspective of "nothing was saved" — the campaign's actually-saved
        # set is untouched because Save was never clicked, even though the
        # modal's own in-progress state lost it.

    def test_removed_image_not_still_present_raises(self):
        """Models Yandex's own remove click silently failing."""
        page = _FakeImagesPage(["a", "b"])
        original_locator = page.locator

        def _locator(selector):
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url="a"
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._set_image(
                    page, 0, "/tmp/fake.png", target_content_id="a"
                )

        self.assertIn("still shown", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])


class TestApplyImageOperations(unittest.TestCase):
    """``_apply_image_operations`` — the bulk one-modal primitive behind
    ``masters adimages add/delete/set`` (unlike ``_set_image``, which opens
    its own modal per call).
    """

    def test_no_op_when_both_lists_empty(self):
        page = _FakeImagesPage(["a", "b"])

        browser_masters._apply_image_operations(
            page, remove_content_ids=(), upload_paths=()
        )

        self.assertEqual(page.ids, ["a", "b"])
        self.assertFalse(page.modal_open)
        self.assertEqual(page.save_clicks, [])

    def test_uploads_into_an_empty_set(self):
        page = _FakeImagesPage([], upload_ids=["new1", "new2"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=(),
            upload_paths=["/tmp/a.png", "/tmp/b.png"],
        )

        self.assertEqual(page.ids, ["new1", "new2"])
        self.assertEqual(page.upload_paths, ["/tmp/a.png", "/tmp/b.png"])
        self.assertEqual(len(page.save_clicks), 1)
        self.assertFalse(page.modal_open)

    def test_removes_every_image_leaving_the_set_empty(self):
        page = _FakeImagesPage(["a", "b", "c"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=["a", "b", "c"],
            upload_paths=(),
        )

        self.assertEqual(page.ids, [])
        self.assertEqual(len(page.save_clicks), 1)

    def test_removes_and_uploads_in_one_modal_session(self):
        """The core invariant bulk ops need: N removes + M uploads, but
        exactly ONE open/Save cycle — not N+M cycles like ``_set_image``."""
        page = _FakeImagesPage(["a", "b", "c"], upload_ids=["x", "y"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=["a", "b", "c"],
            upload_paths=["/tmp/x.png", "/tmp/y.png"],
        )

        self.assertEqual(page.ids, ["x", "y"])
        self.assertEqual(page.upload_paths, ["/tmp/x.png", "/tmp/y.png"])
        self.assertEqual(len(page.save_clicks), 1)

    def test_upload_order_is_preserved(self):
        page = _FakeImagesPage(["a"], upload_ids=["u1", "u2", "u3"])

        browser_masters._apply_image_operations(
            page,
            remove_content_ids=(),
            upload_paths=["/tmp/1.png", "/tmp/2.png", "/tmp/3.png"],
        )

        self.assertEqual(page.upload_paths, ["/tmp/1.png", "/tmp/2.png", "/tmp/3.png"])
        self.assertEqual(page.ids, ["a", "u1", "u2", "u3"])

    def test_unknown_remove_content_id_raises_before_any_click(self):
        page = _FakeImagesPage(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._apply_image_operations(
                page,
                remove_content_ids=["nonexistent"],
                upload_paths=(),
            )

        self.assertIn("not present", str(ctx.exception).lower())
        self.assertEqual(page.ids, ["a", "b"])
        self.assertEqual(page.save_clicks, [])

    def test_upload_that_never_lands_raises_and_does_not_save(self):
        page = _FakeImagesPage(["a"], upload_ids=[])
        original_locator = page.locator

        def _locator(selector):
            if selector == browser_masters._IMAGES_MODAL_FILE_INPUT_SELECTOR:
                return _FakeLocator([_FakeLocatorHandle(on_upload=lambda path: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_UPLOAD_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._apply_image_operations(
                    page,
                    remove_content_ids=(),
                    upload_paths=["/tmp/a.png"],
                )

        self.assertIn("no new", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])

    def test_remove_that_never_takes_effect_raises_and_does_not_save(self):
        page = _FakeImagesPage(["a", "b"])
        original_locator = page.locator

        def _locator(selector):
            remove_testid = browser_masters._IMAGES_MODAL_REMOVE_TESTID_TEMPLATE.format(
                thumb_url="a"
            )
            remove_selector = f'[data-testid="{remove_testid}"]'
            if selector == remove_selector:
                return _FakeLocator([_FakeLocatorHandle(on_click=lambda: None)])
            return original_locator(selector)

        page.locator = _locator
        with patch.object(browser_masters, "_IMAGE_MODAL_OPEN_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters._apply_image_operations(
                    page,
                    remove_content_ids=["a"],
                    upload_paths=(),
                )

        self.assertIn("still shown", str(ctx.exception).lower())
        self.assertEqual(page.save_clicks, [])


class TestUtmSectionReadability(unittest.TestCase):
    """``_read_tracking_params`` / ``_wait_for_utm_section`` — issue
    #769/#774's real root cause: a late-mounting "Дополнительные параметры"
    section made a save that DID take effect look like a failed one.

    Live recon against campaign 713234064 (2026-08-06): after a save whose
    value was demonstrably correct on the next page load, the verifying run
    read the UTM field as unmounted for a full 90s. ``_expand_utm_spoiler``
    returned ``False`` (its trigger wasn't in the DOM yet), that return was
    discarded, and ``text_content()`` on the unmounted field yielded
    ``None`` — which ``_verify_saved`` then reported as a mismatch.
    """

    @staticmethod
    def _page(*, spoiler_appears_after=0, value="utm_source=x"):
        """An edit page whose UTM spoiler trigger only mounts after
        ``spoiler_appears_after`` ``wait_for_timeout`` ticks."""
        ticks = {"n": 0}
        expanded = {"open": False}

        class _LateSpoilerLocator:
            def __init__(self, handles):
                self._handles = handles

            def _mounted(self):
                return ticks["n"] >= spoiler_appears_after

            def count(self):
                return len(self._handles) if self._mounted() else 0

            def nth(self, i):
                return self._handles[i]

            @property
            def first(self):
                if not self._mounted():
                    return _FakeLocatorHandle(raises=True)
                return self._handles[0]

        spoiler_handle = _DynamicAttrsLocatorHandle(
            get_attrs=lambda: {
                "aria-expanded": "true" if expanded["open"] else "false"
            },
            on_click=lambda: expanded.__setitem__("open", True),
        )

        class _UtmFieldLocator:
            @property
            def first(self):
                # Models Playwright's real behaviour for a locator matching
                # nothing in a still-hydrating section: `.first` resolves,
                # and `text_content()` returns an EMPTY STRING rather than
                # raising. That is precisely why the pre-fix
                # `_read_tracking_params` could not tell "not mounted yet"
                # from "genuinely cleared" — a fake that raises here would
                # hide the bug instead of reproducing it.
                if not expanded["open"]:
                    return _FakeContentEditableHandle(text="")
                return _FakeContentEditableHandle(text=value)

            def count(self):
                return 1 if expanded["open"] else 0

        class _TickingPage(FakePage):
            def wait_for_timeout(self, timeout):
                ticks["n"] += 1
                super().wait_for_timeout(timeout)

        return _TickingPage(
            locators={
                browser_masters._EDIT_UTM_SPOILER_BUTTON_TESTID: (
                    _LateSpoilerLocator([spoiler_handle])
                ),
                browser_masters._EDIT_UTM_INPUT_TESTID: _UtmFieldLocator(),
            }
        )

    def test_unmountable_spoiler_reads_as_none_not_empty_string(self):
        # THE bug: an absent spoiler must be "I could not read this"
        # (None), never "the field is empty" ("") — the latter is
        # indistinguishable from a genuinely cleared field and is what made
        # #774's investigation point 3 look like data loss.
        page = self._page(spoiler_appears_after=10**9)

        self.assertIsNone(browser_masters._read_tracking_params(page))

    def test_wait_retries_the_expansion_until_the_trigger_mounts(self):
        # Retrying the READ alone never recovers — the spoiler has to be
        # clicked once its trigger finally exists.
        page = self._page(spoiler_appears_after=3, value="utm_source=late")

        self.assertTrue(browser_masters._wait_for_utm_section(page))
        self.assertEqual(browser_masters._read_tracking_params(page), "utm_source=late")

    def test_wait_returns_false_on_timeout_without_raising(self):
        # Degradation contract (mirrors _wait_for_target_actions_settled):
        # a timeout is reported to the caller, not raised, so the caller's
        # own mismatch reporting stays the single place failures surface.
        page = self._page(spoiler_appears_after=10**9)

        self.assertFalse(browser_masters._wait_for_utm_section(page))

    def test_an_already_open_section_is_readable_immediately(self):
        page = self._page(spoiler_appears_after=0, value="utm_source=ready")

        self.assertTrue(browser_masters._wait_for_utm_section(page))
        self.assertEqual(
            browser_masters._read_tracking_params(page), "utm_source=ready"
        )


class TestVerifyTrackingParamsReloadRetry(unittest.TestCase):
    """``_verify_saved`` re-NAVIGATES before failing a tracking_params check
    (issue #769).

    Live-reproduced 2026-08-06 against campaign 713234064: two
    ``masters update --tracking-params`` runs back to back had the second
    run's verify read back the FIRST run's value. Re-opening the campaign in
    a fresh page load 6.6s later showed the second value correctly saved —
    the save was fine, the post-save reload served a stale render. Polling
    the already-loaded page harder cannot fix that; only a new navigation
    re-fetches the section.
    """

    NEW = "utm_source=new&utm_medium=cpc&utm_campaign={campaign_id}&utm_term={gbid}"
    STALE = "utm_source=old&utm_medium=cpc&utm_campaign={campaign_id}&utm_term={gbid}"

    @staticmethod
    def _page(values_by_load):
        """Edit page whose UTM field yields ``values_by_load[n]`` on the
        n-th POST-SAVE load — the last entry repeats for further loads.

        ``update_master`` navigates once to open the form before saving;
        that load is not counted, so ``values_by_load[0]`` is what
        ``_verify_saved``'s own post-save reload sees (the stale render in
        the #769 scenario) and ``[1]`` is what a re-navigation gets.
        """
        loads = {"n": -2}
        expanded = {"open": False}

        def _current():
            i = min(loads["n"], len(values_by_load) - 1)
            return values_by_load[i]

        spoiler_handle = _DynamicAttrsLocatorHandle(
            get_attrs=lambda: {
                "aria-expanded": "true" if expanded["open"] else "false"
            },
            on_click=lambda: expanded.__setitem__("open", True),
        )

        class _UtmFieldLocator:
            @property
            def first(self):
                return _FakeContentEditableHandle(text=_current())

            def count(self):
                return 1

        class _ReloadingPage(FakePage):
            def goto(self, url, **kwargs):
                loads["n"] += 1
                # A real navigation re-collapses the lazily-mounted spoiler.
                expanded["open"] = False
                return super().goto(url, **kwargs)

        save_handle = _FakeTextLocatorHandle(visible=True)
        edit_form_ready = f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        return _ReloadingPage(
            locators={
                browser_masters._EDIT_UTM_SPOILER_BUTTON_TESTID: _FakeLocator(
                    [spoiler_handle]
                ),
                browser_masters._EDIT_UTM_INPUT_TESTID: _UtmFieldLocator(),
                edit_form_ready: _FakeLocator([_FakeLocatorHandle()]),
            },
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

    def test_a_stale_first_read_is_recovered_by_re_navigating(self):
        # First post-save load serves the PREVIOUS value; the next load has
        # the real one. Must succeed, not raise.
        page = self._page([self.STALE, self.NEW])

        result = browser_masters.update_master(page, 42, tracking_params=self.NEW)

        self.assertEqual(result["TrackingParams"], self.NEW)

    def test_recovers_after_multiple_consecutive_stale_reads(self):
        # Issue #829: on long sequential batch runs (17 campaigns in ~35
        # minutes, same profile), the post-save re-render race #790 already
        # retries for can outlast a single extra reload — live logs showed
        # "did not save as requested" survive whatever reload budget was in
        # place at the time. This models three consecutive stale reads
        # (deeper than the two-load case #790's fix already covers) that
        # only resolve on the fourth: the wider retry budget must still
        # recover it, not just the single-retry case.
        page = self._page([self.STALE, self.STALE, self.STALE, self.NEW])

        result = browser_masters.update_master(page, 42, tracking_params=self.NEW)

        self.assertEqual(result["TrackingParams"], self.NEW)

    def test_a_persistently_wrong_value_still_fails(self):
        # The retry must not paper over a genuine save failure: a value that
        # never converges is still reported.
        page = self._page([self.STALE])

        with self.assertRaises(browser_masters.BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, tracking_params=self.NEW)

        self.assertIn("tracking_params", str(ctx.exception))

    def test_a_genuine_failure_message_carries_the_readable_diff(self):
        # Issue #774's second ask: the failure a user actually sees must
        # explain WHAT differs, not just print two long strings.
        page = self._page([self.STALE])

        with self.assertRaises(browser_masters.BrowserSessionError) as ctx:
            browser_masters.update_master(page, 42, tracking_params=self.NEW)

        self.assertIn("missing", str(ctx.exception))

    def test_an_unmountable_section_fails_without_burning_the_read_budget(self):
        # Cycle-review of PR #780: `_wait_for_utm_section` returns False when
        # the section never mounts, but that verdict was discarded — so the
        # caller went on to spend the FULL `_read_until_matches` budget
        # re-reading a field that returns None instantly, ~50s per attempt
        # (30s wait + 20s read) instead of failing fast on the wait alone.
        # Driven through `_verify_saved` directly: the WRITE path expands the
        # same spoiler, so an always-absent trigger would fail there first and
        # never reach the read budget this test is about.
        class _NeverMountingSpoiler:
            @property
            def first(self):
                # `_expand_utm_spoiler` resolves `.first` before probing
                # `.count()`; the handle is never actually used because the
                # count is 0.
                return _FakeLocatorHandle()

            def count(self):
                return 0

        page = self._page([self.NEW])
        page.goto(browser_masters.WIZARD_EDIT_URL.format(campaign_id=42))
        page._locators[browser_masters._EDIT_UTM_SPOILER_BUTTON_TESTID] = (
            _NeverMountingSpoiler()
        )

        # Counting `_read_until_matches` entries is what actually
        # discriminates the two code paths. Counting field reads does NOT:
        # `_read_tracking_params` short-circuits on the same absent spoiler,
        # so the field locator is untouched whether or not the caller
        # honours the readability verdict — an assertion on field reads
        # passes against the unfixed code too.
        real_read_until = browser_masters._read_until_matches
        budget_entries = {"n": 0}

        def _counting_read_until(page_, reader, expected, **kwargs):
            if reader is browser_masters._read_tracking_params:
                budget_entries["n"] += 1
            return real_read_until(page_, reader, expected, **kwargs)

        with patch.object(browser_masters, "_read_until_matches", _counting_read_until):
            with self.assertRaises(browser_masters.BrowserSessionError) as ctx:
                browser_masters._verify_saved(
                    page,
                    42,
                    weekly_budget=None,
                    promotion_goal=None,
                    directs_helps=None,
                    tracking_params=self.NEW,
                )

        # Reported as unreadable, not as an empty field (issue #774 point 3).
        self.assertIn("could not be read", str(ctx.exception))
        # The unreadable verdict short-circuits: not one read budget is
        # opened on a field that cannot be mounted.
        self.assertEqual(budget_entries["n"], 0)

    def test_re_navigation_re_runs_the_audience_hydration_gate(self):
        # Cycle-review of PR #780: the stale-render reload is page-level, but
        # the retry loop re-navigated WITHOUT re-running
        # `_wait_for_audience_section`. Every audience check runs after the
        # tracking_params block, so on a combined update they then read a
        # freshly-navigated, still-hydrating section — the exact race #681
        # added that gate for.
        # Driven through `_verify_saved` directly rather than
        # `update_master`, so the fake page needs no device dropdown to
        # write through — the gate's re-run on re-navigation is the whole
        # subject here, not the setter.
        calls = {"gate": 0}
        page = self._page([self.STALE, self.NEW])
        # `_verify_saved` navigates itself; `_page` counts post-save loads
        # from -2 because `update_master` opens the form first.
        page.goto(browser_masters.WIZARD_EDIT_URL.format(campaign_id=42))

        def _counting_gate(_page):
            calls["gate"] += 1

        # The devices check itself has no fake dropdown to read and will
        # therefore report a mismatch; irrelevant here — the subject is
        # whether the gate ran again after the re-navigation.
        with patch.object(
            browser_masters, "_wait_for_audience_section", _counting_gate
        ):
            with contextlib.suppress(browser_masters.BrowserSessionError):
                browser_masters._verify_saved(
                    page,
                    42,
                    weekly_budget=None,
                    promotion_goal=None,
                    directs_helps=None,
                    tracking_params=self.NEW,
                    devices={"desktop"},
                )

        # Once for the initial post-save reload, once for the re-navigation.
        self.assertEqual(calls["gate"], 2)

    def test_other_fields_are_re_verified_on_the_re_navigated_page(self):
        # Cycle-review round 2 of PR #780: a stale render is PAGE-level, so
        # the fields checked BEFORE the tracking_params block are stale on
        # the same initial load that made tracking_params stale. They were
        # read once and never re-read on the page the re-navigation just
        # fetched, so a combined update could still false-fail on `name`
        # while tracking_params recovered — the exact false "did not save"
        # this PR exists to remove.
        loads = {"n": -2}
        names = ["stale name", "new name"]

        def _current_name():
            return names[min(max(loads["n"], 0), len(names) - 1)]

        class _NameHandle(_FakeLocatorHandle):
            def inner_text(self, timeout=None):
                return _current_name()

        class _NameLocator:
            @property
            def first(self):
                return _NameHandle()

            def count(self):
                return 1

        page = self._page([self.STALE, self.NEW])
        original_goto = page.goto

        def _tracking_goto(url, **kwargs):
            loads["n"] += 1
            return original_goto(url, **kwargs)

        page.goto = _tracking_goto
        page._locators[browser_masters._NAME_HEADER_SELECTOR] = _NameLocator()
        page.goto(browser_masters.WIZARD_EDIT_URL.format(campaign_id=42))

        # `name` is stale on the first post-save load and correct on the
        # re-navigated one, exactly like tracking_params.
        browser_masters._verify_saved(
            page,
            42,
            weekly_budget=None,
            promotion_goal=None,
            directs_helps=None,
            name="new name",
            tracking_params=self.NEW,
        )

    def test_the_writer_tolerates_a_late_mounting_spoiler(self):
        # Cycle-review of PR #780: this PR's central finding is that the
        # "Дополнительные параметры" section can stay unmounted long after
        # `_wait_for_edit_form` returns (90s measured live). The READ path
        # now waits that out; the WRITE path still raised on the first
        # missing trigger, so the same slow load hard-fails the update with
        # a "Yandex may have changed the page's markup" message that is
        # wrong for a transient hydration delay.
        # Driven straight at `_set_tracking_params`, so the late-mounting
        # trigger is consumed by the WRITE path alone. Going through
        # `update_master` would let the verify path's own probes exhaust the
        # unmounted window first, and the test would pass either way.
        # Must exceed `_SPOILER_EXPAND_MAX_ATTEMPTS`: `_expand_utm_spoiler`
        # already retries its own click that many times, so a shorter delay
        # is absorbed there and the test passes without the outer wait.
        mounts = {"left": browser_masters._SPOILER_EXPAND_MAX_ATTEMPTS + 2}
        expanded = {"open": False}
        field = _FakeContentEditableHandle(text="")

        class _LateMountingHandle(_DynamicAttrsLocatorHandle):
            # `_expand_utm_spoiler` probes `count()` on the HANDLE, not on
            # the locator — putting the counter on the locator leaves it
            # never called and the "late mount" never happens.
            def count(self):
                if mounts["left"] > 0:
                    mounts["left"] -= 1
                    return 0
                return 1

        spoiler_handle = _LateMountingHandle(
            get_attrs=lambda: {
                "aria-expanded": "true" if expanded["open"] else "false"
            },
            on_click=lambda: expanded.__setitem__("open", True),
        )

        page = FakePage(
            locators={
                browser_masters._EDIT_UTM_SPOILER_BUTTON_TESTID: _FakeLocator(
                    [spoiler_handle]
                ),
                browser_masters._EDIT_UTM_INPUT_TESTID: _FakeLocator([field]),
            }
        )

        browser_masters._set_tracking_params(page, self.NEW)

        self.assertEqual(field.text_content(), self.NEW)


class TestDescribeValueMismatch(unittest.TestCase):
    """``describe_value_mismatch`` — issue #774's readable diff for long
    near-identical strings in ``_verify_saved``'s failure message."""

    # The exact pair from issue #774: the reporter's requested value, and the
    # value a screenshot of the UI showed after the "failed" save.
    EXPECTED = (
        "utm_source=yandex_alexey&utm_medium=cpc&utm_campaign={campaign_id}"
        "&utm_term={gbid}|kw|{keyword}&utm_content={ad_id}"
    )
    REORDERED = (
        "utm_source=yandex_alexey&utm_medium=cpc&utm_campaign={campaign_id}"
        "&utm_term={gbid}&utm_content={ad_id}|kw|{keyword}"
    )

    def test_reports_a_relocated_fragment_as_a_single_moved_line(self):
        # The whole point of the helper: #774's signature must collapse to
        # ONE line naming the fragment and both positions, not two
        # 110-character reprs the reader has to align by eye.
        detail = browser_masters.describe_value_mismatch(self.EXPECTED, self.REORDERED)

        self.assertEqual(len(detail.splitlines()), 1, detail)
        self.assertIn("moved", detail)
        self.assertIn("|kw|{keyword}", detail)
        self.assertNotIn("missing", detail)
        self.assertNotIn("extra", detail)

    def test_moved_line_names_both_positions(self):
        detail = browser_masters.describe_value_mismatch(self.EXPECTED, self.REORDERED)

        self.assertIn(str(self.EXPECTED.index("|kw|{keyword}")), detail)
        self.assertIn(str(self.REORDERED.index("|kw|{keyword}")), detail)

    def test_reports_a_dropped_tail_as_missing_not_moved(self):
        # #769's original hypothesis (Yandex truncating the tail) must read
        # differently from #774's reorder — that distinction is the reason
        # the helper exists.
        truncated = self.EXPECTED.replace("|kw|{keyword}", "")

        detail = browser_masters.describe_value_mismatch(self.EXPECTED, truncated)

        self.assertIn("missing", detail)
        self.assertIn("|kw|{keyword}", detail)
        self.assertNotIn("moved", detail)

    def test_reports_unrequested_text_as_extra(self):
        detail = browser_masters.describe_value_mismatch(
            self.EXPECTED, self.EXPECTED + "&utm_extra=1"
        )

        self.assertIn("extra", detail)
        self.assertIn("utm_extra=1", detail)

    def test_empty_page_value_is_called_out_in_words(self):
        # Distinguishing "" from a reorder is #774's investigation point 3;
        # a character diff against "" would be useless noise.
        detail = browser_masters.describe_value_mismatch(self.EXPECTED, "")

        self.assertEqual(detail.strip(), "- expected a value, but the field is empty")

    def test_unreadable_field_is_distinguished_from_an_empty_one(self):
        detail = browser_masters.describe_value_mismatch(self.EXPECTED, None)

        self.assertIn("could not be read", detail)

    def test_equal_values_produce_no_detail(self):
        self.assertEqual(
            browser_masters.describe_value_mismatch(self.EXPECTED, self.EXPECTED), ""
        )

    def test_short_values_produce_no_detail(self):
        # A short pair is already readable as two reprs; adding a diff would
        # only double the message.
        self.assertEqual(browser_masters.describe_value_mismatch("abc", "abd"), "")

    def test_a_one_sided_duplicate_reports_the_move_and_keeps_the_leftover(self):
        # A fragment present twice in `actual` but once in `expected`. The
        # relocation is reported as a move; the SECOND, unrequested copy is
        # a genuine addition and must still show up rather than being
        # absorbed by that pairing.
        expected = "a" * 30 + "|kw|" + "b" * 30
        actual = "a" * 30 + "b" * 30 + "|kw|" + "|kw|"

        detail = browser_masters.describe_value_mismatch(expected, actual)

        self.assertIn("moved", detail)
        self.assertIn("|kw|", detail)
        # Nothing silently vanishes: the extra copy is accounted for on its
        # OWN line. The previous assertion here compared `detail.count(...)`
        # to itself — a tautology that passed while the leftover was in fact
        # being absorbed, because difflib emits the two adjacent copies as a
        # single '|kw||kw|' insert that the move-pairing consumed whole.
        extra_lines = [
            line for line in detail.splitlines() if line.strip().startswith("- extra")
        ]
        self.assertEqual(len(extra_lines), 1, detail)
        self.assertIn("|kw|", extra_lines[0])

    def test_two_distinct_relocations_produce_two_moved_lines(self):
        # The pairing bookkeeping itself: two DISTINCT relocated fragments
        # must produce two distinct moved lines, not one fragment matched
        # against both extras.
        expected = "x" * 20 + "|aaaa|" + "y" * 20 + "|bbbb|" + "z" * 20
        actual = "x" * 20 + "y" * 20 + "|aaaa|" + "z" * 20 + "|bbbb|"

        detail = browser_masters.describe_value_mismatch(expected, actual)

        self.assertEqual(detail.count("moved"), 2, detail)
        self.assertIn("aaaa", detail)
        self.assertIn("bbbb", detail)

    def test_a_two_character_coincidence_is_not_called_a_move(self):
        # _VALUE_DIFF_MIN_MOVE_LEN: a stray delimiter that happens to occur
        # elsewhere is noise, and calling it "moved" would bury the real
        # difference. Reported as plain missing/extra instead.
        expected = "q" * 25 + "ab" + "r" * 25
        actual = "q" * 25 + "r" * 25 + "ab"

        detail = browser_masters.describe_value_mismatch(expected, actual)

        self.assertNotIn("moved", detail)
        self.assertIn("missing", detail)


class TestFormatValueMismatch(unittest.TestCase):
    """``_format_value_mismatch`` — the ``_verify_saved`` line wrapper that
    appends ``describe_value_mismatch``'s breakdown (issue #774)."""

    def test_long_string_mismatch_keeps_the_raw_pair_and_adds_the_diff(self):
        expected = TestDescribeValueMismatch.EXPECTED
        actual = TestDescribeValueMismatch.REORDERED

        line = browser_masters._format_value_mismatch(
            "tracking_params", expected, actual
        )

        # The raw pair stays — it is what a reader copies into a re-run.
        self.assertIn(f"expected {expected!r}", line)
        self.assertIn(f"page now shows {actual!r}", line)
        self.assertIn("moved", line)

    def test_non_string_values_keep_the_plain_form(self):
        line = browser_masters._format_value_mismatch("weekly_budget", 95000, 80000)

        self.assertEqual(line, "weekly_budget: expected 95000, page now shows 80000")
        self.assertEqual(len(line.splitlines()), 1)

    def test_unreadable_string_field_still_gets_a_worded_detail(self):
        line = browser_masters._format_value_mismatch(
            "tracking_params", TestDescribeValueMismatch.EXPECTED, None
        )

        self.assertIn("could not be read", line)


class TestVerifyImageSetMismatches(unittest.TestCase):
    """``_verify_image_set_mismatches`` — absolute end-state verification
    generalizing ``_verify_image_mismatches``'s hardcoded "removed count ==
    added count" assumption, so ``masters adimages add/delete/set`` can each
    state their own expected end size.
    """

    def test_no_mismatches_when_end_state_matches(self):
        page = _FakeImagesPage(["a", "c", "new"])  # "b" removed, "new" added

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=["a", "c"],
            removed_ids={"b"},
            expected_added_count=1,
        )

        self.assertEqual(mismatches, [])

    def test_asserts_the_set_is_now_empty(self):
        """The ``delete --all`` / ``set`` with no files case — the old
        ``_verify_image_mismatches`` couldn't express this at all."""
        page = _FakeImagesPage([])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=[],
            removed_ids={"a", "b", "c"},
            expected_added_count=0,
        )

        self.assertEqual(mismatches, [])

    def test_flags_a_leftover_image_when_set_should_be_empty(self):
        page = _FakeImagesPage(["leftover"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=[],
            removed_ids={"a"},
            expected_added_count=0,
        )

        self.assertTrue(any("expected 0" in m for m in mismatches))

    def test_flags_a_removed_id_still_present(self):
        page = _FakeImagesPage(["a", "b"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page, expected_kept_ids=[], removed_ids={"a", "b"}, expected_added_count=0
        )

        self.assertTrue(any("still present" in m for m in mismatches))

    def test_flags_a_kept_id_that_went_missing(self):
        page = _FakeImagesPage(["a"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page,
            expected_kept_ids=["a", "b"],
            removed_ids=set(),
            expected_added_count=0,
        )

        self.assertTrue(any("missing" in m for m in mismatches))

    def test_flags_wrong_end_size_with_both_numbers(self):
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_set_mismatches(
            page, expected_kept_ids=["a"], removed_ids=set(), expected_added_count=1
        )

        self.assertTrue(any("has 3 image(s), expected 2" in m for m in mismatches))


class TestFetchMasterImages(unittest.TestCase):
    """``fetch_master_images`` — read-only, never saves."""

    def test_returns_positions_content_ids_and_thumb_urls(self):
        page = _FakeImagesPage(["a", "b", "c"])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["CampaignId"], 42)
        self.assertEqual(result["Count"], 3)
        self.assertEqual(result["MaxCount"], browser_masters._IMAGES_MAX_COUNT)
        self.assertEqual(
            result["Images"],
            [
                {"Position": 1, "ContentId": "a", "ThumbUrl": "a"},
                {"Position": 2, "ContentId": "b", "ThumbUrl": "b"},
                {"Position": 3, "ContentId": "c", "ThumbUrl": "c"},
            ],
        )
        self.assertEqual(page.save_clicks, [])

    def test_empty_set_is_a_successful_result_not_an_error(self):
        page = _FakeImagesPage([])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["Count"], 0)
        self.assertEqual(result["Images"], [])
        self.assertEqual(page.save_clicks, [])

    def test_never_clicks_save(self):
        """The modal opens to read thumb URLs, but is abandoned rather than
        Saved — nothing commits to the saved image set (see
        ``fetch_master_images``'s docstring: same abandon-safe invariant
        ``_set_image``/``_apply_image_operations`` rely on)."""
        page = _FakeImagesPage(["a", "b"])

        browser_masters.fetch_master_images(page, 42)

        self.assertEqual(page.save_clicks, [])

    def test_empty_set_never_opens_the_modal(self):
        """Nothing to read a thumb URL for, so the modal stays shut."""
        page = _FakeImagesPage([])

        result = browser_masters.fetch_master_images(page, 42)

        self.assertEqual(result["Count"], 0)
        self.assertFalse(page.modal_open)

    def test_unrendered_editor_raises_rather_than_reporting_no_images(self):
        class _NoEditorPage(_FakeImagesPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.fetch_master_images(page, 42)

        self.assertIn("did not finish rendering", str(ctx.exception))
        self.assertNotIn("no images", str(ctx.exception).lower())


class TestAddMasterImages(unittest.TestCase):
    """``add_master_images`` — append into an existing or empty set."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_appends_into_an_empty_set(self):
        page, save_clicks = self._page_with_save([], upload_ids=["new1"])

        result = browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertEqual(page.ids, ["new1"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Added": 1, "Count": 1})

    def test_appends_onto_an_existing_set(self):
        page, save_clicks = self._page_with_save(["a", "b"], upload_ids=["new1"])

        result = browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertEqual(page.ids, ["a", "b", "new1"])
        self.assertEqual(result, {"CampaignId": 42, "Added": 1, "Count": 3})

    def test_exceeding_the_cap_raises_and_never_opens_the_modal(self):
        page, save_clicks = self._page_with_save(["a", "b", "c", "d", "e"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertIn("cap", str(ctx.exception).lower())
        self.assertFalse(page.modal_open)
        self.assertEqual(save_clicks, [])

    def test_auth_error_during_verification_is_re_raised_non_idempotent(self):
        page, _save_clicks = self._page_with_save([], upload_ids=["new1"])
        with patch.object(
            browser_masters,
            "_verify_saved_images",
            side_effect=BrowserAuthError("stale session"),
        ):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.add_master_images(page, 42, paths=["/tmp/a.png"])

        self.assertIn("not idempotent", str(ctx.exception).lower())


class TestDeleteMasterImages(unittest.TestCase):
    """``delete_master_images`` — by position, by content ID, or ``--all``."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_deletes_by_position(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, positions=[1])

        self.assertEqual(page.ids, ["a", "c"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 1, "Count": 2})

    def test_deletes_by_content_id(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, content_ids=["b"])

        self.assertEqual(page.ids, ["a", "c"])
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 1, "Count": 2})

    def test_deletes_all(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"])

        result = browser_masters.delete_master_images(page, 42, all_images=True)

        self.assertEqual(page.ids, [])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 3, "Count": 0})

    def test_all_on_an_already_empty_set_is_an_idempotent_no_op(self):
        page, save_clicks = self._page_with_save([])

        result = browser_masters.delete_master_images(page, 42, all_images=True)

        self.assertEqual(result, {"CampaignId": 42, "Deleted": 0, "Count": 0})
        self.assertEqual(save_clicks, [])
        self.assertFalse(page.modal_open)

    def test_out_of_range_position_raises(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.delete_master_images(page, 42, positions=[5])

        self.assertIn("out of range", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])

    def test_unknown_content_id_raises(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.delete_master_images(page, 42, content_ids=["ghost"])

        self.assertIn("not present", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])

    def test_all_with_launch_still_publishes_an_already_empty_draft(self):
        """Issue #678: ``--launch`` is a second, independent request ("publish
        the draft while saving") that an images no-op must not swallow — the
        help text's only stated exception is a non-DRAFT campaign, not an
        empty image set.
        """
        clicks = []

        def _on_launch_click():
            clicks.append("launch")
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)

        page = _FakeImagesPage(
            [],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_launch_click)]
                ),
            },
        )

        result = browser_masters.delete_master_images(
            page, 42, all_images=True, launch=True
        )

        self.assertEqual(clicks, ["launch"])
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 0, "Count": 0})
        self.assertFalse(page.modal_open)

    def test_all_on_an_already_empty_set_without_launch_is_still_a_no_op(self):
        """Guard: without ``--launch``, an empty ``--all`` must remain a true
        no-op — nothing clicked, least of all a publish button."""
        clicks = []
        page = _FakeImagesPage(
            [],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            },
        )

        result = browser_masters.delete_master_images(page, 42, all_images=True)

        self.assertEqual(clicks, [])
        self.assertEqual(result, {"CampaignId": 42, "Deleted": 0, "Count": 0})
        self.assertFalse(page.modal_open)


class TestSetMasterImages(unittest.TestCase):
    """``set_master_images`` — whole-set replacement in one modal."""

    def _page_with_save(self, ids, **kwargs):
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = _FakeImagesPage(
            ids,
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
            **kwargs,
        )
        return page, save_clicks

    def test_full_replacement_in_one_modal(self):
        page, save_clicks = self._page_with_save(["a", "b", "c"], upload_ids=["x", "y"])

        result = browser_masters.set_master_images(
            page, 42, paths=["/tmp/x.png", "/tmp/y.png"]
        )

        self.assertEqual(page.ids, ["x", "y"])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Count": 2})

    def test_empty_paths_empties_the_set(self):
        page, save_clicks = self._page_with_save(["a", "b"])

        result = browser_masters.set_master_images(page, 42, paths=[])

        self.assertEqual(page.ids, [])
        self.assertEqual(len(save_clicks), 1)
        self.assertEqual(result, {"CampaignId": 42, "Count": 0})

    def test_already_empty_with_no_paths_is_a_no_op(self):
        page, save_clicks = self._page_with_save([])

        result = browser_masters.set_master_images(page, 42, paths=[])

        self.assertEqual(result, {"CampaignId": 42, "Count": 0})
        self.assertEqual(save_clicks, [])
        self.assertFalse(page.modal_open)

    def test_exceeding_the_cap_raises(self):
        page, save_clicks = self._page_with_save([])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.set_master_images(
                page,
                42,
                paths=[f"/tmp/{i}.png" for i in range(6)],
            )

        self.assertIn("cap", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])

    def test_empty_with_launch_still_publishes_an_already_empty_draft(self):
        """Issue #678, symmetric case: ``set --allow-empty --launch`` on an
        already-empty DRAFT must still publish it."""
        clicks = []

        def _on_launch_click():
            clicks.append("launch")
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(campaign_id=42)

        page = _FakeImagesPage(
            [],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=_on_launch_click)]
                ),
            },
        )

        result = browser_masters.set_master_images(page, 42, paths=[], launch=True)

        self.assertEqual(clicks, ["launch"])
        self.assertEqual(result, {"CampaignId": 42, "Count": 0})
        self.assertFalse(page.modal_open)

    def test_already_empty_with_no_paths_without_launch_is_still_a_no_op(self):
        """Guard: without ``--launch``, empty-in/empty-out remains a true
        no-op — nothing clicked, least of all a publish button."""
        clicks = []
        page = _FakeImagesPage(
            [],
            locators={
                browser_masters._DRAFT_SAVE_DRAFT_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("draft"))]
                ),
                browser_masters._DRAFT_LAUNCH_BUTTON_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(on_click=lambda: clicks.append("launch"))]
                ),
            },
        )

        result = browser_masters.set_master_images(page, 42, paths=[])

        self.assertEqual(clicks, [])
        self.assertEqual(result, {"CampaignId": 42, "Count": 0})
        self.assertFalse(page.modal_open)


class TestVerifyImageMismatches(unittest.TestCase):
    """``_verify_image_mismatches`` (issue #670, Этап D) — set-membership
    verification, NOT positional (see ``_set_image``'s docstring for why).
    """

    def test_no_mismatches_when_replaced_gone_and_kept_present(self):
        page = _FakeImagesPage(["a", "c", "new"])  # "b" was replaced by "new"

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertEqual(mismatches, [])

    def test_flags_a_replaced_id_still_present(self):
        """Yandex silently rejected the replacement — "b" never left."""
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertTrue(any("still present" in m for m in mismatches))

    def test_flags_a_kept_id_that_went_missing(self):
        """Something clobbered an image the caller never asked to touch."""
        page = _FakeImagesPage(["a", "new"])  # "c" vanished unexpectedly

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=["a", "b", "c"], replaced_ids={"b"}
        )

        self.assertTrue(any("missing" in m for m in mismatches))

    def test_no_requested_replacements_is_a_no_op(self):
        page = _FakeImagesPage(["a", "b", "c"])

        mismatches = browser_masters._verify_image_mismatches(
            page, before_ids=[], replaced_ids=set()
        )

        self.assertEqual(mismatches, [])


class TestSetRegion(unittest.TestCase):
    """``_set_region`` (issue #632, re-recon #653) — the one genuinely-empty
    required field.

    Issue #653 re-recon (2026-08-02): Yandex replaced the old text-combobox
    with a tree/tag-group widget. The fake models: clicking the launcher
    (``_REGION_LAUNCHER_TESTID``) reveals a separate filter field
    (``_REGION_EDITOR_TESTID``), typing into it is a no-op on the fake page
    (the real tree-filtering is server/client-state this fake does not
    model), and the node is matched by an XPath string built from
    ``_xpath_literal(region)`` — the fake's ``locator()`` keys on that exact
    XPath string, same convention ``_REGION_INPUT_XPATH`` used pre-#653.

    The fake models the real toggle semantics confirmed live: the LABEL is
    what gets clicked (the ``<input>`` it wraps is not actionable), and the
    input's checked state is what gets read back — so a label click flips the
    input, exactly like the real control.
    """

    def _label_xpath(self, region):
        return (
            "xpath=//label[@data-testid='RegionsTreeNode.Checkbox.label']"
            f"[normalize-space(.)={browser_masters._xpath_literal(region)}]"
        )

    # Relative xpath _set_region scopes off the matched label handle itself
    # (issue #656) — ``handle.locator(_CHECKBOX_SUB_XPATH)``, not a second
    # independent ``page.locator()`` built from the label's own xpath.
    _CHECKBOX_SUB_XPATH = (
        f"xpath=.//input[@data-testid='{browser_masters._REGION_CHECKBOX_TESTID}']"
    )

    def _region_node(self, region, checked, visible=True, node_id=None):
        """A (label, input) pair whose label click toggles the input.

        ``node_id`` models the checkbox's stable ``id="region-node-<id>"``
        attribute (issue #657) — ``None`` means the fake node has no ``id``
        attribute at all, same as any test written before that issue. The
        checkbox is wired onto the label as a ``sub_locators`` child (issue
        #656), mirroring ``_set_region``'s scoped ``handle.locator(...)``
        lookup, not a separate top-level locator.
        """
        state = {"checked": False}

        def _toggle():
            state["checked"] = not state["checked"]
            if state["checked"]:
                checked.append(region)
            else:
                with contextlib.suppress(ValueError):
                    checked.remove(region)

        attrs = {"id": node_id} if node_id is not None else {}
        box = _FakeLocatorHandle(get_checked=lambda: state["checked"], attrs=attrs)
        label = _FakeLocatorHandle(
            visible=visible,
            on_click=_toggle,
            sub_locators={self._CHECKBOX_SUB_XPATH: box},
        )
        return label, box

    def _page_for_region(self, region, checkbox_visible=True, node_id=None):
        launcher = _FakeLocatorHandle()
        editor = _FakeLocatorHandle()
        locators = {
            browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
            browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
        }
        checked = []
        if checkbox_visible:
            label, box = self._region_node(region, checked, node_id=node_id)
            locators[self._label_xpath(region)] = _FakeLocator([label])
        return FakePage(locators=locators), checked

    def test_fills_and_selects_each_region(self):
        page, checked = self._page_for_region("Москва")

        browser_masters._set_region(page, ["Москва"])

        self.assertEqual(checked, ["Москва"])

    def test_accepts_a_plain_string_region_with_no_identity_check(self):
        # A plain str entry (what --region gives, with no known RegionId)
        # must keep working exactly as before #657 — no id attribute is
        # ever read for it.
        page, checked = self._page_for_region("Москва", node_id=None)

        browser_masters._set_region(page, ["Москва"])

        self.assertEqual(checked, ["Москва"])

    def test_accepts_a_name_region_id_pair_whose_node_id_matches(self):
        # Issue #657: a (name, region_id) pair whose checked node's
        # id="region-node-<RegionId>" matches the requested RegionId must
        # select successfully, same as a plain string.
        page, checked = self._page_for_region("Москва", node_id="region-node-213")

        browser_masters._set_region(page, [("Москва", 213)])

        self.assertEqual(checked, ["Москва"])

    def test_rejects_a_node_whose_id_does_not_match_the_requested_region_id(self):
        # The GeoRegions dictionary is not name-unique — a checkbox whose
        # LABEL matches "Сосновка" exactly could still be the WRONG
        # Сосновка. If its id doesn't encode the requested RegionId, this
        # must raise instead of silently selecting the wrong region.
        page, checked = self._page_for_region("Сосновка", node_id="region-node-999")

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._set_region(page, [("Сосновка", 111)])

        self.assertIn("Сосновка", str(ctx.exception))
        self.assertIn("111", str(ctx.exception))
        # The wrong node must not be left checked after the mismatch —
        # it's clicked once to select, then clicked again to undo it.
        self.assertEqual(checked, [])

    def test_rejects_a_node_with_no_id_attribute_when_region_id_is_requested(self):
        # A checkbox with no id attribute at all (e.g. markup drift) cannot
        # be confirmed as the right node, so a requested RegionId must still
        # refuse rather than assume a match.
        page, checked = self._page_for_region("Москва", node_id=None)

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._set_region(page, [("Москва", 213)])

        self.assertEqual(checked, [])

    def test_raises_when_launcher_missing(self):
        # Issue #656: the popup never opened at all (the launcher itself is
        # missing) is a DIFFERENT failure from "the popup opened but the
        # region wasn't in the filtered tree" — the two must raise
        # distinguishable messages, not just "some BrowserSessionError",
        # which would pass equally if the code regressed onto the wrong
        # branch (see test_raises_when_checkbox_not_found for the sibling
        # case).
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._set_region(page, ["Москва"])
        self.assertIn("Could not find or open", str(ctx.exception))
        self.assertNotIn("Москва", str(ctx.exception))

    def test_raises_when_checkbox_not_found(self):
        # Unlike test_raises_when_launcher_missing, the popup DID open (the
        # launcher/editor are present) — the region simply never matched a
        # node in the filtered tree. This must raise the "could not find
        # {region} in the tree" message, not the launcher-missing one.
        page, _ = self._page_for_region("Атлантида", checkbox_visible=False)

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._set_region(page, ["Атлантида"])
        self.assertIn("Атлантида", str(ctx.exception))
        self.assertNotIn("Could not find or open", str(ctx.exception))

    def test_raises_playwright_version_hint_when_clear_never_succeeds(self):
        # Issue #656: if the filter field's clear (select-all + Backspace)
        # never succeeds across every retry — the pre-1.44 Playwright
        # ``ControlOrMeta`` failure _clear_text_field's docstring
        # describes — each retype APPENDS onto the previous attempt's
        # leftover text ("МоскваМосква"), which can never filter-match. The
        # resulting "region not found" must say so, not blame the region
        # name (a real region that legitimately doesn't exist looks
        # identical to the caller otherwise).
        launcher = _FakeLocatorHandle()
        editor = _FakeContentEditableHandle(supports_modifier=False)
        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
                # No label ever matches — an uncleared, ever-appending
                # filter field can never produce a match.
            },
        )

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._set_region(page, ["Москва"])

        self.assertIn("could not be cleared", str(ctx.exception))
        self.assertIn("Playwright", str(ctx.exception))
        self.assertNotIn("check the region name", str(ctx.exception))

    def test_does_not_select_a_decoy_whose_name_only_contains_the_region(self):
        # A decoy checkbox whose label merely CONTAINS the region name
        # (e.g. "Москва и область") must NOT be treated as a match — the
        # fake only registers a locator for the EXACT-match XPath, so a
        # lookup for "Москва" never finds "Москва и область"'s checkbox.
        launcher = _FakeLocatorHandle()
        editor = _FakeLocatorHandle()
        decoy_clicked = []
        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
                self._label_xpath("Москва и область"): _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            visible=True, on_click=lambda: decoy_clicked.append(True)
                        )
                    ]
                ),
            },
        )

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._set_region(page, ["Москва"])
        self.assertEqual(decoy_clicked, [])

    def test_retry_does_not_reclick_launcher_and_clears_before_retyping(self):
        """A retry must start from a known state, not the previous attempt's.

        Issue #653 live testing: the launcher TOGGLES the popup, so clicking
        it again while the popup is open closes it, and ``type()`` APPENDS to
        a contenteditable, so re-typing without clearing yields
        "МоскваМосква" — which filters the tree to zero nodes and can never
        match. Either mistake turns attempts 2..N into guaranteed no-ops that
        only add latency, so both are pinned here.

        The fake models the popup already being open (the editor locator
        matches from the start) and the checkbox only appearing on the second
        attempt.
        """
        launcher_clicks = []
        launcher = _FakeLocatorHandle(on_click=lambda: launcher_clicks.append(True))
        typed = []
        presses = []
        editor = _FakeLocatorHandle(on_fill=typed.append, on_press=presses.append)

        checked = []
        label, box = self._region_node("Москва", checked)

        class _FlakyLabelLocator:
            """Matches nothing on the first attempt, one label afterwards.

            Keyed on how many times the region was TYPED (one per attempt) —
            not on how many times ``count()`` was called, which the caller
            polls repeatedly within a single attempt.
            """

            def count(self):
                return 0 if len(typed) <= 1 else 1

            def nth(self, i):
                return label

        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([editor]),
                self._label_xpath("Москва"): _FlakyLabelLocator(),
            },
        )

        with patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10):
            browser_masters._set_region(page, ["Москва"])

        self.assertEqual(checked, ["Москва"])
        # The popup was already open, so the launcher must never be clicked
        # (clicking it would have closed the popup).
        self.assertEqual(launcher_clicks, [])
        # Two attempts typed the region — each preceded by a clear, so the
        # editor never accumulates "МоскваМосква".
        self.assertEqual(typed, ["Москва", "Москва"])
        self.assertEqual(
            presses, ["ControlOrMeta+a", "Backspace", "ControlOrMeta+a", "Backspace"]
        )

    def test_clicks_launcher_when_popup_is_not_open(self):
        # Mirror of the test above: when the editor is absent (popup closed),
        # the launcher MUST be clicked to open it.
        launcher_clicks = []
        launcher = _FakeLocatorHandle(on_click=lambda: launcher_clicks.append(True))
        page = FakePage(
            locators={
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator([launcher]),
                # No _REGION_EDITOR_TESTID entry -> `.first` raises -> count()==0.
                self._label_xpath("Москва"): _FakeLocator([]),
            },
        )

        with (
            patch.object(browser_masters, "_REGION_FILTER_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._set_region(page, ["Москва"])

        self.assertEqual(len(launcher_clicks), browser_masters._REGION_OPEN_ATTEMPTS)


class TestXpathLiteral(unittest.TestCase):
    """``_xpath_literal`` — safe XPath 1.0 string-literal quoting."""

    def test_quotes_a_plain_value(self):
        self.assertEqual(browser_masters._xpath_literal("Москва"), "'Москва'")

    def test_handles_a_value_containing_a_single_quote(self):
        result = browser_masters._xpath_literal("O'Brien")
        # Must not naively produce 'O'Brien' (invalid XPath) — concat() form.
        self.assertNotEqual(result, "'O'Brien'")
        self.assertTrue(result.startswith("concat("))


class TestReadRegionTags(unittest.TestCase):
    """``_read_region_tags`` (issue #632, re-recon #653) — live-verified tag
    reader for the tree/tag-group widget's accepted selections."""

    def test_returns_every_tag_when_wrapper_present(self):
        page = FakePage(
            locators={
                browser_masters._REGION_TAGS_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._REGION_TAG_TESTID_PATTERN: _FakeLocator(
                    [
                        _FakeLocatorHandle(text="Москва"),
                        _FakeLocatorHandle(text="Санкт-Петербург"),
                    ]
                ),
            }
        )

        self.assertEqual(
            browser_masters._read_region_tags(page), ["Москва", "Санкт-Петербург"]
        )

    def test_returns_empty_list_when_wrapper_missing(self):
        page = FakePage(locators={})

        self.assertEqual(browser_masters._read_region_tags(page), [])


class TestSetWeeklyBudgetOnCreate(unittest.TestCase):
    """``_set_weekly_budget_on_create`` (issue #632)."""

    def test_fills_field_with_bare_integer(self):
        state = {}
        handle = _FakeLocatorHandle(on_fill=lambda v: state.__setitem__("value", v))
        page = FakePage(
            locators={
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator([handle])
            }
        )

        browser_masters._set_weekly_budget_on_create(page, 50000)

        self.assertEqual(state["value"], "50000")

    def test_raises_when_field_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_weekly_budget_on_create(page, 50000)


class TestClickTerminalButton(unittest.TestCase):
    """``_click_terminal_button`` (issue #632) — launch vs. draft, role-scoped.

    Uses ``get_by_role("button", name=text, exact=True)`` (ported from
    ``_click_save``'s fix, issue #631 review): the previous
    ``get_by_text(exact=False)`` risked matching an ancestor container
    instead of the button itself.
    """

    def test_clicks_matching_visible_button(self):
        clicks = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    browser_masters._LAUNCH_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: clicks.append(True)
                    ),
                )
            ]
        )

        browser_masters._click_terminal_button(
            page, browser_masters._LAUNCH_BUTTON_TEXT
        )

        self.assertEqual(len(clicks), 1)

    def test_raises_when_button_missing(self):
        page = FakePage(role_elements=[])

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_terminal_button(
                page, browser_masters._SAVE_DRAFT_BUTTON_TEXT
            )

    def test_does_not_click_a_decoy_whose_name_only_contains_the_button_text(self):
        # A decoy element whose accessible name merely CONTAINS the target
        # text (e.g. "Запустить кампанию сейчас") must NOT be treated as a
        # match — exact=True requires exact equality.
        decoy_clicked = []
        page = FakePage(
            role_elements=[
                (
                    "button",
                    f"{browser_masters._LAUNCH_BUTTON_TEXT} сейчас",
                    _FakeTextLocatorHandle(
                        visible=True, on_click=lambda: decoy_clicked.append(True)
                    ),
                )
            ]
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._click_terminal_button(
                page, browser_masters._LAUNCH_BUTTON_TEXT
            )
        self.assertEqual(decoy_clicked, [])


class TestReadCreatedFormMismatches(unittest.TestCase):
    """``_read_created_form_mismatches`` (issue #632, split out in #744's
    cycle-review) — ported from ``update_master``'s ``_verify_saved`` (issue
    #631 review finding): a click on the terminal button is not proof Yandex
    accepted the form.

    Returns the divergences rather than raising; ``_verify_created`` folds
    them into its own error once the campaign id is known. Reading them is
    deliberately separate from reporting them, because the read must happen
    while the create form still exists — before the post-click redirect.
    """

    CAMPAIGN_ID = 713299002

    def _page(self, headline_values, text_values, budget_value=None, region_tags=None):
        locators = {}
        if region_tags is not None:
            # The tags the reloaded edit page reports (issue #744) --
            # _verify_created only navigates/reads these when the caller
            # passes `regions`, so tests that don't care leave them unset.
            locators[browser_masters._REGION_TAGS_WRAPPER_TESTID] = _FakeLocator(
                [_FakeLocatorHandle()]
            )
            locators[browser_masters._REGION_TAG_TESTID_PATTERN] = _FakeLocator(
                [_FakeLocatorHandle(text=name) for name in region_tags]
            )
        for index, value in enumerate(headline_values):
            selector = (
                '[data-testid="'
                + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=index)
                + '"]'
            )
            locators[selector] = _FakeLocator([_FakeLocatorHandle(text=value)])
        for index, value in enumerate(text_values):
            selector = (
                '[data-testid="'
                + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=index)
                + '"]'
            )
            locators[selector] = _FakeLocator([_FakeLocatorHandle(text=value)])
        if budget_value is not None:
            locators[browser_masters._WEEKLY_BUDGET_INPUT_XPATH] = _FakeLocator(
                [_FakeLocatorHandle(get_value=lambda: budget_value)]
            )
        return FakePage(locators=locators)

    def test_passes_when_every_requested_value_is_present(self):
        page = self._page(["Заголовок"], ["Текст объявления"])

        self.assertEqual(
            browser_masters._read_created_form_mismatches(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            ),
            [],
        )

    def test_raises_when_an_unrequested_headline_variant_survives(self):
        """Extra non-empty slots are published variants (issue #655 review).

        The membership-only check this replaced ("is each requested value
        present?") passed happily while four AI-written headlines sat in the
        remaining slots. Every non-empty slot ships as an ad variant, so a
        leftover the clear missed must be a hard failure — this is the
        defense-in-depth layer behind ``_add_repeating_values``' clear.
        """
        page = self._page(
            ["Заголовок", "Центр оздоровления и китайской гимнастики!"],
            ["Текст объявления"],
        )

        mismatches = browser_masters._read_created_form_mismatches(
            page,
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            weekly_budget=None,
        )

        self.assertIn("unrequested headline variants", "; ".join(mismatches))
        self.assertIn("Центр оздоровления", "; ".join(mismatches))

    def test_raises_when_an_unrequested_text_variant_survives(self):
        # Same invariant on the ad-text slots.
        page = self._page(
            ["Заголовок"],
            ["Текст объявления", "Приходите на пробное занятие цигун!"],
        )

        mismatches = browser_masters._read_created_form_mismatches(
            page,
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            weekly_budget=None,
        )

        self.assertIn("unrequested ad-text variants", "; ".join(mismatches))

    def test_raises_when_a_headline_is_missing(self):
        page = self._page(["Другой заголовок"], ["Текст объявления"])

        mismatches = browser_masters._read_created_form_mismatches(
            page,
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            weekly_budget=None,
        )

        self.assertIn("headline 'Заголовок' not found", "; ".join(mismatches))

    def test_raises_when_a_text_is_missing(self):
        page = self._page(["Заголовок"], ["Другой текст"])

        self.assertTrue(
            browser_masters._read_created_form_mismatches(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            )
        )

    def test_raises_when_weekly_budget_does_not_match(self):
        page = self._page(["Заголовок"], ["Текст объявления"], budget_value="10000")

        self.assertIn(
            "weekly_budget: expected 50000",
            "; ".join(
                browser_masters._read_created_form_mismatches(
                    page,
                    headlines=["Заголовок"],
                    texts=["Текст объявления"],
                    weekly_budget=50000,
                )
            ),
        )

    def test_ignores_weekly_budget_when_not_requested(self):
        page = self._page(["Заголовок"], ["Текст объявления"], budget_value="10000")

        self.assertEqual(
            browser_masters._read_created_form_mismatches(
                page,
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                weekly_budget=None,
            ),
            [],
        )  # budget unchecked — caller never asked for one


class TestCreateMaster(unittest.TestCase):
    """``create_master`` (issue #632) — end-to-end wiring of the helpers above."""

    # The campaign id Yandex's post-click redirect carries (issue #744) --
    # see _redirect_to_overview below.
    CREATED_ID = 713299001

    # The Metrika goal id / CPA the create-page tests add (issue #777).
    # A real goal id from the live recon's auto-discovered counter.
    GOAL_ID = 236386933
    GOAL_PRICE = 150

    def _full_page(
        self,
        region="Москва",
        created_id=None,
        reloaded_regions=None,
        redirect=True,
        node_id=None,
        page_after_redirect_has_no_form=False,
        offer_goal_ids=None,
        add_button_testid=None,
        drop_goal_rows_after_add=False,
        revert_goal_price_after_add=None,
    ):
        url_state = {}
        headline_state = []
        text_state = []
        region_checked = []
        budget_state = {}
        launch_clicks = []
        draft_clicks = []
        created_id = self.CREATED_ID if created_id is None else created_id

        def _redirect_to_overview():
            """Model the redirect confirmed live in issue #744.

            Clicking either terminal button sends page.url to the new
            campaign's overview URL -- the same redirect copy_master has
            relied on since #659. Without this the fake would sit on
            /wizard/campaigns/new/ forever, which is precisely the timeout
            case test_raises_when_yandex_never_redirects covers.
            """
            if not redirect:
                return
            page.url = browser_masters.WIZARD_OVERVIEW_URL.format(
                campaign_id=created_id
            )

        url_field = _FakeContentEditableHandle(
            on_fill=lambda v: url_state.__setitem__("url", v)
        )
        headline_last = {"value": ""}

        def _fill_headline(v):
            headline_state.append(v)
            headline_last["value"] = v

        headline_field = _FakeLocatorHandle(
            on_fill=_fill_headline, get_value=lambda: headline_last["value"]
        )
        text_last = {"value": ""}

        def _fill_text(v):
            text_state.append(v)
            text_last["value"] = v

        text_field = _FakeLocatorHandle(
            on_fill=_fill_text, get_value=lambda: text_last["value"]
        )
        region_launcher = _FakeLocatorHandle()
        region_editor = _FakeLocatorHandle()
        budget_field = _FakeLocatorHandle(
            on_fill=lambda v: budget_state.__setitem__("value", v),
            get_value=lambda: budget_state.get("value", ""),
        )

        next_button = _FakeLocatorHandle()

        # The real page always renders every slot (issue #653 recon: exactly
        # 5 headline / 3 text slots, no "add another" control) — registering
        # only slot 0 was unrealistic and hid the issue #655 round-2 finding
        # that a click failure on an UNUSED slot must still be fatal. Slot 0
        # is the caller-filled one (headline_field/text_field, wired to
        # headline_state/text_state below); the rest start genuinely empty,
        # same as the real create page's trailing slots.
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        text_selector = (
            '[data-testid="'
            + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        extra_headline_selectors = {
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=i)
            + '"]': _FakeLocator([_FakeContentEditableHandle(text="")])
            for i in range(1, browser_masters._HEADLINES_SLOT_COUNT)
        }
        extra_text_selectors = {
            '[data-testid="'
            + browser_masters._TEXTS_TESTID_TEMPLATE.format(index=i)
            + '"]': _FakeLocator([_FakeContentEditableHandle(text="")])
            for i in range(1, browser_masters._TEXTS_SLOT_COUNT)
        }
        region_label_xpath = (
            "xpath=//label[@data-testid='RegionsTreeNode.Checkbox.label']"
            f"[normalize-space(.)={browser_masters._xpath_literal(region)}]"
        )
        # The label is what gets clicked; the input is what gets read back
        # (confirmed live — see _set_region). Model the real toggle. The
        # checkbox is wired onto the label as a sub_locators child (issue
        # #656), mirroring _set_region's scoped handle.locator(...) lookup.
        region_state = {"checked": False}

        def _toggle_region():
            region_state["checked"] = not region_state["checked"]
            if region_state["checked"]:
                region_checked.append(region)

        region_checkbox_handle = _FakeLocatorHandle(
            get_checked=lambda: region_state["checked"],
            # id="region-node-<RegionId>" (issue #657) — only needed when a
            # test passes regions as (name, RegionId) tuples, since
            # _set_region then cross-checks the clicked node's id against
            # the requested RegionId.
            attrs=None if node_id is None else {"id": node_id},
        )
        region_label_handle = _FakeLocatorHandle(
            visible=True,
            on_click=_toggle_region,
            sub_locators={
                (
                    f"xpath=.//input[@data-testid="
                    f"'{browser_masters._REGION_CHECKBOX_TESTID}']"
                ): region_checkbox_handle
            },
        )

        # "Целевые действия" widget (issue #777 live recon, 2026-08-06).
        # Modelled exactly as the create page behaves: the table starts
        # EMPTY with only an add trigger, clicking it reveals one
        # AddTargetAction.OTHER.<goalId> option per goal on the
        # auto-discovered Metrika counter, and clicking an option appends a
        # row whose PriceInput arrives PRE-FILLED with a Yandex suggestion
        # (not empty, unlike the edit page) — which _add_target_action must
        # overwrite rather than accept.
        offer_goal_ids = (
            [self.GOAL_ID] if offer_goal_ids is None else list(offer_goal_ids)
        )
        # Which of the two live-observed trigger testids this page renders.
        # The create page's empty table uses AddTargetButton; the edit page
        # (and the create page once a row exists) uses MiniGrid.AddButton.
        # Defaulting to the empty-table form is what makes these tests cover
        # the create page's actual markup rather than the edit page's.
        add_button_testid = add_button_testid or (
            browser_masters._TARGET_ACTION_ADD_BUTTON_EMPTY_TESTID_TEMPLATE.format(
                category=browser_masters._TARGET_ACTIONS_CATEGORY
            )
        )
        goal_rows = {}
        goal_price_state = {}
        target_action_popup_open = {"value": False}

        def _fill_goal_price(goal_id, value):
            """The price fill, plus the two ways a successful
            ``_add_target_action`` can still leave the table wrong by the
            time the terminal button is reached (issue #777's pre-click
            gate). Both are modelled here, at the LAST step of the add, so
            they land after the add believes it succeeded and before the
            gate reads the table back.
            """
            goal_price_state[goal_id] = value
            if drop_goal_rows_after_add:
                # A React re-render dropping the row behind us.
                goal_rows.clear()
                page._locators[row_prefix_selector] = _FakeLocator([])
            elif revert_goal_price_after_add is not None:
                goal_price_state[goal_id] = revert_goal_price_after_add

        def _make_goal_locators():
            """Row/price locators for goals currently in the table."""
            out = {}
            for goal_id in goal_rows:
                price_testid = (
                    browser_masters._TARGET_ACTION_PRICE_TESTID_TEMPLATE.format(
                        category=browser_masters._TARGET_ACTIONS_CATEGORY,
                        goal_id=goal_id,
                    )
                )
                out[f'[data-testid="{price_testid}"]'] = _FakeLocator(
                    [
                        _FakeLocatorHandle(
                            on_fill=lambda v, g=goal_id: _fill_goal_price(g, v),
                            get_value=lambda g=goal_id: goal_price_state.get(g, ""),
                        )
                    ]
                )
            return out

        def _add_goal_row(goal_id):
            goal_rows[goal_id] = True
            # Pre-filled Yandex suggestion, confirmed live — the value
            # _add_target_action must not trust.
            goal_price_state.setdefault(goal_id, "160")
            page._locators.update(_make_goal_locators())
            row_template = browser_masters._TARGET_ACTION_ROW_TESTID_TEMPLATE
            page._locators[row_prefix_selector] = _FakeLocator(
                [
                    _FakeLocatorHandle(
                        attrs={
                            "data-testid": row_template.format(
                                category=browser_masters._TARGET_ACTIONS_CATEGORY,
                                goal_id=g,
                            )
                        }
                    )
                    for g in goal_rows
                ]
            )

        row_prefix_selector = (
            f'[data-testid^="TargetActions.'
            f'{browser_masters._TARGET_ACTIONS_CATEGORY}."]'
        )
        # The options are hidden until the trigger opens the popup, which is
        # exactly the state _add_target_action's wait_for(state="visible")
        # polls — a fake that renders them visible from the start would let
        # a broken trigger pass.
        goal_option_handles = []
        goal_option_locators = {}
        for _goal_id in offer_goal_ids:
            _option_testid = (
                browser_masters._TARGET_ACTION_ADD_OPTION_TESTID_TEMPLATE.format(
                    category=browser_masters._TARGET_ACTIONS_CATEGORY,
                    goal_id=_goal_id,
                )
            )
            _handle = _FakeLocatorHandle(
                visible=False,
                on_click=lambda g=_goal_id: _add_goal_row(g),
            )
            goal_option_handles.append(_handle)
            goal_option_locators[f'[data-testid="{_option_testid}"]'] = _FakeLocator(
                [_handle]
            )

        def _open_target_action_popup():
            target_action_popup_open["value"] = True
            for handle in goal_option_handles:
                handle._visible = True

        page = FakePage(
            locators={
                browser_masters._TARGET_ACTIONS_SECTION_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                row_prefix_selector: _FakeLocator([]),
                f'[data-testid="{add_button_testid}"]': _FakeLocator(
                    [_FakeLocatorHandle(on_click=_open_target_action_popup)]
                ),
                **goal_option_locators,
                browser_masters._CREATE_URL_INPUT_TESTID: _FakeLocator([url_field]),
                browser_masters._CREATE_NEXT_BUTTON_TESTID: _FakeLocator([next_button]),
                headline_selector: _FakeLocator([headline_field]),
                text_selector: _FakeLocator([text_field]),
                **extra_headline_selectors,
                **extra_text_selectors,
                browser_masters._REGION_LAUNCHER_TESTID: _FakeLocator(
                    [region_launcher]
                ),
                browser_masters._REGION_EDITOR_TESTID: _FakeLocator([region_editor]),
                region_label_xpath: _FakeLocator([region_label_handle]),
                browser_masters._WEEKLY_BUDGET_INPUT_XPATH: _FakeLocator(
                    [budget_field]
                ),
                # The reloaded edit page's region tags (issue #744).
                # _verify_created navigates to WIZARD_EDIT_URL and re-reads
                # the display region there via _read_region_tags; these are
                # the tags that read finds. Defaults to exactly what the
                # caller selected, so the happy path verifies; a test
                # passing reloaded_regions=[...] models Yandex having
                # dropped/changed the region despite the click landing.
                browser_masters._REGION_TAGS_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._REGION_TAG_TESTID_PATTERN: _FakeLocator(
                    [
                        _FakeLocatorHandle(text=name)
                        for name in (
                            [region] if reloaded_regions is None else reloaded_regions
                        )
                    ]
                ),
            },
            role_elements=[
                (
                    "button",
                    browser_masters._LAUNCH_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True,
                        on_click=lambda: (
                            launch_clicks.append(True),
                            _redirect_to_overview(),
                        ),
                    ),
                ),
                (
                    "button",
                    browser_masters._SAVE_DRAFT_BUTTON_TEXT,
                    _FakeTextLocatorHandle(
                        visible=True,
                        on_click=lambda: (
                            draft_clicks.append(True),
                            _redirect_to_overview(),
                        ),
                    ),
                ),
            ],
            text_buttons={
                browser_masters._CREATE_INVALID_URL_TEXT: _FakeGetByTextLocator([]),
            },
            # Issue #744 cycle-review: model what the post-click redirect
            # actually lands on for a LAUNCHED campaign — the stats
            # dashboard, which renders the region widget on the subsequent
            # /edit/ reload but NOT the wizard's headline/text slots or its
            # budget input (only a DRAFT overview re-renders the form,
            # issue #660). Opt-in, because every other test in this class
            # predates the redirect and asserts against the create form.
            locators_after_navigation=(
                {
                    # The launched campaign's overview renders NEITHER the
                    # wizard slots nor the budget input; the /edit/ reload
                    # that _verify_created performs for the region check
                    # does render them again, which is why the headline
                    # slot below is present. The defect is that the slots
                    # are read on the overview, BEFORE that reload.
                    f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]': (
                        _FakeLocator([_FakeLocatorHandle()])
                    ),
                    browser_masters._REGION_TAGS_WRAPPER_TESTID: _FakeLocator(
                        [_FakeLocatorHandle()]
                    ),
                    browser_masters._REGION_TAG_TESTID_PATTERN: _FakeLocator(
                        [
                            _FakeLocatorHandle(text=name)
                            for name in (
                                [region]
                                if reloaded_regions is None
                                else reloaded_regions
                            )
                        ]
                    ),
                }
                if page_after_redirect_has_no_form
                else None
            ),
        )
        return page, {
            "url": url_state,
            "headlines": headline_state,
            "texts": text_state,
            "region_checked": region_checked,
            "budget": budget_state,
            "launch_clicks": launch_clicks,
            "draft_clicks": draft_clicks,
            # Issue #777: {goal_id: price-as-filled}, so a test can assert
            # the CALLER's price landed rather than Yandex's pre-filled
            # suggestion.
            "goal_prices": goal_price_state,
        }

    def test_launches_by_default(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )

        self.assertEqual(state["url"]["url"], "https://ksamata.ru/")
        self.assertEqual(state["headlines"], ["Заголовок"])
        self.assertEqual(state["texts"], ["Текст объявления"])
        self.assertEqual(state["region_checked"], ["Москва"])
        self.assertEqual(len(state["launch_clicks"]), 1)
        self.assertEqual(len(state["draft_clicks"]), 0)
        self.assertEqual(
            result,
            {
                # Issue #744: the id Yandex's post-click redirect carried.
                "CampaignId": self.CREATED_ID,
                "LandingUrl": "https://ksamata.ru/",
                "Headlines": ["Заголовок"],
                "Texts": ["Текст объявления"],
                "Regions": ["Москва"],
                # Issue #777: the conversion goal(s) the create form
                # required, echoed back so the caller can see which CPA was
                # actually published.
                "TargetActions": {self.GOAL_ID: self.GOAL_PRICE},
                # Issue #796: weekly_budget is required, always echoed back.
                "WeeklyBudget": 1000,
                "Launched": True,
            },
        )
        # Two navigations now (issue #744): the create page, then
        # _verify_created's reload of the new campaign's EDIT page to
        # re-read the display region from a genuinely fresh load.
        self.assertEqual(
            page.navigated_to,
            [
                browser_masters.WIZARD_CREATE_URL,
                browser_masters.WIZARD_EDIT_URL.format(campaign_id=self.CREATED_ID),
            ],
        )
        self.assertEqual(page.goto_wait_until, "commit")

    def test_saves_as_draft_when_launch_false(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
            launch=False,
        )

        self.assertEqual(len(state["draft_clicks"]), 1)
        self.assertEqual(len(state["launch_clicks"]), 0)
        self.assertFalse(result["Launched"])

    def test_includes_weekly_budget_when_given(self):
        page, state = self._full_page()

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=50000,
        )

        self.assertEqual(state["budget"]["value"], "50000")
        self.assertEqual(result["WeeklyBudget"], 50000)

    def test_raises_value_error_when_no_weekly_budget(self):
        """Issue #796: the SAME silent-rejection shape as target_actions
        above (test_raises_value_error_when_no_target_actions) — Yandex's
        create form refuses to submit without a weekly budget, and refuses
        SILENTLY: no error appears in the DOM until AFTER a submit attempt
        (a `[data-testid="BudgetWithSuggest.ErrorMessage"]` element reading
        "Не задан недельный бюджет"), so a budget-less call must be refused
        outright rather than driven through the whole form and left to fail
        as an opaque redirect timeout."""
        page, state = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=None,  # type: ignore[arg-type]
            )

        # Fails fast: nothing was published, and no browser work was done.
        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])
        self.assertEqual(page.navigated_to, [])

    def test_raises_value_error_when_weekly_budget_is_not_positive(self):
        """A zero/negative weekly_budget passes both Click's `required=True`
        (it only checks presence, not value) and the `is None` check above —
        the DOM comparison in `_read_created_form_mismatches` reads the
        field back as the same 0, so it would NOT be caught as a mismatch
        even if Yandex's own form silently rejected it exactly like a
        missing budget. Refuse it outright, the same fail-fast shape as the
        None case."""
        page, state = self._full_page()

        for bad_value in (0, -1):
            with self.assertRaises(ValueError):
                browser_masters.create_master(
                    page,
                    "https://ksamata.ru/",
                    headlines=["Заголовок"],
                    texts=["Текст объявления"],
                    regions=["Москва"],
                    target_actions={self.GOAL_ID: self.GOAL_PRICE},
                    weekly_budget=bad_value,
                )

        # Fails fast: nothing was published, and no browser work was done.
        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])
        self.assertEqual(page.navigated_to, [])

    def test_raises_value_error_when_no_target_actions(self):
        """Issue #777: Yandex silently swallows the terminal click when the
        form has no conversion goal, so a goal-less call must be refused
        outright rather than driven through the whole form and left to fail
        as an opaque redirect timeout."""
        page, state = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={},
                weekly_budget=1000,
            )

        # Fails fast: nothing was published, and no browser work was done.
        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])
        self.assertEqual(page.navigated_to, [])

    def test_adds_the_requested_goal_with_its_price_before_clicking(self):
        """The goal must reach the page, and its price must be the one the
        caller asked for — not the value Yandex pre-fills (issue #777 live
        recon found the create page's new row arrives holding a suggested
        "160", unlike the edit page's empty input)."""
        page, state = self._full_page()

        browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: 250},
            weekly_budget=1000,
        )

        self.assertEqual(state["goal_prices"], {self.GOAL_ID: "250"})
        self.assertEqual(len(state["launch_clicks"]), 1)

    def test_adds_multiple_goals_in_one_create(self):
        second_goal = 236386932
        page, state = self._full_page(offer_goal_ids=[self.GOAL_ID, second_goal])

        browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: 250, second_goal: 75},
            weekly_budget=1000,
        )

        self.assertEqual(state["goal_prices"], {self.GOAL_ID: "250", second_goal: "75"})
        self.assertEqual(len(state["launch_clicks"]), 1)

    def test_uses_the_create_pages_empty_table_add_trigger(self):
        """The create page's empty "Целевые действия" table renders its
        "Добавить" button as ``TargetActions.OTHER.AddTargetButton``, NOT
        the edit page's ``MiniGrid.AddButton`` (issue #777 live recon) —
        the one testid that differs between the two pages. ``_full_page``
        already defaults to the create-page form, so this asserts the
        default is the one being exercised."""
        page, state = self._full_page()

        browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )

        self.assertEqual(len(state["launch_clicks"]), 1)

    def test_still_works_against_the_edit_pages_add_trigger(self):
        """The same code path must keep working when the page renders the
        OTHER trigger name — confirmed live that the create page itself
        switches to ``MiniGrid.AddButton`` once a first row exists, so
        neither testid may be assumed."""
        page, state = self._full_page(
            add_button_testid=(
                browser_masters._TARGET_ACTION_ADD_BUTTON_TESTID_TEMPLATE.format(
                    category=browser_masters._TARGET_ACTIONS_CATEGORY
                )
            )
        )

        browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )

        self.assertEqual(state["goal_prices"], {self.GOAL_ID: "150"})
        self.assertEqual(len(state["launch_clicks"]), 1)

    def test_raises_before_clicking_when_the_goal_is_not_offered(self):
        """A goal that isn't on the auto-discovered Metrika counter never
        appears as an option — that must abort BEFORE the terminal click,
        since a create without a valid goal is silently rejected."""
        page, state = self._full_page(offer_goal_ids=[])

        with self.assertRaises(browser_masters.BrowserSessionError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])

    def test_raises_before_clicking_when_the_goal_row_silently_vanished(self):
        """The pre-click gate, and the reason it exists (issue #777).

        ``_add_target_action`` succeeding is not proof the row survived —
        a React re-render can drop it, and Yandex punishes a goal-less form
        by SILENTLY swallowing the terminal click (no redirect, no error,
        both buttons still ``enabled``/``aria-disabled=None``). Without
        this gate the run would publish nothing and fail 48s later as an
        unexplained redirect timeout. Modelled by letting the add succeed
        and then clearing the table behind it.
        """
        page, state = self._full_page(drop_goal_rows_after_add=True)

        with self.assertRaises(browser_masters.BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

        self.assertIn("Целевые действия", str(ctx.exception))
        self.assertIn(str(self.GOAL_ID), str(ctx.exception))
        # Nothing was published — the whole point of gating BEFORE the click.
        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])

    def test_raises_before_clicking_when_the_goal_price_did_not_stick(self):
        """A row with the wrong/blank price is rejected by Yandex's own
        client-side validation exactly like a missing row — same silent
        swallow, so the gate must check the price too, not just presence."""
        # Yandex's suggested value creeping back after the fill.
        page, state = self._full_page(revert_goal_price_after_add="160")

        with self.assertRaises(browser_masters.BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

        self.assertIn(str(self.GOAL_ID), str(ctx.exception))
        self.assertEqual(state["launch_clicks"], [])
        self.assertEqual(state["draft_clicks"], [])

    def test_raises_value_error_when_no_headlines(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=[],
                texts=["t"],
                regions=["r"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

    def test_raises_value_error_when_no_texts(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["h"],
                texts=[],
                regions=["r"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

    def test_raises_value_error_when_no_regions(self):
        page, _ = self._full_page()

        with self.assertRaises(ValueError):
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["h"],
                texts=["t"],
                regions=[],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

    def test_invalid_url_stops_before_step2(self):
        page, _ = self._full_page()
        page._text_buttons[browser_masters._CREATE_INVALID_URL_TEXT] = (
            _FakeGetByTextLocator([_FakeTextLocatorHandle()])
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters.create_master(
                page,
                "not-a-valid-url",
                headlines=["h"],
                texts=["t"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )

    def test_step1_timeout_raises_when_url_field_never_renders(self):
        """issue #685: ``goto`` now uses ``wait_until="commit"``, which
        returns before the page has any real content — the create page's
        step 1 field must be waited on explicitly, and a page that never
        renders it must fail with a specific ``BrowserSessionError``, not an
        opaque markup-changed error from ``_fill_landing_url`` racing an
        unrendered field.
        """
        page, _ = self._full_page()
        del page._locators[browser_masters._CREATE_URL_INPUT_TESTID]

        with patch.object(browser_masters, "_CREATE_STEP1_TIMEOUT_MS", 10):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.create_master(
                    page,
                    "https://ksamata.ru/",
                    headlines=["h"],
                    texts=["t"],
                    regions=["Москва"],
                    target_actions={self.GOAL_ID: self.GOAL_PRICE},
                    weekly_budget=1000,
                )
        self.assertIn("step 1", str(ctx.exception))

    def test_raises_before_launch_when_a_headline_slot_did_not_actually_clear(
        self,
    ):
        """The terminal button must NOT be clicked if pre-click state is
        already wrong (issue #655 round-3 review, Codex).

        Every round of this issue's review (1, 2, 3) found a new way for a
        slot's true content to diverge from what ``_add_repeating_values``
        believes it wrote — a click failure, an unused slot, a no-op
        keypress that succeeds without exception. ``_verify_created``
        already re-reads and compares state correctly; the actual defect was
        never in the check, it was that ``create_master`` only ran that
        check AFTER ``_click_terminal_button`` already launched the
        campaign. This pins the fix at the level that closes ALL variants:
        the state check must gate the click, not just report on it
        afterwards.

        Sabotage: slot 0's ``press()`` succeeds without raising (models a
        prevented Backspace / lost selection / re-render race — issue #655
        round-3 finding) but never actually clears the field, so
        ``.type()`` appends onto the stale AI copy instead of replacing it.
        """
        page, state = self._full_page()
        stuck_handle = _FakeLocatorHandle(text="Старый заголовок")
        stuck_handle.press = lambda key: None  # succeeds, does nothing
        stuck_handle.type = lambda value, delay=None: None  # never reflects
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        page._locators[headline_selector] = _FakeLocator([stuck_handle])

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )
        # The whole point: caught BEFORE the irreversible click, not after.
        self.assertEqual(len(state["launch_clicks"]), 0)
        self.assertIn("before clicking", str(ctx.exception))

    def test_raises_when_terminal_click_does_not_actually_save_headline(self):
        # The headline field reflects correctly right up until the click,
        # but Yandex's OWN post-click processing (client-side validation on
        # submit, not on type) reverts it — the pre-click gate above cannot
        # catch this, since the field looked correct at check time and only
        # diverges as a side effect of the click itself. _verify_created
        # remains the backstop for this case.
        page, state = self._full_page()
        stuck_handle = _FakeLocatorHandle(text="Старый заголовок")

        def _type(value, delay=None):
            stuck_handle._text = value

        stuck_handle.type = _type
        headline_selector = (
            '[data-testid="'
            + browser_masters._HEADLINES_TESTID_TEMPLATE.format(index=0)
            + '"]'
        )
        page._locators[headline_selector] = _FakeLocator([stuck_handle])

        launch_handle = next(
            handle
            for role, name, handle in page._role_elements
            if role == "button" and name == browser_masters._LAUNCH_BUTTON_TEXT
        )
        real_on_click = launch_handle._on_click

        def _revert_then_click():
            stuck_handle._text = "Старый заголовок"
            if real_on_click is not None:
                real_on_click()

        launch_handle._on_click = _revert_then_click

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters.create_master(
                page,
                "https://ksamata.ru/",
                headlines=["Заголовок"],
                texts=["Текст объявления"],
                regions=["Москва"],
                target_actions={self.GOAL_ID: self.GOAL_PRICE},
                weekly_budget=1000,
            )
        self.assertEqual(len(state["launch_clicks"]), 1)  # the click DID happen
        self.assertIn("did not take effect as requested", str(ctx.exception))

    def test_returns_campaign_id_from_the_post_click_redirect(self):
        """Issue #744: the created campaign's ID comes from ``page.url``.

        Live-confirmed that clicking either terminal button redirects to
        WIZARD_OVERVIEW_URL carrying the new ID — the same redirect
        copy_master has used since #659. Before this, create_master returned
        only the caller's own inputs, leaving no way to find what it made.
        """
        page, _ = self._full_page(created_id=713299123)

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )

        self.assertEqual(result["CampaignId"], 713299123)

    def test_raises_when_yandex_never_redirects(self):
        """A click that never redirects must not be reported as success.

        The campaign may still have been created (the click is irreversible
        and not idempotent), so the error has to say so rather than let the
        caller assume nothing happened and retry into a duplicate.
        """
        page, state = self._full_page(redirect=False)

        with patch.object(browser_masters, "_CREATE_VERIFY_TIMEOUT_MS", 10):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.create_master(
                    page,
                    "https://ksamata.ru/",
                    headlines=["Заголовок"],
                    texts=["Текст объявления"],
                    regions=["Москва"],
                    target_actions={self.GOAL_ID: self.GOAL_PRICE},
                    weekly_budget=1000,
                )

        self.assertEqual(len(state["launch_clicks"]), 1)  # the click DID happen
        self.assertIn("did not redirect", str(ctx.exception))
        self.assertIn("not idempotent", str(ctx.exception))

    def test_raises_when_the_reloaded_page_lost_the_requested_region(self):
        """Issue #744: region is verified through a REAL reload.

        This is the check the pre-#744 code could not perform at all — it
        had no campaign ID, so no page to reload. A region silently dropped
        by Yandex would previously have been reported as a clean success.
        """
        page, state = self._full_page(reloaded_regions=["Санкт-Петербург"])

        # _read_until_matches busy-spins for the full production retry
        # budget on a genuine mismatch, and FakePage.wait_for_timeout is a
        # no-op, so this would cost exactly _VERIFY_FIELD_READ_TIMEOUT_MS of
        # wall clock (issue #767) if _verify_created had left that timeout
        # to the parameter default — patching the module constant only
        # reaches it because the call site passes it explicitly.
        with patch.object(browser_masters, "_VERIFY_FIELD_READ_TIMEOUT_MS", 10):
            with self.assertRaises(BrowserSessionError) as ctx:
                browser_masters.create_master(
                    page,
                    "https://ksamata.ru/",
                    headlines=["Заголовок"],
                    texts=["Текст объявления"],
                    regions=["Москва"],
                    target_actions={self.GOAL_ID: self.GOAL_PRICE},
                    weekly_budget=1000,
                )

        self.assertEqual(len(state["launch_clicks"]), 1)  # the click DID happen
        self.assertIn("regions", str(ctx.exception))
        self.assertIn("Москва", str(ctx.exception))
        # The error must name the campaign that DOES now exist, so the
        # caller can inspect it instead of retrying into a duplicate.
        self.assertIn(str(self.CREATED_ID), str(ctx.exception))

    def test_accepts_extra_region_tags_beyond_the_requested_ones(self):
        """Region tags are a SUBSET check, not equality.

        Selecting a region can bring implied parent/child nodes along with
        it, so an exact-set comparison would fail a correct save. Unlike a
        surplus ad-copy slot (which would publish unreviewed text), a
        surplus region tag is not a hazard worth failing on.
        """
        page, _ = self._full_page(
            reloaded_regions=["Москва", "Москва и область"],
        )

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )  # must not raise

        self.assertEqual(result["CampaignId"], self.CREATED_ID)

    def test_verifies_region_passed_as_a_name_id_pair(self):
        """``--region-id`` gives (name, RegionId) tuples, not plain strings.

        _verify_created compares against the NAME half — the reloaded tag
        group renders labels, not ids.
        """
        page, _ = self._full_page(
            reloaded_regions=["Москва"], node_id="region-node-213"
        )

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=[("Москва", 213)],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=1000,
        )  # must not raise

        self.assertEqual(result["Regions"], [("Москва", 213)])

    def test_verifies_ad_copy_before_the_redirect_swaps_the_page(self):
        """Issue #744 cycle-review: read the form's fields while it EXISTS.

        `_wait_for_created_campaign_id` blocks until Yandex has navigated
        away from the create form. A launched campaign lands on the stats
        dashboard, which renders no headline/text slots and no budget input
        at all (only a DRAFT overview re-renders the wizard form — issue
        #660). So a post-redirect read of those fields finds nothing, and
        `_read_repeating_values` maps every absent slot to "" rather than
        raising — turning a campaign that WAS created and launched into a
        hard BrowserSessionError telling the caller to check it by hand.

        The earlier fake could not express this: it kept serving the create
        form's locators after the redirect, so the wrong-page read passed.
        `locators_after_navigation` models the page actually landed on.
        """
        page, state = self._full_page(page_after_redirect_has_no_form=True)

        result = browser_masters.create_master(
            page,
            "https://ksamata.ru/",
            headlines=["Заголовок"],
            texts=["Текст объявления"],
            regions=["Москва"],
            target_actions={self.GOAL_ID: self.GOAL_PRICE},
            weekly_budget=50000,
        )  # must not raise: the campaign really was created

        self.assertEqual(len(state["launch_clicks"]), 1)
        self.assertEqual(result["CampaignId"], self.CREATED_ID)
        self.assertEqual(result["WeeklyBudget"], 50000)


class TestMastersAddCommand(unittest.TestCase):
    """CLI wiring for `masters add` (issue #632)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_registered(self):
        result = self.runner.invoke(cli, ["masters", "add", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_has_no_login_option(self):
        result = self.runner.invoke(cli, ["masters", "add", "--help"])
        self.assertNotIn("--login", result.output)

    def test_headline_text_region_are_required(self):
        result = self.runner.invoke(cli, ["masters", "add", "https://ksamata.ru/"])
        self.assertNotEqual(result.exit_code, 0)

    def test_calls_create_master_with_given_fields(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "Заголовок 1",
                    "--headline",
                    "Заголовок 2",
                    "--text",
                    "Текст",
                    "--add-target-action",
                    "236386933=150",
                    "--region",
                    "Москва",
                    "--weekly-budget",
                    "1000",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["headlines"], ["Заголовок 1", "Заголовок 2"])
        self.assertEqual(kwargs["texts"], ["Текст"])
        self.assertEqual(kwargs["regions"], [("Москва", None)])
        # Issue #777: parsed through the same "goal_id=price" helper
        # `masters update --add-target-action` uses, so both commands
        # accept exactly the same syntax for the same flag name.
        self.assertEqual(kwargs["target_actions"], {236386933: 150.0})
        self.assertTrue(kwargs["launch"])

    def test_draft_flag_disables_launch(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": False}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--add-target-action",
                    "236386933=150",
                    "--region",
                    "Москва",
                    "--weekly-budget",
                    "1000",
                    "--draft",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertFalse(kwargs["launch"])

    def test_passes_weekly_budget(self):
        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--add-target-action",
                    "236386933=150",
                    "--region",
                    "Москва",
                    "--weekly-budget",
                    "50000",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["weekly_budget"], 50000)

    def test_region_or_region_id_is_required(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "add",
                "https://ksamata.ru/",
                "--headline",
                "h",
                "--text",
                "t",
                "--add-target-action",
                "236386933=150",
                "--weekly-budget",
                "1000",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--region/--region-id", result.output)

    def test_weekly_budget_is_required(self):
        """Issue #796: the SAME silent-rejection shape as #777's
        --add-target-action requirement — Yandex's create form is silently
        rejected without a weekly budget, so a budget-less invocation must
        be refused at the CLI boundary (Click's required=True) rather than
        driven through a whole browser session that can only end in an
        unexplained redirect timeout."""
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "add",
                "https://ksamata.ru/",
                "--headline",
                "h",
                "--text",
                "t",
                "--region",
                "Москва",
                "--add-target-action",
                "236386933=150",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--weekly-budget", result.output)

    def test_add_target_action_is_required(self):
        """Issue #777: Yandex's create form is silently rejected without a
        conversion goal — both terminal buttons keep reporting
        visible/enabled/aria-disabled=None — so a goal-less invocation must
        be refused at the CLI boundary rather than driven through a whole
        browser session that can only end in an unexplained timeout."""
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "add",
                "https://ksamata.ru/",
                "--headline",
                "h",
                "--text",
                "t",
                "--region",
                "Москва",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--add-target-action", result.output)

    def test_add_target_action_rejects_a_bare_goal_id_with_no_price(self):
        """Same "goal_id=price" syntax as `masters update
        --add-target-action`, including its price requirement — a newly
        added row's price has no safe default (issue #717/#777)."""
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "add",
                "https://ksamata.ru/",
                "--headline",
                "h",
                "--text",
                "t",
                "--region",
                "Москва",
                "--add-target-action",
                "236386933",
                "--weekly-budget",
                "1000",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("goal_id=price", result.output)

    def test_region_id_resolves_via_geo_regions_dictionary(self):
        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--add-target-action",
                    "236386933=150",
                    "--region-id",
                    "213",
                    "--weekly-budget",
                    "1000",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        body = service.post.call_args_list[0].kwargs["data"]
        self.assertEqual(body["method"], "getGeoRegions")
        self.assertEqual(body["params"]["SelectionCriteria"]["RegionIds"], [213])
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["regions"], [("Москва", 213)])

    def test_region_and_region_id_combine(self):
        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [
                        {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"}
                    ]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_create.return_value = {"Launched": True}
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--add-target-action",
                    "236386933=150",
                    "--region",
                    "Москва",
                    "--region-id",
                    "2",
                    "--weekly-budget",
                    "1000",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _, kwargs = mock_create.call_args
        self.assertEqual(kwargs["regions"], [("Москва", None), ("Санкт-Петербург", 2)])

    def test_unknown_region_id_raises_usage_error(self):
        service = Mock()
        service.post.return_value = Mock(data={"result": {"GeoRegions": []}})
        client = Mock()
        client.dictionaries.return_value = service

        with (
            patch("direct_cli.browser.masters.create_master") as mock_create,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
            patch("direct_cli.commands.masters.create_client", return_value=client),
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "add",
                    "https://ksamata.ru/",
                    "--headline",
                    "h",
                    "--text",
                    "t",
                    "--add-target-action",
                    "236386933=150",
                    "--region-id",
                    "999999",
                    "--weekly-budget",
                    "1000",
                ],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Unknown --region-id value(s): 999999", result.output)
        mock_create.assert_not_called()


def _region_ctx(token="t", login="l", sandbox=False):
    """A minimal Click-context stand-in for `_resolve_region_ids`."""
    ctx = Mock()
    ctx.obj = {"token": token, "login": login, "sandbox": sandbox}
    return ctx


class TestResolveRegionIds(unittest.TestCase):
    """Unit tests for `_resolve_region_ids` (issue #652)."""

    def test_empty_region_ids_skips_api_call(self):
        from direct_cli.commands.masters import _resolve_region_ids

        with patch("direct_cli.commands.masters.create_client") as mock_create_client:
            result = _resolve_region_ids(Mock(), ())

        self.assertEqual(result, [])
        mock_create_client.assert_not_called()

    def test_resolves_multiple_ids_preserving_order(self):
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [
                        {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"},
                        {"GeoRegionId": 213, "GeoRegionName": "Москва"},
                    ]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            result = _resolve_region_ids(Mock(), (213, 2))

        self.assertEqual(result, [("Москва", 213), ("Санкт-Петербург", 2)])

    def test_ambiguous_region_name_raises_usage_error(self):
        """Two distinct RegionIds sharing one GeoRegionName must not resolve
        silently — `_set_region`'s browser-side exact-name match would click
        whichever same-named option appears first, risking a live launch
        against the wrong geography (issue #652 follow-up)."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 111, "GeoRegionName": "Сосновка"}
                        ]
                    }
                }
            ),
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 111, "GeoRegionName": "Сосновка"},
                            {"GeoRegionId": 222, "GeoRegionName": "Сосновка"},
                        ]
                    }
                }
            ),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            with self.assertRaises(click.UsageError) as cm:
                _resolve_region_ids(Mock(), (111,))

        self.assertIn("ambiguous", str(cm.exception).lower())
        self.assertIn("Сосновка", str(cm.exception))
        self.assertIn("--region", str(cm.exception))

        second_call_body = service.post.call_args_list[1].kwargs["data"]
        self.assertIn("SelectionCriteria", second_call_body["params"])
        # `Name`, not `ExactNames` — the latter returns no rows at all from
        # the live API, which made this whole pre-flight dead code (#775).
        self.assertEqual(
            second_call_body["params"]["SelectionCriteria"]["Name"],
            "Сосновка",
        )

    def test_unique_region_name_resolves_normally(self):
        """A RegionId whose name has no duplicates elsewhere in the full
        dictionary must still resolve without raising."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                    }
                }
            ),
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 213, "GeoRegionName": "Москва"},
                            {"GeoRegionId": 2, "GeoRegionName": "Санкт-Петербург"},
                        ]
                    }
                }
            ),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            with patch("direct_cli.commands.masters.print_warning") as mock_warning:
                result = _resolve_region_ids(Mock(), (213,))

        self.assertEqual(result, [("Москва", 213)])
        # The happy path must be silent — a warning on every ordinary run
        # would train the user to ignore it (review of PR #778).
        mock_warning.assert_not_called()

    def test_ambiguity_preflight_without_georegions_key_does_not_crash(self):
        """Issue #775: Yandex omits `GeoRegions` from `result` entirely when
        nothing matches — `result` is `{}`, not `{"GeoRegions": []}`. Indexing
        it unconditionally made every `--region-id` run die with a bare
        `KeyError: 'GeoRegions'` before a browser was opened. The empty
        pre-flight must resolve normally, and must NOT warn: `Name` returns no
        rows for top-level regions (confirmed live — `Name="Москва"` matches
        only "Новая Москва"/"Менеуз-Москва", never Москва itself), so warning
        here would fire on the most common `--region-id` values."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                    }
                }
            ),
            Mock(data={"result": {}}),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            with patch("direct_cli.commands.masters.print_warning") as mock_warning:
                result = _resolve_region_ids(_region_ctx(), (213,))

        self.assertEqual(result, [("Москва", 213)])
        mock_warning.assert_not_called()

    def test_substring_hits_do_not_count_as_ambiguity(self):
        """`Name` is a SUBSTRING search, so its rows include unrelated regions
        that merely contain the name (live: `Name="Москва"` returns "Новая
        Москва" and "Менеуз-Москва"). Only exact-name rows may count toward
        ambiguity — otherwise an ordinary region would look ambiguous and be
        refused."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                    }
                }
            ),
            Mock(
                data={
                    "result": {
                        "GeoRegions": [
                            {"GeoRegionId": 162734, "GeoRegionName": "Новая Москва"},
                            {"GeoRegionId": 176800, "GeoRegionName": "Менеуз-Москва"},
                        ]
                    }
                }
            ),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            result = _resolve_region_ids(_region_ctx(), (213,))

        self.assertEqual(result, [("Москва", 213)])

    def test_initial_lookup_without_georegions_key_reports_unknown_ids(self):
        """The same absent-key shape on the FIRST call must surface as the
        actionable "Unknown --region-id value(s)" UsageError, not a KeyError."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.return_value = Mock(data={"result": {}})
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            with self.assertRaises(click.UsageError) as cm:
                _resolve_region_ids(_region_ctx(), (999999,))

        self.assertIn("Unknown --region-id value(s): 999999", str(cm.exception))

    def test_null_result_does_not_crash(self):
        """A `result` of `None` is the same class of shape as a missing key."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.side_effect = [
            Mock(
                data={
                    "result": {
                        "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                    }
                }
            ),
            Mock(data={"result": None}),
        ]
        client = Mock()
        client.dictionaries.return_value = service

        with patch("direct_cli.commands.masters.create_client", return_value=client):
            result = _resolve_region_ids(_region_ctx(), (213,))

        self.assertEqual(result, [("Москва", 213)])

    def test_lookup_is_pinned_to_russian_locale(self):
        """Issue #775: unpinned, no `Accept-Language` header is sent at all
        and Yandex answered in English, resolving 213 to "Moscow" — a name
        the Russian-language Мастер кампаний region widget cannot match, and
        one Yandex's own `ExactNames` lookup does not round-trip."""
        from direct_cli.commands.masters import _resolve_region_ids

        service = Mock()
        service.post.return_value = Mock(
            data={
                "result": {
                    "GeoRegions": [{"GeoRegionId": 213, "GeoRegionName": "Москва"}]
                }
            }
        )
        client = Mock()
        client.dictionaries.return_value = service

        with patch(
            "direct_cli.commands.masters.create_client", return_value=client
        ) as mock_create:
            _resolve_region_ids(_region_ctx(), (213,))

        self.assertEqual(mock_create.call_args.kwargs["language"], "ru")


class _FakeAudienceTagsPage(FakePage):
    """A ``FakePage`` whose ``_read_audience_tags`` result can be scripted to
    change across successive calls — models the "Интересы и поисковые
    запросы" tag list hydrating over several reads, the exact race
    ``_wait_for_audience_section`` (issue #681, cycle-review PR #751) polls
    for.

    ``counts`` is a queue of tag-list sizes; each call to the tags-wrapper
    locator consumes the next value (the last value repeats once the queue
    is exhausted), and the fake's tag-slot locators are re-derived from
    that count on every read — mirrors how ``_read_audience_tags`` re-reads
    the live DOM on every call rather than caching.
    """

    def __init__(self, counts, **kwargs):
        super().__init__(locators={}, **kwargs)
        self._counts = list(counts)
        self._call_index = 0
        self._scan_started = False

    def locator(self, selector):
        if selector == browser_masters._AUDIENCE_TAG_WRAPPER_TESTID:
            return _FakeLocator([_FakeLocatorHandle()])
        if selector == browser_masters._AUDIENCE_TAG_COUNT_SELECTOR:
            # The count-only selector _wait_for_audience_section's streak
            # predicate uses (it needs a count, not the texts). Consumes one
            # queue entry per call, the same way a full _read_audience_tags
            # scan does, so a scripted `counts` queue drives both readers
            # identically.
            if self._scan_started:
                self._call_index += 1
            self._scan_started = True
            count = self._counts[min(self._call_index, len(self._counts) - 1)]
            return _FakeLocator([_FakeLocatorHandle() for _ in range(count)])
        prefix = "CustomAudienceAndSearchTermsEditor.TagGroup.tag."
        if selector.startswith(f'[data-testid="{prefix}') and not selector.endswith(
            '.close"]'
        ):
            index = int(selector[len(f'[data-testid="{prefix}') : -len('"]')])
            if index == 0:
                # Advance the queue once per full _read_audience_tags scan
                # (a scan always starts by reading index 0, whether count is
                # 0 or 112) -- except on the very first scan, which must see
                # counts[0], not counts[1].
                if self._scan_started:
                    self._call_index += 1
                self._scan_started = True
            count = self._counts[min(self._call_index, len(self._counts) - 1)]
            if index < count:
                return _FakeLocator([_FakeLocatorHandle(text=f"tag{index}")])
            return _FakeLocator([_FakeLocatorHandle(raises=True)])
        return super().locator(selector)


class TestWaitForAudienceSection(unittest.TestCase):
    """``_wait_for_audience_section`` (issue #681, cycle-review PR #751
    round 1): two equal consecutive tag-count reads 250ms apart is not
    enough to trust the count -- a premature value (e.g. 0) can itself read
    stable for two ticks before the real payload starts arriving. Requires
    ``_AUDIENCE_TAG_STABLE_STREAK`` consecutive equal reads, and raises
    (rather than silently proceeding) if the gender trigger or the tag
    count never settles within the timeout.
    """

    def test_does_not_settle_on_two_premature_equal_reads(self):
        # Tag count reads 0, 0, 0, 0, 112, 112, 112, 112, 112 -- the first
        # two (or three) reads are "stable" by a 2-sample test but wrong;
        # only the run of 112s should satisfy the (patched, shorter) streak.
        page = _FakeAudienceTagsPage(
            counts=[0, 0, 0, 0, 112, 112, 112, 112, 112],
            role_elements=[],
        )
        page._locators[browser_masters._GENDER_SELECT_TESTID] = _FakeLocator(
            [_FakeLocatorHandle(text="Любой пол")]
        )

        with (
            patch.object(browser_masters, "_AUDIENCE_TAG_STABLE_STREAK", 3),
            patch.object(browser_masters, "_AUDIENCE_TAG_STABLE_WINDOW_MS", 10_000),
        ):
            browser_masters._wait_for_audience_section(page)

        # Reaching here without raising means the loop kept polling past
        # the premature 0-streak and only settled once 112 repeated 3x.
        self.assertEqual(len(browser_masters._read_audience_tags(page)), 112)

    def test_streak_span_exceeds_the_observed_worst_case_settle_time(self):
        """Issue #752 (R2-1): the streak's own SPAN — not just the overall
        window — has to exceed the ~4s worst-case settle time this module's
        live recon documents. The round-1 values (5 reads x 500ms = 2.5s)
        did not: a count held at a stale 0 for 4s settled inside the window
        and ``update_master`` went straight on to save an empty audience-tag
        payload over a campaign that actually had tags. Guards the widened
        constants against being quietly tuned back under that bound."""
        observed_worst_case_settle_ms = 4_000
        streak_span_ms = (
            browser_masters._AUDIENCE_TAG_STABLE_STREAK
            * browser_masters._AUDIENCE_TAG_STABLE_TICK_MS
        )
        self.assertGreater(streak_span_ms, observed_worst_case_settle_ms)
        # The overall window must still fit at least one full streak, or
        # the poll times out before it can ever succeed.
        self.assertGreater(
            browser_masters._AUDIENCE_TAG_STABLE_WINDOW_MS, streak_span_ms
        )

    def test_does_not_settle_on_a_stale_count_held_past_the_old_window(self):
        """Issue #752 (R2-1) behaviourally: a stale 0 held for longer than
        the OLD 2.5s streak span (5 reads x 500ms) — but shorter than the
        widened one — must not be accepted as settled. Uses the real
        constants rather than patched-down ones, since the value of the
        constants is the whole point of this fix.

        Reads: 0 held for as many ticks as the OLD streak needed to settle
        (5 equal reads + the priming read), then the real 112. Under the
        old constants the poll settles while the count is still 0 — the
        exact silent-data-loss path R2-1 describes, since ``update_master``
        goes straight on to save from that state. The widened streak must
        instead keep polling until the 112s arrive.

        Asserts the count observed AT settle time, not after — a later
        read would show 112 either way and would not discriminate."""
        old_streak_reads = 5 + 1  # round-1 streak of 5, plus the priming read
        real_reads = browser_masters._AUDIENCE_TAG_STABLE_STREAK + 2
        page = _FakeAudienceTagsPage(
            counts=[0] * old_streak_reads + [112] * real_reads,
            role_elements=[],
        )
        page._locators[browser_masters._GENDER_SELECT_TESTID] = _FakeLocator(
            [_FakeLocatorHandle(text="Любой пол")]
        )

        browser_masters._wait_for_audience_section(page)

        # The queue advances once per full _read_audience_tags scan, so the
        # number of scans consumed before settling says which value the
        # poll settled ON: settling inside the stale run would consume at
        # most `old_streak_reads` scans; settling on the real payload has
        # to consume all of them plus a full streak of 112s.
        self.assertGreaterEqual(
            page._call_index,
            old_streak_reads + browser_masters._AUDIENCE_TAG_STABLE_STREAK,
        )

    def test_untouched_tag_list_is_verified_after_a_gender_only_save(self):
        """Issue #752 (R2-1), the second half: a --gender/--age/--device
        update mutates no tag, but still submits the WHOLE form. If the
        readiness poll settled on a stale/empty tag count, the save can
        persist that emptiness and silently drop every targeting tag the
        campaign had — and nothing used to notice, because verification
        only ran when a tag add/remove was requested.

        Models the loss by driving the REAL ``_verify_saved`` branch: 112
        tags went in, the page comes back showing 0, and no tag was
        mutated. It must report a mismatch (which ``update_master`` turns
        into a raised error) rather than silently accepting the loss."""
        tags_before = [f"тег{i}" for i in range(112)]
        # The page comes back EMPTY — the targeting was dropped.
        page = _FakeAudienceTagsPage(counts=[0], role_elements=[])

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_AUDIENCE_SECTION_READY_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                audience_tags_before=tags_before,
            )

        self.assertIn("audience_tags", str(ctx.exception))

    def test_untouched_tag_list_accepts_an_unchanged_list(self):
        """The mirror of the test above: when the untouched list comes back
        intact, the check must stay silent rather than failing every
        gender/age/device update. Compared as a MULTISET — the grid has no
        guaranteed tag ordering, so passing the SAME tags in a different
        order must still verify."""
        page = _FakeAudienceTagsPage(counts=[3], role_elements=[])
        # _FakeAudienceTagsPage names its tags by index; read what the page
        # actually shows, then hand it back reversed.
        actual = browser_masters._read_audience_tags(page)
        self.assertEqual(len(actual), 3)

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_AUDIENCE_SECTION_READY_TIMEOUT_MS", 10),
        ):
            # Must NOT raise: same multiset, different order.
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                audience_tags_before=list(reversed(actual)),
            )

    def test_removing_a_tag_verifies_by_identity_not_just_count(self):
        """Issue #752, the audience path's own version of the #756 fix: the
        old predicate checked the resulting COUNT plus "are the added tags
        present?". That cannot tell "removed the requested tag" from
        "removed a different one" — both leave the same count. Deriving the
        expected multiset from the pre-mutation baseline catches it.

        Baseline [a, b, c], remove position 0 (=a). The page comes back
        with the RIGHT COUNT (2) but the WRONG tags — 'a' survived and 'b'
        went instead. A count check passes; the multiset check must not."""
        page = _FakeAudienceTagsPage(counts=[2], role_elements=[])
        # A removal makes _verify_saved re-settle the section first, which
        # polls the gender trigger — give the fake one.
        page._locators[browser_masters._GENDER_SELECT_TESTID] = _FakeLocator(
            [_FakeLocatorHandle(text="Любой пол")]
        )
        page_tags = browser_masters._read_audience_tags(page)
        # The fake names tags by index, so the page shows [tag0, tag1].
        # Claim a baseline whose position 0 is a tag that is STILL there.
        baseline = [page_tags[0], "удалённый", page_tags[1]]

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_AUDIENCE_SECTION_READY_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                audience_tags_before=baseline,
                remove_audience_tag_indices=[0],
            )

        # Count matches (3 - 1 == 2) — only identity comparison catches it.
        self.assertEqual(len(page_tags), len(baseline) - 1)
        self.assertIn("audience_tags", str(ctx.exception))

    def test_add_metrika_counter_does_not_false_positive_on_format_mismatch(self):
        """Cycle-review finding, issue #648: the pre-fix code compared
        add_metrika_counters' raw suggestion text ("{label} • {domain/path}
        • {id}", one line) directly against _read_metrika_counters' raw
        tag-display text ("{domain} • {id}\\n{N} целей", two lines) — two
        different string formats for the SAME counter, which can never be
        multiset-equal. Every successful add used to raise a false
        BrowserSessionError here. The page shows the counter linked, in its
        own two-line display format that differs from the one-line
        suggestion text used to add it — this must NOT raise."""
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                '[data-testid="MetrikaCountersTagGroup.tag.0"]': _FakeLocator(
                    [_FakeLocatorHandle(text="gc.ksamata.ru • 72112213\n30 целей")]
                ),
            }
        )

        with patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None):
            # Must NOT raise despite the format mismatch between the add
            # text and the read-back tag text -- both share id "72112213".
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                metrika_counters_before=[],
                add_metrika_counters=["Ксамата • yandex.ru/maps • 72112213"],
            )

    def test_add_metrika_counter_still_catches_a_genuinely_missing_counter(self):
        """The mirror of the test above: if the added counter's id truly
        never shows up on the page (e.g. the add silently failed), the
        mismatch must still be reported -- the identity-based comparison
        must not become a tautology that never fails."""
        page = FakePage(locators={})  # no wrapper -> _read_metrika_counters returns []

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_METRIKA_COUNTER_SUGGEST_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                metrika_counters_before=[],
                add_metrika_counters=["Ксамата • yandex.ru/maps • 72112213"],
            )

        self.assertIn("metrika_counters", str(ctx.exception))

    def test_metrika_only_save_gets_the_same_pre_reload_settle_wait_as_audience(self):
        """cycle-review finding, issue #648: the pre-reload settle wait
        (issue #681's confirmed-live save-commit race) was scoped to
        `_audience_touched` only, so a metrika-counters-only save skipped
        it entirely -- even though the Metrika counters widget shares the
        exact same tag-group DOM pattern that race was found on. A
        metrika-only call (no audience fields touched) must still trigger
        the 5s wait."""
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                '[data-testid="MetrikaCountersTagGroup.tag.0"]': _FakeLocator(
                    [_FakeLocatorHandle(text="gc.ksamata.ru • 72112213\n30 целей")]
                ),
            }
        )
        wait_calls = []
        page.wait_for_timeout = lambda timeout: wait_calls.append(timeout)

        with patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                metrika_counters_before=[],
                add_metrika_counters=["Ксамата • yandex.ru/maps • 72112213"],
            )

        self.assertIn(5_000, wait_calls)

    def test_sitelinks_only_save_gets_the_same_pre_reload_settle_wait(self):
        """cycle-review finding (this PR): the pre-reload settle wait
        (issue #681's confirmed-live save-commit race) was extended to
        `_metrika_touched` above but `_sitelinks_touched` was left out of
        the same guard, even though this same PR wires up sitelinks_before/
        add_sitelinks/remove_sitelink_indices as _verify_saved params right
        next to it. A sitelinks-only call (no audience/metrika fields
        touched) must still trigger the 5s wait."""
        page = FakePage(
            locators={
                browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._SITELINK_CARD_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="Title\nhttps://example.com")]
                ),
            }
        )
        wait_calls = []
        page.wait_for_timeout = lambda timeout: wait_calls.append(timeout)

        with patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                sitelinks_before=[],
                add_sitelinks=[
                    {
                        "Title": "Title",
                        "Href": "https://example.com",
                        "Description": "Desc",
                    }
                ],
            )

        self.assertIn(5_000, wait_calls)

    def test_raises_if_gender_trigger_never_shows_a_label(self):
        page = FakePage(locators={})  # no _GENDER_SELECT_TESTID handle at all

        with patch.object(browser_masters, "_AUDIENCE_SECTION_READY_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError):
                browser_masters._wait_for_audience_section(page)

    def test_raises_if_tag_count_never_settles(self):
        # Every read returns a different count -- never two-in-a-row equal,
        # so the stability streak can never be reached.
        page = _FakeAudienceTagsPage(counts=list(range(50)))
        page._locators[browser_masters._GENDER_SELECT_TESTID] = _FakeLocator(
            [_FakeLocatorHandle(text="Любой пол")]
        )

        with (
            patch.object(browser_masters, "_AUDIENCE_TAG_STABLE_STREAK", 3),
            patch.object(browser_masters, "_AUDIENCE_TAG_STABLE_WINDOW_MS", 1),
        ):
            with self.assertRaises(BrowserSessionError):
                browser_masters._wait_for_audience_section(page)


class TestSetGender(unittest.TestCase):
    """``_set_gender``/``_read_gender_label`` (issue #681)."""

    def test_selects_and_verifies_gender(self):
        page = FakePage(
            locators={
                browser_masters._GENDER_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="Женщины")]
                ),
                browser_masters._GENDER_OPTION_TESTID_TEMPLATE.format(
                    value="Female"
                ): _FakeLocator([_FakeLocatorHandle()]),
            }
        )

        browser_masters._set_gender(page, "female")  # no raise == verified

    def test_mismatch_after_click_raises(self):
        page = FakePage(
            locators={
                browser_masters._GENDER_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="Мужчины")]
                ),
                browser_masters._GENDER_OPTION_TESTID_TEMPLATE.format(
                    value="Female"
                ): _FakeLocator([_FakeLocatorHandle()]),
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._set_gender(page, "female")

    def test_rejects_unknown_gender(self):
        with self.assertRaises(ValueError):
            browser_masters._set_gender(FakePage(locators={}), "nonbinary")


class TestFormatAgeBoundLabel(unittest.TestCase):
    """``_format_age_bound_label`` (issue #681) -- the "до" side's unlimited
    option renders as "до 55+", not a literal echo of "Без ограничений"."""

    def test_from_bound(self):
        self.assertEqual(
            browser_masters._format_age_bound_label(is_from=True, age=25), "от 25"
        )

    def test_to_bound_finite(self):
        self.assertEqual(
            browser_masters._format_age_bound_label(is_from=False, age=45), "до 45"
        )

    def test_to_bound_unlimited(self):
        self.assertEqual(
            browser_masters._format_age_bound_label(is_from=False, age=None),
            "до 55+",
        )


class TestSetAgeBound(unittest.TestCase):
    """``_set_age_bound`` (issue #681)."""

    def test_from_has_no_unlimited_option(self):
        with self.assertRaises(ValueError):
            browser_masters._set_age_bound(
                FakePage(locators={}), is_from=True, age=None
            )

    def test_selects_unlimited_to_bound(self):
        page = FakePage(
            locators={
                browser_masters._AGE_TO_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="до\xa055+")]
                ),
                browser_masters._AGE_TO_OPTION_TESTID_TEMPLATE.format(
                    value="Unlimited"
                ): _FakeLocator([_FakeLocatorHandle()]),
            }
        )

        browser_masters._set_age_bound(page, is_from=False, age=None)


class TestReadSetDevices(unittest.TestCase):
    """``_read_devices``/``_set_devices`` (issue #681)."""

    def test_read_devices_returns_checked_subset(self):
        page = FakePage(
            locators={
                browser_masters._DEVICE_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="mobile"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "true"})]),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="desktop"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "false"})]),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="tablet"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "false"})]),
            }
        )

        self.assertEqual(browser_masters._read_devices(page), {"mobile"})

    def test_set_devices_rejects_empty_set(self):
        with self.assertRaises(BrowserSessionError):
            browser_masters._set_devices(FakePage(locators={}), set())

    def test_set_devices_rejects_unknown_device(self):
        with self.assertRaises(ValueError):
            browser_masters._set_devices(FakePage(locators={}), {"smartwatch"})


class TestRemoveAudienceTagPositions(unittest.TestCase):
    """``_parse_remove_audience_tag_options`` (cycle-review PR #751 round 1
    fix): a duplicate position must be rejected up front, mirroring
    ``_parse_remove_target_action_options``'s existing duplicate-goal
    guard -- positions are resolved against a single pre-mutation snapshot,
    so a repeated position would otherwise remove two DIFFERENT tags (the
    one originally at that position, then whatever shifted into it)."""

    def test_rejects_duplicate_position(self):
        from direct_cli.commands.masters import _parse_remove_audience_tag_options

        with self.assertRaises(click.UsageError):
            _parse_remove_audience_tag_options((1, 1))

    def test_accepts_distinct_positions_in_order(self):
        from direct_cli.commands.masters import _parse_remove_audience_tag_options

        self.assertEqual(_parse_remove_audience_tag_options((3, 1, 2)), [3, 1, 2])


class TestMastersUpdateAudienceFlags(unittest.TestCase):
    """CLI wiring for `masters update`'s "Аудитория" flags (issue #681)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_documents_audience_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--gender", result.output)
        self.assertIn("--age-from", result.output)
        self.assertIn("--age-to", result.output)
        self.assertIn("--device", result.output)
        self.assertIn("--add-audience-tag", result.output)
        self.assertIn("--remove-audience-tag", result.output)

    def test_rejects_duplicate_remove_audience_tag_position(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--remove-audience-tag",
                "1",
                "--remove-audience-tag",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output.lower())

    def test_rejects_unknown_gender(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--gender", "nonbinary"]
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_rejects_unknown_device(self):
        result = self.runner.invoke(
            cli, ["masters", "update", "42", "--device", "smartwatch"]
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_passes_gender_age_devices_and_tags(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--gender",
                    "female",
                    "--age-from",
                    "25",
                    "--age-to",
                    "unlimited",
                    "--device",
                    "mobile",
                    "--device",
                    "desktop",
                    "--add-audience-tag",
                    "йога",
                    "--remove-audience-tag",
                    "2",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_update.assert_called_once()
        _args, kwargs = mock_update.call_args
        self.assertEqual(kwargs["gender"], "female")
        self.assertEqual(kwargs["age_from"], 25)
        self.assertTrue(kwargs["age_from_requested"])
        self.assertIsNone(kwargs["age_to"])
        self.assertTrue(kwargs["age_to_requested"])
        self.assertEqual(kwargs["devices"], {"mobile", "desktop"})
        self.assertEqual(kwargs["add_audience_tags"], ["йога"])
        self.assertEqual(kwargs["remove_audience_tags"], [2])

    def test_bare_age_to_without_unlimited_parses_as_int(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli, ["masters", "update", "42", "--age-to", "45"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        _args, kwargs = mock_update.call_args
        self.assertEqual(kwargs["age_to"], 45)
        self.assertTrue(kwargs["age_to_requested"])

    def test_no_fields_still_rejected_with_audience_flags_absent(self):
        result = self.runner.invoke(cli, ["masters", "update", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--gender", result.output)


class TestFetchMasterAudience(unittest.TestCase):
    """``fetch_master_audience`` (issue #681) -- `masters audience get`'s
    browser layer, read-only, mirrors ``fetch_master_target_actions``."""

    def test_returns_gender_age_tags_and_devices(self):
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={
                edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()]),
                browser_masters._GENDER_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="Женщины")]
                ),
                browser_masters._AGE_FROM_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="от\xa025")]
                ),
                browser_masters._AGE_TO_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="до\xa055+")]
                ),
                browser_masters._AUDIENCE_TAG_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DEVICE_SELECT_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="mobile"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "true"})]),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="desktop"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "true"})]),
                browser_masters._DEVICE_OPTION_TESTID_TEMPLATE.format(
                    value="tablet"
                ): _FakeLocator([_FakeLocatorHandle(attrs={"aria-selected": "true"})]),
            }
        )

        with patch.object(browser_masters, "_AUDIENCE_TAG_STABLE_STREAK", 1):
            result = browser_masters.fetch_master_audience(page, 713277109)

        self.assertEqual(result["CampaignId"], 713277109)
        self.assertEqual(result["Gender"], "Женщины")
        self.assertEqual(result["AgeFromLabel"], "от 25")
        self.assertEqual(result["AgeToLabel"], "до 55+")
        self.assertEqual(result["AudienceTags"], [])
        self.assertEqual(result["AudienceTagCount"], 0)
        self.assertEqual(result["Devices"], ["desktop", "mobile", "tablet"])


class TestMastersAudienceGetCommand(unittest.TestCase):
    """CLI wiring for `masters audience get` (issue #681)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_registered(self):
        result = self.runner.invoke(cli, ["masters", "audience", "get", "--help"])
        self.assertEqual(result.exit_code, 0)

    def test_calls_fetch_master_audience(self):
        with (
            patch("direct_cli.browser.masters.fetch_master_audience") as mock_fetch,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_fetch.return_value = {"CampaignId": 42, "Gender": "Любой пол"}
            result = self.runner.invoke(cli, ["masters", "audience", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_fetch.assert_called_once()
        args, _kwargs = mock_fetch.call_args
        self.assertEqual(args[1], 42)


class TestReadSitelinks(unittest.TestCase):
    """``_read_sitelinks`` (issue #648, Этап C) — reads "Быстрые ссылки"
    cards by DOM position, since the card testids are not parameterized by
    index (see the module comment above ``_SITELINKS_EDITOR_TESTID``)."""

    def test_reads_title_and_href_from_each_card(self):
        page = FakePage(
            locators={
                browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._SITELINK_CARD_TESTID: _FakeLocator(
                    [
                        _FakeLocatorHandle(text="Об Авторе\nhttps://example.com/about"),
                        _FakeLocatorHandle(text="Бесплатно\nhttps://example.com/free"),
                    ]
                ),
            }
        )

        result = browser_masters._read_sitelinks(page)

        self.assertEqual(
            result,
            [
                {"Title": "Об Авторе", "Href": "https://example.com/about"},
                {"Title": "Бесплатно", "Href": "https://example.com/free"},
            ],
        )

    def test_returns_empty_list_when_section_never_renders(self):
        page = FakePage(locators={})

        with patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 1):
            result = browser_masters._read_sitelinks(page)

        self.assertEqual(result, [])

    def test_returns_empty_list_for_zero_sitelinks(self):
        page = FakePage(
            locators={
                browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._SITELINK_CARD_TESTID: _FakeLocator([]),
            }
        )

        self.assertEqual(browser_masters._read_sitelinks(page), [])

    def test_card_with_no_newline_reports_empty_href(self):
        """A card whose text has no newline (title only) reports the whole
        text as Title and an empty Href, rather than raising — mirrors
        ``_read_repeating_values``'s "unreadable slot -> empty value"
        convention for a bulk read."""
        page = FakePage(
            locators={
                browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._SITELINK_CARD_TESTID: _FakeLocator(
                    [_FakeLocatorHandle(text="Только заголовок")]
                ),
            }
        )

        result = browser_masters._read_sitelinks(page)

        self.assertEqual(result, [{"Title": "Только заголовок", "Href": ""}])


class TestAddSitelink(unittest.TestCase):
    """``_add_sitelink`` (issue #648, Этап C)."""

    def _page_with_new_card_form(self, existing_count=0):
        row_handles = {
            browser_masters._SITELINK_ROW_NAME_TESTID: _FakeContentEditableHandle(),
            browser_masters._SITELINK_ROW_HREF_TESTID: _FakeContentEditableHandle(),
            browser_masters._SITELINK_ROW_DESCRIPTION_TESTID: (
                _FakeContentEditableHandle()
            ),
        }
        locators = {
            browser_masters._SITELINKS_ADD_BUTTON_TESTID: _FakeLocator(
                [_FakeLocatorHandle()]
            ),
            browser_masters._SITELINK_CARD_TESTID: _FakeLocator(
                [_FakeLocatorHandle() for _ in range(existing_count)]
            ),
            browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                [_FakeLocatorHandle()]
            ),
        }
        for testid, handle in row_handles.items():
            locators[testid] = _FakeLocator([handle])
        return FakePage(locators=locators), row_handles

    def test_fills_all_three_fields(self):
        page, row_handles = self._page_with_new_card_form()

        browser_masters._add_sitelink(
            page, "Об авторе", "https://example.com/about", "Узнайте больше"
        )

        self.assertEqual(
            row_handles[browser_masters._SITELINK_ROW_NAME_TESTID]._text,
            "Об авторе",
        )
        self.assertEqual(
            row_handles[browser_masters._SITELINK_ROW_HREF_TESTID]._text,
            "https://example.com/about",
        )
        self.assertEqual(
            row_handles[browser_masters._SITELINK_ROW_DESCRIPTION_TESTID]._text,
            "Узнайте больше",
        )

    def test_empty_description_still_clears_but_does_not_type(self):
        page, row_handles = self._page_with_new_card_form()
        # Pre-fill the description field the way a "Добавить" click might
        # (NOT LIVE-VERIFIED whether it does) — an empty description
        # request must still clear it.
        row_handles[browser_masters._SITELINK_ROW_DESCRIPTION_TESTID]._text = "leftover"

        browser_masters._add_sitelink(page, "Title", "https://example.com", "")

        self.assertEqual(
            row_handles[browser_masters._SITELINK_ROW_DESCRIPTION_TESTID]._text, ""
        )

    def test_refuses_when_slot_count_already_at_limit(self):
        page, _ = self._page_with_new_card_form(
            existing_count=browser_masters._SITELINKS_SLOT_COUNT
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_sitelink(
                page, "Title", "https://example.com", "Description"
            )

        self.assertIn("already has", str(ctx.exception))

    def test_raises_when_add_button_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_sitelink(
                page, "Title", "https://example.com", "Description"
            )

    def test_raises_when_row_field_never_mounts(self):
        page, _ = self._page_with_new_card_form()
        page._locators[browser_masters._SITELINK_ROW_NAME_TESTID] = _FakeLocator(
            [_FakeLocatorHandle(raises=True)]
        )

        with self.assertRaises(BrowserSessionError) as ctx:
            browser_masters._add_sitelink(
                page, "Title", "https://example.com", "Description"
            )

        self.assertIn("title", str(ctx.exception))


class TestUpdateMasterSitelinkCommitConfirmation(unittest.TestCase):
    """``update_master``'s sitelink add/remove loop (cycle-review finding,
    Codex, this PR) — mirrors the audience-tag/Metrika-counter loops in the
    same function: after each click, poll ``_read_sitelinks`` until the
    on-page count reflects the change, raising BEFORE the save click if it
    never does (issue #681: a save immediately after a non-committed click
    reloaded with the change missing). Unlike ``TestRemoveSitelink``/
    ``TestAddSitelink`` (which test ``_remove_sitelink``/``_add_sitelink``
    in isolation), this exercises the polling loop that wraps them inside
    ``update_master`` itself."""

    def setUp(self):
        self._patches = [
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(
                browser_masters, "_wait_for_draft_status", lambda *a, **k: False
            ),
            patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 1),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def test_raises_before_save_when_removal_click_never_commits(self):
        # _read_sitelinks always reports the ORIGINAL 2 cards -- models a
        # remove-button click that fires with no error but never actually
        # shrinks the on-page list (the exact issue #681 failure mode).
        baseline = [
            {"Title": "a", "Href": "https://example.com/a"},
            {"Title": "b", "Href": "https://example.com/b"},
        ]
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = FakePage(
            locators={},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with (
            patch.object(browser_masters, "_read_sitelinks", lambda p: list(baseline)),
            patch.object(browser_masters, "_remove_sitelink", lambda p, i: None),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters.update_master(page, 42, remove_sitelinks=[0])

        self.assertIn("may not have committed", str(ctx.exception).lower())
        # The save click must NOT have fired -- the whole point of this
        # guard is to catch the problem BEFORE the irreversible save.
        self.assertEqual(save_clicks, [])

    def test_raises_before_save_when_add_click_never_commits(self):
        # _read_sitelinks always reports the ORIGINAL empty list -- models
        # an add that fires with no error but never actually grows the
        # on-page list.
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = FakePage(
            locators={},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with (
            patch.object(browser_masters, "_read_sitelinks", lambda p: []),
            patch.object(
                browser_masters, "_add_sitelink", lambda p, title, href, desc: None
            ),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters.update_master(
                page,
                42,
                add_sitelinks=[
                    {
                        "Title": "New",
                        "Href": "https://example.com/new",
                        "Description": "Desc",
                    }
                ],
            )

        self.assertIn("may not have committed", str(ctx.exception).lower())
        self.assertEqual(save_clicks, [])

    def test_does_not_raise_when_removal_commits_after_a_few_ticks(self):
        # The commit check must tolerate a DOM update landing a beat after
        # the click resolves (the normal case), not just an instantaneous
        # change -- mirrors _clear_repeating_value's own equivalent test.
        # The reader keeps returning the post-removal state once the
        # scripted reads are exhausted (mirrors _read_until_matches'
        # callers elsewhere in this file) since _verify_saved re-reads
        # again after this loop's own commit-confirmation succeeds.
        baseline = [
            {"Title": "a", "Href": "https://example.com/a"},
            {"Title": "b", "Href": "https://example.com/b"},
        ]
        reads = iter([list(baseline), list(baseline)])
        after_removal = [baseline[0]]

        def _next_read(_page):
            try:
                return next(reads)
            except StopIteration:
                return list(after_removal)

        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        page = FakePage(
            locators={edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()])},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )

        with (
            patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 5_000),
            patch.object(browser_masters, "_read_sitelinks", _next_read),
            patch.object(browser_masters, "_remove_sitelink", lambda p, i: None),
        ):
            # Does not raise -- the second read shows the removal committed.
            browser_masters.update_master(page, 42, remove_sitelinks=[1])

        self.assertEqual(save_clicks, [True])

    def test_verifies_against_the_displayed_card_not_the_raw_cli_input(self):
        # cycle-review finding (Codex, cycle 2): Yandex's displayed Href is
        # NOT LIVE-VERIFIED to equal the raw CLI input byte-for-byte (e.g.
        # a trailing slash could be added/stripped on display). Comparing
        # _verify_saved's expected multiset against the raw input would
        # make this successful add report a false "did not save as
        # requested" -- add_sitelinks_observed must carry the DISPLAYED
        # Href ("https://example.com/new/", with a trailing slash) forward
        # to _verify_saved, not the raw CLI Href ("https://example.com/new",
        # without one).
        raw_href = "https://example.com/new"
        displayed_href = "https://example.com/new/"  # Yandex added a slash
        edit_form_ready_selector = (
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]'
        )
        save_clicks = []
        save_handle = _FakeTextLocatorHandle(
            visible=True, on_click=lambda: save_clicks.append(True)
        )
        page = FakePage(
            locators={edit_form_ready_selector: _FakeLocator([_FakeLocatorHandle()])},
            role_elements=[("button", browser_masters._SAVE_BUTTON_TEXT, save_handle)],
        )
        # Empty BEFORE the add, one card (with the DISPLAYED href) after --
        # models the real "add committed" state transition, since
        # sitelinks_before is also read via this same mocked function.
        cards = {"count": 0}

        def _read_sitelinks_stub(_page):
            if cards["count"] == 0:
                return []
            return [{"Title": "New", "Href": displayed_href}]

        def _add_sitelink_stub(_page, _title, _href, _desc):
            cards["count"] = 1

        with (
            patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 5_000),
            patch.object(browser_masters, "_read_sitelinks", _read_sitelinks_stub),
            patch.object(browser_masters, "_add_sitelink", _add_sitelink_stub),
        ):
            # Must NOT raise: the multiset is built from the DISPLAYED
            # value (with the slash), which is exactly what the final
            # _verify_saved re-read also reports -- so it matches.
            browser_masters.update_master(
                page,
                42,
                add_sitelinks=[
                    {"Title": "New", "Href": raw_href, "Description": "Desc"}
                ],
            )

        self.assertEqual(save_clicks, [True])


class TestRemoveSitelink(unittest.TestCase):
    """``_remove_sitelink`` (issue #648, Этап C) — unlike
    ``_remove_audience_tag``, the remove-button testid is NOT
    parameterized by index, so this resolves the button via ``.nth(index)``
    on the shared selector."""

    def test_clicks_the_nth_remove_button(self):
        handles = [_FakeLocatorHandle() for _ in range(3)]
        page = FakePage(
            locators={
                browser_masters._SITELINK_REMOVE_TESTID: _FakeLocator(handles),
            }
        )

        browser_masters._remove_sitelink(page, 1)

        self.assertEqual(handles[1].click_timeouts, [None])
        self.assertEqual(handles[0].click_timeouts, [])
        self.assertEqual(handles[2].click_timeouts, [])

    def test_raises_when_position_out_of_range(self):
        page = FakePage(
            locators={
                browser_masters._SITELINK_REMOVE_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._remove_sitelink(page, 5)


class TestVerifySavedSitelinks(unittest.TestCase):
    """``_verify_saved``'s sitelinks check (issue #648, Этап C) — mirrors
    the audience-tags multiset-derived-from-baseline verification
    (``TestWaitForAudienceSection``'s removal/untouched tests)."""

    def _page_with_sitelinks(self, sitelinks):
        cards = [
            _FakeLocatorHandle(text=f"{s['Title']}\n{s['Href']}") for s in sitelinks
        ]
        return FakePage(
            locators={
                browser_masters._SITELINKS_EDITOR_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                browser_masters._SITELINK_CARD_TESTID: _FakeLocator(cards),
            }
        )

    def test_untouched_list_verifies_when_unchanged(self):
        sitelinks = [
            {"Title": "Об Авторе", "Href": "https://example.com/about"},
            {"Title": "Бесплатно", "Href": "https://example.com/free"},
        ]
        page = self._page_with_sitelinks(sitelinks)

        with patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None):
            # Must not raise: the page still shows exactly the baseline.
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                sitelinks_before=sitelinks,
            )

    def test_removal_verified_by_identity_not_just_count(self):
        """Baseline [a, b, c], remove position 0 (=a). The page comes back
        with the right COUNT (2) but the WRONG sitelinks — 'a' survived and
        'b' is gone instead. A count-only check would pass; the multiset
        check derived from the baseline must not."""
        baseline = [
            {"Title": "a", "Href": "https://example.com/a"},
            {"Title": "b", "Href": "https://example.com/b"},
            {"Title": "c", "Href": "https://example.com/c"},
        ]
        # Page after "save": a survived, b vanished instead of a.
        page = self._page_with_sitelinks([baseline[0], baseline[2]])

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 1),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                sitelinks_before=baseline,
                remove_sitelink_indices=[0],
            )

        self.assertIn("sitelinks", str(ctx.exception))

    def test_add_is_verified_present(self):
        baseline = [{"Title": "a", "Href": "https://example.com/a"}]
        added = [{"Title": "new", "Href": "https://example.com/new"}]
        page = self._page_with_sitelinks(baseline + added)

        with patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                sitelinks_before=baseline,
                add_sitelinks=[{**added[0], "Description": "desc"}],
            )

    def test_add_not_actually_saved_raises(self):
        baseline = [{"Title": "a", "Href": "https://example.com/a"}]
        page = self._page_with_sitelinks(baseline)  # add never took effect

        with (
            patch.object(browser_masters, "_wait_for_edit_form", lambda *a, **k: None),
            patch.object(browser_masters, "_SITELINK_ROW_TIMEOUT_MS", 1),
            self.assertRaises(BrowserSessionError) as ctx,
        ):
            browser_masters._verify_saved(
                page,
                42,
                weekly_budget=None,
                promotion_goal=None,
                directs_helps=None,
                sitelinks_before=baseline,
                add_sitelinks=[
                    {
                        "Title": "new",
                        "Href": "https://example.com/new",
                        "Description": "desc",
                    }
                ],
            )

        self.assertIn("sitelinks", str(ctx.exception))


class TestParseAddSitelinkOptions(unittest.TestCase):
    """``_parse_add_sitelink_options`` (issue #648, Этап C CLI layer)."""

    def test_parses_title_href_description(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        result = _parse_add_sitelink_options(
            ("Об авторе|https://example.com/about|Узнайте больше",)
        )

        self.assertEqual(
            result,
            [
                {
                    "Title": "Об авторе",
                    "Href": "https://example.com/about",
                    "Description": "Узнайте больше",
                }
            ],
        )

    def test_strips_whitespace_around_parts(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        result = _parse_add_sitelink_options(
            (" Title | https://example.com | Description ",)
        )

        self.assertEqual(
            result[0],
            {
                "Title": "Title",
                "Href": "https://example.com",
                "Description": "Description",
            },
        )

    def test_rejects_wrong_number_of_parts(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        with self.assertRaises(click.UsageError):
            _parse_add_sitelink_options(("Title|https://example.com",))

        with self.assertRaises(click.UsageError):
            _parse_add_sitelink_options(
                ("Title|https://example.com|Description|Extra",)
            )

    def test_rejects_empty_title(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        with self.assertRaises(click.UsageError):
            _parse_add_sitelink_options(("|https://example.com|Description",))

    def test_rejects_empty_href(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        with self.assertRaises(click.UsageError):
            _parse_add_sitelink_options(("Title||Description",))

    def test_rejects_empty_description(self):
        from direct_cli.commands.masters import _parse_add_sitelink_options

        with self.assertRaises(click.UsageError):
            _parse_add_sitelink_options(("Title|https://example.com|",))


class TestParseRemoveSitelinkOptions(unittest.TestCase):
    """``_parse_remove_sitelink_options`` (issue #648, Этап C CLI layer) —
    mirrors ``_parse_remove_audience_tag_options``."""

    def test_rejects_duplicate_position(self):
        from direct_cli.commands.masters import _parse_remove_sitelink_options

        with self.assertRaises(click.UsageError):
            _parse_remove_sitelink_options((1, 1))

    def test_accepts_distinct_positions_in_order(self):
        from direct_cli.commands.masters import _parse_remove_sitelink_options

        self.assertEqual(_parse_remove_sitelink_options((3, 1, 2)), [3, 1, 2])


class TestMastersUpdateSitelinkFlags(unittest.TestCase):
    """CLI wiring for `masters update`'s "Быстрые ссылки" flags (issue #648,
    Этап C)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_documents_sitelink_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--add-sitelink", result.output)
        self.assertIn("--remove-sitelink", result.output)

    def test_rejects_duplicate_remove_sitelink_position(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--remove-sitelink",
                "1",
                "--remove-sitelink",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output.lower())

    def test_rejects_malformed_add_sitelink(self):
        result = self.runner.invoke(
            cli,
            ["masters", "update", "42", "--add-sitelink", "OnlyTitle"],
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_passes_add_and_remove_sitelinks(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--add-sitelink",
                    "Об авторе|https://example.com/about|Узнайте больше",
                    "--remove-sitelink",
                    "3",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_update.assert_called_once()
        _args, kwargs = mock_update.call_args
        self.assertEqual(
            kwargs["add_sitelinks"],
            [
                {
                    "Title": "Об авторе",
                    "Href": "https://example.com/about",
                    "Description": "Узнайте больше",
                }
            ],
        )
        self.assertEqual(kwargs["remove_sitelinks"], [3])

    def test_no_fields_still_rejected_with_sitelink_flags_absent(self):
        result = self.runner.invoke(cli, ["masters", "update", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--add-sitelink", result.output)


class TestReadMetrikaCounters(unittest.TestCase):
    """``_read_metrika_counters`` (issue #648, Этап C) — mirrors
    ``_read_audience_tags``, but each "tag" is a whole Metrika counter whose
    on-page text spans two lines (domain+id, then goal count). NOT
    LIVE-VERIFIED beyond the DOM shape recon confirmed BEFORE/immediately
    after opening the editor — see the module comment above
    ``_METRIKA_COUNTER_WRAPPER_TESTID`` in ``direct_cli/browser/masters.py``.
    """

    def _tag_testid(self, index):
        testid = browser_masters._METRIKA_COUNTER_TESTID_TEMPLATE.format(index=index)
        return f'[data-testid="{testid}"]'

    def test_returns_every_counters_full_two_line_text(self):
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                self._tag_testid(0): _FakeLocator(
                    [_FakeLocatorHandle(text="gc.ksamata.ru • 72112213\n30 целей")]
                ),
                self._tag_testid(1): _FakeLocator(
                    [_FakeLocatorHandle(text="example.com • 12345678\n5 целей")]
                ),
            }
        )

        self.assertEqual(
            browser_masters._read_metrika_counters(page),
            [
                "gc.ksamata.ru • 72112213\n30 целей",
                "example.com • 12345678\n5 целей",
            ],
        )

    def test_returns_empty_list_when_wrapper_missing(self):
        page = FakePage(locators={})

        self.assertEqual(browser_masters._read_metrika_counters(page), [])

    def test_stops_at_first_missing_index(self):
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_WRAPPER_TESTID: _FakeLocator(
                    [_FakeLocatorHandle()]
                ),
                self._tag_testid(0): _FakeLocator(
                    [_FakeLocatorHandle(text="a.ru • 1\n1 цель")]
                ),
                # No entry for index 1 -> .first raises -> loop stops.
            }
        )

        self.assertEqual(
            browser_masters._read_metrika_counters(page), ["a.ru • 1\n1 цель"]
        )


class TestRemoveMetrikaCounter(unittest.TestCase):
    """``_remove_metrika_counter`` (issue #648) — mirrors
    ``_remove_audience_tag``'s position-based close-button click."""

    def _close_testid(self, index):
        testid = browser_masters._METRIKA_COUNTER_CLOSE_TESTID_TEMPLATE.format(
            index=index
        )
        return f'[data-testid="{testid}"]'

    def test_clicks_close_button_at_position(self):
        clicked = {"count": 0}
        handle = _FakeLocatorHandle(
            on_click=lambda: clicked.__setitem__("count", clicked["count"] + 1)
        )
        page = FakePage(locators={self._close_testid(1): _FakeLocator([handle])})

        browser_masters._remove_metrika_counter(page, 1)

        self.assertEqual(clicked["count"], 1)

    def test_raises_when_close_button_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._remove_metrika_counter(page, 0)


class TestAddMetrikaCounter(unittest.TestCase):
    """``_add_metrika_counter`` (issue #648) — mirrors ``_add_audience_tag``,
    but clicks a dedicated launcher button instead of the tags-wrapper
    itself (see the module comment above ``_METRIKA_COUNTER_WRAPPER_TESTID``
    for why). NOT LIVE-VERIFIED: recon never exercised typing into the
    input or clicking a suggestion, so the exact input semantics (what text
    a caller must pass) remain unconfirmed."""

    def test_raises_when_launcher_missing(self):
        page = FakePage(locators={})

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_metrika_counter(page, "gc.ksamata.ru")

    def test_raises_when_input_missing_after_launcher_click(self):
        launcher = _FakeLocatorHandle()
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_LAUNCHER_TESTID: _FakeLocator(
                    [launcher]
                ),
                # No entry for the input testid -> .first raises on click().
            }
        )

        with self.assertRaises(BrowserSessionError):
            browser_masters._add_metrika_counter(page, "gc.ksamata.ru")

    def test_clicks_launcher_then_matching_option_by_first_line(self):
        launcher_clicks = {"count": 0}
        launcher = _FakeLocatorHandle(
            on_click=lambda: launcher_clicks.__setitem__(
                "count", launcher_clicks["count"] + 1
            )
        )
        field = _FakeLocatorHandle()
        option_clicked = {"clicked": False}
        matching_option = _FakeLocatorHandle(
            text="gc.ksamata.ru • 72112213\n30 целей",
            on_click=lambda: option_clicked.__setitem__("clicked", True),
        )
        other_option = _FakeLocatorHandle(text="other.ru • 999\n1 цель")
        listbox = _FakeLocatorHandle(role_options=[other_option, matching_option])
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_LAUNCHER_TESTID: _FakeLocator(
                    [launcher]
                ),
                browser_masters._METRIKA_COUNTER_INPUT_TESTID: _FakeLocator([field]),
                browser_masters._METRIKA_COUNTER_LISTBOX_TESTID: _FakeLocator(
                    [listbox]
                ),
            }
        )

        browser_masters._add_metrika_counter(page, "gc.ksamata.ru • 72112213")

        self.assertEqual(launcher_clicks["count"], 1)
        self.assertTrue(option_clicked["clicked"])

    def test_raises_when_no_suggestion_matches(self):
        launcher = _FakeLocatorHandle()
        field = _FakeLocatorHandle()
        non_matching = _FakeLocatorHandle(text="other.ru • 999\n1 цель")
        listbox = _FakeLocatorHandle(role_options=[non_matching])
        page = FakePage(
            locators={
                browser_masters._METRIKA_COUNTER_LAUNCHER_TESTID: _FakeLocator(
                    [launcher]
                ),
                browser_masters._METRIKA_COUNTER_INPUT_TESTID: _FakeLocator([field]),
                browser_masters._METRIKA_COUNTER_LISTBOX_TESTID: _FakeLocator(
                    [listbox]
                ),
            }
        )

        with (
            patch.object(browser_masters, "_METRIKA_COUNTER_SUGGEST_TIMEOUT_MS", 10),
            self.assertRaises(BrowserSessionError),
        ):
            browser_masters._add_metrika_counter(page, "nomatch.ru")


class TestMetrikaCounterIdentity(unittest.TestCase):
    """``_metrika_counter_identity`` (cycle-review finding, issue #648):
    extracts the stable numeric counter id shared by both of this widget's
    text formats, so ``_verify_saved`` can compare an add's suggestion text
    against a read-back tag's display text without a false mismatch."""

    def test_extracts_id_from_suggestion_format(self):
        self.assertEqual(
            browser_masters._metrika_counter_identity(
                "Ксамата • yandex.ru/maps • 88834924"
            ),
            "88834924",
        )

    def test_extracts_id_from_two_line_tag_display_format(self):
        self.assertEqual(
            browser_masters._metrika_counter_identity(
                "gc.ksamata.ru • 72112213\n30 целей"
            ),
            "72112213",
        )

    def test_returns_text_unchanged_when_no_separator(self):
        self.assertEqual(
            browser_masters._metrika_counter_identity("nomatch"), "nomatch"
        )

    def test_returns_text_unchanged_when_trailing_separator_has_no_id(self):
        """cycle-review finding: a trailing " • " with nothing after it
        (e.g. malformed/unexpected markup) must NOT collapse to an empty
        identity -- two different malformed inputs would otherwise both
        become "" and falsely match each other in _verify_saved's Counter
        comparison, masking a real mismatch."""
        self.assertEqual(
            browser_masters._metrika_counter_identity("Label • "), "Label • "
        )

    def test_two_malformed_inputs_do_not_collapse_to_the_same_identity(self):
        a = browser_masters._metrika_counter_identity("Label A • ")
        b = browser_masters._metrika_counter_identity("Label B • ")
        self.assertNotEqual(a, b)

    def test_returns_text_unchanged_when_trailing_separator_has_only_whitespace(self):
        """cycle-review finding (PR #808 round 2): a trailing " • " followed
        only by whitespace (e.g. "Label •  ") is truthy in Python, so the
        bare `if identity` guard let it through as an identity instead of
        falling back to `text` -- the same collapse-to-one-identity bug the
        exactly-empty guard above already fixed, one whitespace-only
        character class narrower."""
        self.assertEqual(
            browser_masters._metrika_counter_identity("Label •  "), "Label •  "
        )

    def test_two_whitespace_only_malformed_inputs_do_not_collapse_to_the_same_identity(
        self,
    ):
        a = browser_masters._metrika_counter_identity("Label A •  ")
        b = browser_masters._metrika_counter_identity("Label B •  ")
        self.assertNotEqual(a, b)

    def test_strips_trailing_whitespace_around_a_real_id(self):
        """issue #809: a real id with incidental trailing whitespace (e.g.
        from the two-line tag-display format's first line) must normalize
        to the same identity as the same id with no surrounding
        whitespace, or _verify_saved's Counter comparison false-mismatches
        an add that actually succeeded."""
        self.assertEqual(
            browser_masters._metrika_counter_identity("domain • 12345 "),
            "12345",
        )

    def test_strips_leading_whitespace_around_a_real_id(self):
        self.assertEqual(
            browser_masters._metrika_counter_identity("domain •  12345"),
            "12345",
        )

    def test_suggestion_and_whitespace_padded_tag_display_share_identity(self):
        """The exact scenario from issue #809: suggestion text has no
        padding, read-back tag-display text has incidental whitespace
        around the same id -- both must normalize to the same identity."""
        suggestion = browser_masters._metrika_counter_identity(
            "label • domain/path • 12345"
        )
        tag_display = browser_masters._metrika_counter_identity(
            "domain • 12345 \n30 целей"
        )
        self.assertEqual(suggestion, tag_display)

    def test_non_numeric_whitespace_padded_malformed_tokens_stay_distinct(self):
        """cycle-review finding (PR #810 round 2): stripping whitespace
        around a non-empty token must NOT extend to non-numeric malformed
        tokens -- only a genuine numeric id (real counter ids are numeric)
        is normalized. Without an .isdigit() guard, "Label A •  foo " and
        "Label B • foo " would both collapse to "foo" and silently match
        each other in _verify_saved's Counter comparison, the exact
        "malformed inputs must not silently match" failure mode the
        empty/whitespace-only guard already exists to prevent -- just for
        a narrower, non-numeric class of malformed input."""
        a = browser_masters._metrika_counter_identity("Label A •  foo ")
        b = browser_masters._metrika_counter_identity("Label B • foo ")
        self.assertNotEqual(a, b)
        self.assertEqual(a, "Label A •  foo ")
        self.assertEqual(b, "Label B • foo ")

    def test_numeric_id_still_stripped_when_padded(self):
        """Sanity check that the .isdigit() guard doesn't regress the
        original issue #809 fix for genuine numeric ids."""
        self.assertEqual(
            browser_masters._metrika_counter_identity("domain •  88834924 "),
            "88834924",
        )


class TestParseRemoveMetrikaCounterOptions(unittest.TestCase):
    """``_parse_remove_metrika_counter_options`` (issue #648) — mirrors
    ``_parse_remove_audience_tag_options``'s duplicate-position guard."""

    def test_rejects_duplicate_position(self):
        from direct_cli.commands.masters import _parse_remove_metrika_counter_options

        with self.assertRaises(click.UsageError):
            _parse_remove_metrika_counter_options((1, 1))

    def test_accepts_distinct_positions_in_order(self):
        from direct_cli.commands.masters import _parse_remove_metrika_counter_options

        self.assertEqual(_parse_remove_metrika_counter_options((3, 1, 2)), [3, 1, 2])


class TestMastersUpdateMetrikaCounterFlags(unittest.TestCase):
    """CLI wiring for `masters update`'s "Счетчики Яндекс Метрики" flags
    (issue #648)."""

    def setUp(self):
        self.runner = CliRunner()

    def test_documents_metrika_counter_flags(self):
        result = self.runner.invoke(cli, ["masters", "update", "--help"])
        self.assertIn("--add-metrika-counter", result.output)
        self.assertIn("--remove-metrika-counter", result.output)

    def test_rejects_duplicate_remove_metrika_counter_position(self):
        result = self.runner.invoke(
            cli,
            [
                "masters",
                "update",
                "42",
                "--remove-metrika-counter",
                "1",
                "--remove-metrika-counter",
                "1",
            ],
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("more than once", result.output.lower())

    def test_passes_add_and_remove_metrika_counters(self):
        with (
            patch("direct_cli.browser.masters.update_master") as mock_update,
            patch("direct_cli.commands.masters._with_session") as mock_with_session,
        ):
            mock_with_session.side_effect = lambda ctx, hf, pd, cp, op: op(object())
            mock_update.return_value = {"CampaignId": 42}
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "42",
                    "--add-metrika-counter",
                    "gc.ksamata.ru",
                    "--remove-metrika-counter",
                    "1",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        mock_update.assert_called_once()
        _args, kwargs = mock_update.call_args
        self.assertEqual(kwargs["add_metrika_counters"], ["gc.ksamata.ru"])
        self.assertEqual(kwargs["remove_metrika_counters"], [1])

    def test_no_fields_still_rejected_with_metrika_counter_flags_absent(self):
        result = self.runner.invoke(cli, ["masters", "update", "42"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--add-metrika-counter", result.output)


class _FakeModerationPage(_FakeImagesPage):
    """Models the images section plus its per-image moderation status buttons
    (issue #814).

    ``statuses`` is one entry per image, positionally aligned with ``ids``,
    each either ``"ok"`` (the efficiency-badge variant) or ``"rejected"`` —
    exactly the two live-confirmed shapes (see
    ``tests/fixtures/masters_wizard_edit_moderation.html``). Defaults to all
    ``"ok"``, so an existing images test that subclasses this gets a clean
    campaign.

    ``extra_statuses`` appends status buttons with NO corresponding image,
    modeling the count-mismatch case ``_read_image_moderation_rejections``
    must survive without misattributing a content ID.

    Each status button's structural content-ID resolution
    (``_IMAGE_STATUS_CONTENT_ID_JS``, issue #817) is modeled as "the Nth
    button structurally belongs to the Nth image" by default — i.e. the fake
    still models the live-confirmed common case where DOM order and the
    structural walk agree. A test wanting to model the walk failing to
    resolve (no single-image ancestor found) passes that index in
    ``unresolvable_structural_indices``; ``extra_statuses`` positions (beyond
    ``len(ids)``) are unresolvable by construction, since no image exists for
    them to resolve to — mirroring the real JS walk finding zero or more than
    one ``ContentImage`` and returning ``null``. A test wanting to model a
    genuine hydration gap — a button MISSING from the middle of the list, so
    a later button's DOM-order index no longer equals its image's position —
    passes the images each *rendered* button structurally belongs to via
    ``button_content_ids`` (positionally aligned with ``statuses``, distinct
    from ``ids``/``_ids`` which lists every image on the page).
    """

    def __init__(
        self,
        ids,
        *,
        statuses=None,
        extra_statuses=(),
        unresolvable_structural_indices=(),
        button_content_ids=None,
        **kwargs,
    ):
        super().__init__(ids, **kwargs)
        self.statuses = list(statuses if statuses is not None else ["ok"] * len(ids))
        self.statuses.extend(extra_statuses)
        self._ids = list(ids)
        self._unresolvable_structural_indices = set(unresolvable_structural_indices)
        self._button_content_ids = (
            list(button_content_ids) if button_content_ids is not None else None
        )

    def _structural_content_id(self, index):
        if index in self._unresolvable_structural_indices:
            return None
        if self._button_content_ids is not None:
            if index < len(self._button_content_ids):
                return self._button_content_ids[index]
            return None
        if index < len(self._ids):
            return self._ids[index]
        # A status button beyond the image list (extra_statuses): the real
        # walk finds no single-image ancestor for it either.
        return None

    def _status_handle(self, status, content_id):
        # ``evaluate_result`` models ``_IMAGE_STATUS_COMBINED_JS``'s return
        # shape (issue #820, Codex round-4 follow-up review of PR #821): the
        # reader reads ``classAttr``/``isRejected``/``contentId`` from a
        # SINGLE ``evaluate()`` call — ``attrs`` is kept only as
        # documentation of the modeled markup's class attribute, it is not
        # read by production code.
        if status == "rejected":
            # No ImageStatusIcon_efficiency class; a negative-label child.
            return _FakeLocatorHandle(
                attrs={"class": "dc-ClickableIcon dc-ClickableIcon_color_gray"},
                evaluate_result={
                    "classAttr": "dc-ClickableIcon dc-ClickableIcon_color_gray",
                    "isRejected": True,
                    "contentId": content_id,
                },
            )
        if status == "ok-with-negative-child":
            # The efficiency badge, but ALSO matching the negative selector.
            # Models the live false-positive class of bug: those classes are
            # not unique to moderation (a video thumbnail's MediaControl
            # renders them too — campaign 713234162, 6 of them, 0 rejected
            # images), so the efficiency class must veto.
            class_attr = (
                "dc-ClickableIcon ImageStatusIcon_button__sqJGQ "
                "ImageStatusIcon_efficiency__pCGiR"
            )
            return _FakeLocatorHandle(
                attrs={"class": class_attr},
                evaluate_result={
                    "classAttr": class_attr,
                    "isRejected": True,
                    "contentId": content_id,
                },
            )
        if status == "unknown":
            # Neither shape: no efficiency class AND no negative child — a
            # hypothetical third variant, which must NOT count as rejected.
            class_attr = "dc-ClickableIcon dc-ClickableIcon_color_gray"
            return _FakeLocatorHandle(
                attrs={"class": class_attr},
                evaluate_result={
                    "classAttr": class_attr,
                    "isRejected": False,
                    "contentId": content_id,
                },
            )
        # "ok": the efficiency badge. Note the real class carries a
        # build-time hash suffix, which the reader must match as a substring.
        class_attr = (
            "dc-ClickableIcon ImageStatusIcon_button__sqJGQ "
            "ImageStatusIcon_efficiency__pCGiR"
        )
        return _FakeLocatorHandle(
            attrs={"class": class_attr},
            evaluate_result={
                "classAttr": class_attr,
                "isRejected": False,
                "contentId": content_id,
            },
        )

    def locator(self, selector):
        if selector == browser_masters._IMAGE_STATUS_SELECTOR:
            return _FakeLocator(
                [
                    self._status_handle(status, self._structural_content_id(index))
                    for index, status in enumerate(self.statuses)
                ]
            )
        return super().locator(selector)


class TestReadModerationStatuses(unittest.TestCase):
    """``read_moderation_statuses`` — issue #814's per-element rejection read.

    Marker shape confirmed live 2026-08-08 on campaigns 713234064 and
    713231614; see ``tests/fixtures/masters_wizard_edit_moderation.html``.
    """

    def test_reports_a_rejected_image_with_position_and_content_id(self):
        page = _FakeModerationPage(
            ["a", "b", "c", "d"], statuses=["ok", "rejected", "ok", "ok"]
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertEqual(
            result["RejectedElements"],
            [
                {
                    "Type": "image",
                    "Position": 2,
                    "ContentId": "b",
                    "Title": browser_masters._MODERATION_REJECTED_TITLE,
                    "Hint": browser_masters._MODERATION_REJECTED_HINT,
                }
            ],
        )

    def test_clean_campaign_reports_no_rejections(self):
        page = _FakeModerationPage(["a", "b", "c"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 0)
        self.assertEqual(result["RejectedElements"], [])

    def test_campaign_without_images_reports_no_rejections(self):
        page = _FakeModerationPage([])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 0)

    def test_reports_every_rejected_image_in_page_order(self):
        page = _FakeModerationPage(
            ["a", "b", "c", "d", "e"],
            statuses=["rejected", "ok", "rejected", "ok", "rejected"],
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(
            [(e["Position"], e["ContentId"]) for e in result["RejectedElements"]],
            [(1, "a"), (3, "c"), (5, "e")],
        )

    def test_efficiency_badge_is_never_a_rejection_despite_hash_suffix(self):
        """The live class is ``ImageStatusIcon_efficiency__<buildhash>`` — the
        reader must match it as a substring, not by equality."""
        page = _FakeModerationPage(["a"], statuses=["ok"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedElements"], [])

    def test_efficiency_badge_wins_even_if_a_negative_class_is_also_present(self):
        """The negative-class check alone is NOT sufficient: those classes are
        not unique to moderation (confirmed live — a video thumbnail's
        ``MediaControl`` renders the same pair). An efficiency badge is never
        a rejection, whatever else it contains."""
        page = _FakeModerationPage(
            ["a", "b"], statuses=["ok-with-negative-child", "rejected"]
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(
            [(e["Position"], e["ContentId"]) for e in result["RejectedElements"]],
            [(2, "b")],
        )

    def test_negative_child_without_efficiency_check_is_not_enough(self):
        """A third button variant (no efficiency class, no negative child) is
        NOT reported — guards against classifying anything unfamiliar as a
        rejection."""
        page = _FakeModerationPage(["a", "b"], statuses=["unknown", "unknown"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedElements"], [])

    def test_extra_status_button_yields_null_content_id_not_a_wrong_one(self):
        """More status buttons than images: the surplus rejection is still
        reported, but must never borrow another image's identity — neither
        its content ID nor its ordinal. Nulled by the GLOBAL count guard
        (button count != image count), not by the per-button structural
        walk — see ``test_surplus_status_button_is_nulled_not_misattributed``
        for why the walk alone cannot be trusted for this case."""
        page = _FakeModerationPage(["a"], statuses=["ok"], extra_statuses=["rejected"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertIsNone(result["RejectedElements"][0]["Position"])
        self.assertIsNone(result["RejectedElements"][0]["ContentId"])

    def test_missing_status_button_still_nulls_rather_than_trusts_the_structural_walk(
        self,
    ):
        """FEWER status buttons than images (issue #817's original deficit
        scenario) is now caught by the SAME global count guard that protects
        the surplus case (issue #817 round-2 follow-up): the structural walk
        alone cannot tell a surplus button apart from a real one sharing its
        card (see ``test_surplus_status_button_is_nulled_not_misattributed``
        below), so any count mismatch — deficit included — nulls every
        rejection's ``ContentId``/``Position`` rather than trusting the
        per-button walk. This is more conservative than the walk alone would
        need to be for a pure deficit, but it is the only guard that also
        covers surplus, so both directions share it.

        Models a genuine hydration gap: image "b"'s status button never
        rendered, so only 3 buttons exist on the page (button count 3 !=
        image count 4), structurally belonging to "a", "c", "d" in DOM order
        (``button_content_ids``) — NOT the first 3 of the 4 images. Even
        though the rejected button ("d"'s) would resolve correctly via the
        structural walk alone, the count mismatch nulls it, matching
        pre-#817 behavior for this direction too.
        """
        page = _FakeModerationPage(
            ["a", "b", "c", "d"],
            statuses=["ok", "ok", "rejected"],
            button_content_ids=["a", "c", "d"],
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertIsNone(result["RejectedElements"][0]["ContentId"])
        self.assertIsNone(result["RejectedElements"][0]["Position"])

    def test_surplus_status_button_is_nulled_not_misattributed(self):
        """MORE status buttons than images: a surplus button (e.g. a
        hydration duplicate) is necessarily nested inside some OTHER
        button's real, single-image card — every real card holds exactly
        one image (see ``_read_image_content_ids``) — so the structural walk
        alone would resolve it to that card's real, innocent content ID
        rather than ``None``, misattributing the rejection (round-2 finding
        on issue #817). ``button_content_ids`` models this realistically: the
        surplus (3rd) button structurally resolves to "b", the SAME card as
        the 2nd (real) button, rather than to nothing. The global count
        guard (3 buttons vs 2 images) is what actually protects this case,
        nulling every rejection in the pass — not the per-button walk, which
        would have happily returned "b" twice."""
        page = _FakeModerationPage(
            ["a", "b"],
            statuses=["ok", "ok", "rejected"],
            button_content_ids=["a", "b", "b"],
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertIsNone(result["RejectedElements"][0]["ContentId"])
        self.assertIsNone(result["RejectedElements"][0]["Position"])

    def test_balanced_surplus_and_deficit_is_nulled_not_misattributed(self):
        """issue #820 finding #1: a BALANCED drift — one image's status
        button missing while a DIFFERENT button duplicates — keeps the total
        button count equal to the image count, so the global ``counts_match``
        guard alone would pass. The duplicate ("b"'s second button)
        structurally resolves to "b" — the same card as the first "b" button
        — which is exactly what the multiset cross-check exists to catch:
        two buttons resolving to the same content ID can never happen on a
        real DOM (every card holds exactly one image), so the whole pass is
        untrusted rather than reporting the duplicate's rejection against
        "b" and silently dropping the real rejection on the missing button's
        own image ("c", never rendered at all).

        3 buttons (counts_match: True against 3 images), but the multiset of
        resolved IDs is {"a", "b", "b"} — "b" appears twice, "c" never
        appears — instead of {"a", "b", "c"}.
        """
        page = _FakeModerationPage(
            ["a", "b", "c"],
            statuses=["ok", "rejected", "rejected"],
            button_content_ids=["a", "b", "b"],
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 2)
        for element in result["RejectedElements"]:
            self.assertIsNone(element["ContentId"])
            self.assertIsNone(element["Position"])

    def test_unresolvable_structural_walk_yields_null_content_id_and_position(self):
        """When the structural walk itself cannot resolve a button to exactly
        one image (the real JS returns ``null`` — no single-image ancestor
        found within the depth budget, or an ambiguous ancestor), both
        ``ContentId`` and ``Position`` are dropped rather than guessed.
        "Something is rejected but this reader cannot say which image" is
        strictly more useful than silence, and far better than misattributing
        the rejection to an innocent image. Counts are kept ALIGNED (2
        buttons, 2 images) so the global count guard passes and this
        specifically exercises the per-button structural-walk fallback, not
        the count guard from the surplus/deficit tests below."""
        page = _FakeModerationPage(
            ["a", "b"],
            statuses=["rejected", "ok"],
            unresolvable_structural_indices={0},
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertEqual(result["RejectedElements"][0]["Type"], "image")
        self.assertIsNone(result["RejectedElements"][0]["Position"])
        self.assertIsNone(result["RejectedElements"][0]["ContentId"])

    def test_aligned_counts_still_resolve_the_content_id(self):
        """The common case — button count matches image count and the
        structural walk resolves cleanly — keeps reporting the content ID it
        always did."""
        page = _FakeModerationPage(["a", "b", "c"], statuses=["ok", "rejected", "ok"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedElements"][0]["ContentId"], "b")

    def test_reordered_but_count_equal_dom_keeps_position_and_content_id_consistent(
        self,
    ):
        """A reordered-but-count-equal DOM (button order != image order) is
        exactly the case the structural walk exists to survive (issue #817).
        The 2nd button (DOM index 1) structurally belongs to image "c" (the
        3rd image in ``_read_image_content_ids`` order), not to the 2nd
        image "b" — modeled via ``button_content_ids``. ``Position`` must be
        derived from where "c" actually sits in the image list (3), NEVER
        from the button's own DOM ordinal (2), so it cannot contradict the
        correctly-resolved ``ContentId``."""
        page = _FakeModerationPage(
            ["a", "b", "c"],
            statuses=["ok", "rejected", "ok"],
            button_content_ids=["a", "c", "b"],
        )

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertEqual(result["RejectedElements"][0]["ContentId"], "c")
        self.assertEqual(result["RejectedElements"][0]["Position"], 3)

    def test_declares_which_element_types_were_actually_checked(self):
        """An empty result must not be readable as "no video/headline/text is
        rejected" — only images have a live-confirmed marker."""
        page = _FakeModerationPage(["a"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["CheckedTypes"], ["image"])
        self.assertEqual(result["UnsupportedTypes"], ["video", "headline", "text"])

    def test_never_clicks_save(self):
        page = _FakeModerationPage(["a", "b"], statuses=["ok", "rejected"])

        browser_masters.read_moderation_statuses(page)

        self.assertEqual(page.save_clicks, [])

    def test_never_opens_the_images_modal(self):
        """Unlike ``fetch_master_images`` there is no thumb URL to read, so
        this reader must stay a pure page-level read."""
        page = _FakeModerationPage(["a"], statuses=["rejected"])

        browser_masters.read_moderation_statuses(page)

        self.assertFalse(page.modal_open)

    def test_unrendered_images_section_raises_rather_than_reporting_clean(self):
        """Same invariant as ``fetch_master_images``: an unsettled section
        must not be reported as "nothing rejected"."""

        class _NoEditorPage(_FakeModerationPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGES_EDITOR_SELECTOR:
                    return _FakeLocator([])
                return super().locator(selector)

        page = _NoEditorPage([])
        with patch.object(browser_masters, "_IMAGES_EDITOR_TIMEOUT_MS", 1):
            with self.assertRaises(BrowserSessionError):
                browser_masters.read_moderation_statuses(page)

    def test_id_resolution_and_status_read_use_a_single_live_access_per_button(
        self,
    ):
        """issue #820 finding #4 (Codex round-4 review of PR #821): real
        Playwright ``Locator.nth(index)`` re-resolves against the LIVE DOM on
        every access — it is not a snapshot/handle. If a reader calls
        ``buttons.nth(index)`` TWICE for the same index (once to resolve the
        structural content ID, once — in a separate later pass — to read
        class/rejection state), a hydration re-render between those two
        calls can swap which button physically sits at that index, silently
        pairing a stale content ID with a fresh rejection read (or vice
        versa) — a confident misattribution. The fix must call
        ``buttons.nth(index)`` at most ONCE per index and read both the
        content ID and the class/rejection state off that SAME access, so
        there is no second live re-query for a reorder to race against.

        Modeled by making the button-1 handle explode on a second
        ``buttons.nth(1)`` call: the fake ``Locator.nth()`` returns a
        *tracking* wrapper around the real handle that raises if the same
        index is fetched more than once. A single-pass reader (one
        ``nth(index)`` call, both operations off that result) never trips
        this; any reader that re-fetches ``nth(1)`` in a second pass does.
        """

        class _SingleFetchLocator(_FakeLocator):
            """Wraps a real ``_FakeLocator`` but raises if ``.nth()`` is
            called more than once for the same index — the fake's stand-in
            for "a second live re-query could return a different button".
            """

            def __init__(self, handles):
                super().__init__(handles)
                self._fetch_counts = [0] * len(handles)

            def nth(self, i):
                self._fetch_counts[i] += 1
                if self._fetch_counts[i] > 1:
                    raise browser_masters.PlaywrightError(
                        f"button at index {i} re-fetched from the live DOM "
                        "a second time — the DOM may have changed between "
                        "the two accesses"
                    )
                return super().nth(i)

        class _SingleFetchPage(_FakeModerationPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGE_STATUS_SELECTOR:
                    real = super().locator(selector)
                    return _SingleFetchLocator(real._handles)
                return super().locator(selector)

        page = _SingleFetchPage(["a", "b", "c"], statuses=["ok", "rejected", "ok"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertEqual(result["RejectedElements"][0]["ContentId"], "b")
        self.assertEqual(result["RejectedElements"][0]["Position"], 2)

    def test_content_id_and_rejection_state_read_from_one_evaluate_call(self):
        """issue #820 finding #4, Codex round-4 follow-up review of PR #821:
        a single ``buttons.nth(index)`` access is not enough on its own —
        calling THREE separate Playwright methods on that one Locator
        (``get_attribute``, a scoped ``.locator().count()``, and
        ``evaluate()``) still re-resolves the Locator's full selector chain
        on EACH call, since a Playwright ``Locator`` is a lazy, re-evaluated
        query rather than a handle to one fixed element. A hydration reorder
        landing between any two of those three calls could still pair one
        button's rejection state with a different button's structural
        ContentId. The fix reads the class attribute, the rejection marker,
        and the structural ContentId all from ONE ``evaluate()`` call
        (``_IMAGE_STATUS_COMBINED_JS``), so there is exactly one live access
        per button — not three.

        Modeled by a handle that raises if ``get_attribute`` or the scoped
        rejection-selector ``.locator()`` is ever called at all: a reader
        satisfying the invariant never touches either, since it gets
        everything from the combined ``evaluate()`` result.
        """

        class _EvaluateOnlyHandle:
            """Wraps a real handle; raises if anything OTHER than
            ``evaluate()`` is called — the fake's stand-in for "a second (or
            third) live re-query could return a different button"."""

            def __init__(self, real_handle):
                self._real = real_handle

            def evaluate(self, script):
                return self._real.evaluate(script)

            def get_attribute(self, name):
                raise browser_masters.PlaywrightError(
                    "get_attribute() called separately from evaluate() — "
                    "the DOM may have changed between the two live accesses"
                )

            def locator(self, selector):
                raise browser_masters.PlaywrightError(
                    "locator() called separately from evaluate() — the DOM "
                    "may have changed between the two live accesses"
                )

        class _EvaluateOnlyLocator(_FakeLocator):
            def nth(self, i):
                return _EvaluateOnlyHandle(super().nth(i))

        class _EvaluateOnlyPage(_FakeModerationPage):
            def locator(self, selector):
                if selector == browser_masters._IMAGE_STATUS_SELECTOR:
                    real = super().locator(selector)
                    return _EvaluateOnlyLocator(real._handles)
                return super().locator(selector)

        page = _EvaluateOnlyPage(["a", "b", "c"], statuses=["ok", "rejected", "ok"])

        result = browser_masters.read_moderation_statuses(page)

        self.assertEqual(result["RejectedCount"], 1)
        self.assertEqual(result["RejectedElements"][0]["ContentId"], "b")
        self.assertEqual(result["RejectedElements"][0]["Position"], 2)


class TestFetchMasterModerationStatuses(unittest.TestCase):
    """``fetch_master_moderation_statuses`` — the navigating wrapper."""

    def test_carries_the_campaign_id_into_the_result(self):
        page = _FakeModerationPage(["a"], statuses=["rejected"])

        result = browser_masters.fetch_master_moderation_statuses(page, 42)

        self.assertEqual(result["CampaignId"], 42)
        self.assertEqual(result["RejectedCount"], 1)

    def test_reads_the_edit_page_not_the_overview_page(self):
        page = _FakeModerationPage(["a"])

        browser_masters.fetch_master_moderation_statuses(page, 42)

        self.assertIn("/edit/", page.navigated_to[-1])


class TestFetchMasterTrackingParams(unittest.TestCase):
    """``fetch_master_tracking_params`` — the navigating wrapper (issue #824).

    Reuses ``TestUtmSectionReadability``'s page shape (a UTM spoiler that may
    mount late), since the readability distinction this function must
    surface is exactly what that class's fake already models.
    """

    @staticmethod
    def _page(*, spoiler_appears_after=0, value="utm_source=x"):
        # TestUtmSectionReadability's fake models the UTM spoiler/field but
        # not the edit form's own ready markers — fetch_master_tracking_params
        # navigates via _wait_for_edit_form first, which needs those present
        # (mirrors _FakeImagesPage's role_elements default).
        page = TestUtmSectionReadability._page(
            spoiler_appears_after=spoiler_appears_after, value=value
        )
        page._locators.setdefault(
            f'[data-testid="{browser_masters._EDIT_FORM_READY_TESTID}"]',
            _FakeLocator([_FakeLocatorHandle()]),
        )
        page._role_elements = [
            (
                "button",
                browser_masters._SAVE_BUTTON_TEXT,
                _FakeTextLocatorHandle(visible=True),
            )
        ]
        return page

    def test_carries_the_campaign_id_into_the_result(self):
        page = self._page(value="utm_source=x")

        result = browser_masters.fetch_master_tracking_params(page, 42)

        self.assertEqual(result["CampaignId"], 42)
        self.assertEqual(result["TrackingParams"], "utm_source=x")

    def test_reads_the_edit_page_not_the_overview_page(self):
        page = self._page(value="utm_source=x")

        browser_masters.fetch_master_tracking_params(page, 42)

        self.assertIn("/edit/", page.navigated_to[-1])

    def test_mounted_and_empty_field_reports_empty_string_not_omitted(self):
        page = self._page(value="")

        result = browser_masters.fetch_master_tracking_params(page, 42)

        self.assertIn("TrackingParams", result)
        self.assertEqual(result["TrackingParams"], "")

    def test_unreadable_section_omits_the_key_rather_than_a_misleading_value(self):
        # A section that never becomes readable within the wait budget must
        # not be reported as "" (that would be indistinguishable from a
        # genuinely empty field) — the key is simply absent, mirroring how
        # the DRAFT overview path already omits an unreadable LandingUrl.
        page = self._page(spoiler_appears_after=10**9)

        result = browser_masters.fetch_master_tracking_params(page, 42)

        self.assertNotIn("TrackingParams", result)
        self.assertEqual(result["CampaignId"], 42)


def _chromium_available():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            return Path(p.chromium.executable_path).exists()
    except Exception:  # noqa: PIE786 - any import/launch failure means "unavailable"
        return False


@unittest.skipUnless(
    _chromium_available(),
    "Playwright Chromium not downloaded (run: playwright install chromium)",
)
class TestImageStatusContentIdJsAgainstRealDom(unittest.TestCase):
    """Executes the REAL ``_IMAGE_STATUS_COMBINED_JS`` string's structural
    ContentId walk against a real, constructed nested DOM via a real
    Chromium page (issue #820 finding #4).

    Every other test in this module drives ``_read_image_moderation_rejections``
    through ``_FakeModerationPage``, whose ``evaluate()`` ignores the script
    argument entirely and returns a precomputed value
    (``_structural_content_id``/``button_content_ids``) — so the JS string's
    own logic (the depth-12 walk, the ``ContentImage.`` prefix selector, the
    ``/ContentImage\\.(.+)$/`` regex, the ``imgs.length > 1`` ambiguity guard)
    had no executed coverage: a future markup change breaking any of those
    would silently degrade every rejection's ``ContentId``/``Position`` to
    ``None`` with all tests green. This class closes that gap by loading a
    real page and calling
    ``element_handle.evaluate(_IMAGE_STATUS_COMBINED_JS)`` for real,
    exercising the exact production code path
    (``_read_image_moderation_rejections`` calls
    ``button.evaluate(_IMAGE_STATUS_COMBINED_JS)`` the same way), reading
    just the returned ``contentId`` field — the class-attribute/rejection
    halves of the combined script are exercised by the ordinary
    ``_FakeModerationPage``-driven tests above via ``_status_handle``'s
    modeled markup, so this class stays scoped to the ONE half those fakes
    cannot exercise: the real structural walk.

    A single module-scoped browser/page is reused across test methods (each
    test sets fresh ``page.content()``) to keep this fast — a full Chromium
    launch per test would multiply the ~1s startup cost across every case.
    """

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        cls._playwright_cm = sync_playwright()
        cls._playwright = cls._playwright_cm.__enter__()
        cls._browser = cls._playwright.chromium.launch()
        cls._page = cls._browser.new_page()

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._playwright_cm.__exit__(None, None, None)

    # Shorthand for the (long) real testid prefix, kept as one constant so
    # the fixture HTML below stays under the repo's line-length limit.
    _CI = "ImageSuggestionsEditor.CampaignContents.ContentImage"

    def _evaluate(self, html, button_selector="#status"):
        self._page.set_content(html)
        handle = self._page.query_selector(button_selector)
        result = handle.evaluate(browser_masters._IMAGE_STATUS_COMBINED_JS)
        return result["contentId"]

    def test_common_aligned_case_resolves_the_sibling_content_image(self):
        """The button and the ``ContentImage`` sit inside the SAME immediate
        card — the live-confirmed depth-4 shape's simplest instance."""
        html = f"""
        <div id="card">
          <div><div>
            <div data-testid="{self._CI}.abc123"></div>
            <button id="status"></button>
          </div></div>
        </div>
        """
        self.assertEqual(self._evaluate(html), "abc123")

    def test_reordered_dom_still_resolves_to_the_buttons_own_card(self):
        """A card whose ``ContentImage`` is declared AFTER a DIFFERENT
        card's button in raw document order — the walk is anchored at the
        button and reads whatever is nested under ITS OWN ancestor, so a
        reordered DOM cannot make it drift onto the wrong image."""
        html = f"""
        <div>
          <div id="card-x">
            <div><div>
              <button id="other-status"></button>
              <div data-testid="{self._CI}.xxx"></div>
            </div></div>
          </div>
          <div id="card-y">
            <div><div>
              <div data-testid="{self._CI}.yyy"></div>
              <button id="status"></button>
            </div></div>
          </div>
        </div>
        """
        self.assertEqual(self._evaluate(html), "yyy")

    def test_card_nested_deeper_than_the_depth_budget_resolves_to_null(self):
        """The walk checks the button itself (depth 0) plus 11 ancestor hops
        (depth < 12), so the shared ancestor containing the ``ContentImage``
        must be found within 12 nodes up from the button. Nesting the button
        13 levels below that shared ancestor puts it just outside the
        budget, so the walk must give up and resolve to ``None`` rather than
        hang or walk past ``document.body``."""
        wrappers_open = "<div>" * 13
        wrappers_close = "</div>" * 13
        html = f"""
        <div>
          <div data-testid="{self._CI}.deep"></div>
          {wrappers_open}
            <button id="status"></button>
          {wrappers_close}
        </div>
        """
        self.assertIsNone(self._evaluate(html))

    def test_card_within_depth_budget_still_resolves(self):
        """Sanity check paired with the depth-budget test above: a card at
        exactly the live-confirmed depth (4) resolves normally, proving the
        ``None`` result above is really the depth budget firing and not an
        unrelated selector/regex break."""
        html = f"""
        <div><div><div><div>
          <div data-testid="{self._CI}.near"></div>
          <button id="status"></button>
        </div></div></div></div>
        """
        self.assertEqual(self._evaluate(html), "near")

    def test_sibling_element_sharing_the_contentimage_prefix_yields_null(self):
        """Two elements sharing the ``ContentImage.`` testid PREFIX under the
        same ancestor (e.g. a thumbnail AND a hidden duplicate/preview using
        a related testid) must trip the ``imgs.length > 1`` ambiguity guard
        and resolve to ``None`` rather than picking one arbitrarily."""
        html = f"""
        <div>
          <div data-testid="{self._CI}.one"></div>
          <div data-testid="{self._CI}.two"></div>
          <button id="status"></button>
        </div>
        """
        self.assertIsNone(self._evaluate(html))

    def test_no_content_image_anywhere_up_to_body_resolves_to_null(self):
        """A button with no ``ContentImage`` ancestor at all (e.g. a surplus
        hydration-duplicate button rendered outside any real card) must
        resolve to ``None``, not throw or return a stale value."""
        html = """
        <div><div>
          <button id="status"></button>
        </div></div>
        """
        self.assertIsNone(self._evaluate(html))


class TestMastersGetModerationStatusesFlag(unittest.TestCase):
    """``masters get --moderation-statuses`` — issue #814's CLI surface."""

    def setUp(self):
        self.runner = CliRunner()

    def _invoke(self, args):
        with patch(
            "direct_cli.commands.masters._with_session",
            side_effect=lambda ctx, headful, profile_dir, chrome_profile, fn: fn(
                object()
            ),
        ):
            return self.runner.invoke(cli, args)

    def test_flag_absent_never_reads_moderation_statuses(self):
        """The default `get` must not pay for a second page load."""
        with patch.object(
            browser_masters, "fetch_master", return_value={"CampaignId": 42}
        ):
            with patch.object(
                browser_masters, "fetch_master_moderation_statuses"
            ) as mock_moderation:
                result = self._invoke(["masters", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_moderation.assert_not_called()
        self.assertNotIn("RejectedElements", result.output)

    def test_flag_merges_rejections_into_the_same_result_object(self):
        """Issue #814: a slice of `get`'s output, not a separate command's."""
        with patch.object(
            browser_masters,
            "fetch_master",
            return_value={"CampaignId": 42, "Name": "campaign"},
        ):
            with patch.object(
                browser_masters,
                "fetch_master_moderation_statuses",
                return_value={
                    "CampaignId": 42,
                    "RejectedElements": [{"Type": "image", "Position": 2}],
                    "RejectedCount": 1,
                    "CheckedTypes": ["image"],
                    "UnsupportedTypes": ["video", "headline", "text"],
                },
            ):
                result = self._invoke(["masters", "get", "42", "--moderation-statuses"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["CampaignId"], 42)
        self.assertEqual(payload["Name"], "campaign")
        self.assertEqual(payload["RejectedCount"], 1)
        self.assertEqual(payload["RejectedElements"][0]["Position"], 2)

    def test_flag_applies_to_every_id_in_a_comma_separated_list(self):
        with patch.object(
            browser_masters,
            "fetch_master",
            side_effect=lambda _page, cid: {"CampaignId": cid},
        ):
            with patch.object(
                browser_masters,
                "fetch_master_moderation_statuses",
                side_effect=lambda _page, cid: {
                    "CampaignId": cid,
                    "RejectedElements": [],
                    "RejectedCount": 0,
                    "CheckedTypes": ["image"],
                    "UnsupportedTypes": ["video", "headline", "text"],
                },
            ) as mock_moderation:
                result = self._invoke(
                    ["masters", "get", "42,43", "--moderation-statuses"]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_moderation.call_count, 2)
        payload = json.loads(result.output)
        self.assertEqual([row["CampaignId"] for row in payload], [42, 43])
        self.assertTrue(all("RejectedCount" in row for row in payload))


class TestMastersGetTrackingParamsFlag(unittest.TestCase):
    """``masters get --tracking-params`` — issue #824's CLI surface."""

    def setUp(self):
        self.runner = CliRunner()

    def _invoke(self, args):
        with patch(
            "direct_cli.commands.masters._with_session",
            side_effect=lambda ctx, headful, profile_dir, chrome_profile, fn: fn(
                object()
            ),
        ):
            return self.runner.invoke(cli, args)

    def test_flag_absent_never_reads_tracking_params(self):
        """The default `get` must not pay for a second page load."""
        with patch.object(
            browser_masters, "fetch_master", return_value={"CampaignId": 42}
        ):
            with patch.object(
                browser_masters, "fetch_master_tracking_params"
            ) as mock_tracking:
                result = self._invoke(["masters", "get", "42"])

        self.assertEqual(result.exit_code, 0, result.output)
        mock_tracking.assert_not_called()
        self.assertNotIn("TrackingParams", result.output)

    def test_flag_merges_tracking_params_into_the_same_result_object(self):
        """A slice of `get`'s output, not a separate command's (mirrors
        --moderation-statuses, issue #814)."""
        with patch.object(
            browser_masters,
            "fetch_master",
            return_value={"CampaignId": 42, "Name": "campaign"},
        ):
            with patch.object(
                browser_masters,
                "fetch_master_tracking_params",
                return_value={
                    "CampaignId": 42,
                    "TrackingParams": "utm_source=yandex",
                },
            ):
                result = self._invoke(["masters", "get", "42", "--tracking-params"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(payload["CampaignId"], 42)
        self.assertEqual(payload["Name"], "campaign")
        self.assertEqual(payload["TrackingParams"], "utm_source=yandex")

    def test_flag_applies_to_every_id_in_a_comma_separated_list(self):
        with patch.object(
            browser_masters,
            "fetch_master",
            side_effect=lambda _page, cid: {"CampaignId": cid},
        ):
            with patch.object(
                browser_masters,
                "fetch_master_tracking_params",
                side_effect=lambda _page, cid: {
                    "CampaignId": cid,
                    "TrackingParams": f"utm_campaign={cid}",
                },
            ) as mock_tracking:
                result = self._invoke(["masters", "get", "42,43", "--tracking-params"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(mock_tracking.call_count, 2)
        payload = json.loads(result.output)
        self.assertEqual([row["CampaignId"] for row in payload], [42, 43])
        self.assertTrue(all("TrackingParams" in row for row in payload))

    def test_unreadable_section_omits_the_key_rather_than_a_misleading_value(self):
        # fetch_master_tracking_params itself omits the key when the UTM
        # section never became readable (see
        # TestFetchMasterTrackingParams) — this asserts the CLI merge
        # preserves that omission instead of coercing it to "".
        with patch.object(
            browser_masters,
            "fetch_master",
            return_value={"CampaignId": 42, "Name": "campaign"},
        ):
            with patch.object(
                browser_masters,
                "fetch_master_tracking_params",
                return_value={"CampaignId": 42},
            ):
                result = self._invoke(["masters", "get", "42", "--tracking-params"])

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertNotIn("TrackingParams", payload)


class TestMastersGetPerCampaignFailureIsolation(unittest.TestCase):
    """Issue #816: one campaign's read failure must not discard the batch."""

    def setUp(self):
        self.runner = CliRunner()

    def _invoke(self, args):
        with patch(
            "direct_cli.commands.masters._with_session",
            side_effect=lambda ctx, headful, profile_dir, chrome_profile, fn: fn(
                object()
            ),
        ):
            return self.runner.invoke(cli, args)

    def test_middle_campaign_failure_keeps_the_others_in_the_output(self):
        def _fetch(_page, cid):
            if cid == 2:
                raise browser_masters.PlaywrightError("overview timeout")
            return {"CampaignId": cid}

        with patch.object(browser_masters, "fetch_master", side_effect=_fetch):
            result = self._invoke(["masters", "get", "1,2,3"])

        self.assertEqual(result.exit_code, 2)
        json_start = result.output.index("[\n")
        json_end = result.output.rindex("]") + 1
        payload = json.loads(result.output[json_start:json_end])
        self.assertEqual([row["CampaignId"] for row in payload], [1, 2, 3])
        self.assertNotIn("Error", payload[0])
        self.assertIn("overview timeout", payload[1]["Error"])
        self.assertNotIn("Error", payload[2])

    def test_all_campaign_failures_keep_exit_one(self):
        with patch.object(
            browser_masters,
            "fetch_master",
            side_effect=browser_masters.PlaywrightError("overview timeout"),
        ):
            result = self._invoke(["masters", "get", "1,2"])

        self.assertEqual(result.exit_code, 1)
        payload = json.loads(result.output[result.output.index("[\n") :])
        self.assertEqual([row["CampaignId"] for row in payload], [1, 2])
        self.assertTrue(all("Error" in row for row in payload))

    def test_mid_batch_auth_error_triggers_with_session_retry(self):
        """Issue #816 follow-up (Codex, cycle-review PR #818): BrowserAuthError
        must propagate to ``_with_session``'s stale-session self-heal retry,
        not be swallowed as a per-campaign error -- ``BrowserAuthError`` is a
        ``BrowserSessionError`` subclass, so a bare ``except
        (BrowserSessionError, PlaywrightError)`` in ``_all`` catches it too
        and defeats the retry ``_with_session`` is built around.
        """
        call_count = {"n": 0}
        auth_error_raised = {"done": False}

        def _fake_with_session(ctx, headful, profile_dir, chrome_profile, fn):
            call_count["n"] += 1
            try:
                return fn(object())
            except BrowserAuthError:
                if call_count["n"] > 1:
                    raise
                return fn(object())

        def _fetch(_page, cid):
            if cid == 2 and not auth_error_raised["done"]:
                auth_error_raised["done"] = True
                raise BrowserAuthError("stale session")
            return {"CampaignId": cid}

        with (
            patch(
                "direct_cli.commands.masters._with_session",
                side_effect=_fake_with_session,
            ),
            patch.object(browser_masters, "fetch_master", side_effect=_fetch),
        ):
            result = self.runner.invoke(cli, ["masters", "get", "1,2,3"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(auth_error_raised["done"])
        payload = json.loads(result.output)
        self.assertEqual([row["CampaignId"] for row in payload], [1, 2, 3])
        for row in payload:
            self.assertNotIn("Error", row)


class _BatchPacingPage:
    """Minimal stand-in page for `masters update`'s batch loop.

    The batch never touches the DOM itself (each campaign's editing happens
    inside the patched `update_master`), so the only Playwright surface it
    needs is the pacing sleep -- which must still advance the module-wide fake
    clock, per `_advance_fake_clock`'s contract.
    """

    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)
        _advance_fake_clock(timeout)


class TestMastersUpdateBatch(unittest.TestCase):
    """`masters update --from-file/--masters-json` — issue #834.

    The plan is applied over ONE browser session, so these tests drive
    `_with_session` itself rather than a fake Playwright page: what matters is
    which campaigns were saved, in what order, exactly once, and what the
    report says about each of them.
    """

    def setUp(self):
        self.runner = CliRunner()

    @staticmethod
    def _plan(tmpdir, rows):
        path = Path(tmpdir) / "plan.jsonl"
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return str(path)

    @staticmethod
    @contextlib.contextmanager
    def _session(update=None, moderation=None, page=None):
        """Patch the batch's three collaborators: the session wrapper, the
        save, and the optional moderation read."""

        def _with_session(ctx, headful, profile_dir, chrome_profile, fn):
            # The batch paces between campaigns, so even a stand-in page must
            # offer `wait_for_timeout` -- and it must advance the module fake
            # clock like every other page here (issue #767).
            return fn(page if page is not None else _BatchPacingPage())

        patches = [
            patch(
                "direct_cli.commands.masters._with_session",
                side_effect=_with_session,
            ),
            patch.object(
                browser_masters,
                "update_master",
                side_effect=update or (lambda p, cid, **kw: {"CampaignId": cid}),
            ),
        ]
        if moderation is not None:
            patches.append(
                patch.object(
                    browser_masters,
                    "fetch_master_moderation_statuses",
                    side_effect=moderation,
                )
            )
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            yield

    # --- the issue's headline scenario -------------------------------------

    def test_middle_row_fails_others_still_applied(self):
        """A failing campaign is isolated: the rows around it still save, its
        own row carries an Error, and the command still exits non-zero."""
        saved = []

        def _update(page, campaign_id, **kwargs):
            if campaign_id == 2:
                raise BrowserSessionError("edit page never loaded")
            saved.append(campaign_id)
            return {"CampaignId": campaign_id, "Name": kwargs.get("name")}

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [
                    {"CampaignId": 1, "Name": "one"},
                    {"CampaignId": 2, "Name": "two"},
                    {"CampaignId": 3, "Name": "three"},
                ],
            )
            with self._session(update=_update):
                result = self.runner.invoke(
                    cli, ["masters", "update", "--from-file", plan]
                )

        self.assertEqual(saved, [1, 3])
        self.assertNotEqual(result.exit_code, 0)
        # The report goes to stdout; the non-zero summary goes to stderr.
        payload = json.loads(result.stdout)
        self.assertEqual([row["CampaignId"] for row in payload], [1, 2, 3])
        self.assertNotIn("Error", payload[0])
        self.assertIn("edit page never loaded", payload[1]["Error"])
        self.assertNotIn("Error", payload[2])

    def test_stale_session_retry_does_not_resave_completed_campaign(self):
        """The critical mutation-safety requirement: `_with_session` replays
        the WHOLE operation on BrowserAuthError, so a campaign already saved
        must be skipped rather than saved a second time."""
        saved = []
        raised = {"done": False}

        def _update(page, campaign_id, **kwargs):
            if campaign_id == 2 and not raised["done"]:
                raised["done"] = True
                raise BrowserAuthError("saved session went stale")
            saved.append(campaign_id)
            return {"CampaignId": campaign_id}

        def _with_session(ctx, headful, profile_dir, chrome_profile, fn):
            try:
                return fn(_BatchPacingPage())
            except BrowserAuthError:
                # Same self-heal `_with_session` performs: re-run the WHOLE
                # operation under a fresh session.
                return fn(_BatchPacingPage())

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [{"CampaignId": 1, "Name": "a"}, {"CampaignId": 2, "Name": "b"}],
            )
            with (
                patch(
                    "direct_cli.commands.masters._with_session",
                    side_effect=_with_session,
                ),
                patch.object(browser_masters, "update_master", side_effect=_update),
            ):
                result = self.runner.invoke(
                    cli, ["masters", "update", "--from-file", plan]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(raised["done"])
        # 1 is saved once despite the replay; 2 succeeds on the second pass.
        self.assertEqual(saved, [1, 2])
        self.assertEqual(
            [row["CampaignId"] for row in json.loads(result.output)], [1, 2]
        )

    def test_auth_failure_while_reading_moderation_keeps_saved_row_reported(self):
        """A save that succeeded must never vanish from the report because the
        OPTIONAL moderation read afterwards hit a stale session."""
        saved = []
        reads = {"n": 0}

        def _update(page, campaign_id, **kwargs):
            saved.append(campaign_id)
            return {"CampaignId": campaign_id}

        def _moderation(page, campaign_id):
            reads["n"] += 1
            if reads["n"] == 1:
                raise BrowserAuthError("stale while reading statuses")
            return {"Statuses": ["MODERATION"]}

        def _with_session(ctx, headful, profile_dir, chrome_profile, fn):
            try:
                return fn(_BatchPacingPage())
            except BrowserAuthError:
                # Same self-heal `_with_session` performs: re-run the WHOLE
                # operation under a fresh session.
                return fn(_BatchPacingPage())

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [{"CampaignId": 1, "Name": "a"}, {"CampaignId": 2, "Name": "b"}],
            )
            with (
                patch(
                    "direct_cli.commands.masters._with_session",
                    side_effect=_with_session,
                ),
                patch.object(browser_masters, "update_master", side_effect=_update),
                patch.object(
                    browser_masters,
                    "fetch_master_moderation_statuses",
                    side_effect=_moderation,
                ),
            ):
                result = self.runner.invoke(
                    cli,
                    [
                        "masters",
                        "update",
                        "--from-file",
                        plan,
                        "--moderation-statuses",
                    ],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(saved, [1, 2])
        payload = json.loads(result.output)
        self.assertEqual([row["CampaignId"] for row in payload], [1, 2])
        # Campaign 1 was saved but its statuses could not be read -- say so
        # explicitly instead of omitting the key.
        self.assertIn("not read", payload[0]["ModerationStatuses"])
        self.assertEqual(payload[1]["ModerationStatuses"], {"Statuses": ["MODERATION"]})

    # --- one session, paced ------------------------------------------------

    def test_whole_plan_runs_in_one_session_paced_between_campaigns(self):
        sessions = {"n": 0}

        page = _BatchPacingPage()

        def _with_session(ctx, headful, profile_dir, chrome_profile, fn):
            sessions["n"] += 1
            return fn(page)

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp, [{"CampaignId": cid, "Name": "x"} for cid in (1, 2, 3)]
            )
            with (
                patch(
                    "direct_cli.commands.masters._with_session",
                    side_effect=_with_session,
                ),
                patch.object(
                    browser_masters,
                    "update_master",
                    side_effect=lambda p, cid, **kw: {"CampaignId": cid},
                ),
            ):
                result = self.runner.invoke(
                    cli,
                    ["masters", "update", "--from-file", plan, "--pacing-ms", "250"],
                )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(sessions["n"], 1)
        # Paced BETWEEN campaigns only -- no trailing pause after the last one.
        self.assertEqual(page.waits, [250, 250])

    def test_pacing_still_applied_after_a_failed_campaign(self):
        """Issue #829's lesson is about how often the profile hits Yandex; a
        row that failed still navigated there, so it must be paced too."""

        page = _BatchPacingPage()

        def _update(page_, campaign_id, **kwargs):
            if campaign_id == 2:
                raise PlaywrightError("boom")
            return {"CampaignId": campaign_id}

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp, [{"CampaignId": cid, "Name": "x"} for cid in (1, 2, 3)]
            )
            with self._session(update=_update, page=page):
                self.runner.invoke(
                    cli,
                    ["masters", "update", "--from-file", plan, "--pacing-ms", "100"],
                )

        self.assertEqual(page.waits, [100, 100])

    # --- dry-run -----------------------------------------------------------

    def test_dry_run_reports_plan_without_opening_a_browser(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [
                    {
                        "CampaignId": 713234064,
                        "Headlines": {"1": "Новый заголовок"},
                        "ClearTexts": [2],
                        "Devices": ["mobile", "desktop"],
                        "AgeTo": "unlimited",
                    }
                ],
            )
            with patch(
                "direct_cli.commands.masters._with_session",
                side_effect=AssertionError("dry-run must not open a session"),
            ):
                result = self.runner.invoke(
                    cli, ["masters", "update", "--from-file", plan, "--dry-run"]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        # Reported in the PLAN's vocabulary: PascalCase keys, 1-based slots,
        # no internal snake_case or *_requested bookkeeping.
        self.assertEqual(
            payload,
            [
                {
                    "CampaignId": 713234064,
                    "Headlines": {"1": "Новый заголовок"},
                    "ClearTexts": [2],
                    "Devices": ["desktop", "mobile"],
                    "AgeTo": "unlimited",
                }
            ],
        )

    def test_dry_run_validates_local_image_paths_before_any_save(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp, [{"CampaignId": 1, "Images": {"1": "/nope/missing.jpg"}}]
            )
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", plan, "--dry-run"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("Row 1", result.output)
        self.assertIn("missing.jpg", result.output)

    def test_a_bad_last_row_blocks_the_whole_plan_before_the_first_save(self):
        """Validation is plan-wide and up-front, so a typo in the last row
        cannot leave earlier campaigns already mutated."""
        saved = []

        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [
                    {"CampaignId": 1, "Name": "fine"},
                    {"CampaignId": 2, "Images": {"1": "/nope/missing.jpg"}},
                ],
            )
            with self._session(
                update=lambda p, cid, **kw: saved.append(cid) or {"CampaignId": cid}
            ):
                result = self.runner.invoke(
                    cli, ["masters", "update", "--from-file", plan]
                )

        self.assertEqual(result.exit_code, 2)
        self.assertEqual(saved, [])

    def test_single_campaign_dry_run_matches_the_batch_report_shape(self):
        with patch(
            "direct_cli.commands.masters._with_session",
            side_effect=AssertionError("dry-run must not open a session"),
        ):
            result = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "713234064",
                    "--headline",
                    "1=Новый заголовок",
                    "--clear-text",
                    "2",
                    "--device",
                    "mobile",
                    "--device",
                    "desktop",
                    "--age-to",
                    "unlimited",
                    "--dry-run",
                ],
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            json.loads(result.output),
            {
                "CampaignId": 713234064,
                "Headlines": {"1": "Новый заголовок"},
                "ClearTexts": [2],
                "Devices": ["desktop", "mobile"],
                "AgeTo": "unlimited",
            },
        )

    # --- input validation --------------------------------------------------

    def test_malformed_jsonl_line_names_its_row(self):
        with self.runner.isolated_filesystem() as tmp:
            path = Path(tmp) / "plan.jsonl"
            path.write_text(
                '{"CampaignId": 1, "Name": "ok"}\nnot json at all\n', encoding="utf-8"
            )
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", str(path), "--dry-run"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("Row 2", result.output)

    def test_unknown_key_names_the_row_and_lists_allowed_keys(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp,
                [
                    {"CampaignId": 1, "Name": "ok"},
                    {"CampaignId": 2, "Headline": "typo, singular"},
                ],
            )
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", plan, "--dry-run"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("Unknown field 'Headline'", result.output)
        self.assertIn("row 2", result.output)
        self.assertIn("Headlines", result.output)

    def test_typed_values_are_validated_exactly_like_the_single_flags(self):
        """Every check Click gives the flag path (`type=int`, `click.Choice`,
        the slot/position parsers) is re-applied to a JSON value -- otherwise
        the batch surface would be strictly less safe than the flags."""
        cases = [
            ({"CampaignId": 1, "WeeklyBudget": "не-число"}, "WeeklyBudget"),
            ({"CampaignId": 1, "WeeklyBudget": True}, "boolean"),
            ({"CampaignId": 1, "AgeFrom": 999}, "AgeFrom"),
            ({"CampaignId": 1, "Gender": "ZZZ"}, "Gender"),
            ({"CampaignId": 1, "Devices": ["NOPE"]}, "Devices"),
            ({"CampaignId": 1, "Launch": "yes-please"}, "Launch"),
            ({"CampaignId": 1, "AddSitelinks": "garbage"}, "AddSitelinks"),
            ({"CampaignId": 1, "Headlines": {"99": "x"}}, "out of range"),
            ({"CampaignId": 1, "Headlines": {"1": "   "}}, "non-empty"),
            ({"CampaignId": 1, "RemoveSitelinks": [1, 1]}, "more than once"),
            ({"CampaignId": "713", "Name": "x"}, "CampaignId"),
            ({"CampaignId": 1}, "at least one update field"),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                result = self.runner.invoke(
                    cli,
                    [
                        "masters",
                        "update",
                        "--masters-json",
                        json.dumps([row]),
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("Row 1", result.output)
                self.assertIn(expected, result.output)

    def test_slot_numbers_are_1_based_in_both_modes(self):
        """A plan is usually written by transcribing the equivalent flags, so
        the same number must mean the same slot in either mode."""
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(tmp, [{"CampaignId": 1, "Headlines": {"1": "first"}}])
            captured = {}
            with self._session(
                update=lambda p, cid, **kw: captured.update(kw) or {"CampaignId": cid}
            ):
                result = self.runner.invoke(
                    cli, ["masters", "update", "--from-file", plan]
                )

        self.assertEqual(result.exit_code, 0, result.output)
        # Slot 1 in the plan is index 0 for the browser layer -- the same
        # translation `--headline "1=first"` performs.
        self.assertEqual(captured["headlines"], {0: "first"})

    def test_cross_field_conflicts_are_rejected_per_row(self):
        cases = [
            (
                {"CampaignId": 1, "Headlines": {"1": "a"}, "ClearHeadlines": [1]},
                "not both",
            ),
            (
                {
                    "CampaignId": 1,
                    "PromotionGoal": "max-clicks",
                    "AddTargetActions": {"5": 1.0},
                },
                "max-clicks",
            ),
            (
                {
                    "CampaignId": 1,
                    "PromotionGoal": "max-conversions",
                    "GoalPrice": 10.0,
                },
                "max-conversions",
            ),
            (
                {
                    "CampaignId": 1,
                    "TargetActionPrices": {"5": 1.0},
                    "RemoveTargetActionGoalIds": [5],
                },
                "Goal 5",
            ),
        ]
        for row, expected in cases:
            with self.subTest(row=row):
                result = self.runner.invoke(
                    cli,
                    [
                        "masters",
                        "update",
                        "--masters-json",
                        json.dumps([row]),
                        "--dry-run",
                    ],
                )
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn(expected, result.output)

    def test_duplicate_campaign_id_is_rejected(self):
        """Two rows for one campaign would mean two saves, and completion is
        tracked per campaign id -- so it is also the one input that could make
        a retry skip a row that never ran."""
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(
                tmp, [{"CampaignId": 1, "Name": "a"}, {"CampaignId": 1, "Name": "b"}]
            )
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", plan, "--dry-run"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("rows 1 and 2", result.output)

    def test_empty_plan_is_rejected_in_both_batch_forms(self):
        with self.runner.isolated_filesystem() as tmp:
            path = Path(tmp) / "plan.jsonl"
            path.write_text("\n\n", encoding="utf-8")
            from_file = self.runner.invoke(
                cli, ["masters", "update", "--from-file", str(path), "--dry-run"]
            )
        inline = self.runner.invoke(
            cli, ["masters", "update", "--masters-json", "[]", "--dry-run"]
        )

        self.assertEqual(from_file.exit_code, 2)
        self.assertIn("no campaign rows", from_file.output)
        self.assertEqual(inline.exit_code, 2)
        self.assertIn("no campaign rows", inline.output)

    # --- mode exclusivity, mirroring `keywords add` -------------------------

    def test_modes_are_mutually_exclusive(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(tmp, [{"CampaignId": 1, "Name": "a"}])
            both_batch = self.runner.invoke(
                cli,
                [
                    "masters",
                    "update",
                    "--from-file",
                    plan,
                    "--masters-json",
                    '[{"CampaignId": 2, "Name": "b"}]',
                ],
            )
            id_and_file = self.runner.invoke(
                cli, ["masters", "update", "1", "--from-file", plan]
            )
        neither = self.runner.invoke(cli, ["masters", "update"])

        for result in (both_batch, id_and_file):
            self.assertEqual(result.exit_code, 2, result.output)
            self.assertIn("mutually exclusive", result.output)
        self.assertEqual(neither.exit_code, 2)
        self.assertIn("Provide exactly one of", neither.output)

    def test_single_item_flags_are_refused_in_batch_mode(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(tmp, [{"CampaignId": 1, "Name": "a"}])
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", plan, "--name", "x"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("--name", result.output)
        self.assertIn("single-item mode", result.output)

    def test_batch_mode_requires_json_format(self):
        with self.runner.isolated_filesystem() as tmp:
            plan = self._plan(tmp, [{"CampaignId": 1, "Name": "a"}])
            result = self.runner.invoke(
                cli, ["masters", "update", "--from-file", plan, "--format", "table"]
            )

        self.assertEqual(result.exit_code, 2)
        self.assertIn("batch mode", result.output)

    def test_batch_only_flags_are_refused_in_single_mode(self):
        for flag in (["--moderation-statuses"], ["--pacing-ms", "500"]):
            with self.subTest(flag=flag):
                result = self.runner.invoke(
                    cli, ["masters", "update", "1", "--name", "x", *flag]
                )
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertIn("batch mode", result.output)

    def test_every_batch_key_mirrors_a_single_campaign_flag(self):
        """Guard against the two surfaces drifting: a field added to one mode
        and not the other is silent data loss in a plan file."""
        from direct_cli.commands.masters import (
            _UPDATE_FILE_FIELD_FLAGS,
            _UPDATE_FILE_FIELDS,
        )

        batch_keys = set(_UPDATE_FILE_FIELDS) - {"CampaignId"}
        self.assertEqual(batch_keys, set(_UPDATE_FILE_FIELD_FLAGS))

        update_command = cli.commands["masters"].commands["update"]
        declared = {opt for param in update_command.params for opt in param.opts}
        for key, flag in _UPDATE_FILE_FIELD_FLAGS.items():
            with self.subTest(key=key):
                self.assertIn(flag, declared)

        # ...and every mirrored key must actually reach `update_master`.
        browser_kwargs = set(
            inspect.signature(browser_masters.update_master).parameters
        )
        for key, target in _UPDATE_FILE_FIELDS.items():
            if key == "CampaignId":
                continue
            with self.subTest(key=key):
                self.assertIn(target, browser_kwargs)


if __name__ == "__main__":
    unittest.main()

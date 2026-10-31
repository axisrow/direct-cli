"""
Support chat (переписка со службой поддержки) — browser-backed, issue #897.

Yandex Direct has no API for its support: the chat in the UI's right panel is
a Yandex Messenger widget (an iframe of ``yandex.ru/chat`` carrying the
support account's GUID as ``unreadCounterOtherGuid``), and the very same
private chat opens full-page in the Messenger web client at
``https://telemost.yandex.ru/user/<guid>``. Live recon on 2026-10-30 found:

* the page talks over a binary WebSocket (Xiva push, MessagePack frames), not
  over a JSON API that could be replayed the way ``change_history.py`` and
  ``masters.py`` replay Direct's GraphQL calls — decoding that protocol would
  mean reverse-engineering Messenger's bundle, so this module reads the
  rendered DOM instead, the one place the chat is already in plain text;
* every message is an ``<article class="message" aria-posinset=N>``, ``N``
  being the message's sequence number (large and consecutive — thousands, not
  1-based in practice); the user's own bubbles carry ``yamb-message-*_own``
  classes; a day's date separator ("16 июля", no year) is rendered inside the
  first message of that day; only ~10-16 articles exist at a time;
* the list is Yandex's custom virtualized ``ui-InfiniteList``: its scroll
  container is ``overflow: hidden`` and ``scrollTop`` stays 0, so the list is
  driven by the mouse wheel over it, which also loads older history.

The composer is a ``div.ProseMirror`` (``contenteditable``, no ``role``, so
``_find_composer`` lands on the ``[contenteditable="true"]`` selector). An
empty one reports its placeholder ("Сообщение…") as real ``innerText``, so
check the text typed into it, not its emptiness. Enter sends: confirmed by one
live ``send`` on 2026-10-30. A mismatch fails loudly with the markup-drift
hint, never with silently empty output.

What the chat means as "conversations", and how ids are derived, lives in
``direct_cli/_support_chat.py`` (pure, calendar-aware logic is kept out of
this package — its clock guard bans ``time``/``datetime``). Every poll
deadline here goes through ``_clock.now()`` and ``page.wait_for_timeout``
(issue #767); the scroll loop is bounded by round counts, not by time.

The bot's request to rate its work carries an inline keyboard: a
``div.yamb-message-buttons`` inside the message's own ``<article>``, one
``<button>`` per label (1-5), which also shows up as a "12345" line of the
article's text (recon of 2026-10-30). ``rate_support`` presses one of them.

Sending a message or a rating is a real, irreversible action on the user's
Yandex account (the text lands with the support team and may open a
request), so ``send_support_message`` and ``rate_support`` never retry and
say so when they cannot confirm delivery. Enter is pressed only after the
composer reads back as exactly the message: a leftover draft, or typing that
missed the composer, must not turn into a wrong message (an Enter over a
focused rating request would even press its first button).
"""

import contextlib
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Tuple

from . import _clock
from .._support_chat import group_threads, is_rating_prompt, parse_messages, summarize
from ..output import print_warning
from .session import (
    BrowserAuthError,
    BrowserSessionError,
    _goto_with_network_retry,
    _stale_marker_hint,
    _wait_for_marker,
    assert_not_captcha,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import date

    from playwright.sync_api import Page

try:  # pragma: no cover - import shape mirrors change_history.py
    from playwright.sync_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - exercised only when playwright is absent
    PlaywrightError = Exception  # type: ignore[assignment,misc]


#: The support account's private chat in the Messenger web client. The GUID is
#: the widget's ``unreadCounterOtherGuid``; ``DIRECT_SUPPORT_CHAT_URL``
#: overrides the whole URL should Yandex serve another account's chat.
CHAT_URL = "https://telemost.yandex.ru/user/840c4ce4-ed25-4c66-a7c7-ba8c001e02d9"
CHAT_URL_ENV = "DIRECT_SUPPORT_CHAT_URL"

_MESSAGE_SELECTOR = "article.message"
_COMPOSER_SELECTORS = (
    '[role="textbox"]',
    '[contenteditable="true"]',
    "textarea",
)

_CHAT_RENDER_TIMEOUT_MS = 30_000
# The list jumps to the newest message after first paint; wheeling before that
# settles fights the auto-scroll.
_CHAT_SETTLE_MS = 2_000
_SCROLL_TICK_MS = 800
# Each round wheels the list up by half the window height — less than the
# list's visible part, so consecutive windows overlap and list virtualization
# skips no message between them (~4-5 messages per step at 1280x720).
_WHEEL_FRACTION = 0.5
_MAX_SCROLL_ROUNDS = 400
# Rounds with nothing new before the history counts as fully loaded (older
# messages arrive asynchronously, one round is sometimes quiet while loading).
_TOP_STALL_ROUNDS = 6
_SEND_CONFIRM_TIMEOUT_MS = 15_000
_SEND_POLL_MS = 500
_COMPOSER_CLICK_TIMEOUT_MS = 10_000

# The inline keyboard under a message: one <button> per answer option.
_KEYBOARD_BUTTONS = ".yamb-message-buttons button"
# The composer's text as typed: a contenteditable reports innerText, a textarea
# (the last fallback in _COMPOSER_SELECTORS) its value.
_COMPOSER_TEXT_JS = "el => el.value ?? el.innerText"

# One record per rendered message. `ownClass` is the BEM "own" modifier on the
# message or any descendant; `ownGeom` (the bubble sits right of the message's
# centre) is the fallback should the class not be spelled as expected.
# `buttons` are the labels of the message's inline keyboard (1-5 on a rating
# request); they also appear in the article's text.
_EXTRACT_JS = r"""
() => {
  const OWN = /(?:^|\s)[\w-]*(?:_|--)own(?![A-Za-z0-9])/;
  const TIME = /\d{1,2}:\d{2}/;
  const classOf = (el) => (typeof el.className === 'string' ? el.className : '');
  return Array.from(document.querySelectorAll('article.message')).map((article) => {
    const position = article.getAttribute('aria-posinset');
    const balloon = article.querySelector('[class*="balloon"]') || article;
    const outer = article.getBoundingClientRect();
    const inner = balloon.getBoundingClientRect();
    const labels = [];
    const stamped = article.querySelectorAll('[aria-label],[title],[datetime]');
    for (const el of [article, ...stamped]) {
      for (const name of ['aria-label', 'title', 'datetime']) {
        const value = el.getAttribute(name);
        if (value && TIME.test(value)) labels.push(value);
      }
    }
    const everything = [article, ...article.querySelectorAll('*')];
    const anchors = Array.from(article.querySelectorAll('a[href]'));
    return {
      seq: position === null ? null : Number(position),
      ownClass: everything.some((el) => OWN.test(classOf(el))),
      ownGeom: inner.left + inner.width / 2 > outer.left + outer.width / 2 + 1,
      lines: article.innerText
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean),
      labels,
      media: Boolean(article.querySelector('img, video, audio, canvas')),
      links: anchors.slice(0, 10).map((a) => a.href),
      buttons: Array.from(article.querySelectorAll('.yamb-message-buttons button'))
        .map((button) => button.innerText.trim())
        .filter(Boolean),
    };
  });
}
"""

# [x, y, window height]: where a message can really be hovered — centre inside
# the window, not clipped by the list's scroller, not covered by an overlay.
# The list's own ancestors are no guide to its visible area: the live chat has
# a zero-height `overflow: hidden` <body> around a `position: fixed` app.
_WHEEL_POINT_JS = r"""
() => {
  const width = window.innerWidth, height = window.innerHeight;
  for (const article of document.querySelectorAll('article.message')) {
    const box = article.getBoundingClientRect();
    const x = box.left + box.width / 2, y = box.top + box.height / 2;
    if (x < 0 || y < 0 || x > width || y > height) continue;
    const hit = document.elementFromPoint(x, y);
    if (hit && article.contains(hit)) return [x, y, height];
  }
  return null;
}
"""


def chat_url() -> str:
    return os.environ.get(CHAT_URL_ENV) or CHAT_URL


def _open_chat(page: "Page", ready_selectors: Tuple[str, ...], what: str) -> None:
    """Navigate to the support chat and wait until ``ready_selectors`` show up.

    ``commit`` + marker polling, like every Yandex SPA in this package: the
    Messenger keeps push connections open, so ``networkidle`` never settles.
    The login/captcha checks run only on failure — a healthy page's HTML is
    not a reliable place to look for login-page strings.
    """
    _goto_with_network_retry(page, chat_url())
    if _wait_for_marker(page, ready_selectors, _CHAT_RENDER_TIMEOUT_MS):
        page.wait_for_timeout(_CHAT_SETTLE_MS)
        return
    assert_not_captcha(page.content())
    if "passport.yandex" in page.url:
        raise BrowserAuthError(
            "Yandex redirected the support chat to its login page: the saved "
            "session is expired or belongs to another account."
        )
    raise BrowserSessionError(
        f"The support chat showed no {what} within "
        f"{_CHAT_RENDER_TIMEOUT_MS // 1000}s (a chat nobody has written in "
        f"looks the same). {_stale_marker_hint()}"
    )


def _merge(raw: Dict[int, Dict[str, Any]], articles: List[Dict[str, Any]]) -> int:
    """Add newly rendered messages to ``raw`` (keyed by sequence number)."""
    added = 0
    for article in articles:
        seq = article.get("seq")
        if not isinstance(seq, (int, float)) or isinstance(seq, bool):
            raise BrowserSessionError(
                "A support chat message has no aria-posinset sequence number, "
                f"so messages cannot be ordered. {_stale_marker_hint()}"
            )
        if int(seq) not in raw:
            raw[int(seq)] = {**article, "seq": int(seq)}
            added += 1
    return added


def _scroll_up(page: "Page") -> None:
    """Wheel the message list up one step and give older history time to load."""
    point = page.evaluate(_WHEEL_POINT_JS)
    if not point:
        raise BrowserSessionError(
            "No support chat message is visible to scroll the list over. "
            f"{_stale_marker_hint()}"
        )
    x, y, height = point
    page.mouse.move(x, y)
    page.mouse.wheel(0, -height * _WHEEL_FRACTION)
    page.wait_for_timeout(_SCROLL_TICK_MS)


def _collect(
    page: "Page",
    today: "date",
    enough: Callable[[List[Dict[str, Any]]], bool],
) -> Tuple[List[Dict[str, Any]], bool]:
    """Scroll the chat up, merging rendered messages, until ``enough`` is true.

    Returns ``(messages, at_top)``: ``at_top`` says the whole history was
    loaded, so the oldest conversation is complete; otherwise it is cut off.
    """
    raw: Dict[int, Dict[str, Any]] = {}
    stalled = 0
    for _ in range(_MAX_SCROLL_ROUNDS):
        added = _merge(raw, page.evaluate(_EXTRACT_JS))
        messages = parse_messages(raw.values(), today)
        if enough(messages):
            return messages, False
        # aria-posinset is 1-based: nothing older than message 1 can exist.
        if raw and min(raw) <= 1:
            return messages, True
        stalled = 0 if added else stalled + 1
        if stalled >= _TOP_STALL_ROUNDS:
            return messages, True
        _scroll_up(page)
    print_warning(
        f"Stopped after {_MAX_SCROLL_ROUNDS} scroll rounds; the chat history "
        "may be longer than what was read."
    )
    return parse_messages(raw.values(), today), False


def fetch_support_threads(
    page: "Page", *, limit: int, today: "date"
) -> List[Dict[str, Any]]:
    """The newest ``limit`` conversations, newest first (``support list``)."""
    _open_chat(page, (_MESSAGE_SELECTOR,), "messages")
    messages, at_top = _collect(
        page, today, lambda found: len(group_threads(found)) > limit
    )
    threads = group_threads(messages)
    if not at_top and len(threads) > 1:
        threads = threads[1:]  # the oldest one is cut off mid-way
    return [summarize(thread) for thread in reversed(threads)][:limit]


def _thread_ready(messages: List[Dict[str, Any]], thread_id: int) -> bool:
    """Whether ``messages`` settle the question "what is conversation N?".

    A conversation's first message is only trustworthy once an older one is
    loaded (the boundary is decided by the previous conversation's closing
    phrase). Two older conversations loaded without a match mean there is no
    such id, so an unknown id does not scroll the whole history.
    """
    threads = group_threads(messages)
    if any(thread[0]["id"] == thread_id for thread in threads[1:]):
        return True
    return sum(1 for thread in threads if thread[0]["id"] < thread_id) >= 2


def fetch_support_thread(
    page: "Page", thread_id: int, *, today: "date"
) -> List[Dict[str, Any]]:
    """Every message of one conversation, oldest first (``support get``)."""
    _open_chat(page, (_MESSAGE_SELECTOR,), "messages")
    messages, at_top = _collect(
        page, today, lambda found: _thread_ready(found, thread_id)
    )
    threads = group_threads(messages)
    if not at_top:
        threads = threads[1:]  # cut off mid-way: its first message is not loaded
    for thread in threads:
        if thread[0]["id"] == thread_id:
            return thread
    known = ", ".join(str(thread[0]["id"]) for thread in reversed(threads))
    raise BrowserSessionError(
        f"No support conversation with id {thread_id}. Ids seen in the "
        f"history that was read (newest first): {known or 'none'}. "
        "Run `direct support list` for the current ones."
    )


def _find_composer(page: "Page") -> Any:
    for selector in _COMPOSER_SELECTORS:
        candidate = page.locator(selector).last
        with contextlib.suppress(PlaywrightError):
            if candidate.count() and candidate.is_visible():
                return candidate
    raise BrowserSessionError(
        "Could not find the message composer in the support chat. "
        f"{_stale_marker_hint()}"
    )


def _numeric_seqs(articles: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    return [
        (int(article["seq"]), article)
        for article in articles
        if isinstance(article.get("seq"), (int, float))
    ]


def _squash(value: str) -> str:
    return " ".join(value.split())


def _wait_until_listed(page: "Page", text: str, newer_than: int) -> int:
    """Poll until a message newer than ``newer_than`` shows ``text``'s first line.

    Returns its sequence number, or 0 if it never appeared.
    """
    needle = " ".join(text.split("\n")[0].split())
    deadline = _clock.now() + _SEND_CONFIRM_TIMEOUT_MS / 1000
    while _clock.now() < deadline:
        for seq, article in _numeric_seqs(page.evaluate(_EXTRACT_JS)):
            shown = " ".join(" ".join(article.get("lines", [])).split())
            if seq > newer_than and needle in shown:
                return seq
        page.wait_for_timeout(_SEND_POLL_MS)
    return 0


def send_support_message(page: "Page", text: str) -> Dict[str, Any]:
    """Type ``text`` into the composer, check it, press Enter, wait until listed.

    NOT idempotent and never retried: a second run sends a second message.
    Enter sends; a newline inside the text is typed as Shift+Enter. Enter is
    pressed only when the composer reads back as exactly ``text``; otherwise
    nothing is sent and the composer is left as it is for the user to clear
    (it may hold their own draft, which is not ours to delete). After Enter
    every failure says so: the message may already be delivered.
    """
    _open_chat(page, _COMPOSER_SELECTORS, "message composer")
    newest = max(
        (seq for seq, _ in _numeric_seqs(page.evaluate(_EXTRACT_JS))), default=0
    )
    composer = _find_composer(page)
    try:
        composer.click(timeout=_COMPOSER_CLICK_TIMEOUT_MS)
        for index, line in enumerate(text.split("\n")):
            if index:
                page.keyboard.press("Shift+Enter")
            if line:
                page.keyboard.type(line)
        typed = composer.evaluate(_COMPOSER_TEXT_JS) or ""
        if _squash(typed) != _squash(text):
            raise BrowserSessionError(
                "The composer does not hold exactly the message to send (it "
                f"reads {len(_squash(typed))} characters instead of "
                f"{len(_squash(text))}): a leftover draft, or the typing did "
                "not reach it. Enter was NOT pressed and nothing was sent; the "
                "composer was left as it is — open the chat and clear it."
            )
        page.keyboard.press("Enter")
    except PlaywrightError as exc:
        raise BrowserSessionError(
            f"Could not type into the support chat composer: {exc}"
        ) from exc
    try:
        seq = _wait_until_listed(page, text, newest)
    except Exception as exc:  # Enter is already pressed: say so, whatever broke
        raise BrowserSessionError(
            "The message was typed and sent with Enter, but reading the chat "
            f"back failed ({exc}). It may or may not have been delivered — "
            "check the chat before retrying."
        ) from exc
    if not seq:
        raise BrowserSessionError(
            "The message was typed and sent with Enter, but it did not show "
            f"up in the chat within {_SEND_CONFIRM_TIMEOUT_MS // 1000}s. It may "
            "or may not have been delivered — check the chat before retrying."
        )
    return {"sent": True, "id": seq, "text": text}


def _wait_for_own_message(
    page: "Page", text: str, newer_than: int, today: "date"
) -> int:
    """Poll until the user's own message newer than ``newer_than`` is ``text``.

    Exact, unlike ``_wait_until_listed``'s substring: a one-digit rating would
    otherwise be "found" in every timestamp. Returns its sequence number, or 0
    if it never appeared. Like ``_wait_until_listed`` it skips a message with no
    ``aria-posinset``: the click is already done, so a bubble the chat renders
    without one must not abort the read-back (it just confirms nothing).
    """
    deadline = _clock.now() + _SEND_CONFIRM_TIMEOUT_MS / 1000
    while _clock.now() < deadline:
        raw: Dict[int, Dict[str, Any]] = {}
        articles = page.evaluate(_EXTRACT_JS)
        _merge(raw, [article for _, article in _numeric_seqs(articles)])
        for message in parse_messages(raw.values(), today):
            if (
                message["id"] > newer_than
                and message["from"] == "me"
                and message["text"] == text
            ):
                return message["id"]
        page.wait_for_timeout(_SEND_POLL_MS)
    return 0


def rate_support(page: "Page", rating: int, *, today: "date") -> Dict[str, Any]:
    """Press button ``rating`` of the bot's pending request to rate its work.

    NOT idempotent and never retried: a rating cannot be changed afterwards.
    Only the newest message counts, and only when it is the bot's rating
    request whose keyboard offers ``rating``; anything else (no request, one
    already answered, a keyboard that is not a rating) is refused before a
    click. The button's own text is read back first, so the digit that is
    sent is the digit that was asked for. After the click every failure says
    the button was pressed: the rating may already be recorded.
    """
    _open_chat(page, (_MESSAGE_SELECTOR,), "messages")
    raw: Dict[int, Dict[str, Any]] = {}
    _merge(raw, page.evaluate(_EXTRACT_JS))
    messages = parse_messages(raw.values(), today)
    newest = messages[-1] if messages else None
    if newest is None or not is_rating_prompt(newest):
        raise BrowserSessionError(
            "No rating request is waiting for an answer: the newest message "
            "in the support chat is not the support's request to rate its "
            "work (it never came, or it was already answered). Nothing was "
            "pressed. If the chat does show such a request, Yandex may have "
            "changed its markup (the answer buttons are read from "
            f"`{_KEYBOARD_BUTTONS}`)."
        )
    label = str(rating)
    buttons = newest.get("buttons", [])
    if label not in buttons:
        raise BrowserSessionError(
            f"The rating request offers no button {label} (it offers: "
            f"{', '.join(buttons) or 'none'}). Nothing was pressed."
        )
    seq = newest["id"]
    button = page.locator(
        f'article.message[aria-posinset="{seq}"] {_KEYBOARD_BUTTONS}'
    ).nth(buttons.index(label))
    try:
        shown = button.inner_text().strip()
        if shown != label:
            raise BrowserSessionError(
                f"The button found for {label} reads {shown!r}; nothing was pressed."
            )
        button.click(timeout=_COMPOSER_CLICK_TIMEOUT_MS)
    except PlaywrightError as exc:
        raise BrowserSessionError(f"Could not press the rating button: {exc}") from exc
    try:
        rated = _wait_for_own_message(page, label, seq, today)
    except Exception as exc:  # the button is already pressed: say so, whatever broke
        raise BrowserSessionError(
            f"Button {label} was pressed, but reading the chat back failed "
            f"({exc}). It may or may not have been recorded — check the chat "
            "before retrying."
        ) from exc
    if not rated:
        raise BrowserSessionError(
            f"Button {label} was pressed, but the rating did not show up in "
            f"the chat within {_SEND_CONFIRM_TIMEOUT_MS // 1000}s. It may or "
            "may not have been recorded — check the chat before retrying."
        )
    return {"rated": True, "id": rated, "rating": rating}

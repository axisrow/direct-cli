# The Page fake implements only the Playwright surface the code calls
# (narrower signatures) and exposes test-only attributes.
# pyright: reportIncompatibleMethodOverride=false, reportAttributeAccessIssue=false
"""
Tests for `direct support` — the Yandex Messenger support chat (issue #897).

Everything here is offline: ``FakePage`` replays scripted snapshots of the
chat's rendered messages (what ``_EXTRACT_JS`` would return at each wheel
step), so the scroll/merge loop, the conversation heuristics and the CLI run
without a browser. The messages are synthetic — the markup they mimic
(`aria-posinset`, BEM ``own`` modifier, ``HH:MM`` lines, date separators)
comes from the 2026-10-30 recon and live read-only check, so the raw shape is
written out by ``art`` in one place.

The fake clock below is mandatory, not decoration: the poll loops read their
deadline from ``_clock.now()`` and tick with ``page.wait_for_timeout``, which
is a no-op here (issue #767).
"""

import datetime
import json
import re
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from direct_cli import _support_chat as chat
from direct_cli.browser import _clock, support
from direct_cli.browser.session import (
    BrowserAuthError,
    BrowserCaptchaError,
    BrowserSessionError,
)
from direct_cli.cli import _NO_CREDENTIALS_GROUPS, cli

if TYPE_CHECKING:
    from playwright.sync_api import Page as _PageBase
else:
    _PageBase = object

TODAY = datetime.date(2026, 10, 30)
_COMPOSER = '[contenteditable="true"]'
_NOW = [0.0]
WHEEL_POINT = [500, 300, 700]  # x, y of a visible message; the window's height


@pytest.fixture(autouse=True)
def fake_clock():
    _NOW[0] = 0.0
    previous = _clock.set_clock(lambda: _NOW[0])
    yield
    _clock.set_clock(previous)


def art(
    seq, *lines, own=False, labels=(), media=False, links=(), geom=None, buttons=()
):
    """One raw record, in the shape ``_EXTRACT_JS`` returns per message."""
    return {
        "seq": seq,
        "ownClass": own,
        "ownGeom": own if geom is None else geom,
        "lines": list(lines),
        "labels": list(labels),
        "media": media,
        "links": list(links),
        "buttons": list(buttons),
    }


def msg(seq, sender, text):
    return {"id": seq, "from": sender, "date": None, "time": None, "text": text}


CLOSING = "Напишите нам, если вопрос ещё актуален."


def chat_history(offset=0):
    """Three conversations: ids 1, 5 and 8 (+ offset), the first two closed."""
    n = offset
    return [
        art(
            n + 1,
            "6 октября 2025 г.",
            "Первый вопрос",
            "10:00",
            own=True,
        ),
        art(n + 2, "Яндекс Директ", "Это бот поддержки Яндекс Директа", "10:01"),
        art(n + 3, CLOSING, "10:30"),
        art(n + 4, "5", "10:31", own=True),
        art(n + 5, "7 октября 2025 г.", "Второй вопрос", "09:00", own=True),
        art(n + 6, "Яндекс Директ", "Ответ оператора", "09:10"),
        art(n + 7, CLOSING, "09:40"),
        art(n + 8, "Третий вопрос", "12:00", own=True),
        art(n + 9, "Это бот поддержки Яндекс Директа", "12:01"),
    ]


def windows(history, *spans):
    """Snapshots of a virtualized list: ``spans`` are inclusive seq ranges."""
    return [[a for a in history if lo <= a["seq"] <= hi] for lo, hi in spans]


class FakeKeyboard:
    def __init__(self, page):
        self.page = page
        self.actions = []

    def type(self, text):  # noqa: A003 - mirrors Playwright's Keyboard.type
        self.actions.append(("type", text))
        if self.page.typing_works:
            self.page.draft[-1] += text

    def press(self, key):
        self.actions.append(("press", key))
        if key == "Shift+Enter":
            self.page.draft.append("")
        elif key == "Enter":
            self.page.submit()


class FakeMouse:
    """A wheel up reveals the next (older) snapshot; the last one is the top."""

    def __init__(self, page):
        self.page = page
        self.moves = []
        self.wheels = []

    def move(self, x, y):
        self.moves.append((x, y))

    def wheel(self, delta_x, delta_y):
        self.wheels.append((delta_x, delta_y))
        if delta_y < 0:
            self.page.depth = min(self.page.depth + 1, len(self.page.snapshots) - 1)


def _keyboard_seq(selector):
    """The message a keyboard-button selector points at."""
    found = re.search(r'aria-posinset="(\d+)"', selector)
    assert found, selector
    return int(found.group(1))


class FakeLocator:
    def __init__(self, page, selector, index=None):
        self.page = page
        self.selector = selector
        self.index = index  # set by nth(): one button of a message's keyboard

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def nth(self, index):
        return FakeLocator(self.page, self.selector, index)

    def count(self):
        return 1 if self.selector in self.page.present else 0

    def is_visible(self):
        return self.selector in self.page.present

    def inner_text(self):
        return self.page.button_labels(self.selector)[self.index]

    def evaluate(self, script, arg=None):
        assert script is support._COMPOSER_TEXT_JS
        return "\n".join(self.page.draft)

    def click(self, timeout=None):
        if self.index is None:
            self.page.clicked.append(self.selector)
        else:
            self.page.press_button(self.selector, self.index)


class FakePage(_PageBase):
    def __init__(
        self,
        snapshots,
        *,
        composer=True,
        deliver=True,
        url="https://telemost.yandex.ru/user/x",
        html="<html></html>",
        visible=True,
        draft=None,
        typing_works=True,
        dom_buttons=None,
        echo=None,
        after_press=(),
        fail_after_press=None,
    ):
        self.snapshots = snapshots
        self.depth = 0
        self.present = {"article.message"} if snapshots and snapshots[0] else set()
        if composer:
            self.present.add(_COMPOSER)
        self.deliver = deliver
        self.url = url
        self._html = html
        self.visible = visible
        self.navigated_to = []
        self.goto_wait_until = None
        self.sent = []
        self.draft = list(draft) if draft else [""]  # text already in the composer
        self.typing_works = typing_works  # False: typing never reaches the composer
        self.dom_buttons = dom_buttons  # the keyboard's real DOM order, if it differs
        self.echo = echo  # what the chat shows after a button press, if not its label
        self.after_press = list(after_press)  # extra raw articles a press renders
        # what reading the chat raises once a button or Enter was pressed
        self.fail_after_press = fail_after_press
        self.clicked = []
        self.pressed = []  # (message seq, button index) of every keyboard press
        self.keyboard = FakeKeyboard(self)
        self.mouse = FakeMouse(self)

    def goto(self, url, wait_until=None, timeout=None):
        self.navigated_to.append(url)
        self.goto_wait_until = wait_until

    def content(self):
        return self._html

    def locator(self, selector):
        return FakeLocator(self, selector)

    def wait_for_timeout(self, ms):
        _NOW[0] += ms / 1000

    def current(self):
        return (self.snapshots[self.depth] if self.snapshots else []) + self.sent

    def submit(self):
        if self.deliver:
            seqs = [a["seq"] for a in self.current() if a["seq"] is not None]
            lines = [line for line in self.draft if line]
            self.sent.append(art(max(seqs, default=0) + 1, *lines, own=True))
        self.draft = [""]

    def button_labels(self, selector):
        article = next(a for a in self.current() if a["seq"] == _keyboard_seq(selector))
        return list(self.dom_buttons or article["buttons"])

    def press_button(self, selector, index):
        label = self.button_labels(selector)[index]
        self.pressed.append((_keyboard_seq(selector), index))
        if self.deliver:
            seqs = [a["seq"] for a in self.current() if a["seq"] is not None]
            self.sent.append(
                art(max(seqs, default=0) + 1, self.echo or label, own=True)
            )
        self.sent.extend(self.after_press)

    def evaluate(self, script, arg=None):
        if script is support._EXTRACT_JS:
            if self.fail_after_press and (
                self.pressed or ("press", "Enter") in self.keyboard.actions
            ):
                raise self.fail_after_press
            return self.current()
        assert script is support._WHEEL_POINT_JS
        return WHEEL_POINT if self.visible else None


# ---------------------------------------------------------------- parsing


def test_parse_strips_author_and_stamp_and_reads_separator_date():
    [message] = chat.parse_messages(
        [art(10, "6 октября 2025 г.", "Яндекс Директ", "Здравствуйте!", "22:37")],
        TODAY,
    )

    assert message == {
        "id": 10,
        "from": "support",
        "date": "2025-10-06",
        "time": "22:37",
        "text": "Здравствуйте!",
    }


def test_date_separator_applies_to_following_messages_until_the_next():
    first, second, third = chat.parse_messages(
        [
            art(1, "6 октября 2025 г.", "привет", "10:00", own=True),
            art(2, "ответ", "10:05"),
            art(3, "Вчера", "ещё", "09:00", own=True),
        ],
        TODAY,
    )

    assert (first["date"], second["date"], third["date"]) == (
        "2025-10-06",
        "2025-10-06",
        "2026-10-29",
    )
    assert second["from"] == "support" and first["from"] == "me"


def test_label_with_day_and_month_wins_and_year_is_inferred():
    article = art(5, "текст", labels=["22:37 15 июля"])

    [this_year] = chat.parse_messages([article], TODAY)
    [last_year] = chat.parse_messages([article], datetime.date(2026, 3, 1))

    assert (this_year["date"], this_year["time"]) == ("2026-07-15", "22:37")
    assert last_year["date"] == "2025-07-15"


def test_time_mentioned_inside_text_is_not_a_stamp():
    [message] = chat.parse_messages(
        [art(1, "созвонимся в 10:30", "11:00", own=True)], TODAY
    )

    assert message["text"] == "созвонимся в 10:30"
    assert message["time"] == "11:00"


def test_ownership_uses_the_class_and_falls_back_to_bubble_position():
    by_class = chat.parse_messages(
        [art(1, "a", own=True, geom=False), art(2, "b", own=False, geom=True)], TODAY
    )
    by_position = chat.parse_messages(
        [
            {**art(1, "a"), "ownGeom": True},
            {**art(2, "b"), "ownGeom": False},
        ],
        TODAY,
    )

    assert [m["from"] for m in by_class] == ["me", "support"]
    assert [m["from"] for m in by_position] == ["me", "support"]


def test_attachments_are_kept_only_when_present():
    plain, rich = chat.parse_messages(
        [art(1, "a"), art(2, "b", media=True, links=["https://example.test/f"])],
        TODAY,
    )

    assert "media" not in plain and "links" not in plain
    assert rich["media"] is True and rich["links"] == ["https://example.test/f"]


# ----------------------------------------------------------- conversations


def test_closing_phrase_ends_a_conversation_and_the_next_question_starts_one():
    threads = chat.group_threads(
        [
            msg(1, "me", "вопрос"),
            msg(2, "support", "Это бот поддержки"),
            msg(3, "support", CLOSING),
            msg(4, "support", "Оцените ответ"),
            msg(5, "me", "5"),
            msg(6, "support", "Спасибо за оценку"),
            msg(7, "me", "новый вопрос"),
        ]
    )

    assert [[m["id"] for m in t] for t in threads] == [[1, 2, 3, 4, 5, 6], [7]]


@pytest.mark.parametrize("rating", ["1", "👍", "⭐⭐⭐⭐⭐"])
def test_a_rating_reply_stays_in_the_closed_conversation(rating):
    threads = chat.group_threads(
        [msg(1, "me", "q"), msg(2, "support", CLOSING), msg(3, "me", rating)]
    )

    assert len(threads) == 1


def test_support_broadcast_after_closing_does_not_open_a_conversation():
    threads = chat.group_threads(
        [
            msg(1, "me", "q"),
            msg(2, "support", CLOSING),
            msg(3, "support", "Скидка на рекламу"),
            msg(4, "me", "ещё вопрос"),
        ]
    )

    assert [[m["id"] for m in t] for t in threads] == [[1, 2, 3], [4]]


def test_a_chat_without_a_closing_phrase_is_one_conversation():
    threads = chat.group_threads(
        [msg(1, "me", "q"), msg(2, "support", "a"), msg(3, "me", "q2")]
    )

    assert len(threads) == 1


def test_a_rating_ends_a_conversation_without_a_closing_phrase():
    threads = chat.group_threads(
        [
            msg(1, "me", "вопрос"),
            msg(2, "support", "Ответ оператора"),
            msg(3, "support", "Оцените, пожалуйста, нашу работу"),
            msg(4, "me", "5"),
            msg(5, "support", "Спасибо!"),
            msg(6, "me", "другой вопрос"),
        ]
    )

    assert [[m["id"] for m in t] for t in threads] == [[1, 2, 3, 4, 5], [6]]


def test_the_bot_asking_what_went_wrong_keeps_the_conversation_going():
    threads = chat.group_threads(
        [
            msg(1, "me", "вопрос"),
            msg(2, "support", "Оцените, пожалуйста, нашу работу"),
            msg(3, "me", "1"),
            msg(4, "support", "Простите! Расскажите, что пошло не так?"),
            msg(5, "me", "вот что не так"),
            msg(6, "support", "Разберёмся"),
        ]
    )

    assert len(threads) == 1


def test_nudges_do_not_end_a_conversation():
    threads = chat.group_threads(
        [
            msg(1, "me", "вопрос"),
            msg(2, "support", "Готовы помочь и ждем от вас информацию."),
            msg(3, "support", "Мы здесь и готовы помочь."),
            msg(4, "me", "вот информация"),
        ]
    )

    assert len(threads) == 1


def at(message, when):
    """``message`` stamped with ``"YYYY-MM-DD HH:MM"``."""
    day, hour = when.split()
    return {**message, "date": day, "time": hour}


def test_writing_again_after_two_days_of_support_silence_opens_a_conversation():
    threads = chat.group_threads(
        [
            at(msg(1, "me", "вопрос"), "2025-05-05 23:03"),
            at(msg(2, "support", "Ответ"), "2025-05-05 23:46"),
            at(msg(3, "me", "ещё вопрос"), "2025-05-12 09:00"),
        ]
    )

    assert [[m["id"] for m in t] for t in threads] == [[1, 2], [3]]


def test_a_follow_up_within_two_days_or_after_no_answer_stays_in_the_conversation():
    threads = chat.group_threads(
        [
            at(msg(1, "me", "вопрос"), "2025-05-05 23:03"),
            at(msg(2, "support", "Ответ"), "2025-05-06 09:00"),
            at(msg(3, "me", "уточнение"), "2025-05-07 08:00"),
            at(msg(4, "me", "а можно побыстрее?"), "2025-05-20 08:00"),
        ]
    )

    assert len(threads) == 1


def test_summary_previews_the_users_question_and_flags_closed():
    thread = [
        msg(7, "support", "Это бот поддержки"),
        {
            **msg(8, "me", "Почему не открывается кампания\nПодробности ниже"),
            "date": "2025-10-06",
            "time": "10:00",
        },
        {**msg(9, "support", CLOSING), "date": "2025-10-06", "time": "10:30"},
    ]

    summary = chat.summarize(thread)

    assert summary == {
        "id": 7,
        "started": None,
        "updated": "2025-10-06 10:30",
        "status": "closed",
        "messages": 3,
        "preview": "Почему не открывается кампания Подробности ниже",
    }


def test_summary_is_closed_after_a_rating_and_open_when_the_bot_asks_more():
    asked = [
        msg(1, "me", "q"),
        msg(2, "me", "1"),
        msg(3, "support", "Расскажите, что пошло не так?"),
    ]

    assert chat.summarize(asked[:2])["status"] == "closed"
    assert chat.summarize(asked)["status"] == "open"


def test_summary_preview_skips_a_rating_heading_the_loaded_history():
    summary = chat.summarize([msg(1, "me", "5"), msg(2, "me", "реальный вопрос")])

    assert summary["preview"] == "реальный вопрос"


def test_summary_truncates_a_long_preview():
    summary = chat.summarize([msg(1, "me", "я" * 200)])

    assert len(summary["preview"]) == 80 and summary["preview"].endswith("…")
    assert summary["status"] == "open"


# ------------------------------------------------------------ page reading


def test_list_scrolls_up_until_the_requested_conversations_are_complete():
    page = FakePage(windows(chat_history(), (7, 9), (5, 8), (2, 6), (1, 4)))

    rows = support.fetch_support_threads(page, limit=2, today=TODAY)

    # Three conversations were visible after the third window; the oldest is
    # cut off mid-way and dropped, so the newest two come back, newest first.
    assert [row["id"] for row in rows] == [8, 5]
    assert page.depth == 2
    assert rows[1]["started"] == "2025-10-07 09:00"
    assert rows[1]["status"] == "closed" and rows[0]["status"] == "open"


def test_list_reaching_sequence_one_keeps_the_oldest_conversation():
    page = FakePage(windows(chat_history(), (7, 9), (5, 8), (2, 6), (1, 4)))

    rows = support.fetch_support_threads(page, limit=10, today=TODAY)

    assert [row["id"] for row in rows] == [8, 5, 1]
    assert rows[2]["started"] == "2025-10-06 10:00"
    assert rows[2]["preview"] == "Первый вопрос"


def test_list_ends_at_the_top_by_stalling_when_sequence_never_reaches_one():
    history = chat_history(offset=100)
    page = FakePage(windows(history, (107, 109), (105, 108), (101, 106)))

    rows = support.fetch_support_threads(page, limit=10, today=TODAY)

    assert [row["id"] for row in rows] == [108, 105, 101]
    # three windows of news, then _TOP_STALL_ROUNDS quiet rounds before giving up
    assert len(page.mouse.wheels) == 3 + support._TOP_STALL_ROUNDS - 1


def test_a_quiet_round_while_history_loads_does_not_end_the_scroll():
    history = chat_history(offset=100)
    page = FakePage(windows(history, (107, 109), (107, 109), (105, 108), (101, 106)))

    rows = support.fetch_support_threads(page, limit=10, today=TODAY)

    assert [row["id"] for row in rows] == [108, 105, 101]


def test_scrolling_wheels_up_over_a_visible_message():
    page = FakePage(windows(chat_history(offset=100), (107, 109), (105, 108)))

    support.fetch_support_threads(page, limit=2, today=TODAY)

    x, y, height = WHEEL_POINT
    assert page.mouse.moves[0] == (x, y)
    assert page.mouse.wheels[0] == (0, pytest.approx(-height * support._WHEEL_FRACTION))


def test_chat_is_given_time_to_settle_before_it_is_read():
    page = FakePage(windows(chat_history(), (1, 9)))

    support.fetch_support_threads(page, limit=10, today=TODAY)

    assert _NOW[0] >= support._CHAT_SETTLE_MS / 1000


def test_list_warns_when_the_scroll_budget_runs_out(monkeypatch, capsys):
    monkeypatch.setattr(support, "_MAX_SCROLL_ROUNDS", 3)
    page = FakePage(windows(chat_history(offset=100), (107, 109), (105, 108)))

    rows = support.fetch_support_threads(page, limit=10, today=TODAY)

    captured = capsys.readouterr()
    assert "Stopped after 3 scroll rounds" in captured.out + captured.err
    assert rows  # best effort, not an error


def test_get_returns_the_requested_conversation_in_order():
    page = FakePage(windows(chat_history(), (7, 9), (5, 8), (2, 6), (1, 4)))

    thread = support.fetch_support_thread(page, 5, today=TODAY)

    assert [m["id"] for m in thread] == [5, 6, 7]
    assert thread[0]["from"] == "me" and thread[1]["from"] == "support"
    assert thread[0]["text"] == "Второй вопрос"
    assert page.depth == 2  # stopped as soon as an older conversation was seen


def test_get_unknown_id_names_the_ids_it_saw():
    page = FakePage(windows(chat_history(), (7, 9), (5, 8), (2, 6), (1, 4)))

    with pytest.raises(BrowserSessionError) as excinfo:
        support.fetch_support_thread(page, 6, today=TODAY)

    message = str(excinfo.value)
    assert "No support conversation with id 6" in message
    # the oldest loaded conversation is cut off mid-way, so it is not listed
    assert "(newest first): 8, 5." in message
    assert page.depth == 2  # stops once two older conversations are seen


def test_navigation_uses_commit_and_the_configured_url(monkeypatch):
    monkeypatch.delenv(support.CHAT_URL_ENV, raising=False)
    page = FakePage(windows(chat_history(), (1, 9)))
    support.fetch_support_threads(page, limit=10, today=TODAY)
    assert page.navigated_to == [support.CHAT_URL]
    assert page.goto_wait_until == "commit"

    monkeypatch.setenv(support.CHAT_URL_ENV, "https://example.test/chat")
    other = FakePage(windows(chat_history(), (1, 9)))
    support.fetch_support_threads(other, limit=10, today=TODAY)
    assert other.navigated_to == ["https://example.test/chat"]


def test_message_without_a_sequence_number_fails_loudly():
    page = FakePage([[art(None, "no position")]])

    with pytest.raises(BrowserSessionError, match="aria-posinset"):
        support.fetch_support_threads(page, limit=5, today=TODAY)


def test_no_visible_message_to_scroll_over_fails_loudly():
    page = FakePage(windows(chat_history(offset=100), (107, 109)), visible=False)

    with pytest.raises(BrowserSessionError, match="No support chat message is visible"):
        support.fetch_support_threads(page, limit=10, today=TODAY)

    assert page.mouse.wheels == []


def test_login_redirect_is_an_auth_error_not_a_markup_error():
    page = FakePage([], url="https://passport.yandex.ru/auth?retpath=x")

    with pytest.raises(BrowserAuthError):
        support.fetch_support_threads(page, limit=5, today=TODAY)


def test_captcha_page_is_reported_as_captcha():
    page = FakePage([], html="<html>showcaptcha</html>")

    with pytest.raises(BrowserCaptchaError):
        support.fetch_support_threads(page, limit=5, today=TODAY)


def test_empty_chat_reports_markup_hint_instead_of_silent_empty_output():
    page = FakePage([])

    with pytest.raises(BrowserSessionError, match="showed no messages"):
        support.fetch_support_threads(page, limit=5, today=TODAY)


# ---------------------------------------------------------------- sending


def test_send_types_lines_with_shift_enter_and_confirms_delivery():
    page = FakePage(windows(chat_history(), (1, 9)))

    result = support.send_support_message(page, "Первая строка\nВторая строка")

    assert page.keyboard.actions == [
        ("type", "Первая строка"),
        ("press", "Shift+Enter"),
        ("type", "Вторая строка"),
        ("press", "Enter"),
    ]
    assert page.clicked == [_COMPOSER]
    assert result == {"sent": True, "id": 10, "text": "Первая строка\nВторая строка"}


def test_send_works_in_a_chat_with_no_messages_yet():
    page = FakePage([[]])

    result = support.send_support_message(page, "Здравствуйте")

    assert result["sent"] is True and result["id"] == 1


def test_send_that_never_shows_up_is_not_reported_as_sent():
    page = FakePage(windows(chat_history(), (1, 9)), deliver=False)

    with pytest.raises(BrowserSessionError, match="may or may not"):
        support.send_support_message(page, "Здравствуйте")

    assert page.keyboard.actions[-1] == ("press", "Enter")  # tried exactly once


def test_send_failure_after_enter_says_the_message_was_sent():
    page = FakePage(
        windows(chat_history(), (1, 9)),
        fail_after_press=RuntimeError("Execution context was destroyed"),
    )

    with pytest.raises(
        BrowserSessionError,
        match=r"sent with Enter.*Execution context was destroyed.*check the chat",
    ):
        support.send_support_message(page, "Здравствуйте")

    assert page.keyboard.actions.count(("press", "Enter")) == 1  # never retried


def test_send_without_a_composer_fails_before_typing():
    page = FakePage(windows(chat_history(), (1, 9)), composer=False)

    with pytest.raises(BrowserSessionError, match="message composer"):
        support.send_support_message(page, "Здравствуйте")

    assert page.keyboard.actions == []


def test_send_does_not_press_enter_over_a_leftover_draft():
    page = FakePage(windows(chat_history(), (1, 9)), draft=["Недописанный черновик "])

    with pytest.raises(BrowserSessionError, match="does not hold exactly"):
        support.send_support_message(page, "Здравствуйте")

    assert ("press", "Enter") not in page.keyboard.actions
    assert page.sent == []


def test_send_does_not_press_enter_when_the_typing_misses_the_composer():
    page = FakePage(windows(chat_history(), (1, 9)), typing_works=False)

    with pytest.raises(BrowserSessionError, match="does not hold exactly"):
        support.send_support_message(page, "Здравствуйте")

    assert ("press", "Enter") not in page.keyboard.actions
    assert page.sent == []


# ----------------------------------------------------------------- rating

RATING_REQUEST = "Хотим убедиться, что помогли. Оцените, пожалуйста, нашу работу."
KEYBOARD = ("1", "2", "3", "4", "5")


def rating_chat(*, buttons=KEYBOARD, text=RATING_REQUEST):
    """A short chat whose newest message is the bot's request to rate its work.

    The keyboard's labels are part of the article's text too ("12345"), as on
    the live page.
    """
    return [
        art(1, "30 октября", "Почему наложены ограничения?", "15:51", own=True),
        art(2, "Яндекс Директ", "Ответ оператора", "15:54"),
        art(3, text, "15:54", "".join(buttons), buttons=buttons),
    ]


@pytest.mark.parametrize("keyboard_lines", [("12345",), KEYBOARD])
def test_parse_moves_the_keyboard_out_of_the_text(keyboard_lines):
    [message] = chat.parse_messages(
        [art(3, RATING_REQUEST, "15:54", *keyboard_lines, buttons=KEYBOARD)], TODAY
    )

    assert message["text"] == RATING_REQUEST
    assert message["buttons"] == list(KEYBOARD)


def test_a_message_without_a_keyboard_has_no_buttons():
    [message] = chat.parse_messages([art(1, "Привет", "10:00")], TODAY)

    assert "buttons" not in message


def test_only_the_support_asking_for_a_rating_is_a_rating_request():
    assert chat.is_rating_prompt(msg(3, "support", RATING_REQUEST))
    assert not chat.is_rating_prompt(msg(3, "me", RATING_REQUEST))
    assert not chat.is_rating_prompt(msg(3, "support", "Ответ оператора"))


def test_the_rating_request_and_its_answer_close_the_conversation():
    history = rating_chat() + [
        art(4, "5", "15:57", own=True),
        art(5, "Яндекс Директ", "Спасибо!", "15:57"),
    ]

    [thread] = chat.group_threads(chat.parse_messages(history, TODAY))

    assert [m["id"] for m in thread] == [1, 2, 3, 4, 5]
    assert chat.summarize(thread)["status"] == "closed"


def test_rate_presses_the_matching_button_once_and_confirms():
    page = FakePage([rating_chat()])

    result = support.rate_support(page, 4, today=TODAY)

    assert result == {"rated": True, "id": 4, "rating": 4}
    assert page.pressed == [(3, 3)]  # message 3, its fourth button
    assert page.keyboard.actions == []  # nothing typed, Enter never pressed


def test_rate_refuses_when_the_newest_message_is_not_a_rating_request():
    answered = rating_chat() + [
        art(4, "5", "15:57", own=True),
        art(5, "Яндекс Директ", "Спасибо!", "15:57"),
    ]
    page = FakePage([answered])

    with pytest.raises(BrowserSessionError, match="No rating request"):
        support.rate_support(page, 5, today=TODAY)

    assert page.pressed == []


def test_rate_refuses_a_keyboard_that_is_not_a_rating_request():
    page = FakePage([rating_chat(text="Выберите тему обращения")])

    with pytest.raises(BrowserSessionError, match="No rating request"):
        support.rate_support(page, 5, today=TODAY)

    assert page.pressed == []


def test_rate_refuses_a_button_the_request_does_not_offer():
    page = FakePage([rating_chat(buttons=("1", "2", "3"))])

    with pytest.raises(
        BrowserSessionError, match=r"no button 5 \(it offers: 1, 2, 3\)"
    ):
        support.rate_support(page, 5, today=TODAY)

    assert page.pressed == []


def test_rate_reads_the_button_back_before_pressing_it():
    page = FakePage([rating_chat()], dom_buttons=("5", "4", "3", "2", "1"))

    with pytest.raises(BrowserSessionError, match="reads '2'"):
        support.rate_support(page, 4, today=TODAY)

    assert page.pressed == []


def test_rate_that_never_shows_up_is_not_reported_as_rated():
    page = FakePage([rating_chat()], deliver=False)

    with pytest.raises(BrowserSessionError, match="may or may not"):
        support.rate_support(page, 4, today=TODAY)

    assert page.pressed == [(3, 3)]  # pressed exactly once


def test_rate_confirmation_is_the_exact_digit_not_a_substring():
    page = FakePage([rating_chat()], echo="45")

    with pytest.raises(BrowserSessionError, match="may or may not"):
        support.rate_support(page, 4, today=TODAY)


def test_rate_reads_the_press_back_past_a_message_without_a_position():
    # A message with no aria-posinset after the click must not turn a rating
    # that is already sent into an error that reads like nothing happened.
    page = FakePage([rating_chat()], after_press=[art(None, "5", "15:57", own=True)])

    result = support.rate_support(page, 5, today=TODAY)

    assert result == {"rated": True, "id": 4, "rating": 5}
    assert page.pressed == [(3, 4)]  # message 3, its fifth button, pressed once


def test_rate_does_not_take_a_message_without_a_position_for_its_confirmation():
    page = FakePage(
        [rating_chat()],
        deliver=False,
        after_press=[art(None, "5", "15:57", own=True)],
    )

    with pytest.raises(BrowserSessionError, match="may or may not"):
        support.rate_support(page, 5, today=TODAY)

    assert page.pressed == [(3, 4)]


def test_rate_failure_after_the_press_says_the_button_was_pressed():
    page = FakePage(
        [rating_chat()],
        fail_after_press=RuntimeError("Execution context was destroyed"),
    )

    with pytest.raises(
        BrowserSessionError,
        match=r"Button 4 was pressed.*Execution context was destroyed.*check the chat",
    ):
        support.rate_support(page, 4, today=TODAY)

    assert page.pressed == [(3, 3)]  # pressed exactly once, never retried


def test_rate_still_refuses_a_message_without_a_position_before_the_press():
    page = FakePage([rating_chat() + [art(None, "no position")]])

    with pytest.raises(BrowserSessionError, match="aria-posinset"):
        support.rate_support(page, 5, today=TODAY)

    assert page.pressed == []


# -------------------------------------------------------------------- CLI


@pytest.fixture
def session_calls(monkeypatch):
    """Route the browser session to a placeholder page and record the calls."""
    calls = []

    def fake_with_session(ctx, headful, profile_dir, chrome_profile, operation):
        calls.append("session")
        return operation(object())

    monkeypatch.setattr("direct_cli.commands.support._with_session", fake_with_session)
    return calls


def _patch(monkeypatch, name, result):
    seen = {}

    def fake(page, *args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return result

    monkeypatch.setattr(support, name, fake)
    return seen


def test_group_needs_no_api_credentials():
    assert "support" in _NO_CREDENTIALS_GROUPS


def test_list_prints_rows_and_passes_limit_and_today(monkeypatch, session_calls):
    rows = [{"id": 8, "status": "open", "preview": "Третий вопрос"}]
    seen = _patch(monkeypatch, "fetch_support_threads", rows)

    result = CliRunner().invoke(cli, ["support", "list", "--limit", "3"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == rows
    assert seen["kwargs"]["limit"] == 3
    assert isinstance(seen["kwargs"]["today"], datetime.date)


def test_list_rejects_a_non_positive_limit(monkeypatch, session_calls):
    result = CliRunner().invoke(cli, ["support", "list", "--limit", "0"])

    assert result.exit_code == 2 and "--limit" in result.output
    assert session_calls == []


def test_get_passes_the_integer_id(monkeypatch, session_calls):
    seen = _patch(monkeypatch, "fetch_support_thread", [{"id": 5, "text": "x"}])

    result = CliRunner().invoke(cli, ["support", "get", "5"])

    assert result.exit_code == 0, result.output
    assert seen["args"] == (5,)
    assert json.loads(result.output) == [{"id": 5, "text": "x"}]


def test_get_rejects_a_non_numeric_id(session_calls):
    result = CliRunner().invoke(cli, ["support", "get", "abc"])

    assert result.exit_code == 2
    assert session_calls == []


def test_send_dry_run_shows_the_request_and_opens_no_session(session_calls):
    result = CliRunner().invoke(
        cli, ["support", "send", "--message", "  привет  ", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"chat": support.CHAT_URL, "message": "привет"}
    assert session_calls == []


def test_send_without_a_terminal_requires_yes(session_calls):
    result = CliRunner().invoke(cli, ["support", "send", "--message", "привет"])

    assert result.exit_code == 2 and "--yes" in result.output
    assert session_calls == []


def test_send_with_yes_sends_the_trimmed_text(monkeypatch, session_calls):
    sent = {"sent": True, "id": 10, "text": "привет"}
    seen = _patch(monkeypatch, "send_support_message", sent)

    result = CliRunner().invoke(
        cli, ["support", "send", "--message", " привет ", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert seen["args"] == ("привет",)
    assert json.loads(result.output) == sent


def test_send_declined_at_the_prompt_sends_nothing(monkeypatch, session_calls):
    monkeypatch.setattr(
        "direct_cli.commands.support._stdin_is_interactive", lambda: True
    )
    seen = _patch(monkeypatch, "send_support_message", {})

    result = CliRunner().invoke(
        cli, ["support", "send", "--message", "привет"], input="n\n"
    )

    assert result.exit_code == 1
    assert session_calls == [] and seen == {}


def test_send_confirmed_at_the_prompt_sends(monkeypatch, session_calls):
    monkeypatch.setattr(
        "direct_cli.commands.support._stdin_is_interactive", lambda: True
    )
    _patch(monkeypatch, "send_support_message", {"sent": True})

    result = CliRunner().invoke(
        cli, ["support", "send", "--message", "привет"], input="y\n"
    )

    assert result.exit_code == 0, result.output
    assert session_calls == ["session"]


def test_send_rejects_an_empty_message(session_calls):
    result = CliRunner().invoke(cli, ["support", "send", "--message", "   ", "--yes"])

    assert result.exit_code == 2 and "--message" in result.output
    assert session_calls == []


def test_rate_dry_run_shows_the_request_and_opens_no_session(session_calls):
    result = CliRunner().invoke(cli, ["support", "rate", "5", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"chat": support.CHAT_URL, "rating": 5}
    assert session_calls == []


@pytest.mark.parametrize("value", ["0", "6", "abc"])
def test_rate_rejects_a_rating_outside_one_to_five(session_calls, value):
    result = CliRunner().invoke(cli, ["support", "rate", value, "--yes"])

    assert result.exit_code == 2
    assert session_calls == []


def test_rate_without_a_terminal_requires_yes(session_calls):
    result = CliRunner().invoke(cli, ["support", "rate", "5"])

    assert result.exit_code == 2 and "--yes" in result.output
    assert session_calls == []


def test_rate_with_yes_presses_the_rating(monkeypatch, session_calls):
    rated = {"rated": True, "id": 4, "rating": 4}
    seen = _patch(monkeypatch, "rate_support", rated)

    result = CliRunner().invoke(cli, ["support", "rate", "4", "--yes"])

    assert result.exit_code == 0, result.output
    assert seen["args"] == (4,)
    assert isinstance(seen["kwargs"]["today"], datetime.date)
    assert json.loads(result.output) == rated


def test_rate_declined_at_the_prompt_presses_nothing(monkeypatch, session_calls):
    monkeypatch.setattr(
        "direct_cli.commands.support._stdin_is_interactive", lambda: True
    )
    seen = _patch(monkeypatch, "rate_support", {})

    result = CliRunner().invoke(cli, ["support", "rate", "4"], input="n\n")

    assert result.exit_code == 1
    assert session_calls == [] and seen == {}

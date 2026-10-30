"""
Pure parsing of the Yandex Direct support chat (issue #897).

The support "correspondence" is not a Direct API resource. It is a private
chat with the «Яндекс Директ» account in Yandex Messenger: the chat widget in
the Direct UI is an iframe of ``yandex.ru/chat``, and the same chat opens in
the Messenger web client (see ``direct_cli/browser/support.py`` for how the
page is read). It is ONE continuous chat — Yandex keeps no ticket ids — so a
"conversation" here is inferred, not read:

* ``id`` of a conversation is the sequence number (``aria-posinset``) of its
  first message, which is stable because the chat only ever appends;
* a conversation ends when the support bot auto-closes the request
  (``CLOSE_MARKERS``) or when the user rates it — the bot asks for a rating
  at the end of every request and the answer is a bare digit or an emoji. A
  low rating makes the bot ask what went wrong (``REOPEN_MARKERS``) and the
  dialog goes on in the same conversation. The user's next real message after
  the end opens a new one;
* not every request is rated or auto-closed, so silence ends one too: the
  user writing again more than ``NEW_TOPIC_GAP`` after the last support
  message opens a new conversation. Nudges ("Готовы помочь и ждем от вас…")
  do not end anything, and broadcasts from the «Яндекс Директ» account (promo
  mailings) are plain support messages that attach to the conversation they
  arrive in;
* a chat with none of these signals is a single conversation.

The bot's request to rate its work carries an inline keyboard (buttons 1-5).
Those labels are controls, not text: ``parse_messages`` returns them as
``buttons`` instead of leaving a "12345" line in ``text``, and ``support
rate`` (``direct_cli/browser/support.py``) presses one.

This module is free of Playwright and of any clock of its own: it turns the
raw per-message records the page reader extracts into messages and
conversations, and ``today`` is always passed in. (``direct_cli/browser/``
may not read the calendar at all — see ``tests/test_masters.py``'s clock
guard — which is why this logic lives outside that package.)
"""

import re
from datetime import date, datetime, timedelta
from functools import reduce
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Display name of the support account; it heads every run of its messages.
SUPPORT_NAME = "Яндекс Директ"

#: Sentences with which the bot closes a request, compared after ``_norm``.
CLOSE_MARKERS = ("напишите нам, если вопрос еще актуален",)

#: The bot's reaction to a low rating ("Расскажите, что пошло не так?"): the
#: request is not over, the user is expected to go on.
REOPEN_MARKERS = ("что пошло не так",)

#: The bot's request to rate its work ("Хотим убедиться, что помогли. Оцените,
#: пожалуйста, нашу работу."), compared after ``_norm``.
RATING_MARKERS = ("оцените",)

#: Silence after the last support message beyond which the user's next message
#: is a new request even though nothing closed the previous one.
NEW_TOPIC_GAP = timedelta(days=2)

_PREVIEW_CHARS = 80
# A rating reply is a lone digit or a few emoji — never a word.
_MAX_RATING_CHARS = 6

_MONTH_NAMES = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, start=1)}
_RELATIVE_DAYS = {"сегодня": 0, "вчера": 1}

# The year is omitted for the current one ("15 июля") and spelled out for
# earlier ones ("6 октября 2025 г.").
_DATE_SRC = r"(\d{1,2})\s+(" + "|".join(_MONTH_NAMES) + r")(?:\s+(\d{4})(?:\s*г\.?)?)?"
_DATE_RE = re.compile(_DATE_SRC, re.IGNORECASE)
_DATE_LINE_RE = re.compile("^" + _DATE_SRC + "$", re.IGNORECASE)
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

Stamp = Tuple[Optional[date], str]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold().replace("ё", "е")


def _make_date(
    day: str, month: str, year: Optional[str], today: date
) -> Optional[date]:
    """A date from its parts; without a year, the latest one not after today."""
    number = _MONTHS[month.lower()]
    for candidate in [int(year)] if year else [today.year, today.year - 1]:
        try:
            found = date(candidate, number, int(day))
        except ValueError:
            continue
        if year or found <= today:
            return found
    return None


def _date_separator(line: str, today: date) -> Optional[date]:
    """The day a date-separator line announces, or None if it is not one."""
    relative = _RELATIVE_DAYS.get(_norm(line))
    if relative is not None:
        return today - timedelta(days=relative)
    match = _DATE_LINE_RE.match(line)
    if match is None:
        return None
    day, month, year = match.groups()
    return _make_date(day, month, year, today)


def _stamp(text: str, today: date, *, whole_line: bool) -> Optional[Stamp]:
    """``(date or None, "HH:MM")`` read from a message time label.

    ``whole_line`` is for visible text: the line must consist of the label
    alone ("22:37", "22:37 15 июля"), otherwise a message that merely
    mentions a time ("созвонимся в 10:30") would be eaten. Attribute values
    (``title``/``aria-label``) are labels by nature and are searched.
    """
    time_match = _TIME_RE.search(text)
    if time_match is None:
        return None
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    if hour > 23 or minute > 59:
        return None
    date_match = _DATE_RE.search(text)
    if whole_line:
        rest = text
        for found in (time_match, date_match):
            if found:
                rest = rest.replace(found.group(0), " ", 1)
        if rest.strip(" ,вг."):
            return None
    stamp_date = None
    if date_match:
        day, month, year = date_match.groups()
        stamp_date = _make_date(day, month, year, today)
    return stamp_date, f"{hour:02d}:{minute:02d}"


def parse_messages(
    raw_articles: Iterable[Dict[str, Any]], today: date
) -> List[Dict[str, Any]]:
    """Turn the page reader's raw per-message records into chat messages.

    Each raw record carries ``seq`` (``aria-posinset``), ``lines`` (the
    visible text split by line), ``labels`` (time-bearing attribute values),
    the two ownership signals ``ownClass``/``ownGeom``, ``media``, ``links``
    and ``buttons`` (the labels of an inline keyboard, whose text also shows
    up among ``lines``). Messages come back oldest first as ``{id, from,
    date, time, text}`` (+ ``media``/``links``/``buttons`` when present);
    ``from`` is ``me`` or ``support``. A date separator sits inside the first
    message of its day and applies to every message after it, until the next
    one.
    """
    articles = sorted(raw_articles, key=lambda article: article["seq"])
    # A BEM "own" modifier is the reliable ownership signal; the bubble's
    # position is the fallback, used only when no message carries the class
    # at all (i.e. the class name is not what we expect).
    class_marks_own = any(article.get("ownClass") for article in articles)
    messages: List[Dict[str, Any]] = []
    current_date: Optional[date] = None
    for article in articles:
        body: List[str] = []
        line_stamp: Optional[Stamp] = None
        buttons = [" ".join(label.split()) for label in article.get("buttons", [])]
        buttons = [label for label in buttons if label]
        # An inline keyboard's labels render as text too: "12345", or one per line.
        keyboard = {"".join(buttons), " ".join(buttons), *buttons}
        for raw_line in article.get("lines", []):
            line = " ".join(raw_line.split())
            if not line or (buttons and line in keyboard):
                continue
            separator = _date_separator(line, today)
            if separator is not None:
                current_date = separator
                continue
            stamp = _stamp(line, today, whole_line=True)
            if stamp is not None:
                line_stamp = line_stamp or stamp
                continue
            body.append(line)
        label_stamp = next(
            filter(
                None,
                (
                    _stamp(label, today, whole_line=False)
                    for label in article.get("labels", [])
                ),
            ),
            None,
        )
        stamp_date, stamp_time = label_stamp or line_stamp or (None, None)
        while body and _norm(body[0]) == _norm(SUPPORT_NAME):
            del body[0]
        when = stamp_date or current_date
        own = bool(article.get("ownClass")) or (
            not class_marks_own and bool(article.get("ownGeom"))
        )
        message: Dict[str, Any] = {
            "id": article["seq"],
            "from": "me" if own else "support",
            "date": when.isoformat() if when else None,
            "time": stamp_time,
            "text": "\n".join(body),
        }
        if article.get("media"):
            message["media"] = True
        if article.get("links"):
            message["links"] = list(article["links"])
        if buttons:
            message["buttons"] = buttons
        messages.append(message)
    return messages


def is_closing(message: Dict[str, Any]) -> bool:
    """True for the support message that closes a request."""
    return message["from"] == "support" and any(
        marker in _norm(message["text"]) for marker in CLOSE_MARKERS
    )


def is_rating_prompt(message: Dict[str, Any]) -> bool:
    """True for the support message that asks the user to rate its work."""
    return message["from"] == "support" and any(
        marker in _norm(message["text"]) for marker in RATING_MARKERS
    )


def _is_rating(message: Dict[str, Any]) -> bool:
    text = message["text"].strip()
    return (
        message["from"] == "me"
        and 0 < len(text) <= _MAX_RATING_CHARS
        and not any(char.isalpha() for char in text)
    )


def _ends(closed: bool, message: Dict[str, Any]) -> bool:
    """Whether the conversation is over once ``message`` has arrived."""
    if is_closing(message) or _is_rating(message):
        return True
    if message["from"] == "support" and any(
        marker in _norm(message["text"]) for marker in REOPEN_MARKERS
    ):
        return False
    return closed


def _moment(message: Dict[str, Any]) -> Optional[datetime]:
    if not (message["date"] and message["time"]):
        return None
    return datetime.fromisoformat(f"{message['date']}T{message['time']}")


def _after_silence(previous: Dict[str, Any], message: Dict[str, Any]) -> bool:
    """Whether the user writes again long after the support's last word."""
    then, now = _moment(previous), _moment(message)
    return (
        previous["from"] == "support"
        and then is not None
        and now is not None
        and now - then >= NEW_TOPIC_GAP
    )


def group_threads(messages: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Split messages into conversations, oldest first (see module docstring)."""
    threads: List[List[Dict[str, Any]]] = []
    closed = False
    for message in sorted(messages, key=lambda item: item["id"]):
        opens = (
            message["from"] == "me"
            and not _is_rating(message)
            and bool(threads)
            and (closed or _after_silence(threads[-1][-1], message))
        )
        if not threads or opens:
            threads.append([])
            closed = False
        threads[-1].append(message)
        closed = _ends(closed, message)
    return threads


def _when(message: Dict[str, Any]) -> Optional[str]:
    return " ".join(part for part in (message["date"], message["time"]) if part) or None


def summarize(thread: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One ``support list`` row for a conversation."""
    first = thread[0]
    # The preview is what the user asked, not the bot's greeting or a rating.
    starter = next(
        (m for m in thread if m["from"] == "me" and m["text"] and not _is_rating(m)),
        first,
    )
    preview = " ".join(starter["text"].split())  # the 1st line is often a greeting
    if len(preview) > _PREVIEW_CHARS:
        preview = preview[: _PREVIEW_CHARS - 1] + "…"
    return {
        "id": first["id"],
        "started": _when(first),
        "updated": _when(thread[-1]),
        "status": "closed" if reduce(_ends, thread, False) else "open",
        "messages": len(thread),
        "preview": preview,
    }

"""
detector.py - finds deadlines in chat messages.

Two simple steps, no AI needed:
  1. Does the message sound like a deadline?  (keyword rules)
  2. Can we find a date in it?                (regex + dateparser)
Both must be true for the message to count as a deadline.
"""
import re
from datetime import datetime, timedelta

import dateparser

# Words that make a message sound like a deadline
DEADLINE_WORDS = [
    "submit", "submission", "due", "deadline", "last date", "last day",
    "register", "registration", "pay", "payment", "before", "must", "need to",
    "don't forget", "dont forget", "reminder", "apply", "upload", "by",
]

# Words that mean an EXISTING deadline is being changed
UPDATE_WORDS = ["extended", "postponed", "preponed", "rescheduled", "shifted", "moved",
                "changed", "revised", "updated", "advanced", "pushed", "instead"]

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
DAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"

# Ways people write dates in chats
DATE_PATTERNS = [
    r"\b(?:today|tonight|tomorrow)\b",
    rf"\b(?:next\s+)?(?:{DAYS})\b",
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTHS})[a-z]*\b(?:\s+\d{{4}})?",
    rf"\b(?:{MONTHS})[a-z]*\s+\d{{1,2}}(?:st|nd|rd|th)?\b(?:,?\s+\d{{4}})?",
    r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b",
    r"\b\d{1,2}(?:st|nd|rd|th)\b",  # bare "23rd" (lowest priority)
]
TIME_PATTERN = r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b"
LINK_PATTERN = r"https?://\S+"


def _find_date_text(message: str):
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _find_time_text(message: str):
    match = re.search(TIME_PATTERN, message, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _parse_time(time_text):
    """'5 pm' / '11:59 pm' -> (hour, minute)"""
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", time_text.strip(), flags=re.IGNORECASE)
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    return hour, minute


def _fallback_calendar_date(text: str, now: datetime):
    """Tiny built-in parser for '24 October', 'Oct 24', '28/10' (used if dateparser fails)."""
    month_names = ["jan", "feb", "mar", "apr", "may", "jun",
                   "jul", "aug", "sep", "oct", "nov", "dec"]
    t = text.lower()
    m = re.search(rf"(\d{{1,2}})\s+(?:of\s+)?({MONTHS})[a-z]*(?:\s+(\d{{4}}))?", t)
    if m:
        day, month, year = int(m.group(1)), month_names.index(m.group(2)[:3]) + 1, m.group(3)
    else:
        m = re.search(rf"({MONTHS})[a-z]*\s+(\d{{1,2}})(?:,?\s+(\d{{4}}))?", t)
        if m:
            day, month, year = int(m.group(2)), month_names.index(m.group(1)[:3]) + 1, m.group(3)
        else:
            m = re.match(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
            if not m:
                return None
            day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)

    explicit_year = year is not None
    year = int(year) if explicit_year else now.year
    if year < 100:
        year += 2000
    try:
        result = datetime(year, month, day)
    except ValueError:
        return None
    # "25 Jan" said in December means next year
    if not explicit_year and result.date() < now.date():
        result = result.replace(year=result.year + 1)
    return result


def _parse_date(date_text: str, time_text, now: datetime):
    """Turn a phrase like 'tomorrow', 'Monday' or '25th Oct' into a datetime."""
    word = date_text.lower().strip()
    word = re.sub(r"^next\s+", "", word)

    # Relative words and weekdays are handled directly (no library needed)
    if word in ("today", "tonight", "tomorrow"):
        base = now + timedelta(days=1 if word == "tomorrow" else 0)
    elif word in WEEKDAYS:
        ahead = (WEEKDAYS.index(word) - now.weekday()) % 7 or 7
        base = now + timedelta(days=ahead)
    elif re.fullmatch(r"\d{1,2}(?:st|nd|rd|th)", word):
        # Bare day number, e.g. "23rd" -> this month, or next month if it has passed
        day = int(re.match(r"\d+", word).group(0))
        base = None
        for add in (0, 1, 2):
            month = (now.month - 1 + add) % 12 + 1
            year = now.year + (now.month - 1 + add) // 12
            try:
                candidate = datetime(year, month, day)
            except ValueError:
                continue
            if candidate.date() >= now.date():
                base = candidate
                break
        if base is None:
            return None
    else:
        # Calendar dates like "25th Oct" or "28/04"
        cleaned = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", date_text, flags=re.IGNORECASE)
        base = None
        try:
            base = dateparser.parse(
                cleaned,
                settings={
                    "PREFER_DATES_FROM": "future",
                    "RELATIVE_BASE": now,
                    "DATE_ORDER": "DMY",
                    "PARSERS": ["custom-formats", "absolute-time"],
                },
            )
        except Exception:
            base = None  # e.g. odd timezone setup on this computer -> use fallback
        if base is None:
            base = _fallback_calendar_date(cleaned, now)
        if base is None:
            return None

    hour, minute = _parse_time(time_text) if time_text else (23, 59)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _clean_title(message: str) -> str:
    """Turn a chat message into a short task name WITHOUT the date (the date is shown separately)."""
    text = re.sub(LINK_PATTERN, " ", message)
    text = re.sub(r"[^\w\s/:,.'&()!?-]", "", text)  # drop emojis
    for p in DATE_PATTERNS + [TIME_PATTERN]:
        text = re.sub(p, " ", text, flags=re.IGNORECASE)
    # remove change words ("extended", "changed"...) - they describe the update, not the task
    text = re.sub(r"\b(" + "|".join(UPDATE_WORDS) + r")\b", " ", text, flags=re.IGNORECASE)
    # remove greetings and filler
    text = re.sub(r"\b(hey|hi|hello)\b(\s+(everyone|guys|all))?", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(please|guys|everyone|don'?t forget|start early)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*reminder\s*:", " ", text, flags=re.IGNORECASE)

    # first sentence that still has real words
    title = ""
    for sentence in re.split(r"[.!?]+", text):
        sentence = re.sub(r"\s+", " ", sentence).strip(" ,:;-")
        if len(sentence.split()) >= 2:
            title = sentence
            break
    if not title:
        title = re.sub(r"\s+", " ", text).strip(" ,:;-.!?")

    # drop dangling connector words left behind by removed dates ("... due on")
    connectors = {"by", "on", "before", "due", "at", "to", "until", "till", "from", "is", "the", "of", "and", "in", "for"}
    words = title.split()
    while words and words[-1].lower().strip(",:;") in connectors:
        words.pop()
    title = " ".join(words).strip(" ,:;-")
    title = title[:70]
    return title[:1].upper() + title[1:] if title else "Deadline"


def extract_deadline(message: str, now: datetime = None):
    """
    Returns a dict {title, due, link, is_update} or None if the message
    is not a deadline.
    """
    now = now or datetime.now()
    lowered = message.lower().replace("by the way", "")

    is_update = any(word in lowered for word in UPDATE_WORDS)
    sounds_like_deadline = is_update or any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in DEADLINE_WORDS)
    if not sounds_like_deadline:
        return None

    date_text = _find_date_text(message)
    if not date_text:
        return None

    time_text = _find_time_text(message)
    due = _parse_date(date_text, time_text, now)
    if due is None:
        return None

    link_match = re.search(LINK_PATTERN, message)
    return {
        "title": _clean_title(message),
        "due": due,
        "link": link_match.group(0) if link_match else None,
        "is_update": is_update,
    }


# ---------- Matching "same task" messages ----------
_STOP = set("the a an on by to for of in at is are be please guys everyone hey hi do not dont "
            "don't forget reminder submit submission due deadline before this that it and or "
            "all you your our we need must last date day".split())


def content_words(text: str) -> set:
    """Meaningful words of a message, ignoring dates, times and filler."""
    t = text.lower()
    t = re.sub(LINK_PATTERN, " ", t)
    for p in DATE_PATTERNS + [TIME_PATTERN]:
        t = re.sub(p, " ", t, flags=re.IGNORECASE)
    words = re.findall(r"[a-z]{3,}", t)
    return {w for w in words if w not in _STOP and w not in UPDATE_WORDS}


def similarity(a: str, b: str) -> float:
    """0..1 - how much two messages talk about the same task."""
    wa, wb = content_words(a), content_words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))

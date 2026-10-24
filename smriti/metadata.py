"""Conservative document-date extraction from local OCR text."""

from __future__ import annotations

import re
from datetime import date

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_WORDS = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b")
_SKIP = re.compile(r"\b(?:dob|date\s+of\s+birth|birth)\b", re.IGNORECASE)
_LABELS = (
    ("collection_date", re.compile(r"\b(?:collection|sample|specimen)\s*date\b", re.I)),
    ("doc_date", re.compile(r"\b(?:report|reported|test|result|issued)\s*date\b", re.I)),
    ("doc_date", re.compile(r"\bdate\b", re.I)),
)


def _numeric_date(day: str, month: str, year: str) -> date | None:
    first, second = int(day), int(month)
    year_value = int(year)
    if year_value < 100:
        year_value += 2000
    if first > 12 and second <= 12:
        day_value, month_value = first, second
    elif second > 12 and first <= 12:
        day_value, month_value = second, first
    else:
        # Local reports are day-first unless the values make that impossible.
        day_value, month_value = first, second
    try:
        return date(year_value, month_value, day_value)
    except ValueError:
        return None


def _date_in(text: str) -> date | None:
    match = _ISO.search(text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    match = _NUMERIC.search(text)
    if match:
        parsed = _numeric_date(*match.groups())
        if parsed:
            return parsed
    match = _WORDS.search(text)
    if match:
        month = _MONTHS.get(match.group(2).lower())
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                pass
    return None


def extract_document_dates(text: str) -> dict[str, str]:
    """Return labelled collection/report dates. Never guesses from a DOB."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if _SKIP.search(line):
            continue
        for field, label in _LABELS:
            if field in found or not label.search(line):
                continue
            parsed = _date_in(line)
            if parsed:
                found[field] = parsed.isoformat()
                break
    return found

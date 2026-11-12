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
_ISO = re.compile(r"\b(\d{4})[/.-](\d{2})[/.-](\d{2})\b")
_NUMERIC = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b")
_WORDS = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})[/.-]([A-Za-z]{3,9})[/.-](\d{2,4})(?=\d{1,2}:\d{2}|[^0-9]|$)"
)
_SKIP = re.compile(r"\b(?:dob|date\s+of\s+birth|birth)\b", re.IGNORECASE)
_LABELS = (
    (
        "collection_date",
        re.compile(
            r"\b(?:collection|sample|specimen|coll|drawn)\s*date\b|\b(?:sample|specimen)\s*collected\b",
            re.I,
        ),
    ),
    (
        "registration_date",
        re.compile(
            r"\b(?:reg|registration|admission|admit)\s*date\b|\b(?:doa|date\s+of\s+admission)\b|\badmitted\s*(?:on|at)\b|\bregistered\s*(?:on|at)\b",
            re.I,
        ),
    ),
    (
        "report_date",
        re.compile(
            r"\b(?:report|reported|result|discharge|dod)\s*date\b|\b(?:date\s+of\s+discharge|dod)\b|\breported\s*(?:on|at)\b|\bdischarged\s*(?:on|at)\b|\bissued\s*date\b",
            re.I,
        ),
    ),
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
    for pattern in (_WORDS, _DAY_MONTH_YEAR):
        match = pattern.search(text)
        if match:
            month = _MONTHS.get(match.group(2).lower())
            if month:
                try:
                    year = int(match.group(3))
                    if year < 100:
                        year += 2000
                    return date(year, month, int(match.group(1)))
                except ValueError:
                    pass
    return None


def parse_date(text: str) -> date | None:
    """Parse the first date-like value, ignoring date-of-birth lines."""
    for line in text.splitlines():
        if _SKIP.search(line):
            continue
        parsed = _date_in(line)
        if parsed:
            return parsed
    return _date_in("\n".join(line for line in text.splitlines() if not _SKIP.search(line)))


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
    found.setdefault(
        "doc_date",
        found.get("collection_date")
        or found.get("registration_date")
        or found.get("report_date"),
    )
    return {k: v for k, v in found.items() if v is not None}


_UHID_PATTERNS = [
    re.compile(
        r"\b(?:uhid|cr\s*no|mrd\s*no|ipd\s*no|opd\s*no|patient\s*id|mrn)\s*[:.\-]?\s*([A-Za-z0-9/\-_]{4,30})\b",
        re.I,
    ),
    re.compile(
        r"\bpatient\s*reg(?:n)?\.?\s*(?:no\.?)?\s*[:.\-]\s*([A-Za-z0-9/\-_]{4,30})\b",
        re.I,
    ),
]

_DOCTOR_COUNCIL_PATTERNS = [
    re.compile(
        r"\b(?:mci|dmc|smc|hmc|upmc|krag)\s*(?:reg|regn)?\.?\s*(?:no\.?)?\s*[:.\-]?\s*([A-Za-z0-9/\-_]{3,20})\b",
        re.I,
    ),
]

_DOCTOR_CONTEXT = re.compile(
    r"\b(dr\.?|doctor|consultant|physician|pathologist|surgeon|m\.?d\.?|m\.?b\.?b\.?s\.?|dnb|signature)\b",
    re.I,
)
_PATIENT_CONTEXT = re.compile(r"\b(patient|pt\.?|bed|ward|age|sex|gender|dob)\b", re.I)
_DOCTOR_REG_PATTERN = re.compile(
    r"\b(?:reg|regn)\.?\s*(?:no\.?)?\s*[:.\-]?\s*([A-Za-z0-9/\-_]{3,20})\b", re.I
)

_FACILITY_PATTERNS = re.compile(
    r"(hospital|medical\s+college|diagnostics?|laborator(?:y|ies)|clinic|healthcare|institute\s+of\s+medical\s+sciences)",
    re.I,
)


def extract_document_identifiers(text: str) -> dict[str, str | None]:
    patient_uhid: str | None = None
    doctor_reg_no: str | None = None
    facility_name: str | None = None

    lines = text.splitlines()

    for line in lines[:8]:
        stripped = line.strip()
        if _FACILITY_PATTERNS.search(stripped) and len(stripped) <= 80:
            facility_name = stripped
            break

    for line in lines:
        stripped = line.strip()

        if patient_uhid is None:
            for pattern in _UHID_PATTERNS:
                match = pattern.search(stripped)
                if match:
                    patient_uhid = match.group(1).strip()
                    break

        if doctor_reg_no is None:
            for pattern in _DOCTOR_COUNCIL_PATTERNS:
                match = pattern.search(stripped)
                if match:
                    candidate = match.group(1).strip()
                    if not _PATIENT_CONTEXT.search(stripped):
                        doctor_reg_no = candidate
                        break

            if doctor_reg_no is None and _DOCTOR_CONTEXT.search(stripped):
                if not _PATIENT_CONTEXT.search(stripped):
                    match = _DOCTOR_REG_PATTERN.search(stripped)
                    if match:
                        doctor_reg_no = match.group(1).strip()

    return {
        "patient_uhid": patient_uhid,
        "doctor_reg_no": doctor_reg_no,
        "facility_name": facility_name,
    }


def extract_metadata(text: str) -> dict[str, str | None]:
    dates = extract_document_dates(text)
    identifiers = extract_document_identifiers(text)
    return {
        "doc_date": dates.get("doc_date"),
        "collection_date": dates.get("collection_date"),
        "registration_date": dates.get("registration_date"),
        "report_date": dates.get("report_date"),
        "patient_uhid": identifiers.get("patient_uhid"),
        "doctor_reg_no": identifiers.get("doctor_reg_no"),
        "facility_name": identifiers.get("facility_name"),
    }


def extract_metadata_lines(lines) -> dict[str, str | None]:
    """Same document-wide precedence and first-eight-line facility rule, with bounded line reads."""
    dates = {}
    identifiers = {"patient_uhid": None, "doctor_reg_no": None, "facility_name": None}
    for index, line in enumerate(lines):
        if not _SKIP.search(line):
            for field, label in _LABELS:
                if field not in dates and label.search(line):
                    parsed = _date_in(line)
                    if parsed:
                        dates[field] = parsed.isoformat()
                        break
        found = extract_document_identifiers(line)
        for key in identifiers:
            if identifiers[key] is None and (key != "facility_name" or index < 8):
                identifiers[key] = found[key]
    dates.setdefault("doc_date", dates.get("collection_date") or dates.get("registration_date") or dates.get("report_date"))
    return {key: dates.get(key) for key in ("doc_date", "collection_date", "registration_date", "report_date")} | identifiers

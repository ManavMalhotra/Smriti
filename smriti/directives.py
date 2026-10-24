"""Conservative follow-up directive grammar over local OCR text.

Rules keep the source span exact. Dates are computed only from a written
interval or a written absolute date and a stored document anchor; today is
never an anchor.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from smriti.metadata import parse_date

_ACTION = (
    r"(?:r\s*/\s*v|review|follow[\s-]?up|f\s*/\s*u|repeat|re[\s-]?test|"
    r"retest|recheck|come(?:\s+back)?|return|visit|consult|admit|start|"
    r"stop|increase|decrease|continue)"
)
_ACTION_GROUP = rf"(?P<action>{_ACTION})"
_INTERVAL = (
    r"(?P<value>\d+)\s*"
    r"(?P<unit>days?|d|wks?|weeks?|wk|months?|mths?|mth|years?|yrs?|yr)"
)
_DATE = (
    r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
)

_RELATIVE_PREP = re.compile(
    rf"(?<![A-Za-z]){_ACTION_GROUP}(?![A-Za-z])"
    rf"(?P<middle>[^\n.;]{{0,80}}?)\s+(?:after|in|within)\s+{_INTERVAL}(?![A-Za-z])",
    re.IGNORECASE,
)
_RELATIVE_BARE = re.compile(
    rf"(?<![A-Za-z]){_ACTION_GROUP}(?![A-Za-z])"
    rf"(?!\s+(?:after|in|within)\b)"
    rf"(?P<middle>[^\n.;]{{0,60}}?)\s+{_INTERVAL}(?![A-Za-z])",
    re.IGNORECASE,
)
_ABSOLUTE = re.compile(
    rf"(?<![A-Za-z]){_ACTION_GROUP}(?![A-Za-z])"
    rf"(?P<middle>[^\n.;]{{0,60}}?)\s+(?:on|by|before)?\s*"
    rf"(?P<date>{_DATE})(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_CONDITIONAL_ACTION = re.compile(
    rf"(?<![A-Za-z]){_ACTION_GROUP}(?![A-Za-z])"
    rf"(?P<middle>[^\n.;]{{0,80}}?)\s+"
    rf"(?P<condition>(?:after\s+stopping|if|when)\b[^\n.;]*)",
    re.IGNORECASE,
)
_CONDITIONAL_FIRST = re.compile(
    rf"(?P<condition>(?:if|when)\b[^,.;\n]+)[,;]?\s*"
    rf"{_ACTION_GROUP}(?![A-Za-z])(?P<tail>[^\n.;]*)",
    re.IGNORECASE,
)
_PRN = re.compile(
    r"(?<![A-Za-z])(?P<prn>sos|prn|as\s+needed|if\s+needed)(?![A-Za-z])"
    r"(?P<tail>\s+for\s+[^\n.;]+)",
    re.IGNORECASE,
)
_MEDICATION_LINE = re.compile(
    r"\b(?:tab|cap|syp|inj|tablet|capsule|syrup|injection)\.?\b",
    re.IGNORECASE,
)
_CONDITION_WORDS = re.compile(
    r"\b(?:if|when|after|before|beyond|stopping|until|unless)\b",
    re.IGNORECASE,
)
_TIMING_TAIL = re.compile(
    r"\s+(?:after|in|within|on|by|before)\s+\d.*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Directive:
    span_text: str
    span_start: int
    span_end: int
    action_type: str
    timing_type: str
    time_value: int | None
    time_unit: str | None
    anchor_event: str
    condition_text: str | None
    target: str | None
    anchor_date: date | None
    due_date: date | None
    state: str


def _as_date(value: date | str | None) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _anchor(collection_date: date | str | None, doc_date: date | str | None) -> tuple[str, date | None]:
    collection = _as_date(collection_date)
    if collection:
        return "collection_date", collection
    document = _as_date(doc_date)
    if document:
        return "doc_date", document
    return "unknown", None


def _unit_name(raw: str) -> str:
    value = raw.lower()
    if value.startswith("d"):
        return "day"
    if value.startswith("w"):
        return "week"
    if value.startswith("m"):
        return "month"
    return "year"


def _add_interval(anchor: date, value: int, unit: str) -> date:
    if unit == "day":
        return anchor + timedelta(days=value)
    if unit == "week":
        return anchor + timedelta(weeks=value)
    months = value if unit == "month" else value * 12
    year = anchor.year + (anchor.month - 1 + months) // 12
    month = (anchor.month - 1 + months) % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _action_type(action: str, target: str | None) -> str:
    value = action.lower().replace(" ", "")
    if value in {"repeat", "re-test", "retest", "recheck"}:
        if target and re.search(
            r"\b(?:mri|ct|scan|x-?ray|usg|ultrasound|imaging)\b", target, re.IGNORECASE
        ):
            return "imaging"
        return "test"
    if value == "admit":
        return "admission"
    if value in {"start", "stop", "increase", "decrease", "continue"}:
        return "medication_change"
    return "review"


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = " ".join(value.split()).strip(" :-,")
    return text or None


def _target(action: str, middle: str | None) -> str | None:
    text = _clean(middle)
    if text:
        text = _clean(_TIMING_TAIL.sub("", text))
    if text:
        return text
    return "review" if _action_type(action, None) == "review" else None


def _condition_first_target(action: str, tail: str | None) -> str | None:
    text = _clean(tail)
    if text and _action_type(action, text) == "review" and text.lower() in {
        "immediately",
        "now",
        "soon",
    }:
        return "review"
    return _target(action, tail)


def _condition(value: str | None) -> str | None:
    text = _clean(value)
    if text:
        text = re.sub(r"^(?:if|when)\b\s*", "", text, flags=re.IGNORECASE)
        return _clean(text)
    return None


def _relative(
    match: re.Match[str],
    offset: int,
    anchor_event: str,
    anchor_date: date | None,
    as_of: date,
) -> Directive:
    action = match.group("action")
    middle = match.group("middle")
    value = int(match.group("value"))
    unit = _unit_name(match.group("unit"))
    target = _target(action, middle)
    due = _add_interval(anchor_date, value, unit) if anchor_date else None
    state = "open" if due is not None and due >= as_of else "unknown_date"
    if due is not None and due < as_of:
        due = None
    return Directive(
        span_text=match.group(0),
        span_start=offset + match.start(),
        span_end=offset + match.end(),
        action_type=_action_type(action, target),
        timing_type="relative",
        time_value=value,
        time_unit=unit,
        anchor_event=anchor_event,
        condition_text=None,
        target=target,
        anchor_date=anchor_date,
        due_date=due,
        state=state,
    )


def _absolute(
    match: re.Match[str],
    offset: int,
    as_of: date,
) -> Directive | None:
    action = match.group("action")
    target = _target(action, match.group("middle"))
    due = parse_date(match.group("date"))
    if due is None:
        return None
    state = "open" if due >= as_of else "unknown_date"
    if due < as_of:
        due = None
    return Directive(
        span_text=match.group(0),
        span_start=offset + match.start(),
        span_end=offset + match.end(),
        action_type=_action_type(action, target),
        timing_type="absolute",
        time_value=None,
        time_unit=None,
        anchor_event="unknown",
        condition_text=None,
        target=target,
        anchor_date=None,
        due_date=due,
        state=state,
    )


def _conditional(
    match: re.Match[str],
    offset: int,
    condition: str,
    target: str | None,
    action: str,
) -> Directive:
    return Directive(
        span_text=match.group(0),
        span_start=offset + match.start(),
        span_end=offset + match.end(),
        action_type=_action_type(action, target),
        timing_type="conditional",
        time_value=None,
        time_unit=None,
        anchor_event="unknown",
        condition_text=_condition(condition),
        target=target,
        anchor_date=None,
        due_date=None,
        state="open",
    )


def _prn(match: re.Match[str], offset: int) -> Directive:
    target = _clean(re.sub(r"^\s*for\s+", "", match.group("tail"), flags=re.IGNORECASE))
    return Directive(
        span_text=match.group(0),
        span_start=offset + match.start(),
        span_end=offset + match.end(),
        action_type="other",
        timing_type="prn",
        time_value=None,
        time_unit=None,
        anchor_event="unknown",
        condition_text="as needed",
        target=target,
        anchor_date=None,
        due_date=None,
        state="open",
    )


def _parse_line(
    line: str,
    offset: int,
    anchor_event: str,
    anchor_date: date | None,
    as_of: date,
) -> list[Directive]:
    candidates: list[tuple[int, int, int, Directive]] = []

    for match in _RELATIVE_PREP.finditer(line):
        candidates.append((match.start(), match.end(), 0, _relative(
            match, offset, anchor_event, anchor_date, as_of
        )))
    for match in _RELATIVE_BARE.finditer(line):
        if _CONDITION_WORDS.search(match.group("middle") or ""):
            continue
        candidates.append((match.start(), match.end(), 1, _relative(
            match, offset, anchor_event, anchor_date, as_of
        )))
    for match in _ABSOLUTE.finditer(line):
        directive = _absolute(match, offset, as_of)
        if directive is not None:
            candidates.append((match.start(), match.end(), 2, directive))
    for match in _CONDITIONAL_ACTION.finditer(line):
        target = _target(match.group("action"), match.group("middle"))
        candidates.append((match.start(), match.end(), 3, _conditional(
            match, offset, match.group("condition"), target, match.group("action")
        )))
    for match in _CONDITIONAL_FIRST.finditer(line):
        action = match.group("action")
        target = _condition_first_target(action, match.group("tail"))
        candidates.append((match.start(), match.end(), 4, _conditional(
            match, offset, match.group("condition"), target, action
        )))
    if not _MEDICATION_LINE.search(line):
        for match in _PRN.finditer(line):
            candidates.append((match.start(), match.end(), 5, _prn(match, offset)))

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0]), item[2]))
    selected: list[Directive] = []
    last_end = -1
    for start, end, _priority, directive in candidates:
        if start < last_end:
            continue
        selected.append(directive)
        last_end = end
    return selected


def extract_directives(
    text: str,
    *,
    collection_date: date | str | None = None,
    doc_date: date | str | None = None,
    as_of: date | None = None,
) -> list[Directive]:
    anchor_event, anchor_date = _anchor(collection_date, doc_date)
    reference = as_of or date.today()
    directives: list[Directive] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        directives.extend(_parse_line(line, offset, anchor_event, anchor_date, reference))
        offset += len(raw_line)
    directives.sort(key=lambda directive: (directive.span_start, directive.span_end))
    unique: list[Directive] = []
    for directive in directives:
        if unique and directive.span_start < unique[-1].span_end:
            continue
        unique.append(directive)
    return unique

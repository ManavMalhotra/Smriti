"""Rule extraction over local OCR words. Everything stays on the device."""

from __future__ import annotations

import re
from dataclasses import dataclass

from smriti.analytes import Analyte, analytes
from smriti.assembly import assemble_page
from smriti.engines import LOCAL_RULES
from smriti.ocr import OcrWord
from smriti.resolution import resolve

_UNIT = re.compile(
    r"(?:%|mg/dL|g/dL|mmol/L|mEq/L|U/L|IU/L|cells/µL|cells/uL|/µL|"
    r"ng/mL|pg/mL|µIU/mL|mIU/mL|mm/hr)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9.-])([<>]?)\s*(-?\d+(?:\.\d+)?)")
_RANGE = re.compile(
    r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)"
)
_FLAG = re.compile(r"\b(high|low|h|l|abnormal)\b", re.IGNORECASE)
_MED_FREQ = (
    r"od|bd|tds|qid|hs|sos|prn|once\s+daily|twice\s+daily|"
    r"thrice\s+daily|every\s+day|\d\s*-\s*\d\s*-\s*\d|\d\s*/\s*\d\s*/\s*\d"
)
_MED = re.compile(
    r"\b(?:(?P<form>tab|cap|syp|inj|tablet|capsule|syrup|injection)\.?\s+)?"
    r"(?P<brand>[A-Za-z][A-Za-z0-9-]{1,40})"
    r"(?:\s+(?P<dose>\d+(?:\.\d+)?\s*(?:mg|g|ml|mcg|iu)))?"
    rf"(?:\s+(?P<freq>{_MED_FREQ}))?",
    re.IGNORECASE,
)
# Headers, identifiers, and dates never become unresolved lab fields.
_NON_RESULT_WORDS = (
    "date",
    "dob",
    "age",
    "sex",
    "gender",
    "phone",
    "mobile",
    "address",
    "bill",
    "invoice",
    "barcode",
    "report",
    "reported",
    "page",
    "sample",
    "specimen",
    "collection",
    "lab no",
    "reg",
    "registration",
    "uhid",
    "mrn",
    "patient",
    "name",
    "id",
    "doctor",
    "dr",
    "consultant",
    "hospital",
    "clinic",
    "diagnosis",
    "history",
    "advice",
    "note",
)


@dataclass(frozen=True)
class ExtractedField:
    analyte_id: str | None
    label_raw: str
    value_num: str | None
    value_text: str
    unit_raw: str | None
    ref_low: str | None
    ref_high: str | None
    flag_printed: str | None
    bbox: list[float]
    page: int
    confidence: float
    mapping_rule: str
    engine: str = str(LOCAL_RULES)


@dataclass(frozen=True)
class ExtractedMedication:
    brand_raw: str
    dose: str | None
    freq: str | None
    confidence: float


@dataclass(frozen=True)
class Extraction:
    fields: list[ExtractedField]
    medications: list[ExtractedMedication]


def _canonical_number(value: str) -> str:
    return f"{float(value):g}"


def _line_groups(words: list[OcrWord]) -> list[list[OcrWord]]:
    return [list(row.words) for row in assemble_page(words).rows]


def words_to_text(words: list[OcrWord]) -> str:
    return "\n".join(" ".join(word.text for word in line) for line in _line_groups(words))


def _line_bbox(words: list[OcrWord]) -> list[float]:
    return [
        max(0.0, min(1.0, min(word.bbox[0] for word in words))),
        max(0.0, min(1.0, min(word.bbox[1] for word in words))),
        max(0.0, min(1.0, max(word.bbox[2] for word in words))),
        max(0.0, min(1.0, max(word.bbox[3] for word in words))),
    ]


def _confidence(words: list[OcrWord]) -> float:
    return round(sum(word.confidence for word in words) / max(1, len(words)), 3)


def _analyte_matches(text: str) -> list[tuple[int, int, Analyte, str]]:
    lowered = text.lower()
    found: list[tuple[int, int, Analyte, str]] = []
    for analyte in analytes():
        for synonym in analyte.synonyms:
            for match in re.finditer(
                rf"(?<![a-z0-9]){re.escape(synonym)}(?![a-z0-9])", lowered
            ):
                found.append((match.start(), match.end(), analyte, synonym))
    found.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, Analyte, str]] = []
    for candidate in found:
        if any(
            candidate[0] < existing[1] and candidate[1] > existing[0]
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return selected


def _parse_value(text: str) -> tuple[str, str | None, str | None] | None:
    match = _NUMBER.search(text)
    if not match:
        return None
    prefix, number = match.groups()
    unit = _UNIT.search(text[match.end() :])
    value_text = f"{prefix}{_canonical_number(number)}"
    return _canonical_number(number), value_text, unit.group(0) if unit else None


def _parse_range(text: str) -> tuple[str | None, str | None]:
    match = _RANGE.search(text)
    if not match:
        return None, None
    return _canonical_number(match.group(1)), _canonical_number(match.group(2))


def _printed_flag(text: str) -> str | None:
    match = _FLAG.search(text)
    if not match:
        return None
    value = match.group(1).lower()
    if value in ("h", "high"):
        return "H"
    if value in ("l", "low"):
        return "L"
    return "A"


def _bbox_for_value(words: list[OcrWord], value: str) -> list[float]:
    for word in words:
        if value in word.text or value.replace(".", "") in word.text.replace(".", ""):
            return word.bbox
    return _line_bbox(words)


def _extract_line(
    words: list[OcrWord], page: int, engine: str
) -> list[ExtractedField]:
    text = " ".join(word.text for word in words)
    matches = _analyte_matches(text)
    fields: list[ExtractedField] = []
    if matches:
        for index, (start, end, analyte, _synonym) in enumerate(matches):
            next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
            tail = text[end:next_start]
            parsed = _parse_value(tail)
            if parsed is None:
                continue
            value_num, value_text, unit = parsed
            ref_low, ref_high = _parse_range(tail)
            label_raw = text[start:end].strip()
            resolution = resolve(label_raw, value_num, unit, ref_low, ref_high)
            fields.append(
                ExtractedField(
                    analyte_id=resolution.analyte_id or analyte.id,
                    label_raw=label_raw,
                    value_num=value_num,
                    value_text=value_text,
                    unit_raw=unit,
                    ref_low=ref_low,
                    ref_high=ref_high,
                    flag_printed=_printed_flag(tail),
                    bbox=_bbox_for_value(words, value_text or value_num),
                    page=page,
                    confidence=resolution.confidence,
                    mapping_rule=resolution.mapping_rule,
                    engine=engine,
                )
            )
        return fields

    lowered = text.lower()
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _NON_RESULT_WORDS):
        return fields
    label = text.strip(" :-")
    if len(label) < 3:
        return fields
    parsed = _parse_value(text)
    if parsed is None or parsed[0] is None:
        return fields
    value_num, value_text, unit = parsed
    label_match = re.match(r"^[A-Za-z][A-Za-z0-9 ()\-/%.,']{2,60}", label)
    if not label_match:
        return fields
    label_raw = label_match.group(0).strip()
    ref_low, ref_high = _parse_range(text)
    fields.append(
        ExtractedField(
            analyte_id=None,
            label_raw=label_raw,
            value_num=value_num,
            value_text=value_text,
            unit_raw=unit,
            ref_low=ref_low,
            ref_high=ref_high,
            flag_printed=_printed_flag(text),
            bbox=_bbox_for_value(words, value_text or value_num),
            page=page,
            confidence=0.0,
            mapping_rule="unresolved",
            engine=engine,
        )
    )
    return fields


def _extract_medications(words: list[OcrWord]) -> list[ExtractedMedication]:
    text = " ".join(word.text for word in words)
    medications: list[ExtractedMedication] = []
    for match in _MED.finditer(text):
        form = match.group("form")
        dose = match.group("dose")
        freq = match.group("freq")
        # A bare word is not a medication; require a form, a dose, or both.
        if not (form or dose):
            continue
        brand = match.group("brand").strip()
        brand_raw = f"{form.capitalize()}. {brand}" if form else brand
        medications.append(
            ExtractedMedication(
                brand_raw=brand_raw,
                dose=" ".join(dose.split()) if dose else None,
                freq=" ".join(freq.upper().split()) if freq else None,
                confidence=_confidence(words),
            )
        )
    return medications


def extract_document(
    pages: list[list[OcrWord]],
    doc_type: str,
    capture_type: str,
    *,
    engine: str = str(LOCAL_RULES),
) -> Extraction:
    fields: list[ExtractedField] = []
    medications: list[ExtractedMedication] = []
    for page_number, words in enumerate(pages, start=1):
        for row in assemble_page(words).rows:
            line = list(row.words)
            if capture_type == "printed" and doc_type in (
                "lab_report",
                "other",
                "discharge_summary",
            ):
                fields.extend(_extract_line(line, page_number, engine))
            if capture_type == "printed" and doc_type in (
                "prescription",
                "pharmacy",
                "other",
                "discharge_summary",
            ):
                medications.extend(_extract_medications(line))
    # Keep one field per analyte per printed line; OCR often repeats a label.
    unique: dict[tuple[str, str, int], ExtractedField] = {}
    for field in fields:
        key = (field.analyte_id or field.label_raw.lower(), field.value_num or "", field.page)
        unique.setdefault(key, field)
    unique_meds: dict[tuple[str, str | None, str | None], ExtractedMedication] = {}
    for medication in medications:
        unique_meds.setdefault(
            (medication.brand_raw.lower(), medication.dose, medication.freq), medication
        )
    return Extraction(list(unique.values()), list(unique_meds.values()))

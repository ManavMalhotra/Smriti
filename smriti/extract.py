"""Rule extraction over local OCR words. Everything stays on the device."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from smriti.analytes import Analyte, analytes
from smriti.assembly import (
    TableTemplate,
    align_words_to_template,
    assemble_page,
    find_table_header,
)
from smriti.checks import check_bounds, validate_numeric_dual_read
from smriti.engines import LOCAL_RULES
from smriti.ocr import OcrWord
from smriti.resolution import resolve

_UNIT = re.compile(
    r"(?:%|mg/dL|g/dL|mmol/L|mEq/L|U/L|IU/L|cells/µL|cells/uL|/µL|"
    r"ng/mL|pg/mL|µIU/mL|mIU/mL|mm/hr)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9.-])([<>]?)\s*(-?\d+(?:,\d+)*(?:\.\d+)?)")
_RANGE = re.compile(
    r"(?<![\d.])(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:,\d+)*(?:\.\d+)?)"
)
_SINGLE_RANGE = re.compile(
    r"(?<![A-Za-z0-9.-])([<>≤≥])\s*(-?\d+(?:,\d+)*(?:\.\d+)?)"
)
_DATE_VALUE = re.compile(r"\b\d{1,4}[/.-](?:\d{1,2}|[A-Za-z]{3,9})[/.-]\d{2,4}\b")
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
    "plot",
    "street",
    "sector",
    "pincode",
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
    "method",
    "machine",
    "instrument",
    "analyzer",
    "technique",
    "kit",
)

_METADATA_LINE = re.compile(
    r"^(?:method|machine|instrument|analyzer|technique|kit)\s*[:.]",
    re.IGNORECASE,
)
_REF_HEADER_LINE = re.compile(
    r"^(?:reference\s*range|bio(?:logical)?\s*ref(?:erence)?\s*interval|"
    r"test\s*description|interpretation|desirable\s*:|borderline\s*:|"
    r"very\s*high\s*:|high\s*:|low\s*:)\b",
    re.IGNORECASE,
)
_PROSE_INDICATORS = re.compile(
    r"\b(?:is|are|was|were|can|that|which|such\s+as|in\s+the|of\s+the|associated\s+with|recommended|recommends)\b",
    re.IGNORECASE,
)
_SIGNATURE_END = re.compile(
    r"\b(dr\.?\s+[a-z]|mbbs|m\.?d\.?|dnb|consultant|pathologist|biochemist|signature|end\s*of\s*report)\b",
    re.IGNORECASE,
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
    reason: str | None = None
    evidence_quote: str | None = None
    clinical_metadata: dict | None = None


@dataclass(frozen=True)
class ExtractedMedication:
    brand_raw: str
    dose: str | None
    freq: str | None
    confidence: float
    page: int | None = None
    bbox: list[float] | None = None
    engine: str | None = None
    clinical_metadata: dict | None = None


@dataclass(frozen=True)
class Extraction:
    fields: list[ExtractedField]
    medications: list[ExtractedMedication]


def _canonical_number(value: str) -> str:
    return f"{float(value.replace(',', '')):g}"


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
    is_ratio = bool(re.search(r"\b(?:ratio|index)\b", lowered))
    has_mch = bool(re.search(r"\b(?:mean\s+corp|mch|mchc|corpuscular)\b", lowered))
    has_fractional_bili = bool(
        re.search(r"\b(?:direct|conjugated|indirect|unconjugated)\b", lowered)
    )
    has_bun = bool(re.search(r"\b(?:nitrogen|bun)\b", lowered))

    found: list[tuple[int, int, Analyte, str]] = []
    for analyte in analytes():
        if is_ratio and analyte.id in {
            "creatinine",
            "urea",
            "albumin",
            "ast",
            "alt",
            "platelets",
            "wbc",
        }:
            continue
        if has_mch and analyte.id == "hemoglobin":
            continue
        if has_fractional_bili and analyte.id == "bilirubin_total":
            continue
        if has_bun and analyte.id == "urea":
            continue

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
    range_match = _RANGE.search(text)
    if range_match and match.end() > range_match.start():
        return None
    date_match = _DATE_VALUE.search(text)
    if date_match and date_match.start() <= match.end() <= date_match.end():
        return None
    prefix, number = match.groups()
    unit = _UNIT.search(text[match.end() :])
    value_text = f"{prefix}{_canonical_number(number)}"
    return _canonical_number(number), value_text, unit.group(0) if unit else None


def _parse_range(text: str) -> tuple[str | None, str | None]:
    match = _RANGE.search(text)
    if match:
        return _canonical_number(match.group(1)), _canonical_number(match.group(2))
    single = _SINGLE_RANGE.search(text)
    if single:
        op, val = single.groups()
        canonical = _canonical_number(val)
        if op in ("<", "≤"):
            return None, canonical
        if op in (">", "≥"):
            return canonical, None
    return None, None


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
    clean_val = value.replace(",", "").strip()
    for word in reversed(words):
        clean_word = word.text.replace(",", "").strip()
        if clean_val == clean_word:
            return word.bbox
    for word in reversed(words):
        clean_word = word.text.replace(",", "").strip().rstrip(".:-;")
        if clean_val == clean_word:
            return word.bbox
    for word in reversed(words):
        clean_word = word.text.replace(",", "").strip()
        if clean_val in clean_word or clean_val.replace(".", "") in clean_word.replace(".", ""):
            return word.bbox
    return _line_bbox(words)


def _evaluate_field_reason(
    analyte_id: str | None,
    value_text: str,
    value_num: str | None,
    label_raw: str,
    mapping_rule: str,
) -> str:
    verdict, bounds_reason = check_bounds(analyte_id, value_num)
    if verdict == "review" and bounds_reason:
        return bounds_reason

    valid_num, dual_reason = validate_numeric_dual_read(value_text, value_num or "")
    if not valid_num and dual_reason:
        return f"Dual-read validation: {dual_reason}"

    if mapping_rule == "unresolved":
        return f"Unmapped parameter '{label_raw}'; review required."

    return "Extracted locally; review required."


def _extract_line(
    words: list[OcrWord],
    page: int,
    engine: str,
    template: TableTemplate | None = None,
) -> list[ExtractedField]:
    text = " ".join(word.text for word in words).strip()
    lowered = text.lower()

    if (
        _METADATA_LINE.search(text)
        or _REF_HEADER_LINE.search(text)
        or (_PROSE_INDICATORS.search(text) and not _parse_range(text)[0])
    ):
        return []
    if any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in _NON_RESULT_WORDS):
        return []
    if len(text) > 70 and not _parse_range(text)[0]:
        return []

    matches = _analyte_matches(text)
    fields: list[ExtractedField] = []
    if matches:
        for index, (start, end, analyte, _synonym) in enumerate(matches):
            next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
            tail = text[end:next_start]
            parsed = _parse_value(tail)
            if parsed is None or parsed[0] is None:
                continue
            value_num, value_text, unit = parsed
            ref_low, ref_high = _parse_range(tail)
            label_raw = text[start:end].strip()
            resolution = resolve(label_raw, value_num, unit, ref_low, ref_high)
            analyte_id = resolution.analyte_id or analyte.id
            reason = _evaluate_field_reason(
                analyte_id, value_text, value_num, label_raw, resolution.mapping_rule
            )
            fields.append(
                ExtractedField(
                    analyte_id=analyte_id,
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
                    reason=reason,
                )
            )
        return fields

    # If table column template is carried, attempt column-aligned extraction
    if template is not None:
        aligned = align_words_to_template(words, template)
        if aligned["value"] and aligned["label"]:
            val_text = " ".join(w.text for w in aligned["value"])
            parsed = _parse_value(val_text)
            if parsed and parsed[0] is not None:
                value_num, value_text, unit = parsed
                unit_raw = unit or (" ".join(w.text for w in aligned["unit"]) if aligned["unit"] else None)
                ref_text = " ".join(w.text for w in aligned["ref_range"]) if aligned["ref_range"] else ""
                ref_low, ref_high = _parse_range(ref_text)
                label_raw = " ".join(w.text for w in aligned["label"]).strip()

                if len(label_raw) >= 2 and not any(
                    re.search(rf"\b{re.escape(w)}\b", label_raw.lower())
                    for w in _NON_RESULT_WORDS
                ):
                    resolution = resolve(label_raw, value_num, unit_raw, ref_low, ref_high)
                    reason = _evaluate_field_reason(
                        resolution.analyte_id,
                        value_text,
                        value_num,
                        label_raw,
                        resolution.mapping_rule,
                    )
                    fields.append(
                        ExtractedField(
                            analyte_id=resolution.analyte_id,
                            label_raw=label_raw,
                            value_num=value_num,
                            value_text=value_text,
                            unit_raw=unit_raw,
                            ref_low=ref_low,
                            ref_high=ref_high,
                            flag_printed=_printed_flag(text),
                            bbox=_bbox_for_value(words, value_text or value_num),
                            page=page,
                            confidence=resolution.confidence,
                            mapping_rule=resolution.mapping_rule,
                            engine=engine,
                            reason=reason,
                        )
                    )
                    return fields

    num_match = _NUMBER.search(text)
    if not num_match or num_match.start() <= 1:
        return fields
    prefix = text[:num_match.start()].strip(" :-,")
    if not (2 <= len(prefix) <= 50 and re.match(r"^[A-Za-z]", prefix)):
        return fields
    if any(re.search(rf"\b{re.escape(word)}\b", prefix.lower()) for word in _NON_RESULT_WORDS):
        return fields
    if _PROSE_INDICATORS.search(prefix):
        return fields
    parsed = _parse_value(text[num_match.start():])
    if parsed is None or parsed[0] is None:
        return fields
    value_num, value_text, unit = parsed
    ref_low, ref_high = _parse_range(text[num_match.start():])
    label_raw = prefix
    reason = _evaluate_field_reason(
        None, value_text, value_num, label_raw, "unresolved"
    )
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
            reason=reason,
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
    if medications and re.search(r"\bOR\b", text, re.I):
        # Keep alternatives together; splitting this line would imply two scheduled medicines.
        return [ExtractedMedication(text.strip(), None, None, _confidence(words))]
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
    carried_template: TableTemplate | None = None

    for page_number, words in enumerate(pages, start=1):
        from smriti.classify import is_boilerplate
        if is_boilerplate(" ".join(word.text for word in words)):
            carried_template = None
            continue
        layout = assemble_page(words)
        page_header = find_table_header(layout.rows)
        if page_header is not None:
            carried_template = page_header

        in_table = page_header is None
        for row in layout.rows:
            if page_header is not None and row.bbox == page_header.bbox:
                in_table = True
                continue
            if not in_table:
                continue

            line = list(row.words)
            line_text = " ".join(w.text for w in line).strip()
            if row.bbox[1] > 0.35 and _SIGNATURE_END.search(line_text):
                break

            if capture_type == "printed" and doc_type in (
                "lab_report",
                "other",
                "discharge_summary",
            ):
                fields.extend(
                    _extract_line(line, page_number, engine, template=carried_template)
                )
            if capture_type == "printed" and doc_type in (
                "prescription",
                "pharmacy",
                "other",
                "discharge_summary",
            ):
                medications.extend(replace(med, page=page_number, bbox=row.bbox, engine=engine)
                                   for med in _extract_medications(line))
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


def extraction_candidates(page_words, doc_type, capture_type, *, engine=str(LOCAL_RULES)):
    """One page's layout at a time; scratch handles document-wide first-seen deduplication."""
    carried_template = None
    for page_number, words in enumerate(page_words, start=1):
        from smriti.classify import is_boilerplate
        if is_boilerplate(" ".join(word.text for word in words)):
            carried_template = None
            continue
        layout = assemble_page(words)
        page_header = find_table_header(layout.rows)
        if page_header is not None:
            carried_template = page_header
        in_table = page_header is None
        for row in layout.rows:
            if page_header is not None and row.bbox == page_header.bbox:
                in_table = True
                continue
            if not in_table:
                continue
            line = list(row.words)
            if row.bbox[1] > 0.35 and _SIGNATURE_END.search(" ".join(w.text for w in line).strip()):
                break
            if capture_type == "printed" and doc_type in ("lab_report", "other", "discharge_summary"):
                for field in _extract_line(line, page_number, engine, template=carried_template):
                    yield "field", field
            if capture_type == "printed" and doc_type in ("prescription", "pharmacy", "other", "discharge_summary"):
                for medication in _extract_medications(line):
                    yield "medication", replace(medication, page=page_number, bbox=row.bbox, engine=engine)
        del layout, words

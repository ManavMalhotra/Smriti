"""Clinical cross-check helpers. Runtime ownership and scheduling live in service/coordinator."""

from __future__ import annotations

import json

from smriti.checks import exact_numeric_second_read
from smriti.extract import ExtractedField, _bbox_for_value
from smriti.ocr import OcrWord


def cross_check_extractions(
    ocr_fields: list[ExtractedField],
    vlm_fields: list[ExtractedField],
    pages: list[list[OcrWord]],
) -> list[ExtractedField]:
    """Mandatory accuracy double-check: cross-reference OCR rules against VLM extraction."""
    vlm_by_key: dict[tuple[str, int], ExtractedField] = {
        ((f.analyte_id or f.label_raw).strip().lower(), f.page): f for f in vlm_fields
    }
    checked: list[ExtractedField] = []
    seen_vlm_keys: set[tuple[str, int]] = set()

    for ocr_f in ocr_fields:
        key = ((ocr_f.analyte_id or ocr_f.label_raw).strip().lower(), ocr_f.page)
        vlm_f = vlm_by_key.get(key)
        if vlm_f is not None:
            seen_vlm_keys.add(key)
            if ocr_f.value_num and vlm_f.value_num:
                matches, _err = exact_numeric_second_read(ocr_f.value_num, vlm_f.value_num)
                if matches:
                    reason = "Dual-read verified: OCR and Qwen3-VL exact match."
                    confidence = min(1.0, max(ocr_f.confidence, vlm_f.confidence) + 0.15)
                    engine = f"{ocr_f.engine}+{vlm_f.engine}"
                else:
                    reason = f"Dual-read discrepancy: OCR='{ocr_f.value_num}' vs VLM='{vlm_f.value_num}' - review required."
                    confidence = min(ocr_f.confidence, vlm_f.confidence)
                    engine = f"{ocr_f.engine}+{vlm_f.engine}"
            else:
                reason = ocr_f.reason or "Cross-checked with VLM."
                confidence = max(ocr_f.confidence, vlm_f.confidence)
                engine = f"{ocr_f.engine}+{vlm_f.engine}"

            checked.append(
                ExtractedField(
                    analyte_id=ocr_f.analyte_id or vlm_f.analyte_id,
                    label_raw=ocr_f.label_raw,
                    value_num=ocr_f.value_num or vlm_f.value_num,
                    value_text=ocr_f.value_text or vlm_f.value_text,
                    unit_raw=ocr_f.unit_raw or vlm_f.unit_raw,
                    ref_low=ocr_f.ref_low or vlm_f.ref_low,
                    ref_high=ocr_f.ref_high or vlm_f.ref_high,
                    flag_printed=ocr_f.flag_printed or vlm_f.flag_printed,
                    bbox=ocr_f.bbox,
                    page=ocr_f.page,
                    confidence=confidence,
                    mapping_rule=ocr_f.mapping_rule,
                    engine=engine,
                    reason=reason,
                    evidence_quote=ocr_f.evidence_quote,
                )
            )
        else:
            checked.append(
                ExtractedField(
                    analyte_id=ocr_f.analyte_id,
                    label_raw=ocr_f.label_raw,
                    value_num=ocr_f.value_num,
                    value_text=ocr_f.value_text,
                    unit_raw=ocr_f.unit_raw,
                    ref_low=ocr_f.ref_low,
                    ref_high=ocr_f.ref_high,
                    flag_printed=ocr_f.flag_printed,
                    bbox=ocr_f.bbox,
                    page=ocr_f.page,
                    confidence=ocr_f.confidence,
                    mapping_rule=ocr_f.mapping_rule,
                    engine=ocr_f.engine,
                    reason="OCR-only reading; Qwen3-VL did not confirm it. Review required.",
                    evidence_quote=ocr_f.evidence_quote,
                )
            )

    for key, vlm_f in vlm_by_key.items():
        if key not in seen_vlm_keys:
            page_idx = vlm_f.page - 1
            bbox = vlm_f.bbox
            if 0 <= page_idx < len(pages) and pages[page_idx]:
                bbox = _relocate_vlm_bbox(pages[page_idx], vlm_f)
            checked.append(
                ExtractedField(
                    analyte_id=vlm_f.analyte_id,
                    label_raw=vlm_f.label_raw,
                    value_num=vlm_f.value_num,
                    value_text=vlm_f.value_text,
                    unit_raw=vlm_f.unit_raw,
                    ref_low=vlm_f.ref_low,
                    ref_high=vlm_f.ref_high,
                    flag_printed=vlm_f.flag_printed,
                    bbox=bbox,
                    page=vlm_f.page,
                    confidence=vlm_f.confidence,
                    mapping_rule=vlm_f.mapping_rule,
                    engine=vlm_f.engine,
                    reason=vlm_f.reason or "Single-read (VLM only)",
                )
            )

    return checked


def _relocate_vlm_bbox(words: list[OcrWord], vlm_f: ExtractedField) -> list[float]:
    """Relocate VLM bounding box using exact value match or RapidFuzz label matching."""
    if not words:
        return vlm_f.bbox or [0.0, 0.0, 1.0, 1.0]

    candidate_bbox = None
    if vlm_f.value_num:
        candidate_bbox = _bbox_for_value(words, vlm_f.value_num)
    if candidate_bbox is None or candidate_bbox in ([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]):
        candidate_bbox = _bbox_for_value(words, vlm_f.label_raw)

    if candidate_bbox and candidate_bbox not in ([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 0.0, 0.0]):
        return candidate_bbox

    try:
        from rapidfuzz import fuzz
        from smriti.assembly import _row_groups, _bbox
        rows = _row_groups(words)
        best_score = 0.0
        best_row_bbox = None
        target_label = vlm_f.label_raw.strip().lower()

        for row_words in rows:
            row_text = " ".join(w.text for w in row_words).lower()
            score = fuzz.token_set_ratio(target_label, row_text)
            if score > best_score:
                best_score = score
                best_row_bbox = list(_bbox(row_words))

        if best_score >= 65 and best_row_bbox:
            return best_row_bbox
    except Exception:
        pass

    return candidate_bbox or vlm_f.bbox or [0.0, 0.0, 1.0, 1.0]


def _handwritten_pages(quality_json: str | None) -> set[int]:
    if not quality_json:
        return set()
    try:
        pages = json.loads(quality_json).get("pages", [])
    except (TypeError, ValueError):
        return set()
    return {
        item["page"]
        for item in pages
        if item.get("capture_type") == "handwritten"
        and isinstance(item.get("page"), int)
    }

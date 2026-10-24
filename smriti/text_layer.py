"""Digital PDF text-layer inspector.

A PDF page can carry a real text layer, a junk layer written by a scanner, or
no layer at all. Only a clean layer is trusted: it is faster and more exact
than OCR. Everything else falls back to OCR for that page alone.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from smriti.ocr import OcrWord

MIN_WORDS = 20
MAX_GARBAGE_RATIO = 0.02
MAX_CID_RATIO = 0.02
MAX_OUTSIDE_RATIO = 0.02
MAX_OVERLAP_RATIO = 0.25
FULL_PAGE_IMAGE_COVERAGE = 0.85
MODEL_VERSION = f"pymupdf:{pymupdf.__version__}"

_CID = re.compile(r"\(cid:\d+\)")
_NUMBER = re.compile(r"^[<>]?-?\d+(?:[.,]\d+)?$")
_RANGE = re.compile(r"^\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?$")
_UNIT = re.compile(
    r"(?i)^(?:%|mg|g|kg|ml|l|dl|ul|mg/dl|g/dl|mg/l|mmol/l|umol/l|iu/l|u/l|"
    r"miu/ml|ng/ml|pg/ml|cells/ul|/ul|meq/l|mmhg|bpm|mm/hr)$"
)


@dataclass(frozen=True)
class TextLayerInspection:
    usable: bool
    words: tuple[OcrWord, ...]
    metrics: dict


def _is_garbage(char: str) -> bool:
    if char == "\ufffd":
        return True
    return unicodedata.category(char) in {"Co", "Cs", "Cn", "Cc"}


def _transform(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    width: float,
    height: float,
    rotation: int,
) -> tuple[float, float, float, float]:
    left, right = x0 / width, x1 / width
    top, bottom = y0 / height, y1 / height
    if rotation == 90:
        return (1 - bottom, left, 1 - top, right)
    if rotation == 180:
        return (1 - right, 1 - bottom, 1 - left, 1 - top)
    if rotation == 270:
        return (top, 1 - right, bottom, 1 - left)
    return (left, top, right, bottom)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _overlap_ratio(boxes: list[tuple[float, float, float, float]]) -> float:
    if len(boxes) < 2:
        return 0.0
    order = sorted(range(len(boxes)), key=lambda index: boxes[index][0])
    hits = 0
    for position, first in enumerate(order):
        ax0, ay0, ax1, ay1 = boxes[first]
        area_first = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
        for second in order[position + 1 :]:
            bx0, by0, bx1, by1 = boxes[second]
            if bx0 >= ax1:
                break
            width = min(ax1, bx1) - max(ax0, bx0)
            height = min(ay1, by1) - max(ay0, by0)
            if width <= 0 or height <= 0:
                continue
            area_second = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
            smaller = min(area_first, area_second)
            if smaller > 0 and width * height / smaller > 0.5:
                hits += 1
                break
    return hits / len(boxes)


def inspect(
    raw_words,
    *,
    width: float,
    height: float,
    rotation: int = 0,
    image_coverage: float = 0.0,
) -> TextLayerInspection:
    """Decide whether a page's text layer can replace OCR for that page."""
    if width <= 0 or height <= 0:
        return TextLayerInspection(False, (), {"words": 0, "reason": "bad_page_box"})
    tokens = [word for word in raw_words if word[4].strip()]
    characters = [char for word in tokens for char in word[4]]
    garbage = sum(1 for char in characters if _is_garbage(char))
    cid = sum(1 for word in tokens if _CID.search(word[4]))

    words: list[OcrWord] = []
    boxes: list[tuple[float, float, float, float]] = []
    outside = 0
    numeric = 0
    anchors = 0
    for x0, y0, x1, y1, text, *_ in tokens:
        left, top, right, bottom = _transform(
            x0, y0, x1, y1, width, height, rotation
        )
        if left < -0.01 or top < -0.01 or right > 1.01 or bottom > 1.01:
            outside += 1
        box = (_clamp(left), _clamp(top), _clamp(right), _clamp(bottom))
        boxes.append(box)
        words.append(OcrWord(text=text, bbox=list(box), confidence=1.0))
        if _NUMBER.match(text):
            numeric += 1
        elif _RANGE.match(text) or _UNIT.match(text):
            anchors += 1

    total = max(1, len(tokens))
    garbage_ratio = garbage / max(1, len(characters))
    cid_ratio = cid / total
    outside_ratio = outside / total
    overlap_ratio = _overlap_ratio(boxes)

    failures: list[str] = []
    if len(tokens) < MIN_WORDS:
        failures.append("too_few_words")
    if garbage_ratio > MAX_GARBAGE_RATIO:
        failures.append("garbage_characters")
    if cid_ratio > MAX_CID_RATIO:
        failures.append("cid_glyphs")
    if outside_ratio > MAX_OUTSIDE_RATIO:
        failures.append("outside_page")
    if overlap_ratio > MAX_OVERLAP_RATIO:
        failures.append("overlapping_boxes")
    if image_coverage >= FULL_PAGE_IMAGE_COVERAGE:
        # A scan with an OCR layer: the layer may look fine and still be wrong.
        failures.append("full_page_image")

    metrics = {
        "words": len(tokens),
        "garbage_ratio": round(garbage_ratio, 4),
        "cid_ratio": round(cid_ratio, 4),
        "outside_ratio": round(outside_ratio, 4),
        "overlap_ratio": round(overlap_ratio, 4),
        "numeric_ratio": round(numeric / total, 4),
        "anchors": anchors,
        "image_coverage": round(image_coverage, 4),
        "reason": ",".join(failures) or None,
    }
    usable = not failures
    return TextLayerInspection(usable, tuple(words) if usable else (), metrics)


def _image_coverage(page: pymupdf.Page, box: pymupdf.Rect) -> float:
    area = box.width * box.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"])
        covered = max(covered, max(0.0, rect.width) * max(0.0, rect.height) / area)
    return min(covered, 1.0)


def inspect_page(page: pymupdf.Page) -> TextLayerInspection:
    box = page.cropbox
    try:
        raw = page.get_text("words", sort=True)
        coverage = _image_coverage(page, box)
    except Exception:
        # A malformed page must not fail the upload; OCR is the safe fallback.
        return TextLayerInspection(False, (), {"words": 0, "reason": "text_layer_error"})
    return inspect(
        raw,
        width=box.width,
        height=box.height,
        rotation=page.rotation % 360,
        image_coverage=coverage,
    )


def words_path(page_image: Path) -> Path:
    return page_image.with_suffix(".words.json")


def save_words(path: Path, words) -> None:
    payload = {
        "source": "text_layer",
        "words": [
            {"text": word.text, "bbox": word.bbox, "confidence": word.confidence}
            for word in words
        ],
    }
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")


def load_words(path: Path) -> list[OcrWord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        OcrWord(
            text=item["text"],
            bbox=[float(value) for value in item["bbox"]],
            confidence=float(item["confidence"]),
        )
        for item in payload["words"]
    ]

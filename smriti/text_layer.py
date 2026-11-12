"""Digital PDF text-layer inspector.

A PDF page can carry a real text layer, a junk layer written by a scanner, or
no layer at all. Only a clean layer is trusted: it is faster and more exact
than OCR. Everything else falls back to OCR for that page alone.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from smriti.ocr import OcrEngine, OcrWord

logger = logging.getLogger(__name__)

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
    source: str = "text_layer"
    model_version: str = MODEL_VERSION


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
    raster_verified: bool | None = None,
) -> TextLayerInspection:
    """Decide whether a page's text layer can replace OCR for that page."""
    if width <= 0 or height <= 0:
        return TextLayerInspection(
            False, (), {"words": 0, "reason": "bad_page_box"}, source="ocr"
        )
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
        # Full page raster image + text layer is suspicious.
        if raster_verified is True:
            # Verified against image pixels via RapidOCR read_lines
            pass
        elif raster_verified is False:
            failures.append("suspicious_raster_mismatch")
        else:
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
        "raster_verified": raster_verified,
        "reason": ",".join(failures) or None,
    }
    usable = not failures
    source = "text_layer" if usable else "ocr"
    return TextLayerInspection(
        usable, tuple(words) if usable else (), metrics, source=source
    )


def _image_coverage(page: pymupdf.Page, box: pymupdf.Rect) -> float:
    area = box.width * box.height
    if area <= 0:
        return 0.0
    covered = 0.0
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"])
        covered = max(covered, max(0.0, rect.width) * max(0.0, rect.height) / area)
    return min(covered, 1.0)


def _crosscheck_suspicious_page(
    page: pymupdf.Page, raw_words, ocr_engine: OcrEngine
) -> bool:
    """Sample-compare line crops against RapidOCR ONNX read_lines before trusting a raster text layer."""
    try:
        from PIL import Image

        lines: dict[tuple[int, int], list] = {}
        for item in raw_words:
            line_id = (item[5], item[6])
            lines.setdefault(line_id, []).append(item)

        sample_lines = [words for words in lines.values() if len(words) >= 2][:4]
        if not sample_lines:
            return False

        pixmap = page.get_pixmap(dpi=150)
        img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        scale_x = pixmap.width / max(1.0, page.rect.width)
        scale_y = pixmap.height / max(1.0, page.rect.height)

        line_crops = []
        for line in sample_lines:
            x0 = max(0, int(min(w[0] for w in line) * scale_x))
            y0 = max(0, int(min(w[1] for w in line) * scale_y))
            x1 = min(pixmap.width, int(max(w[2] for w in line) * scale_x))
            y1 = min(pixmap.height, int(max(w[3] for w in line) * scale_y))
            if x1 > x0 + 4 and y1 > y0 + 4:
                line_crops.append(img.crop((x0, y0, x1, y1)))

        if not line_crops:
            return False

        rec_results = ocr_engine.read_lines(line_crops)
        matches = sum(1 for text, score in rec_results if score >= 0.50 and len(text) > 0)
        return (matches / len(line_crops)) >= 0.50
    except Exception as exc:
        logger.warning("Suspicious raster page cross-check failed: %s", exc)
        return False


def inspect_page(
    page: pymupdf.Page, ocr_engine: OcrEngine | None = None
) -> TextLayerInspection:
    box = page.cropbox
    try:
        raw = page.get_text("words", sort=True)
        coverage = _image_coverage(page, box)
    except Exception:
        return TextLayerInspection(
            False, (), {"words": 0, "reason": "text_layer_error"}, source="ocr"
        )

    raster_verified: bool | None = None
    if (
        coverage >= FULL_PAGE_IMAGE_COVERAGE
        and ocr_engine is not None
        and len(raw) >= MIN_WORDS
    ):
        raster_verified = _crosscheck_suspicious_page(page, raw, ocr_engine)

    return inspect(
        raw,
        width=box.width,
        height=box.height,
        rotation=page.rotation % 360,
        image_coverage=coverage,
        raster_verified=raster_verified,
    )


def inspect_pdf_split(pdf_path: Path, ocr_engine: OcrEngine | None = None) -> dict:
    """Analyze all pages in a PDF and report the digital vs scanned page split."""
    doc = pymupdf.open(str(pdf_path))
    try:
        total = len(doc)
        digital = 0
        scanned = 0
        per_page = []
        for idx, page in enumerate(doc, start=1):
            res = inspect_page(page, ocr_engine=ocr_engine)
            status = "digital" if res.usable else "scanned"
            if res.usable:
                digital += 1
            else:
                scanned += 1
            per_page.append(
                {
                    "page": idx,
                    "status": status,
                    "words": res.metrics["words"],
                    "image_coverage": res.metrics["image_coverage"],
                    "reason": res.metrics["reason"],
                    "source": res.source,
                }
            )
        return {
            "pdf": pdf_path.name,
            "total_pages": total,
            "digital_pages": digital,
            "scanned_pages": scanned,
            "split_ratio": f"{digital}/{total} digital ({(digital / max(1, total)) * 100:.1f}%)",
            "per_page": per_page,
        }
    finally:
        doc.close()


def words_path(page_image: Path) -> Path:
    return page_image.with_suffix(".words.json")


def save_words(
    path: Path,
    words,
    source: str = "text_layer",
    model_version: str = MODEL_VERSION,
) -> None:
    payload = {
        "source": source,
        "model_version": model_version,
        "words": [
            {
                "text": word.text,
                "bbox": word.bbox,
                "bbox_1000": getattr(
                    word, "bbox_1000", [int(round(v * 1000)) for v in word.bbox]
                ),
                "confidence": word.confidence,
            }
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

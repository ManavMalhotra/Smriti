"""Pure page geometry. No I/O, no config reads: callers compose these steps."""

from __future__ import annotations

import cv2
import io
import re
import uuid
import numpy as np
from PIL import Image, ImageOps

PIPELINE: tuple[str, ...] = (
    "exif_strip",
    "rotate",
    "perspective",
    "deskew",
    "clahe",
    "upscale",
    "downscale",
)


def to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def find_page_quad(bgr: np.ndarray) -> np.ndarray | None:
    """Return the largest four-corner contour that covers most of the frame."""
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best: np.ndarray | None = None
    best_area = 0.0
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        x, _y, w, h = cv2.boundingRect(approx)
        if w < 0.7 * width or h < 0.7 * height:
            continue
        area = cv2.contourArea(approx)
        if area > best_area:
            best_area = area
            best = approx.reshape(4, 2).astype(np.float32)
    return best


def order_quad(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).ravel()
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def warp_perspective(bgr: np.ndarray, quad: np.ndarray) -> np.ndarray:
    top_left, top_right, bottom_right, bottom_left = order_quad(quad)
    width = int(
        max(
            np.linalg.norm(top_right - top_left),
            np.linalg.norm(bottom_right - bottom_left),
        )
    )
    height = int(
        max(
            np.linalg.norm(bottom_left - top_left),
            np.linalg.norm(bottom_right - top_right),
        )
    )
    if width < 2 or height < 2:
        return bgr
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(
        np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32),
        destination,
    )
    return cv2.warpPerspective(
        bgr,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def estimate_skew(bgr: np.ndarray) -> float:
    """Estimate page rotation in degrees; zero when no reliable ink is present."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(
        cv2.GaussianBlur(gray, (3, 3), 0),
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    coordinates = cv2.findNonZero(mask)
    if coordinates is None or len(coordinates) < 50:
        return 0.0
    raw_angle = cv2.minAreaRect(coordinates)[-1]
    # minAreaRect uses different angle conventions across OpenCV releases.
    # Fold the rectangle angle into (-45, 45] so the result is version-stable.
    angle = (90 - raw_angle + 45) % 90 - 45
    return float(angle) if abs(angle) <= 15 else 0.0


def rotate(bgr: np.ndarray, angle: float) -> np.ndarray:
    height, width = bgr.shape[:2]
    center = (width / 2, height / 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    cosine, sine = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width = int(height * sine + width * cosine)
    new_height = int(height * cosine + width * sine)
    matrix[0, 2] += new_width / 2 - center[0]
    matrix[1, 2] += new_height / 2 - center[1]
    return cv2.warpAffine(
        bgr,
        matrix,
        (new_width, new_height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def apply_clahe(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness, a_channel, b_channel = cv2.split(lab)
    equalised = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((equalised, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


def upscale(bgr: np.ndarray, min_long_edge: int = 1500) -> np.ndarray:
    height, width = bgr.shape[:2]
    long_edge = max(height, width)
    if long_edge >= min_long_edge:
        return bgr
    scale = min_long_edge / long_edge
    return cv2.resize(
        bgr,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_CUBIC,
    )


def downscale(bgr: np.ndarray, max_long_edge: int = 1800) -> np.ndarray:
    height, width = bgr.shape[:2]
    long_edge = max(height, width)
    if long_edge <= max_long_edge:
        return bgr
    scale = max_long_edge / long_edge
    return cv2.resize(
        bgr,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )


def normalise_page(
    image: Image.Image,
    upscale_long_edge: int = 1500,
    max_long_edge: int = 1800,
    geometry: bool = True,
) -> tuple[np.ndarray, list[str]]:
    orientation = image.getexif().get(0x0112)
    rotated = bool(image.info.pop("smriti_exif_rotated", False))
    image = ImageOps.exif_transpose(image)
    bgr = to_bgr(image)

    steps = ["exif_strip"]
    if orientation or rotated:
        steps.append("rotate")

    # Digital pages keep their own geometry so text-layer boxes stay aligned.
    if geometry:
        quad = find_page_quad(bgr)
        if quad is not None:
            bgr = warp_perspective(bgr, quad)
            steps.append("perspective")

        angle = estimate_skew(bgr)
        if abs(angle) >= 0.2:
            bgr = rotate(bgr, angle)
            steps.append("deskew")

    bgr = apply_clahe(bgr)
    steps.append("clahe")

    if max(bgr.shape[:2]) < upscale_long_edge:
        bgr = upscale(bgr, upscale_long_edge)
        steps.append("upscale")
    elif max(bgr.shape[:2]) > max_long_edge:
        bgr = downscale(bgr, max_long_edge)
        steps.append("downscale")

    return bgr, steps


_PII_ANCHOR = re.compile(
    r"patient\s*name|\bname\s*:|\bmrs?\.|\buhid\b|regn\s*no|registration\s*no|"
    r"episode\s*no|booking\s*id|order\s*id|patient\s*id|\bdob\b|date\s*of\s*birth|"
    r"address|barcode|sin\s*no|\bmobile\b|\bphone\b",
    re.I,
)
_PII_PATTERN = re.compile(r"\b[6-9]\d{9}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def propose_pii_masks(ocr_boxes, width, height, discovered_pii_tokens=(), image_np=None):
    """Return editable pixel-coordinate masks; do not alter the source image."""
    from rapidfuzz.fuzz import partial_ratio

    boxes = _redaction_boxes(ocr_boxes, width, height)
    tokens = set(discovered_pii_tokens) | discover_pii_tokens(ocr_boxes)
    proposals, seen = [], set()

    def add(box, label):
        x0, y0, x1, y1 = (max(0, int(box[0])), max(0, int(box[1])),
                          min(width, int(box[2])), min(height, int(box[3])))
        if x1 <= x0 or y1 <= y0:
            return
        key = (x0, y0, x1, y1, label)
        if key not in seen:
            seen.add(key)
            proposals.append([x0, y0, x1 - x0, y1 - y0, label, str(uuid.uuid4())])

    for text, (x0, y0, x1, y1) in boxes:
        if _PII_ANCHOR.search(text):
            add((x0, y0, x1 + int(3.5 * (x1 - x0)), y1 + int(1.3 * (y1 - y0)),), "label_value")
        if _PII_PATTERN.search(text):
            add((x0, y0, x1, y1), "contact")
        elif any(partial_ratio(text.casefold(), token.casefold()) >= 70 for token in tokens if len(token) >= 3):
            add((x0, y0, x1, y1), "name")
        if re.search(r"\b(?:dob|date of birth|age|sex|gender|uhid|patient id|id no|address)\b", text, re.I):
            add((x0, y0, x1 + int(4 * (x1 - x0)), y1 + int(1.5 * (y1 - y0))), "demographic")
    for index, (text, box) in enumerate(boxes):
        if text.casefold().strip() == "patient":
            for value, other in boxes[index + 1:]:
                if "name" in value.casefold() and abs(other[1] - box[1]) < max(10, box[3] - box[1]):
                    add((box[0], box[1], other[2] + int(3.5 * (other[2] - box[0])), max(box[3], other[3])), "name")
                    break
    if image_np is not None:
        found, points = cv2.QRCodeDetector().detectMulti(image_np)
        if found and points is not None:
            for corners in points:
                add((corners[:, 0].min(), corners[:, 1].min(),
                     corners[:, 0].max(), corners[:, 1].max()), "barcode")
    return proposals


def apply_pii_masks(image_np, masks, page_num):
    if image_np.dtype != np.uint8 or image_np.ndim != 3 or image_np.shape[2] != 3 or page_num < 1:
        raise ValueError("Redaction requires a BGR page and positive source page")
    image = image_np.copy()
    height, width = image.shape[:2]
    for mask in masks:
        if (not isinstance(mask, list) or len(mask) != 6 or type(mask[0]) is not int
                or type(mask[1]) is not int or type(mask[2]) is not int or type(mask[3]) is not int
                or not isinstance(mask[4], str) or not isinstance(mask[5], str)
                or mask[0] < 0 or mask[1] < 0 or mask[2] < 1 or mask[3] < 1
                or mask[0] + mask[2] > 1000 or mask[1] + mask[3] > 1000):
            raise ValueError("Invalid user redaction mask")
        x0, y0 = int(mask[0] * width / 1000), int(mask[1] * height / 1000)
        x1, y1 = int((mask[0] + mask[2]) * width / 1000), int((mask[1] + mask[3]) * height / 1000)
        cv2.rectangle(image, (x0, y0), (x1, y1), (0, 0, 0), -1)
    stamp = f"SOURCE_PAGE: {page_num}"
    scale = min(.55, max(.2, width / 900))
    (tw, th), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = max(0, width - tw - 8), min(height - 2, 35)
    cv2.rectangle(image, (max(0, x - 4), max(0, y - th - 4)), (width - 1, min(height - 1, y + 4)), (0, 0, 0), -1)
    cv2.putText(image, stamp, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    output = io.BytesIO()
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(output, format="JPEG", quality=95, subsampling=0)
    return output.getvalue()


def encode_preview(image_np):
    output = io.BytesIO()
    Image.fromarray(cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)).save(output, format="JPEG", quality=85, subsampling=0)
    return output.getvalue()


def _redaction_boxes(ocr_boxes, width, height):
    boxes = []
    for word in ocr_boxes:
        text = word["text"] if isinstance(word, dict) else word.text
        box = word["bbox"] if isinstance(word, dict) else word.bbox
        if (len(box) != 4 or not np.isfinite(box).all()
                or box[0] >= box[2] or box[1] >= box[3] or min(box) < 0):
            raise ValueError("Invalid OCR box for redaction")
        scale = [width, height, width, height] if max(box) <= 1 else [1] * 4
        boxes.append((text, [int(v * s) for v, s in zip(box, scale)]))
    return boxes


def discover_pii_tokens(ocr_boxes) -> set[str]:
    """Discover names locally before masking any page, including split OCR labels."""
    from smriti.extract import _line_groups
    from smriti.ocr import OcrWord

    words = [OcrWord(**word) if isinstance(word, dict) else word for word in ocr_boxes]
    tokens = set()
    for line in _line_groups(words):
        match = re.search(r"patient\s*name\s*[:.-]?\s*(.+)", " ".join(w.text for w in line), re.I)
        if match:
            name = re.split(r"\b(?:age|sex|gender|uhid|regn|dob)\b|[;|]", match[1], flags=re.I)[0]
            tokens.update(token.casefold() for token in re.findall(r"[A-Za-z]{3,}", name)
                          if token.casefold() not in {"mr", "mrs", "miss", "name", "patient"})
    return tokens


def redact_page_for_cloud(image_np: np.ndarray, ocr_boxes: list, discovered_pii_tokens: set[str],
                          is_handwritten_opd: bool, page_num: int, extra_user_boxes: list | None = None) -> bytes:
    """Mask a BGR raster; OCR boxes are xyxy, user boxes are yxyx in 0–1000."""
    from rapidfuzz.fuzz import partial_ratio

    if image_np.dtype != np.uint8 or image_np.ndim != 3 or image_np.shape[2] != 3 or page_num < 1:
        raise ValueError("Redaction requires a BGR page and positive source page")
    image = image_np.copy()
    height, width = image.shape[:2]
    boxes = _redaction_boxes(ocr_boxes, width, height)
    discovered_pii_tokens.update(discover_pii_tokens(ocr_boxes))

    def mask(box, padding=0):
        x0, y0, x1, y1 = box
        cv2.rectangle(image, (max(0, x0 - padding), max(0, y0 - padding)),
                      (min(width - 1, x1 + padding), min(height - 1, y1 + padding)), (0, 0, 0), -1)

    for text, (x0, y0, x1, y1) in boxes:
        if _PII_ANCHOR.search(text):
            mask([x0, y0, x1 + int(3.5 * (x1 - x0)), y0 + int(1.3 * (y1 - y0))], 10)
        if (_PII_PATTERN.search(text) or any(partial_ratio(text.casefold(), token.casefold()) >= 70
                                           for token in discovered_pii_tokens if len(token) >= 3)):
            mask([x0, y0, x1, y1], 10)
    # Split labels such as separate "Patient" / "Name" words also mask their adjacent value.
    for index, (text, box) in enumerate(boxes):
        if text.casefold().strip() == "patient":
            for other_text, other in boxes[index + 1:]:
                if "name" in other_text.casefold() and abs(other[1] - box[1]) < max(10, box[3] - box[1]):
                    mask([box[0], box[1], other[2] + int(3.5 * (other[2] - box[0])), max(box[3], other[3])], 10)
                    break
    detector = cv2.QRCodeDetector()
    found, points = detector.detectMulti(image_np)
    if found and points is not None:
        for corners in points:
            mask([int(corners[:, 0].min()), int(corners[:, 1].min()),
                  int(corners[:, 0].max()), int(corners[:, 1].max())], 10)
    if is_handwritten_opd:
        letterhead_bottom = max((box[3] for text, box in boxes if box[3] <= height * .25
                                and re.search(r"doctor|hospital|clinic|consultant|\bdr\.?|mbbs|\bmd\b", text, re.I)),
                               default=int(height * .15))
        # shortcut: heuristic 80px demographic strip; user preview is mandatory, upgrade with labeled OPD layouts.
        mask([0, letterhead_bottom, int(width * .65), letterhead_bottom + 80])
    for box in extra_user_boxes or []:
        if (len(box) != 4 or any(type(v) is not int or not 0 <= v <= 1000 for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise ValueError("Invalid user redaction box")
        y0, x0, y1, x1 = box
        mask([int(x0 * width / 1000), int(y0 * height / 1000),
              int(x1 * width / 1000), int(y1 * height / 1000)])
    stamp = f"SOURCE_PAGE: {page_num}"
    scale = min(.55, max(.2, width / 900))
    (text_width, text_height), _ = cv2.getTextSize(stamp, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = max(0, width - text_width - 8), min(height - 2, 35)
    cv2.rectangle(image, (x - 4, max(0, y - text_height - 4)), (width - 1, min(height - 1, y + 4)), (0, 0, 0), -1)
    cv2.putText(image, stamp, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    output = io.BytesIO()
    Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB)).save(output, format="JPEG", quality=95, subsampling=0)
    return output.getvalue()

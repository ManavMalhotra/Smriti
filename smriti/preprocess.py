"""Pure page geometry. No I/O, no config reads: callers compose these steps."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageOps

PIPELINE: tuple[str, ...] = (
    "exif_strip",
    "rotate",
    "perspective",
    "deskew",
    "clahe",
    "upscale",
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


def normalise_page(image: Image.Image, upscale_long_edge: int = 1500) -> tuple[np.ndarray, list[str]]:
    orientation = image.getexif().get(0x0112)
    rotated = bool(image.info.pop("smriti_exif_rotated", False))
    image = ImageOps.exif_transpose(image)
    bgr = to_bgr(image)

    steps = ["exif_strip"]
    if orientation or rotated:
        steps.append("rotate")

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

    return bgr, steps

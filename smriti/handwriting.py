"""Server-side capture-type detection.

Conservative by design: anything that does not look strongly like machine-printed
text is marked handwritten, so it can never be auto-accepted.
"""

from __future__ import annotations

import cv2
import numpy as np


def _component_features(
    bgr: np.ndarray,
) -> tuple[int, float, float, float, float, float, float]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)

    heights: list[int] = []
    widths: list[int] = []
    centres: list[float] = []
    fills: list[float] = []
    solids: list[float] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 6 or height < 3:
            continue
        heights.append(int(height))
        widths.append(int(width))
        centres.append(y + height / 2)
        fills.append(area / (width * height))
        patch = (labels[y : y + height, x : x + width] == index).astype(np.uint8)
        contours, _ = cv2.findContours(
            patch, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        hull_area = cv2.contourArea(cv2.convexHull(contours[0])) if contours else area
        solids.append(area / hull_area if hull_area else 0.0)

    if not heights:
        return 0, 9.0, 9.0, 9.0, 0.0, 0.0, 0.0

    height_array = np.asarray(heights, dtype=np.float64)
    width_array = np.asarray(widths, dtype=np.float64)
    centre_array = np.asarray(centres, dtype=np.float64)
    median_height = float(np.median(height_array))
    height_cv = float(height_array.std() / max(1.0, height_array.mean()))
    baseline_ratio = float(centre_array.std() / max(1.0, median_height))
    median_width_height = float(np.median(width_array / height_array))
    median_fill = float(np.median(fills))
    median_solidity = float(np.median(solids))

    gradient_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = np.hypot(gradient_x, gradient_y)
    angle = np.abs(np.arctan2(gradient_y, gradient_x)) * 180 / np.pi
    strong = magnitude > 30
    axis_ratio = (
        float(np.mean((angle[strong] < 20) | (angle[strong] > 70)))
        if strong.any()
        else 0.0
    )

    return (
        len(heights),
        height_cv,
        baseline_ratio,
        median_width_height,
        median_fill,
        median_solidity,
        axis_ratio,
    )


def detect_capture_type(bgr: np.ndarray) -> str:
    # shortcut: heuristic detector, not a trained classifier. It defaults to
    # handwritten on doubt; replace with OCR/classifier evidence after P2 evaluation.
    (
        count,
        height_cv,
        _baseline_ratio,
        width_height,
        fill,
        solidity,
        axis_ratio,
    ) = _component_features(bgr)

    # Machine-printed text features:
    # - Discrete glyphs: count >= 150
    # - Real documents have mixed font sizes (headings, tables, footnotes),
    #   so height_cv can range up to 2.2 across titles and small table text.
    # - Bounding box aspect ratios for standard letter glyphs: 0.15 to 2.2
    # - Solid letter strokes: fill >= 0.25 and solidity >= 0.45
    # - Orthogonal horizontal/vertical stems: axis_ratio >= 0.60
    looks_printed = (
        count >= 150
        and height_cv <= 2.2
        and 0.15 <= width_height <= 2.2
        and fill >= 0.25
        and solidity >= 0.45
        and axis_ratio >= 0.60
    )
    return "printed" if looks_printed else "handwritten"

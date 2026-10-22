"""Hard quality checks and a 64-bit perceptual hash for duplicate pages."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class QualityMetrics:
    width: int
    height: int
    short_edge: int
    long_edge: int
    aspect: float
    laplacian: float
    ink_ratio: float
    score: float

    def as_dict(self) -> dict:
        return asdict(self)


def measure(bgr: np.ndarray) -> QualityMetrics:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    short_edge = min(height, width)
    long_edge = max(height, width)
    laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    _, mask = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    ink_ratio = float(np.count_nonzero(mask)) / mask.size

    score = min(short_edge / 1500, laplacian / 300, 1.0)
    return QualityMetrics(
        width=width,
        height=height,
        short_edge=short_edge,
        long_edge=long_edge,
        aspect=round(long_edge / max(1, short_edge), 3),
        laplacian=round(laplacian, 1),
        ink_ratio=round(ink_ratio, 5),
        score=round(max(0.0, score), 3),
    )


def failure(
    metrics: QualityMetrics,
    *,
    min_short_edge: int = 1000,
    blur_floor: float = 100.0,
    max_aspect: float = 4.0,
    min_ink_ratio: float = 0.0005,
) -> str | None:
    if metrics.short_edge < min_short_edge:
        return f"Short edge {metrics.short_edge} px is below {min_short_edge} px."
    if metrics.ink_ratio < min_ink_ratio:
        return "Page appears blank."
    if metrics.laplacian < blur_floor:
        return f"Blur score {metrics.laplacian:.1f} is below {blur_floor:.0f}."
    if metrics.aspect > max_aspect:
        return f"Aspect ratio {metrics.aspect:.2f} is implausible."
    return None


def dhash(bgr: np.ndarray, hash_size: int = 8) -> int:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(
        gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA
    )
    differences = resized[:, 1:] > resized[:, :-1]
    bits = "".join("1" if value else "0" for value in differences.flatten())
    return int(bits, 2)


def is_duplicate(first: int, second: int, threshold: int = 3) -> bool:
    return (first ^ second).bit_count() <= threshold

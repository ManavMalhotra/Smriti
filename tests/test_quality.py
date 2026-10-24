from __future__ import annotations

import io

import pytest
from PIL import Image

from smriti import quality
from smriti.config import Settings
from smriti.preprocess import to_bgr
from tests.factory import (
    blurred_image,
    handwritten_image,
    jpeg_bytes,
    shadowed_image,
    skewed_image,
    text_image,
)

pytestmark = pytest.mark.unit


def _check(image: Image.Image):
    metrics = quality.measure(to_bgr(image))
    settings = Settings()
    reason = quality.failure(
        metrics,
        min_short_edge=settings.quality_min_short_edge,
        blur_floor=settings.quality_blur,
        max_aspect=settings.quality_max_aspect,
        min_ink_ratio=settings.quality_min_ink_ratio,
    )
    return metrics, reason


def test_five_document_fixture_set_passes():
    fixtures = {
        "clean": text_image(),
        "skewed": skewed_image(text_image(), 5),
        "shadowed": shadowed_image(text_image()),
        "compressed": Image.open(io.BytesIO(jpeg_bytes(text_image(), quality=30))),
        "handwritten": handwritten_image(),
    }
    for name, image in fixtures.items():
        metrics, reason = _check(image)
        assert reason is None, f"{name}: {reason}"
        assert metrics.score > 0


def test_low_resolution_is_rejected():
    image = text_image(width=600, height=800, lines=8, font_size=14, line_gap=30)
    _metrics, reason = _check(image)
    assert reason is not None
    assert "Short edge" in reason


def test_blurred_page_is_rejected():
    _metrics, reason = _check(blurred_image(text_image(), radius=8))
    assert reason is not None
    assert "Blur score" in reason


def test_blank_page_is_rejected():
    _metrics, reason = _check(Image.new("RGB", (1200, 1600), "white"))
    assert reason == "Page appears blank."


def test_implausible_aspect_ratio_is_rejected():
    image = text_image(width=5000, height=1000, lines=8)
    _metrics, reason = _check(image)
    assert reason is not None
    assert "Aspect ratio" in reason


def test_perceptual_hash_detects_duplicates():
    first = quality.dhash(to_bgr(text_image()))
    second = quality.dhash(to_bgr(text_image()))
    different = quality.dhash(to_bgr(handwritten_image()))
    assert quality.is_duplicate(first, second)
    assert not quality.is_duplicate(first, different)

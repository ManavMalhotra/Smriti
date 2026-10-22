from __future__ import annotations

from smriti.preprocess import PIPELINE, estimate_skew, normalise_page, to_bgr
from tests.factory import skewed_image, text_image


def test_preprocess_order_is_recorded_in_pipeline_order():
    _processed, steps = normalise_page(text_image())
    positions = [PIPELINE.index(step) for step in steps]
    assert positions == sorted(positions)
    assert steps[0] == "exif_strip"
    assert set(steps) <= set(PIPELINE)


def test_deskew_estimate_stays_within_half_a_degree():
    for degrees in (7, -7, 3, -3):
        image = skewed_image(text_image(), degrees)
        assert abs(estimate_skew(to_bgr(image)) - degrees) <= 0.5


def test_small_page_is_upscaled_to_1500_long_edge():
    image = text_image(width=1000, height=1200, lines=12, font_size=18, line_gap=40)
    processed, steps = normalise_page(image)
    assert max(processed.shape[:2]) >= 1500
    assert "upscale" in steps

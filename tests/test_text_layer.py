from __future__ import annotations

import pytest

from smriti.text_layer import (
    _transform,
    inspect,
    load_words,
    save_words,
    words_path,
)
from smriti.ocr import OcrWord

pytestmark = pytest.mark.unit


def _word(text: str, x: float, y: float, width: float = 0.05, height: float = 0.02):
    return (x, y, x + width, y + height, text, 0, 0, 0)


def _grid(count: int = 30, text: str = "word") -> list[tuple]:
    words = []
    for index in range(count):
        row, column = divmod(index, 6)
        words.append(
            _word(f"{text}{index}", 0.05 + column * 0.15, 0.05 + row * 0.05)
        )
    return words


def test_clean_layer_is_usable_and_normalised():
    result = inspect(_grid(), width=1.0, height=1.0)
    assert result.usable
    assert len(result.words) == 30
    assert all(0.0 <= value <= 1.0 for word in result.words for value in word.bbox)
    assert result.metrics["reason"] is None


def test_cid_glyphs_fall_back_to_ocr():
    words = _grid() + [_word("(cid:12)", 0.9, 0.9)] * 3
    result = inspect(words, width=1.0, height=1.0)
    assert not result.usable
    assert "cid_glyphs" in result.metrics["reason"]


def test_private_use_characters_fall_back_to_ocr():
    words = [_word("\ue000\ue001glyph", 0.05 + index * 0.15, 0.05) for index in range(10)]
    words += _grid(20)
    result = inspect(words, width=1.0, height=1.0)
    assert not result.usable
    assert "garbage_characters" in result.metrics["reason"]


def test_devanagari_is_text_not_garbage():
    words = _grid(30, text="रक्त")
    result = inspect(words, width=1.0, height=1.0)
    assert result.usable


def test_words_outside_the_page_fall_back_to_ocr():
    words = _grid(29) + [_word("stray", 1.4, 0.5)]
    result = inspect(words, width=1.0, height=1.0)
    assert not result.usable
    assert "outside_page" in result.metrics["reason"]


def test_overlapping_boxes_fall_back_to_ocr():
    words = [_word("double", 0.2, 0.2) for _ in range(30)]
    result = inspect(words, width=1.0, height=1.0)
    assert not result.usable
    assert "overlapping_boxes" in result.metrics["reason"]


def test_full_page_image_is_treated_as_a_scan():
    result = inspect(_grid(), width=1.0, height=1.0, image_coverage=0.95)
    assert not result.usable
    assert "full_page_image" in result.metrics["reason"]


def test_too_few_words_fall_back_to_ocr():
    result = inspect(_grid(5), width=1.0, height=1.0)
    assert not result.usable
    assert "too_few_words" in result.metrics["reason"]


def test_zero_size_page_falls_back_to_ocr():
    result = inspect(_grid(), width=0.0, height=1.0)
    assert not result.usable
    assert result.metrics["reason"] == "bad_page_box"


def test_rotation_90_maps_top_left_to_top_right():
    assert _transform(0.0, 0.0, 0.1, 0.1, 1.0, 1.0, 90) == (0.9, 0.0, 1.0, 0.1)


def test_rotation_180_maps_top_left_to_bottom_right():
    assert _transform(0.0, 0.0, 0.1, 0.1, 1.0, 1.0, 180) == (0.9, 0.9, 1.0, 1.0)


def test_rotation_270_maps_top_left_to_bottom_left():
    assert _transform(0.0, 0.0, 0.1, 0.1, 1.0, 1.0, 270) == (0.0, 0.9, 0.1, 1.0)


def test_saved_words_round_trip(tmp_path):
    words = [OcrWord("HbA1c", [0.1, 0.2, 0.3, 0.4], 1.0)]
    path = words_path(tmp_path / "page_1.webp")
    save_words(path, words)
    assert load_words(path) == words
    # Check bbox_1000 serialization
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["source"] == "text_layer"
    assert data["words"][0]["bbox_1000"] == [100, 200, 300, 400]


def test_suspicious_raster_verified_by_ocr():
    # If full page image coverage is high but raster_verified is True, layer is usable
    result = inspect(_grid(30), width=1.0, height=1.0, image_coverage=0.95, raster_verified=True)
    assert result.usable
    assert result.source == "text_layer"
    assert result.metrics["reason"] is None


def test_suspicious_raster_rejected_when_mismatched():
    result = inspect(_grid(30), width=1.0, height=1.0, image_coverage=0.95, raster_verified=False)
    assert not result.usable
    assert result.source == "ocr"
    assert "suspicious_raster_mismatch" in result.metrics["reason"]

import io

import cv2
import numpy as np
import pytest
from PIL import Image

from smriti.ocr import OcrWord
from smriti.preprocess import redact_page_for_cloud

pytestmark = pytest.mark.unit
pytest.importorskip("rapidfuzz", reason="Install requirements-cloud.txt to test optional cloud redaction")


def test_boilerplate():
    from smriti.classify import BOILERPLATE_SKIP, classify_text
    from smriti.extract import extract_document
    text = "Terms & Conditions Health Advisory HbA1c 8.9 %"
    assert classify_text(text).doc_type == BOILERPLATE_SKIP
    result = extract_document([[OcrWord(text, [.1, .1, .9, .2], .99)]], "lab_report", "printed")
    assert not result.fields and not result.medications


def decoded(jpeg):
    return np.asarray(Image.open(io.BytesIO(jpeg)))


def test_masks_anchor_adjacent_value_discovered_names_regex_and_custom_boxes():
    image = np.full((1000, 1000, 3), 255, np.uint8)
    words = [OcrWord("Patient Name: Ananya Sharma", [.05, .1, .25, .14], .99),
             OcrWord("Ananva", [.5, .4, .65, .44], .8),
             OcrWord("9876543210", [.05, .5, .25, .54], .99),
             OcrWord("private@example.org", [.05, .6, .25, .64], .99),
             OcrWord("Hemoglobin 9.1 g/dL", [.05, .8, .35, .84], .99)]
    tokens = set()
    jpeg = redact_page_for_cloud(image, words, tokens, False, 25, [[700, 500, 750, 650]])
    pixels = decoded(jpeg)
    assert {"ananya", "sharma"} <= tokens
    for y, x in [(120, 100), (120, 650), (420, 550), (520, 100), (620, 100), (720, 550)]:
        assert np.all(pixels[y, x] == 0)
    assert np.all(pixels[820, 100] == 255)
    assert np.all(image == 255)  # The locally retained source is not altered.
    with Image.open(io.BytesIO(jpeg)) as flat:
        assert flat.format == "JPEG" and not flat.getexif()
        assert not flat.info.get("icc_profile") and not flat.info.get("comment")


def test_split_patient_label_and_handwritten_demographic_strip():
    image = np.full((1000, 1000, 3), 255, np.uint8)
    words = [OcrWord("Dr. Hospital Consultant", [.05, .05, .5, .1], .99),
             OcrWord("Patient", [.05, .3, .13, .34], .99),
             OcrWord("Name:", [.14, .3, .21, .34], .99),
             OcrWord("Ananya", [.23, .3, .38, .34], .99)]
    pixels = decoded(redact_page_for_cloud(image, words, set(), True, 2))
    assert np.all(pixels[140, 300] == 0)
    assert np.all(pixels[140, 800] == 255)
    assert np.all(pixels[320, 600] == 0)


def test_qr_detector_masks_pixels_even_without_ocr(monkeypatch):
    class Detector:
        def detectMulti(self, _):
            return True, np.array([[[500, 500], [600, 500], [600, 600], [500, 600]]], np.float32)
    monkeypatch.setattr(cv2, "QRCodeDetector", Detector)
    pixels = decoded(redact_page_for_cloud(np.full((1000, 1000, 3), 255, np.uint8), [], set(), False, 31))
    assert np.all(pixels[550, 550] == 0)


@pytest.mark.parametrize("box", [[400, 300, 200, 600], [0, 0, 1001, 100], [0, 0, 100]])
def test_invalid_masks_fail_closed(box):
    with pytest.raises(ValueError):
        redact_page_for_cloud(np.full((300, 300, 3), 255, np.uint8), [], set(), False, 1, [box])

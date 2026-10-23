from __future__ import annotations

from pathlib import Path

from PIL import Image

from smriti.classify import classify_text
from smriti.extract import extract_document
from smriti.ocr import OcrWord, PaddleOcrEngine


def _word(text: str, y: float, x: float = 0.1, width: float = 0.5) -> OcrWord:
    return OcrWord(text=text, bbox=[x, y, x + width, y + 0.04], confidence=0.98)


def test_classify_lab_report():
    result = classify_text(
        "CITY LABORATORY\nHaemoglobin 13.2 g/dL 12-16\n"
        "Fasting glucose 92 mg/dL 70-100\nReference range"
    )
    assert result.doc_type == "lab_report"
    assert result.confidence >= 0.5


def test_classify_prescription():
    result = classify_text(
        "PRESCRIPTION\nRx\nTab. Metformin 500 mg BD\nTake twice daily after food"
    )
    assert result.doc_type == "prescription"
    assert result.confidence >= 0.5


def test_classify_pharmacy_slip():
    result = classify_text(
        "CITY PHARMACY\nInvoice Bill No 123\nBatch 456 Exp 12/27\nMRP 120\nGST"
    )
    assert result.doc_type == "pharmacy"
    assert result.confidence >= 0.5


def test_classify_unknown_is_other():
    assert classify_text("A handwritten note with no medical headings").doc_type == "other"


def test_extract_known_lab_rows():
    words = [
        _word("HbA1c", 0.10),
        _word("8.9", 0.10, x=0.62, width=0.06),
        _word("%", 0.10, x=0.70, width=0.04),
        _word("4.0-6.0", 0.10, x=0.76, width=0.12),
        _word("Glucose", 0.20),
        _word("126", 0.20, x=0.62, width=0.06),
        _word("mg/dL", 0.20, x=0.70, width=0.08),
        _word("70-100", 0.20, x=0.80, width=0.12),
    ]
    extraction = extract_document([words], "lab_report", "printed")
    by_id = {field.analyte_id: field for field in extraction.fields}
    assert by_id["hba1c"].value_num == "8.9"
    assert by_id["hba1c"].unit_raw == "%"
    assert by_id["hba1c"].ref_low == "4"
    assert by_id["hba1c"].ref_high == "6"
    assert by_id["glucose"].value_num == "126"
    assert by_id["glucose"].unit_raw == "mg/dL"
    assert all(field.mapping_rule in ("exact", "synonym") for field in extraction.fields)


def test_extract_unknown_label_stays_unresolved():
    extraction = extract_document(
        [[_word("Some assay", 0.1), _word("42", 0.1, x=0.6, width=0.05)]],
        "other",
        "printed",
    )
    assert len(extraction.fields) == 1
    field = extraction.fields[0]
    assert field.analyte_id is None
    assert field.mapping_rule == "unresolved"
    assert field.value_num == "42"


def test_extract_medication_line():
    extraction = extract_document(
        [[_word("Tab. Metformin 500 mg BD", 0.1, width=0.8)]],
        "prescription",
        "printed",
    )
    assert len(extraction.medications) == 1
    medication = extraction.medications[0]
    assert medication.brand_raw == "Tab. Metformin"
    assert medication.dose == "500 mg"
    assert medication.freq == "BD"


def test_handwritten_document_does_not_create_numeric_fields():
    extraction = extract_document(
        [[_word("HbA1c 8.9 %", 0.1)]],
        "lab_report",
        "handwritten",
    )
    assert extraction.fields == []


def test_paddle_adapter_maps_boxes(tmp_path: Path):
    image_path = tmp_path / "page.webp"
    Image.new("RGB", (1000, 1000), "white").save(image_path)

    class FakePaddle:
        def predict(self, _path):
            return [
                {
                    "rec_texts": ["HbA1c 8.9 %"],
                    "rec_scores": [0.97],
                    "rec_boxes": [[100, 200, 500, 260]],
                }
            ]

    engine = PaddleOcrEngine("det", "rec")
    engine._ocr = FakePaddle()
    words = engine.read(image_path)
    assert len(words) == 1
    assert words[0].text == "HbA1c 8.9 %"
    assert words[0].bbox == [0.1, 0.2, 0.5, 0.26]
    assert words[0].confidence == 0.97

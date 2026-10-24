from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from smriti.classify import classify_text
from smriti.extract import extract_document
from smriti.ocr import OcrWord, PaddleOcrEngine

pytestmark = pytest.mark.unit


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


def test_classify_ct_report():
    result = classify_text(
        "CITY HOSPITAL\nCT SCAN OF CHEST\nComputed tomography of the thorax\n"
        "Impression: No active lesion."
    )
    assert result.doc_type == "ct"


def test_classify_mri_report():
    result = classify_text(
        "MRI BRAIN\nMagnetic resonance imaging of the brain\n"
        "T2 weighted images show no acute infarct."
    )
    assert result.doc_type == "mri"


def test_classify_xray_report():
    result = classify_text(
        "CHEST X-RAY\nRadiograph of the chest, PA view\nImpression: Clear lungs."
    )
    assert result.doc_type == "xray"


def test_classify_pathology_report():
    result = classify_text(
        "HISTOPATHOLOGY REPORT\nBiopsy from left breast\n"
        "Gross examination: grey white tissue.\n"
        "Microscopic examination: invasive carcinoma."
    )
    assert result.doc_type == "pathology"


def test_classify_discharge_summary():
    result = classify_text(
        "DISCHARGE SUMMARY\nDate of admission: 02/11/2025\n"
        "Date of discharge: 06/11/2025\nCourse in hospital: stable.\n"
        "Final diagnosis: community acquired pneumonia."
    )
    assert result.doc_type == "discharge_summary"


def test_classify_ultrasound_report():
    result = classify_text(
        "ULTRASOUND ABDOMEN\nUSG abdomen and pelvis\nImpression: normal study."
    )
    assert result.doc_type == "radiology"


def test_extract_discharge_summary_medications():
    extraction = extract_document(
        [[_word("Tab. Metformin 500 mg BD", 0.1, width=0.8)]],
        "discharge_summary",
        "printed",
    )
    assert len(extraction.medications) == 1


def test_extract_imaging_report_has_no_numeric_fields():
    extraction = extract_document(
        [[_word("HbA1c 8.9 %", 0.1, width=0.8)]],
        "ct",
        "printed",
    )
    assert extraction.fields == []


def test_cross_page_header_carry():
    # Page 1: Header row + 1 test row
    page1_words = [
        # Table Header
        _word("Investigation", 0.05, x=0.10, width=0.20),
        _word("Result", 0.05, x=0.45, width=0.10),
        _word("Unit", 0.05, x=0.65, width=0.08),
        _word("Reference Interval", 0.05, x=0.78, width=0.18),
        # Data row
        _word("HbA1c", 0.12, x=0.10, width=0.15),
        _word("8.9", 0.12, x=0.45, width=0.06),
        _word("%", 0.12, x=0.65, width=0.04),
        _word("4.0-6.0", 0.12, x=0.78, width=0.12),
    ]

    # Page 2: No table header, row continues directly using carried column positions
    page2_words = [
        _word("Uric Acid", 0.10, x=0.10, width=0.18),
        _word("6.2", 0.10, x=0.45, width=0.06),
        _word("mg/dL", 0.10, x=0.65, width=0.08),
        _word("3.5-7.2", 0.10, x=0.78, width=0.12),
    ]

    extraction = extract_document(
        [page1_words, page2_words],
        "lab_report",
        "printed",
    )

    # Asserts that the header row itself is NOT extracted as an observation
    labels = [field.label_raw for field in extraction.fields]
    assert "Investigation" not in labels
    assert "Result" not in labels

    # Asserts both page 1 and carried-header page 2 observations are extracted
    analytes = {field.analyte_id: field for field in extraction.fields}
    assert "hba1c" in analytes
    assert analytes["hba1c"].page == 1
    assert analytes["hba1c"].value_num == "8.9"

    assert "uric_acid" in analytes
    assert analytes["uric_acid"].page == 2
    assert analytes["uric_acid"].value_num == "6.2"


def test_extract_out_of_bounds_reason():
    words = [
        _word("HbA1c", 0.10, x=0.10, width=0.15),
        _word("45.0", 0.10, x=0.40, width=0.08),
        _word("%", 0.10, x=0.55, width=0.04),
    ]
    extraction = extract_document([words], "lab_report", "printed")
    assert len(extraction.fields) == 1
    field = extraction.fields[0]
    assert field.analyte_id == "hba1c"
    assert field.value_num == "45"
    assert field.reason is not None
    assert "SI-03: value 45" in field.reason
    assert "out of biological bounds" in field.reason


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


def test_extract_medication_without_form_and_with_schedule():
    extraction = extract_document(
        [
            [_word("Metformin 500 mg BD", 0.1, width=0.8)],
            [_word("Tab. Telma 40 mg 1-0-0", 0.2, width=0.8)],
        ],
        "prescription",
        "printed",
    )
    by_brand = {medication.brand_raw: medication for medication in extraction.medications}
    assert by_brand["Metformin"].freq == "BD"
    assert by_brand["Tab. Telma"].freq == "1-0-0"


def test_header_ids_are_not_unresolved_fields():
    extraction = extract_document(
        [
            [
                _word("Patient: P-01", 0.1, width=0.4),
                _word("Age: 45", 0.1, x=0.5, width=0.3),
                _word("Report No: 12345", 0.2, width=0.5),
            ]
        ],
        "lab_report",
        "printed",
    )
    assert extraction.fields == []


def test_handwritten_document_does_not_create_numeric_fields():
    extraction = extract_document(
        [[_word("HbA1c 8.9 %", 0.1)]],
        "lab_report",
        "handwritten",
    )
    assert extraction.fields == []


def test_engine_is_recorded_on_every_field():
    words = [
        _word("HbA1c", 0.10),
        _word("8.9", 0.10, x=0.62, width=0.06),
        _word("%", 0.10, x=0.70, width=0.04),
    ]
    extraction = extract_document(
        [words], "lab_report", "printed", engine="fake-ocr+local-rules:line-rules@1.0+cpu"
    )
    assert extraction.fields
    assert all(
        field.engine == "fake-ocr+local-rules:line-rules@1.0+cpu"
        for field in extraction.fields
    )


def test_confidence_is_derived_from_signals_not_ocr_confidence():
    words = [
        _word("HbA1c", 0.10),
        _word("5.0", 0.10, x=0.62, width=0.06),
        _word("%", 0.10, x=0.70, width=0.04),
        _word("4-6", 0.10, x=0.76, width=0.10),
    ]
    words = [OcrWord(word.text, word.bbox, 0.10) for word in words]
    extraction = extract_document([words], "lab_report", "printed")
    assert extraction.fields[0].confidence == 1.0
    assert extraction.fields[0].mapping_rule == "exact"


def test_missing_unit_is_not_invented_and_stays_unresolved():
    extraction = extract_document(
        [[_word("HbA1c", 0.10), _word("8.9", 0.10, x=0.62, width=0.06)]],
        "lab_report",
        "printed",
    )
    field = extraction.fields[0]
    assert field.analyte_id == "hba1c"
    assert field.unit_raw is None
    assert field.mapping_rule == "unresolved"
    assert field.confidence == 0.333


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

from __future__ import annotations

import pytest

from smriti.checks import (
    check_anc,
    check_bilirubin,
    check_bounds,
    check_dlc,
    check_friedewald,
    check_mcv,
    load_bounds,
    validate_numeric_dual_read,
)

pytestmark = pytest.mark.unit


def test_bounds_table_monotonic():
    bounds = load_bounds()
    assert len(bounds) >= 30
    for analyte_id, bound in bounds.items():
        assert bound.hard_low < bound.hard_high, f"{analyte_id}: low not less than high"
        assert bound.source_citation, f"{analyte_id}: missing citation"


def test_check_bounds_pass():
    verdict, reason = check_bounds("hba1c", "8.9")
    assert verdict == "pass"
    assert reason is None

    verdict, reason = check_bounds("glucose", 126)
    assert verdict == "pass"

    verdict, reason = check_bounds("potassium", "4.2")
    assert verdict == "pass"


def test_check_bounds_out_of_range():
    verdict, reason = check_bounds("hba1c", "35.0")
    assert verdict == "review"
    assert reason and "out of biological bounds" in reason

    verdict, reason = check_bounds("potassium", "15.0")
    assert verdict == "review"
    assert reason and "out of biological bounds" in reason

    verdict, reason = check_bounds("sodium", "50.0")
    assert verdict == "review"
    assert reason and "out of biological bounds" in reason


def test_check_bounds_skipped():
    verdict, reason = check_bounds(None, "10.0")
    assert verdict == "skipped"

    verdict, reason = check_bounds("unknown_analyte_xyz", "10.0")
    assert verdict == "skipped"

    verdict, reason = check_bounds("hba1c", None)
    assert verdict == "skipped"


def test_dual_read_valid_numbers():
    valid, reason = validate_numeric_dual_read("126", "126")
    assert valid is True
    assert reason is None

    valid, reason = validate_numeric_dual_read("8.9", "8.9")
    assert valid is True

    valid, reason = validate_numeric_dual_read("<0.05", "0.05")
    assert valid is True


def test_dual_read_catches_confusion_and_corruptions():
    valid, reason = validate_numeric_dual_read("8.O", "8.0")
    assert valid is False
    assert "confusion" in reason.lower()

    valid, reason = validate_numeric_dual_read("1..2", "1.2")
    assert valid is False
    assert "decimal" in reason.lower()

    valid, reason = validate_numeric_dual_read("abc", "abc")
    assert valid is False


def test_dlc_sum_gate():
    # 60 + 30 + 6 + 3 + 1 = 100% -> pass
    verdict, _ = check_dlc(60.0, 30.0, 6.0, 3.0, 1.0)
    assert verdict == "pass"

    # 70 + 40 = 110% -> review
    verdict, reason = check_dlc(70.0, 40.0)
    assert verdict == "review"
    assert "DLC sum" in reason

    # Missing inputs -> skipped
    verdict, _ = check_dlc(None, 40.0)
    assert verdict == "skipped"


def test_friedewald_gate():
    # TC=200, HDL=50, TG=150 => LDL = 200 - 50 - 30 = 120
    verdict, _ = check_friedewald(200.0, 50.0, 150.0, 120.0)
    assert verdict == "pass"

    # Inconsistent: reported LDL 180 vs calculated 120
    verdict, reason = check_friedewald(200.0, 50.0, 150.0, 180.0)
    assert verdict == "review"
    assert "Friedewald" in reason

    # TG > 400 is invalid for Friedewald
    verdict, _ = check_friedewald(200.0, 50.0, 450.0, 120.0)
    assert verdict == "skipped"


def test_bilirubin_gate():
    # Total 1.2, Direct 0.4, Indirect 0.8
    verdict, _ = check_bilirubin(1.2, 0.4, 0.8)
    assert verdict == "pass"

    # Mismatch: 3.5 != 0.4 + 0.8
    verdict, reason = check_bilirubin(3.5, 0.4, 0.8)
    assert verdict == "review"
    assert "G3" in reason


def test_mcv_gate():
    # MCV = Hct(45) / RBC(5.0) * 10 = 90
    verdict, _ = check_mcv(45.0, 5.0, 90.0)
    assert verdict == "pass"

    verdict, reason = check_mcv(45.0, 5.0, 120.0)
    assert verdict == "review"
    assert "G4" in reason


def test_anc_gate():
    # ANC = WBC(6000) * Neutrophils(60%) / 100 = 3600
    verdict, _ = check_anc(6000.0, 60.0, 3600.0)
    assert verdict == "pass"


def test_exact_numeric_second_read_no_tolerance():
    from smriti.checks import exact_numeric_second_read

    ok, reason = exact_numeric_second_read("13.2", "13.2")
    assert ok is True
    assert reason is None

    # Even 1% difference fails under zero-tolerance second read
    ok, reason = exact_numeric_second_read("13.2", "13.3")
    assert ok is False
    assert "mismatch" in reason.lower()

    ok, reason = exact_numeric_second_read("1,20,000", "120000")
    assert ok is True


def test_validate_date_window():
    from smriti.checks import validate_date_window

    # Valid within window
    ok, reason = validate_date_window("25/09/2026", "23/09/2026", "06/10/2026")
    assert ok is True
    assert reason is None

    # Out of window (precedes DOA)
    ok, reason = validate_date_window("20/09/2026", "23/09/2026", "06/10/2026")
    assert ok is False
    assert "precedes DOA" in reason

    # Out of window (succeeds DOD)
    ok, reason = validate_date_window("10/10/2026", "23/09/2026", "06/10/2026")
    assert ok is False
    assert "succeeds DOD" in reason


def test_validate_patient_identity():
    from smriti.checks import validate_patient_identity

    ok, _ = validate_patient_identity("51851", "51851", "Harnam Malhotra", "Harnam Malhotra")
    assert ok is True

    ok, reason = validate_patient_identity("51851", "99999")
    assert ok is False
    assert "UHID mismatch" in reason


def test_orphan_token_report():
    from smriti.checks import generate_orphan_token_report
    from smriti.ocr import OcrWord

    words = [
        OcrWord("HbA1c", [0.1, 0.1, 0.2, 0.15], 0.99),
        OcrWord("8.9", [0.3, 0.1, 0.4, 0.15], 0.99),
        OcrWord("OrphanHeader", [0.8, 0.8, 0.9, 0.85], 0.95),
    ]
    claimed = [[0.05, 0.05, 0.45, 0.20]]
    report = generate_orphan_token_report(words, claimed)

    assert report["total_tokens"] == 3
    assert report["claimed_tokens"] == 2
    assert report["orphan_count"] == 1
    assert report["orphan_tokens"] == ["OrphanHeader"]

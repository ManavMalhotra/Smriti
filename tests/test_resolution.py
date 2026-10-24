from __future__ import annotations

from smriti.resolution import range_contains, resolve, unit_matches


def test_two_of_three_agreement_table():
    cases = [
        ("HbA1c", "5.0", "%", "4", "6", "hba1c", "exact", 1.0),
        ("Haemoglobin", "13.2", "g/dL", "12", "16", "hemoglobin", "synonym", 1.0),
        ("Haemoglobin", "13.2", "mg/dL", "12", "16", "hemoglobin", "synonym", 0.667),
        ("HbA1c", "8.9", "%", None, None, "hba1c", "exact", 0.667),
        ("HbA1c", "8.9", None, None, None, "hba1c", "unresolved", 0.333),
        ("Some assay", "42", None, None, None, None, "unresolved", 0.0),
    ]
    for label, value, unit, low, high, analyte, rule, confidence in cases:
        resolution = resolve(label, value, unit, low, high)
        assert resolution.analyte_id == analyte
        assert resolution.mapping_rule == rule
        assert resolution.confidence == confidence


def test_range_and_unit_helpers():
    assert range_contains("5.0", "4", "6")
    assert not range_contains("8.9", "4", "6")
    assert not range_contains("5.0", None, "6")
    assert unit_matches("cells/uL", "cells/µL")
    assert unit_matches("MG/DL", "mg/dL")
    assert not unit_matches(None, "mg/dL")

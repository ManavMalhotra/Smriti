from __future__ import annotations

from datetime import date

import pytest

from smriti.metadata import (
    extract_document_dates,
    extract_document_identifiers,
    extract_metadata,
    parse_date,
)


pytestmark = pytest.mark.unit


def test_extracts_labelled_collection_and_report_dates():
    dates = extract_document_dates(
        "CITY LABORATORY\nCollection Date: 02/11/2025\nReport Date: 03/11/2025"
    )
    assert dates["collection_date"] == "2025-11-02"
    assert dates["report_date"] == "2025-11-03"
    assert dates["doc_date"] in ("2025-11-02", "2025-11-03")


def test_extracts_registration_and_admission_dates():
    dates = extract_document_dates(
        "Date of Admission: 12/08/2024\nDate of Discharge: 16/08/2024"
    )
    assert dates["registration_date"] == "2024-08-12"
    assert dates["report_date"] == "2024-08-16"


def test_extract_patient_uhid_and_identifiers():
    meta = extract_document_identifiers("Patient UHID: 105234567\nAge: 45 / Male")
    assert meta["patient_uhid"] == "105234567"

    meta2 = extract_document_identifiers("CR No: 2024-009876\nWard: 5")
    assert meta2["patient_uhid"] == "2024-009876"

    meta3 = extract_document_identifiers("MRD NO: 451234\nBed: 12")
    assert meta3["patient_uhid"] == "451234"


def test_extract_doctor_reg_no_and_disambiguation():
    # Doctor line with DMC Reg No
    meta = extract_document_identifiers(
        "Dr. Rajesh Gupta, MD\nDMC Reg No: 54321\nConsultant Physician"
    )
    assert meta["doctor_reg_no"] == "54321"

    # Patient Reg No must NOT be classified as Doctor Reg No
    patient_text = "Patient Name: Jane Doe\nPatient Reg No: 998877\nAge: 32"
    meta_patient = extract_document_identifiers(patient_text)
    assert meta_patient["doctor_reg_no"] is None
    assert meta_patient["patient_uhid"] == "998877"


def test_extract_facility_name():
    text = "Vardhman Mahavir Medical College & Safdarjung Hospital\nNew Delhi - 110029\nOPD Card"
    meta = extract_document_identifiers(text)
    assert meta["facility_name"] is not None
    assert "Safdarjung Hospital" in meta["facility_name"]


def test_extracts_iso_and_month_name_dates():
    assert extract_document_dates("Report Date: 2025-11-02")["doc_date"] == "2025-11-02"
    assert extract_document_dates("Report Date: 2025/11/02")["doc_date"] == "2025-11-02"
    assert extract_document_dates("Date: 2 Nov 2025")["doc_date"] == "2025-11-02"


def test_extracts_dot_separated_dates():
    assert extract_document_dates("Date: 01.08.2022")["doc_date"] == "2022-08-01"
    assert extract_document_dates("Report Date: 2025.11.03")["doc_date"] == "2025-11-03"


def test_parses_compact_day_month_year_dates():
    from smriti.metadata import parse_date

    assert parse_date("PatientRegisteredOn: 16/Dec/202112:31PM") == date(2021, 12, 16)
    assert parse_date("Report Generated On: 16/Dec/202103:02PM") == date(2021, 12, 16)


def test_does_not_use_date_of_birth():
    assert extract_document_dates("DOB: 01/01/1990\nDate of Birth: 01/01/1990") == {}


@pytest.mark.parametrize("text", [
    "DOB: 01/01/1990", "Date of Birth: 01/01/1990", "Birth: 01/01/1990\nNo report date",
])
def test_unlabelled_date_fallback_never_uses_birth_date(text):
    assert parse_date(text) is None


def test_date_fallback_keeps_non_birth_date_and_cross_line_month():
    assert parse_date("DOB: 01/01/1990\nIssued 02/11/2025") == date(2025, 11, 2)
    assert parse_date("DOB: 01/01/1990\nIssued 2\nNov\n2025") == date(2025, 11, 2)

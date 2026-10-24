from __future__ import annotations

from smriti.metadata import extract_document_dates


def test_extracts_labelled_collection_and_report_dates():
    dates = extract_document_dates(
        "CITY LABORATORY\nCollection Date: 02/11/2025\nReport Date: 03/11/2025"
    )
    assert dates == {"collection_date": "2025-11-02", "doc_date": "2025-11-03"}


def test_extracts_iso_and_month_name_dates():
    assert extract_document_dates("Report Date: 2025-11-02")["doc_date"] == "2025-11-02"
    assert extract_document_dates("Date: 2 Nov 2025")["doc_date"] == "2025-11-02"


def test_does_not_use_date_of_birth():
    assert extract_document_dates("DOB: 01/01/1990\nDate of Birth: 01/01/1990") == {}

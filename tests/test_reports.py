from __future__ import annotations

import pytest

from smriti.reports import build_reports, fact_type_for, normalise_label

pytestmark = pytest.mark.unit


class _Field:
    def __init__(self, label_raw, analyte_id=None, value_num=None):
        self.label_raw = label_raw
        self.analyte_id = analyte_id
        self.value_num = value_num


def test_groups_consecutive_pages_by_date_and_facility():
    pages = [
        "CITY DIAGNOSTICS\nDate: 16.12.2021\nCT CHEST\nFindings: ...",
        "CITY DIAGNOSTICS\nPage 2 of 2\nImpression: ...",
        "CITY DIAGNOSTICS\nDate: 01.08.2022\nHRCT\nFindings: ...",
        "CITY HOSPITAL\nDate: 02.03.2024\nCECT\nFindings: ...",
        "CITY HOSPITAL\nDate: 03.11.2025\nHRCT\nFindings: ...",
    ]

    reports = build_reports(pages, "ct")

    assert [(report.page_start, report.page_end) for report in reports] == [
        (1, 2),
        (3, 3),
        (4, 4),
        (5, 5),
    ]
    assert [report.report_date for report in reports] == [
        "2021-12-16",
        "2022-08-01",
        "2024-03-02",
        "2025-11-03",
    ]
    assert [report.category for report in reports] == ["imaging"] * 4
    assert reports[0].facility_name == "CITY DIAGNOSTICS"
    assert reports[3].facility_name == "CITY HOSPITAL"


def test_splits_compact_dates_without_labels():
    pages = [
        "CITY DIAGNOSTICS\nAge/Gender: 45Y/Male PatientRegisteredOn: 16/Dec/202112:31PM\nCT",
        "CITY DIAGNOSTICS\nReport Generated On: 16/Dec/202103:02PM\nPage 2",
        "CITY HOSPITAL\nPATIENT NAME 47M 01.08.2022\nDATE: AREA SCANNED",
    ]

    reports = build_reports(pages, "ct")

    assert [(report.page_start, report.page_end) for report in reports] == [
        (1, 2),
        (3, 3),
    ]
    assert [report.report_date for report in reports] == [
        "2021-12-16",
        "2022-08-01",
    ]


def test_undated_page_continues_current_report_but_starts_review_when_first():
    reports = build_reports(["No date here\nFindings: ..."], "ct")
    assert len(reports) == 1
    assert reports[0].status == "review"
    assert reports[0].report_date is None

    reports = build_reports(
        ["Date: 02/03/2024\nFindings: ...", "Page 2 of 2\nImpression: ..."],
        "ct",
    )
    assert len(reports) == 1
    assert (reports[0].page_start, reports[0].page_end) == (1, 2)


def test_ocr_concatenated_facility_stays_one_report():
    reports = build_reports(
        [
            "CITY HOSPITAL\nDate: 01.08.2022\nFindings: ...",
            "CITYHOSPITAL\nPage 2 of 2\nImpression: ...",
        ],
        "ct",
    )
    assert len(reports) == 1
    assert (reports[0].page_start, reports[0].page_end) == (1, 2)


def test_fact_types_and_normalised_labels():
    assert fact_type_for(_Field("Impression", value_num=None)) == "impression"
    assert fact_type_for(_Field("Findings", value_num=None)) == "imaging_finding"
    assert fact_type_for(_Field("Advice", value_num=None)) == "recommendation"
    assert fact_type_for(_Field("HbA1c", analyte_id="hba1c", value_num="8.9")) == "lab"
    assert fact_type_for(_Field("Nodule size", value_num="8")) == "measurement"
    assert normalise_label(" Nodule  size ") == "nodule size"


def test_birth_date_does_not_date_or_split_reports():
    report = build_reports(["DOB: 01/01/1990\nCT CHEST"], "ct")[0]
    assert report.report_date is None
    assert report.status == "review"
    reports = build_reports(["Date: 02/11/2025\nCT CHEST", "DOB: 01/01/1990\nImpression"], "ct")
    assert len(reports) == 1
    assert reports[0].report_date == "2025-11-02"
    assert reports[0].page_end == 2

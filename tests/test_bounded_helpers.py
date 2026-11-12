from __future__ import annotations

from dataclasses import asdict

import pytest

from smriti.bounded_text import document_lines
from smriti.directives import extract_directives, iter_directives
from smriti.extract import extract_document, extraction_candidates
from smriti.prose import ProseSection
from smriti.reports import attach_summaries, build_reports, iter_reports
from tests.test_extract import _word

pytestmark = pytest.mark.unit


def test_table_template_and_first_seen_candidates_cross_page_twenty_one():
    header = [_word("Investigation", .05, .10, .20), _word("Result", .05, .45, .10),
              _word("Unit", .05, .65, .08), _word("Reference Interval", .05, .78, .18)]
    row = [_word("Uric Acid", .10, .10, .18), _word("6.2", .10, .45, .06),
           _word("mg/dL", .10, .65, .08), _word("3.5-7.2", .10, .78, .12)]
    medication = [_word("Tab. Metformin 500 mg BD", .2, width=.8)]
    pages = [header + row + medication] + [[]] * 19 + [row + row + medication]
    legacy = extract_document(pages, "discharge_summary", "printed")
    fields, meds = {}, {}
    for kind, candidate in extraction_candidates(iter(pages), "discharge_summary", "printed"):
        if kind == "field":
            fields.setdefault((candidate.analyte_id or candidate.label_raw.lower(), candidate.value_num or "", candidate.page), candidate)
        else:
            meds.setdefault((candidate.brand_raw.lower(), candidate.dose, candidate.freq), candidate)
    assert list(fields.values()) == legacy.fields
    assert list(meds.values()) == legacy.medications
    assert any(field.page == 21 for field in fields.values())
    assert sum(med.brand_raw == "Tab. Metformin" for med in meds.values()) == 1


def test_reports_and_summary_precedence_continue_across_windows():
    pages = ["CITY HOSPITAL\nDate: 02/11/2025\nCT CHEST"] + ["continuation"] * 19 + [
        "CITYHOSPITAL\nImpression: synthetic finding", "OTHER HOSPITAL\nDate: 03/11/2025", "continuation"]
    sections = [ProseSection("diagnosis", "Diagnosis", "first summary", 1, [], 1, True),
                ProseSection("findings", "Findings", "early findings", 2, [], 1, True),
                ProseSection("impression", "Impression", "later impression", 21, [], 1, True),
                ProseSection("findings", "Findings", "new report findings", 23, [], 1, True)]
    legacy = build_reports(pages, "ct")
    attach_summaries(legacy, sections)
    streamed = list(iter_reports(iter(pages), "ct", sections_for_page=lambda page: (s for s in sections if s.page == page)))
    assert [asdict(r) | {"id": None} for r in streamed] == [asdict(r) | {"id": None} for r in legacy]
    assert streamed[0].page_end == 21 and streamed[0].summary == "later impression"
    assert streamed[1].summary == "new report findings"


@pytest.mark.parametrize("separator", ["\n", "\r\n", "\u2028", "\x85"])
def test_directive_offsets_and_overlap_match_original_document(separator):
    pages = ["Ω" + separator + "Review after 2 weeks"] + ["continuation"] * 19 + [
        "Repeat CBC in 1 month" + separator + "Return if pain persists" + separator + "SOS for pain"]
    text = "\n".join(pages)
    kwargs = {"collection_date": "2025-11-02"}
    assert list(iter_directives(document_lines(iter(pages), keepends=True), **kwargs)) == extract_directives(text, **kwargs)


def test_streaming_helpers_do_not_prefetch_the_document():
    def pages():
        yield "Date: 02/11/2025"
        yield "Date: 03/11/2025"
        raise AssertionError("Should stop after first closed report")

    assert next(iter_reports(pages(), "ct")).page_start == 1
    raw_lines = iter(["Review after 2 weeks\n", "later"])
    assert next(iter_directives(raw_lines)).span_start == 0
    assert next(raw_lines) == "later"

from __future__ import annotations

from datetime import date
from typing import get_args

import pytest
from sqlalchemy import text

from smriti.directives import extract_directives
from smriti.models import AnchorEvent
from smriti.ocr import OcrWord
from smriti.worker import process_next
from tests.factory import jpeg_bytes, make_patient, text_image

pytestmark = pytest.mark.integration


def test_relative_directive_anchors_on_collection_date():
    text = "Advice: Review after 2 weeks."
    directive = extract_directives(
        text,
        collection_date="2026-11-02",
        doc_date="2026-11-03",
        as_of=date(2026, 10, 24),
    )[0]
    assert directive.span_text == "Review after 2 weeks"
    assert text[directive.span_start : directive.span_end] == directive.span_text
    assert directive.timing_type == "relative"
    assert directive.time_value == 2
    assert directive.time_unit == "week"
    assert directive.anchor_event == "collection_date"
    assert directive.anchor_date == date(2026, 11, 2)
    assert directive.due_date == date(2026, 11, 16)
    assert directive.state == "open"


def test_anchor_priority_uses_doc_date_then_unknown():
    doc_anchor = extract_directives(
        "Review in 1 month",
        collection_date=None,
        doc_date="2026-11-03",
        as_of=date(2026, 10, 24),
    )[0]
    assert doc_anchor.anchor_event == "doc_date"
    assert doc_anchor.due_date == date(2026, 12, 3)

    unknown = extract_directives(
        "Review in 1 month",
        collection_date=None,
        doc_date=None,
        as_of=date(2026, 10, 24),
    )[0]
    assert unknown.anchor_event == "unknown"
    assert unknown.anchor_date is None
    assert unknown.due_date is None
    assert unknown.state == "unknown_date"


def test_absolute_future_and_past():
    future = extract_directives(
        "Review on 15/11/2026", as_of=date(2026, 10, 24)
    )[0]
    assert future.timing_type == "absolute"
    assert future.due_date == date(2026, 11, 15)
    assert future.state == "open"

    past = extract_directives(
        "Review on 15/11/2026", as_of=date(2026, 12, 1)
    )[0]
    assert past.due_date is None
    assert past.state == "unknown_date"


def test_past_relative_is_not_scheduled_but_keeps_anchor():
    directive = extract_directives(
        "Review after 2 weeks",
        collection_date="2025-01-01",
        as_of=date(2026, 10, 24),
    )[0]
    assert directive.anchor_event == "collection_date"
    assert directive.anchor_date == date(2025, 1, 1)
    assert directive.due_date is None
    assert directive.state == "unknown_date"


def test_conditional_and_prn_have_no_due_date():
    conditional = extract_directives(
        "Repeat KFT after stopping Atorvastatin",
        collection_date="2026-11-02",
        as_of=date(2026, 10, 24),
    )[0]
    assert conditional.action_type == "test"
    assert conditional.timing_type == "conditional"
    assert conditional.condition_text == "after stopping Atorvastatin"
    assert conditional.target == "KFT"
    assert conditional.due_date is None
    assert conditional.state == "open"

    condition_first = extract_directives(
        "If fever, come immediately",
        collection_date="2026-11-02",
        as_of=date(2026, 10, 24),
    )[0]
    assert condition_first.timing_type == "conditional"
    assert condition_first.condition_text == "fever"
    assert condition_first.target == "review"
    assert condition_first.due_date is None

    timed_condition = extract_directives(
        "Review KFT after 2 weeks if fever persists",
        collection_date="2026-11-02",
        as_of=date(2026, 10, 24),
    )[0]
    assert timed_condition.timing_type == "conditional"
    assert timed_condition.target == "KFT"

    prn = extract_directives(
        "SOS for pain",
        collection_date="2026-11-02",
        as_of=date(2026, 10, 24),
    )[0]
    assert prn.timing_type == "prn"
    assert prn.action_type == "other"
    assert prn.target == "pain"
    assert prn.due_date is None


def test_relative_phrasings_and_span_offsets_roundtrip():
    text = "R/V 15 days\nf/u in 1 mth\nreview after 2 wks"
    directives = extract_directives(
        text,
        collection_date="2026-11-02",
        as_of=date(2026, 10, 24),
    )
    assert [directive.span_text for directive in directives] == [
        "R/V 15 days",
        "f/u in 1 mth",
        "review after 2 wks",
    ]
    assert [directive.due_date for directive in directives] == [
        date(2026, 11, 17),
        date(2026, 12, 2),
        date(2026, 11, 16),
    ]
    for directive in directives:
        assert text[directive.span_start : directive.span_end] == directive.span_text


def test_non_directives_are_ignored():
    assert extract_directives("Continue same treatment") == []
    assert extract_directives("Tab. Metformin 500 mg PRN") == []


def test_enum_has_no_today():
    assert "today" not in get_args(AnchorEvent)


class _DirectiveOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("Prescription", [0.1, 0.02, 0.4, 0.06], 0.99),
            OcrWord("Collection Date: 02/01/2099", [0.1, 0.08, 0.8, 0.12], 0.98),
            OcrWord("Tab. Metformin 500 mg BD", [0.1, 0.16, 0.8, 0.20], 0.98),
            OcrWord("Review after 2 weeks", [0.1, 0.24, 0.8, 0.28], 0.98),
        ]


def test_worker_persists_directive_to_summary(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = client.post(
        "/api/documents",
        data={"patient_id": patient_id, "consent_scope": "local"},
        files={"file": ("page.jpg", jpeg_bytes(text_image()), "image/jpeg")},
    )
    assert uploaded.status_code == 202, uploaded.text
    body = uploaded.json()

    assert process_next(app.state.engine, settings, ocr_engine=_DirectiveOcr()) is True
    detail = client.get(f"/api/documents/{body['document_id']}").json()
    assert detail["doc_type"] == "prescription"
    assert len(detail["medications"]) == 1

    summary = client.get(f"/api/patients/{patient_id}/summary").json()
    assert len(summary["pending"]) == 1
    pending = summary["pending"][0]
    assert pending["text"] == "Review after 2 weeks"
    assert pending["due_date"] == "2099-01-16"
    assert pending["anchor_event"] == "collection_date"
    assert pending["state"] == "open"


def test_worker_does_not_persist_handwritten_directives(client, app, settings):
    patient_id = make_patient(client, alias="P-02")
    uploaded = client.post(
        "/api/documents",
        data={"patient_id": patient_id, "consent_scope": "local"},
        files={"file": ("page.jpg", jpeg_bytes(text_image()), "image/jpeg")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["document_id"]
    with app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE document SET capture_type = 'handwritten' WHERE id = :id"),
            {"id": document_id},
        )

    assert process_next(app.state.engine, settings, ocr_engine=_DirectiveOcr()) is True
    summary = client.get(f"/api/patients/{patient_id}/summary").json()
    assert summary["pending"] == []

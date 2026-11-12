from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text

from smriti.config import BASE_DIR
from smriti.models import Summary


pytestmark = pytest.mark.integration

FIXTURE = BASE_DIR / "web" / "src" / "fixtures" / "summary.json"
SUMMARY_KEYS = {
    "patient",
    "coverage",
    "problems",
    "medications",
    "results",
    "pending",
    "documents",
}


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_summary_fixture_has_exactly_seven_keys():
    assert set(_payload()) == SUMMARY_KEYS


def test_contract():
    summary = Summary.model_validate(_payload())

    point = summary.results[0].points[0]
    assert len(point.bbox) == 4
    assert all(0 <= coordinate <= 1 for coordinate in point.bbox)
    assert summary.results[0].excluded == []


def test_summary_gap_uses_from_alias():
    dumped = Summary.model_validate(_payload()).model_dump(by_alias=True, mode="json")
    assert "from" in dumped["coverage"]["gaps"][0]


def test_build_summary_excludes_unmapped_observations(app):
    from smriti.summary import build_summary

    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO patient (id, alias, created_at) "
                "VALUES ('p-test', 'Tester', '2026-10-27T00:00:00Z')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO document (id, patient_id, doc_type, capture_type, "
                "image_path, page_count, content_hash, status, created_at) "
                "VALUES ('d-test', 'p-test', 'lab_report', 'printed', 'img', 1, "
                "'hash-test', 'done', '2026-10-27T00:00:00Z')"
            )
        )
        # One mapped analyte, one unmapped observation
        conn.execute(
            text(
                "INSERT INTO observation (id, document_id, analyte_id, label_raw, "
                "value_num, value_text, bbox_json, page, engine, status, created_at) "
                "VALUES ('o-1', 'd-test', 'hba1c', 'HbA1c', '8.9', '8.9', "
                "'[0.1,0.2,0.3,0.4]', 1, 'test', 'auto', '2026-10-27T00:00:00Z')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO observation (id, document_id, analyte_id, label_raw, "
                "value_num, value_text, bbox_json, page, engine, status, created_at) "
                "VALUES ('o-2', 'd-test', NULL, 'Some unmapped test', '42', '42', "
                "'[0.1,0.2,0.3,0.4]', 1, 'test', 'review', '2026-10-27T00:00:00Z')"
            )
        )

    with app.state.engine.connect() as conn:
        summary = build_summary(conn, "p-test")

    assert len(summary.results) == 1
    assert summary.results[0].analyte_id == "hba1c"
    assert summary.results[0].display == "HbA1c"


def _patient_with_document(conn, document_id: str, **document) -> None:
    conn.execute(
        text(
            "INSERT OR IGNORE INTO patient (id, alias, created_at) "
            "VALUES ('p-units', 'Tester', '2026-10-27T00:00:00Z')"
        )
    )
    values = {
        "doc_date": None,
        "collection_date": None,
        "registration_date": None,
        "created_at": "2026-06-01T00:00:00Z",
    }
    values.update(document)
    conn.execute(
        text(
            "INSERT INTO document (id, patient_id, doc_type, capture_type, "
            "image_path, page_count, content_hash, status, created_at, "
            "doc_date, collection_date, registration_date) "
            "VALUES (:id, 'p-units', 'lab_report', 'printed', 'img', 1, "
            ":hash, 'done', :created_at, :doc_date, :collection_date, "
            ":registration_date)"
        ),
        {"id": document_id, "hash": f"hash-{document_id}", **values},
    )


def _observation(conn, observation_id: str, document_id: str, **values) -> None:
    row = {
        "analyte_id": "glucose",
        "label_raw": "Glucose",
        "value_num": "90",
        "value_text": "90",
        "unit_raw": "mg/dL",
        "unit_norm": "mg/dL",
        "ref_low": "70",
        "ref_high": "100",
    }
    row.update(values)
    conn.execute(
        text(
            "INSERT INTO observation (id, document_id, analyte_id, label_raw, "
            "value_num, value_text, unit_raw, unit_norm, ref_low, ref_high, "
            "bbox_json, page, engine, status, created_at) "
            "VALUES (:id, :document_id, :analyte_id, :label_raw, :value_num, "
            ":value_text, :unit_raw, :unit_norm, :ref_low, :ref_high, "
            "'[0.1,0.2,0.3,0.4]', 1, 'test', 'auto', '2026-10-27T00:00:00Z')"
        ),
        {"id": observation_id, "document_id": document_id, **row},
    )


def test_build_summary_keeps_mixed_units_apart(app):
    from smriti.summary import build_summary

    with app.state.engine.begin() as conn:
        _patient_with_document(conn, "d-a", doc_date="2026-01-01")
        _patient_with_document(conn, "d-b", doc_date="2026-02-01")
        _observation(conn, "o-mg", "d-a", value_num="90", unit_raw="mg/dL", unit_norm="mg/dL")
        _observation(
            conn,
            "o-mmol",
            "d-b",
            value_num="5.0",
            unit_raw="mmol/L",
            unit_norm="mmol/L",
            ref_low="3.9",
            ref_high="5.5",
        )

    with app.state.engine.connect() as conn:
        summary = build_summary(conn, "p-units")

    series = {result.unit: result for result in summary.results}
    assert set(series) == {"mg/dL", "mmol/L"}
    assert series["mg/dL"].ref_low == 70.0
    assert series["mmol/L"].ref_low == 3.9
    assert [point.value for point in series["mg/dL"].points] == [90.0]
    assert [point.value for point in series["mmol/L"].points] == [5.0]


def test_build_summary_uses_registration_date_when_other_dates_missing(app):
    from smriti.summary import build_summary

    with app.state.engine.begin() as conn:
        _patient_with_document(
            conn,
            "d-reg",
            registration_date="2026-02-03",
            created_at="2026-06-01T00:00:00Z",
        )
        _observation(conn, "o-reg", "d-reg")

    with app.state.engine.connect() as conn:
        summary = build_summary(conn, "p-units")

    assert summary.results[0].points[0].date.isoformat() == "2026-02-03"
    assert summary.documents[0].registration_date == date(2026, 2, 3)
    assert summary.coverage.first_date.isoformat() == "2026-02-03"

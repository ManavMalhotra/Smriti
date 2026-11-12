from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.factory import make_patient

pytestmark = pytest.mark.integration


def _seed(app, patient_id: str) -> None:
    with app.state.engine.begin() as conn:
        for index, (doc_type, report_date, category) in enumerate(
            [
                ("ct", "2024-03-02", "imaging"),
                ("lab_report", "2025-11-02", "lab"),
            ],
            start=1,
        ):
            document_id = f"d-{index}"
            conn.execute(
                text(
                    """
                    INSERT INTO document
                        (id, patient_id, doc_type, capture_type, image_path,
                         page_count, content_hash, status, created_at)
                    VALUES
                        (:id, :patient_id, :doc_type, 'printed', :id, 1, :hash,
                         'done', '2026-01-01T00:00:00Z')
                    """
                ),
                {
                    "id": document_id,
                    "patient_id": patient_id,
                    "doc_type": doc_type,
                    "hash": f"hash-{index}",
                },
            )
            report_id = f"r-{index}"
            conn.execute(
                text(
                    """
                    INSERT INTO report
                        (id, document_id, patient_id, category, report_type,
                         report_date, facility_name, title, summary, page_start,
                         page_end, status, model_version, created_at)
                    VALUES
                        (:id, :document_id, :patient_id, :category, :report_type,
                         :report_date, 'City Hospital', :title, :summary, 1, 1,
                         'auto', 'test', '2026-01-01T00:00:00Z')
                    """
                ),
                {
                    "id": report_id,
                    "document_id": document_id,
                    "patient_id": patient_id,
                    "category": category,
                    "report_type": doc_type,
                    "report_date": report_date,
                    "title": "City Hospital",
                    "summary": "Report summary.",
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO observation
                        (id, document_id, report_id, analyte_id, label_raw, label_norm,
                         value_num, value_text, bbox_json, page, engine, status,
                         fact_type, evidence_quote, created_at)
                    VALUES
                        (:id, :document_id, :report_id, :analyte_id, :label, :label_norm,
                         :value_num, :value_text, '[0.1,0.2,0.3,0.4]', 1, 'test',
                         'review', :fact_type, :evidence, '2026-01-01T00:00:00Z')
                    """
                ),
                {
                    "id": f"o-{index}",
                    "document_id": document_id,
                    "report_id": report_id,
                    "analyte_id": "hba1c" if index == 2 else None,
                    "label": "HbA1c" if index == 2 else "Impression",
                    "label_norm": "hba1c" if index == 2 else "impression",
                    "value_num": "8.9" if index == 2 else None,
                    "value_text": "8.9" if index == 2 else "No acute abnormality.",
                    "fact_type": "lab" if index == 2 else "impression",
                    "evidence": "HbA1c 8.9" if index == 2 else "No acute abnormality.",
                },
            )


def test_timeline_returns_reports_newest_first_and_filters(client, app):
    patient_id = make_patient(client, alias="P-01")
    _seed(app, patient_id)

    response = client.get(f"/api/patients/{patient_id}/timeline")
    assert response.status_code == 200, response.text
    reports = response.json()["reports"]
    assert [report["report_date"] for report in reports] == [
        "2025-11-02",
        "2024-03-02",
    ]
    assert reports[0]["review_count"] == 1
    assert reports[0]["facts"][0]["fact_type"] == "lab"
    assert reports[1]["facts"][0]["fact_type"] == "impression"

    filtered = client.get(
        f"/api/patients/{patient_id}/timeline", params={"category": "imaging"}
    )
    assert [report["id"] for report in filtered.json()["reports"]] == ["r-1"]

    dated = client.get(
        f"/api/patients/{patient_id}/timeline",
        params={"from": "2024-01-01", "to": "2024-12-31"},
    )
    assert [report["id"] for report in dated.json()["reports"]] == ["r-1"]


def test_timeline_rejects_inverted_dates_and_omits_rejected_reports(client, app):
    patient_id = make_patient(client, alias="P-01")
    _seed(app, patient_id)

    inverted = client.get(
        f"/api/patients/{patient_id}/timeline",
        params={"from": "2025-01-01", "to": "2024-01-01"},
    )
    assert inverted.status_code == 400

    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE report SET status = 'rejected' WHERE id = 'r-2'"))
    response = client.get(f"/api/patients/{patient_id}/timeline")
    assert [report["id"] for report in response.json()["reports"]] == ["r-1"]


def test_timeline_is_scoped_to_the_owning_patient(app):
    with TestClient(app) as alice:
        alice_id = make_patient(alice, alias="Alice")
        _seed(app, alice_id)

    with TestClient(app) as bob:
        bob_id = make_patient(bob, alias="Bob")
        response = bob.get(f"/api/patients/{alice_id}/timeline")
        assert response.status_code == 403
        assert bob.get(f"/api/patients/{bob_id}/timeline").json()["reports"] == []


def test_report_correction_updates_date_category_and_audit(client, app):
    patient_id = make_patient(client, alias="P-01")
    _seed(app, patient_id)

    response = client.patch(
        "/api/reports/r-1",
        json={"report_date": "2024-03-03", "category": "lab"},
    )
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["report_date"] == "2024-03-03"
    assert report["category"] == "lab"
    assert report["status"] == "auto"

    with app.state.engine.connect() as conn:
        audit_rows = conn.execute(
            text(
                "SELECT field, old, new FROM audit "
                "WHERE entity = 'report' AND entity_id = 'r-1' ORDER BY ts"
            )
        ).all()
    assert ("report_date", "2024-03-02", "2024-03-03") in [tuple(row) for row in audit_rows]
    assert ("category", "imaging", "lab") in [tuple(row) for row in audit_rows]

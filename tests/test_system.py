"""End-to-end journeys through intake, worker, review, and summary."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from smriti.ocr import OcrWord
from tests.staged_runtime import run_batch
from tests.factory import handwritten_image, jpeg_bytes, make_patient, text_image, upload

pytestmark = pytest.mark.system


class _PrintedLabOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("Collection Date: 02/01/2099", [0.08, 0.04, 0.9, 0.08], 0.99),
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.08, 0.12, 0.9, 0.16], 0.99),
            OcrWord("Glucose 126 mg/dL 70-100", [0.08, 0.20, 0.9, 0.24], 0.98),
            OcrWord("Creatinine 1.2 mg/dL 0.6-1.3", [0.08, 0.28, 0.9, 0.32], 0.98),
            OcrWord("Advice: Review after 2 weeks.", [0.08, 0.36, 0.9, 0.40], 0.98),
        ]


class _HandwrittenOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.08, 0.12, 0.9, 0.16], 0.99),
            OcrWord("Review after 2 weeks.", [0.08, 0.20, 0.9, 0.24], 0.98),
        ]


def _review(client, observation_id: str, payload: dict):
    response = client.post(
        f"/api/observations/{observation_id}/review",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_printed_lab_journey_from_upload_to_reviewed_summary(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()))
    assert uploaded.status_code == 202, uploaded.text
    body = uploaded.json()

    assert run_batch(app.state.engine, settings, ocr_engine=_PrintedLabOcr()) is True

    job = client.get(f"/api/jobs/{body['job_id']}")
    assert job.status_code == 200
    assert job.json()["state"] == "done"

    document = client.get(f"/api/documents/{body['document_id']}")
    assert document.status_code == 200
    detail = document.json()
    assert detail["status"] == "done"
    assert detail["doc_type"] == "lab_report"
    assert detail["capture_type"] == "printed"
    assert detail["collection_date"] == "2099-01-02"
    assert "HbA1c" in detail["page_text"][0]["text"]
    observations = {item["analyte_id"]: item for item in detail["observations"]}
    assert set(observations) == {"hba1c", "glucose", "creatinine"}

    page = client.get(detail["pages"][0]["url"])
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/webp"
    assert page.content

    _review(client, observations["hba1c"]["id"], {"action": "accept"})
    corrected = _review(
        client,
        observations["glucose"]["id"],
        {"action": "correct", "value_num": "118", "unit_norm": "mg/dL"},
    )
    assert corrected["observation"]["value_num"] == "118"
    _review(
        client,
        observations["creatinine"]["id"],
        {"action": "reject", "reason": "Not this patient's row"},
    )

    summary = client.get(f"/api/patients/{patient_id}/summary")
    assert summary.status_code == 200
    data = summary.json()
    results = {result["display"]: result for result in data["results"]}
    assert results["HbA1c"]["points"][0]["value"] == 8.9
    assert results["HbA1c"]["points"][0]["status"] == "auto"
    assert results["Glucose"]["points"][0]["value"] == 118.0
    assert "Creatinine" not in results
    assert data["documents"][0]["review_count"] == 0
    assert len(data["pending"]) == 1
    assert data["pending"][0]["text"] == "Review after 2 weeks"
    assert data["pending"][0]["due_date"] == "2099-01-16"
    assert data["pending"][0]["state"] == "open"

    with app.state.engine.connect() as conn:
        audit = {
            (row[0], row[1])
            for row in conn.execute(
                text("SELECT entity_id, field FROM audit")
            ).all()
        }
    assert (observations["hba1c"]["id"], "status") in audit
    assert (observations["glucose"]["id"], "value_num") in audit
    assert (observations["creatinine"]["id"], "status") in audit


def test_handwritten_journey_creates_no_numeric_results_or_directives(
    client, app, settings
):
    patient_id = make_patient(client, alias="P-02")
    uploaded = upload(client, patient_id, jpeg_bytes(handwritten_image()))
    assert uploaded.status_code == 202, uploaded.text
    body = uploaded.json()

    assert run_batch(app.state.engine, settings, ocr_engine=_HandwrittenOcr()) is True

    detail = client.get(f"/api/documents/{body['document_id']}").json()
    assert detail["status"] == "done"
    assert detail["capture_type"] == "handwritten"
    assert "HbA1c" in detail["page_text"][0]["text"]
    assert detail["observations"] == []
    assert detail["medications"] == []

    summary = client.get(f"/api/patients/{patient_id}/summary").json()
    assert summary["results"] == []
    assert summary["pending"] == []
    assert summary["documents"][0]["review_count"] == 0

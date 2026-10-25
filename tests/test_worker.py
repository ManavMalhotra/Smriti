from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.ocr import OcrUnavailable, OcrWord
from smriti.worker import process_next
from tests.factory import (
    jpeg_bytes,
    make_patient,
    pdf_bytes,
    scanned_pdf_bytes,
    text_image,
    upload,
)

pytestmark = pytest.mark.integration


class _FakeOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("Collection Date: 02/11/2025", [0.1, 0.04, 0.8, 0.08], 0.98),
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.1, 0.10, 0.8, 0.14], 0.98),
            OcrWord("Glucose 126 mg/dL 70-100", [0.1, 0.20, 0.8, 0.24], 0.97),
        ]


class _NeverCalledOcr:
    name = "never-called"

    def read(self, _path):
        raise AssertionError("OCR must not run for a clean digital PDF")


class _FailingOcr:
    name = "failing-ocr"

    def read(self, _path):
        raise OcrUnavailable("OCR model is missing")


class _CtOcr:
    name = "ct-ocr"

    def read(self, _path):
        return [
            OcrWord("CT CHEST WITH IV CONTRAST", [0.1, 0.05, 0.8, 0.09], 0.99),
            OcrWord("Computed tomography of the thorax.", [0.1, 0.10, 0.8, 0.14], 0.99),
            OcrWord("Findings: Both lungs show normal aeration.", [0.1, 0.20, 0.8, 0.24], 0.98),
            OcrWord(
                "Impression: Normal CT scan of chest. No acute abnormality.",
                [0.1, 0.35, 0.8, 0.39],
                0.98,
            ),
        ]


def _upload_without_type(client, patient_id):
    return client.post(
        "/api/documents",
        data={"patient_id": patient_id, "consent_scope": "local"},
        files={"file": ("page.jpg", jpeg_bytes(text_image()), "image/jpeg")},
    )


def test_worker_extracts_lab_report_and_summary(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = _upload_without_type(client, patient_id)
    assert uploaded.status_code == 202, uploaded.text
    body = uploaded.json()

    assert process_next(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    job = client.get(f"/api/jobs/{body['job_id']}")
    assert job.status_code == 200
    assert job.json()["state"] == "done"

    document = client.get(f"/api/documents/{body['document_id']}")
    assert document.status_code == 200
    detail = document.json()
    assert detail["doc_type"] == "lab_report"
    assert detail["status"] == "done"
    assert detail["collection_date"] == "2025-11-02"
    assert len(detail["observations"]) == 2
    assert len(detail["page_text"]) == 1
    assert "HbA1c" in detail["page_text"][0]["text"]
    assert {item["status"] for item in detail["observations"]} == {"review"}
    assert {item["source"] for item in detail["observations"]} == {"ocr"}
    assert {item["model_version"] for item in detail["observations"]} == {"fake-ocr"}

    summary = client.get(f"/api/patients/{patient_id}/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["patient"]["alias"] == "P-01"
    assert len(data["documents"]) == 1
    assert data["documents"][0]["review_count"] == 2
    assert len(data["results"]) == 2
    by_display = {result["display"]: result for result in data["results"]}
    assert by_display["HbA1c"]["points"][0]["value"] == 8.9
    assert by_display["HbA1c"]["points"][0]["status"] == "review"
    assert by_display["Glucose"]["points"][0]["value"] == 126.0


def test_worker_failure_is_visible(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = _upload_without_type(client, patient_id)
    body = uploaded.json()

    assert process_next(app.state.engine, settings, ocr_engine=_FailingOcr()) is True

    job = client.get(f"/api/jobs/{body['job_id']}").json()
    assert job["state"] == "failed"
    assert "OCR model is missing" in job["error"]
    document = client.get(f"/api/documents/{body['document_id']}").json()
    assert document["status"] == "failed"


def test_duplicate_detection_is_scoped_per_patient(app, settings):
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_id = make_patient(alice, alias="Alice")
        bob_id = make_patient(bob, alias="Bob")
        data = jpeg_bytes(text_image())

        first = alice.post(
            "/api/documents",
            data={"patient_id": alice_id, "consent_scope": "local"},
            files={"file": ("page.jpg", data, "image/jpeg")},
        )
        second = bob.post(
            "/api/documents",
            data={"patient_id": bob_id, "consent_scope": "local"},
            files={"file": ("page.jpg", data, "image/jpeg")},
        )

        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["document_id"] != second.json()["document_id"]


def test_patients_cannot_read_each_others_records(app, settings):
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_id = make_patient(alice, alias="Alice")
        bob_id = make_patient(bob, alias="Bob")
        uploaded = _upload_without_type(alice, alice_id)
        body = uploaded.json()

        assert bob.get(f"/api/documents/{body['document_id']}").status_code == 404
        assert bob.get(f"/api/jobs/{body['job_id']}").status_code == 404
        assert bob.get(f"/api/patients/{alice_id}/summary").status_code == 403
        assert bob.post(
            "/api/documents",
            data={"patient_id": alice_id, "consent_scope": "local"},
            files={"file": ("page.jpg", jpeg_bytes(text_image()), "image/jpeg")},
        ).status_code == 403

        own_summary = bob.get(f"/api/patients/{bob_id}/summary")
        assert own_summary.status_code == 200
        assert own_summary.json()["documents"] == []


def test_digital_pdf_uses_text_layer_without_ocr(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    response = upload(
        client,
        patient_id,
        pdf_bytes(2),
        filename="report.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 202, response.text
    body = response.json()

    assert process_next(app.state.engine, settings, ocr_engine=_NeverCalledOcr()) is True

    assert client.get(f"/api/jobs/{body['job_id']}").json()["state"] == "done"
    detail = client.get(f"/api/documents/{body['document_id']}").json()
    assert detail["status"] == "done"
    assert {page["engine"] for page in detail["page_text"]} == {"text_layer"}
    assert {page["source"] for page in detail["page_text"]} == {"text_layer"}
    assert all(
        page["model_version"].startswith("pymupdf:")
        for page in detail["page_text"]
    )
    assert any("HbA1c" in page["text"] for page in detail["page_text"])


def test_scanned_pdf_falls_back_to_ocr(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    response = upload(
        client,
        patient_id,
        scanned_pdf_bytes(),
        filename="scan.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 202, response.text
    body = response.json()

    assert process_next(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    detail = client.get(f"/api/documents/{body['document_id']}").json()
    assert detail["status"] == "done"
    assert {page["engine"] for page in detail["page_text"]} == {"fake-ocr"}
    assert {page["source"] for page in detail["page_text"]} == {"ocr"}
    assert {page["model_version"] for page in detail["page_text"]} == {"fake-ocr"}


def test_stage_artifacts_cached_and_reused_on_resume(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    response = upload(
        client,
        patient_id,
        scanned_pdf_bytes(),
        filename="scan_stage.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 202
    body = response.json()
    job_id = body["job_id"]
    doc_id = body["document_id"]

    # Initial processing with OCR
    assert process_next(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    # Verify stage_artifact rows created in SQLite
    with app.state.engine.connect() as conn:
        doc = conn.execute(
            text("SELECT content_hash FROM document WHERE id = :id"), {"id": doc_id}
        ).first()
        content_hash = doc[0]
        artifacts = conn.execute(
            text(
                "SELECT page, stage, model_version FROM stage_artifact WHERE content_hash = :hash"
            ),
            {"hash": content_hash},
        ).all()
        assert len(artifacts) >= 1
        assert artifacts[0][1] == "ocr"

        job = conn.execute(
            text("SELECT state, stage FROM jobs WHERE id = :id"), {"id": job_id}
        ).first()
        assert job[0] == "done"
        assert job[1] == "done"

    # Reset job to queued to simulate a resume/re-run
    with app.state.engine.begin() as conn:
        conn.execute(
            text("UPDATE jobs SET state = 'queued', stage = 'stage_ocr' WHERE id = :id"),
            {"id": job_id},
        )

    # Process again with _NeverCalledOcr() - proves OCR is completely bypassed via stage_artifact cache!
    assert process_next(app.state.engine, settings, ocr_engine=_NeverCalledOcr()) is True

    detail = client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "done"


def test_worker_extracts_prose_sections_from_imaging_report(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    response = upload(
        client,
        patient_id,
        scanned_pdf_bytes(),
        filename="ct_report.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 202
    body = response.json()

    assert process_next(app.state.engine, settings, ocr_engine=_CtOcr()) is True

    detail = client.get(f"/api/documents/{body['document_id']}").json()
    assert detail["status"] == "done"
    assert detail["doc_type"] == "ct"

    labels = {obs["label_raw"]: obs for obs in detail["observations"]}
    assert "Impression" in labels
    assert "Normal CT scan of chest" in labels["Impression"]["value_text"]
    assert "Grounded prose extraction" in labels["Impression"]["reason"]
    assert labels["Impression"]["value_num"] is None
    assert labels["Impression"]["status"] == "review"

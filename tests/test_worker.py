from __future__ import annotations

from fastapi.testclient import TestClient

from smriti.ocr import OcrUnavailable, OcrWord
from smriti.worker import process_next
from tests.factory import jpeg_bytes, make_patient, text_image


class _FakeOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.1, 0.10, 0.8, 0.14], 0.98),
            OcrWord("Glucose 126 mg/dL 70-100", [0.1, 0.20, 0.8, 0.24], 0.97),
        ]


class _FailingOcr:
    name = "failing-ocr"

    def read(self, _path):
        raise OcrUnavailable("OCR model is missing")


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
    assert len(detail["observations"]) == 2
    assert len(detail["page_text"]) == 1
    assert "HbA1c" in detail["page_text"][0]["text"]
    assert {item["status"] for item in detail["observations"]} == {"review"}

    summary = client.get(f"/api/patients/{patient_id}/summary")
    assert summary.status_code == 200
    data = summary.json()
    assert data["patient"]["alias"] == "P-01"
    assert len(data["documents"]) == 1
    assert len(data["results"]) == 2
    by_display = {result["display"]: result for result in data["results"]}
    assert by_display["HbA1c"]["points"][0]["value"] == 8.9
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

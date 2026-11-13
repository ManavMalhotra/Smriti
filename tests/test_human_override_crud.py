from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.factory import jpeg_bytes, make_patient, text_image, upload
from tests.staged_runtime import run_batch
from smriti.ocr import OcrWord

pytestmark = pytest.mark.integration


class _FakeOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.1, 0.10, 0.8, 0.14], 0.98),
            OcrWord("Glucose 126 mg/dL 70-100", [0.1, 0.20, 0.8, 0.24], 0.97),
        ]


def test_document_patch_cascades_to_reports_and_summary(client, app, settings):
    patient_id = make_patient(client, alias="P-CRUD")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type="lab_report")
    assert uploaded.status_code == 202
    doc_id = uploaded.json()["document_id"]
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    # Patch verified_date and doc_type
    patch_res = client.patch(
        f"/api/documents/{doc_id}",
        json={
            "display_name": "Thyroid & Sugar Panel",
            "doc_type": "prescription",
            "verified_date": "2026-05-15",
            "facility_name": "Apollo Clinic",
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    data = patch_res.json()
    assert data["document"]["display_name"] == "Thyroid & Sugar Panel"
    assert data["document"]["doc_type"] == "prescription"
    assert data["document"]["verified_date"] == "2026-05-15"
    assert data["document"]["facility_name"] == "Apollo Clinic"
    assert "summary" in data

    # Verify report row was cascaded
    with app.state.engine.connect() as conn:
        report = conn.execute(
            text("SELECT category, report_type, report_date, facility_name FROM report WHERE document_id = :id"),
            {"id": doc_id},
        ).mappings().first()
        assert report is not None
        assert report["category"] == "prescription"
        assert report["report_type"] == "prescription"
        assert report["report_date"] == "2026-05-15"
        assert report["facility_name"] == "Apollo Clinic"


def test_manual_observation_creation(client, app, settings):
    patient_id = make_patient(client, alias="P-OBS")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type="lab_report")
    doc_id = uploaded.json()["document_id"]
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    # Add missing observation manually
    create_res = client.post(
        f"/api/documents/{doc_id}/observations",
        json={
            "raw_label": "Serum Creatinine",
            "analyte_id": "creatinine",
            "value_num": "1.2",
            "unit_norm": "mg/dL",
            "ref_low": "0.7",
            "ref_high": "1.3",
            "flag": "Normal",
            "page": 1,
            "bbox": [0.1, 0.4, 0.8, 0.45],
        },
    )
    assert create_res.status_code == 201, create_res.text
    body = create_res.json()
    assert body["observation"]["label_raw"] == "Serum Creatinine"
    assert body["observation"]["analyte_id"] == "creatinine"
    assert body["observation"]["value_num"] == "1.2"
    assert body["observation"]["engine"] == "human"
    assert body["observation"]["status"] == "auto"

    # Confirm it appears in patient summary results
    results_by_id = {r["analyte_id"]: r for r in body["summary"]["results"]}
    assert "creatinine" in results_by_id
    assert results_by_id["creatinine"]["points"][0]["value"] == 1.2


def test_medication_crud(client, app, settings):
    patient_id = make_patient(client, alias="P-MED")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type="prescription")
    doc_id = uploaded.json()["document_id"]

    # Insert a medication via quick-entry or direct
    entry_res = client.post(
        f"/api/documents/{doc_id}/quick-entry",
        json={
            "doc_type": "prescription",
            "doc_date": "2026-06-01",
            "medications": [
                {"name": "Metformin 500mg", "dose": "500 mg", "frequency": "1-0-1", "page": 1}
            ],
        },
    )
    assert entry_res.status_code == 200, entry_res.text

    # Get medication ID
    detail = client.get(f"/api/documents/{doc_id}").json()
    assert len(detail["medications"]) == 1
    med_id = detail["medications"][0]["id"]

    # Patch medication
    patch_res = client.patch(
        f"/api/medications/{med_id}",
        json={
            "brand_raw": "Metformin Extended Release",
            "dose": "1000 mg",
            "freq": "0-0-1",
            "status": "reported_ongoing",
        },
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["medication"]["brand_raw"] == "Metformin Extended Release"
    assert patch_res.json()["medication"]["dose"] == "1000 mg"
    assert patch_res.json()["medication"]["status"] == "reported_ongoing"

    # Delete medication
    del_res = client.delete(f"/api/medications/{med_id}")
    assert del_res.status_code == 200, del_res.text
    assert del_res.json()["deleted"] is True

    # Verify gone from document
    detail_after = client.get(f"/api/documents/{doc_id}").json()
    assert len(detail_after["medications"]) == 0


def test_document_delete(client, app, settings):
    patient_id = make_patient(client, alias="P-DEL")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type="lab_report")
    doc_id = uploaded.json()["document_id"]
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr()) is True

    # Delete document
    del_res = client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200, del_res.text
    assert del_res.json()["deleted"] is True

    # Verify document returns 404
    get_res = client.get(f"/api/documents/{doc_id}")
    assert get_res.status_code == 404

    # Verify database is cleaned up
    with app.state.engine.connect() as conn:
        for tbl in ("document", "observation", "report", "page_text", "jobs"):
            cnt = conn.execute(text(f"SELECT COUNT(*) FROM {tbl} WHERE document_id = :id" if tbl != "document" else "SELECT COUNT(*) FROM document WHERE id = :id"),
                               {"id": doc_id}).scalar_one()
            assert cnt == 0, f"Table {tbl} still has rows for document"

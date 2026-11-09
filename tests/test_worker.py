"""Connected synthetic journeys through the bounded coordinator, never an eager production fallback."""

from dataclasses import replace
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti import vlm, publication, model_stages
from smriti.extract import ExtractedField
from smriti.ocr import OcrWord, OcrUnavailable
from smriti.worker import _handwritten_pages, cross_check_extractions
from tests.factory import jpeg_bytes, make_patient, pdf_bytes, scanned_pdf_bytes, text_image, upload
from tests.staged_runtime import OCR_NAME, run_batch

pytestmark = pytest.mark.integration


def _field(value: str, *, engine: str) -> ExtractedField:
    return ExtractedField(analyte_id="glucose", label_raw="Glucose", value_num=value,
        value_text=value, unit_raw="mg/dL", ref_low="70", ref_high="100", flag_printed=None,
        bbox=[0.1, 0.1, 0.2, 0.2], page=1, confidence=0.9, mapping_rule="exact", engine=engine)


def test_cross_check_marks_exact_match_and_discrepancy():
    ocr = _field("126", engine="ocr")
    matched = cross_check_extractions([ocr], [_field("126", engine="vlm")], [[]])
    assert matched[0].reason == "Dual-read verified: OCR and Qwen3-VL exact match."
    assert matched[0].engine == "ocr+vlm"
    mismatched = cross_check_extractions([ocr], [_field("128", engine="vlm")], [[]])
    assert "OCR='126' vs VLM='128'" in mismatched[0].reason


def test_cross_check_marks_unconfirmed_ocr_reading():
    checked = cross_check_extractions([_field("126", engine="ocr")], [], [[]])
    assert checked[0].reason == "OCR-only reading; Qwen3-VL did not confirm it. Review required."


def test_handwritten_pages_reads_page_level_ingest_metadata():
    quality = '{"pages":[{"page":1,"capture_type":"printed"},{"page":2,"capture_type":"handwritten"}]}'
    assert _handwritten_pages(quality) == {2}


class _FakeOcr:
    def read(self, _path):
        return [
            OcrWord("Collection Date: 02/11/2025", [0.1, 0.04, 0.8, 0.08], 0.98),
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.1, 0.10, 0.8, 0.14], 0.98),
            OcrWord("Glucose 126 mg/dL 70-100", [0.1, 0.20, 0.8, 0.24], 0.97),
        ]


class _NeverCalledOcr:
    def read(self, _path):
        pytest.fail("No OCR for usable PDF text or completed documents")


def untyped(client, patient):
    return upload(client, patient, jpeg_bytes(text_image()), doc_type=None)


def test_worker_extracts_lab_report_and_summary(client, app, settings):
    patient = make_patient(client)
    result = untyped(client, patient).json()
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr())
    job = client.get(f"/api/jobs/{result['job_id']}").json()
    assert job["state"] == "done" and job["finished_at"] and job["elapsed_seconds"] >= 0
    events = [event["event"] for event in job["events"]]
    assert events[:3] == ["intake_accepted", "preparing", "prepared"]
    assert events.index("page_read") < events.index("extracting") < events.index("saving") < events.index("done")
    assert "HbA1c" not in json.dumps(job) and "2025-11-02" not in json.dumps(job)
    detail = client.get(f"/api/documents/{result['document_id']}").json()
    assert detail["doc_type"] == "lab_report" and detail["status"] == "done"
    assert detail["collection_date"] == "2025-11-02"
    assert len(detail["observations"]) == 2 and len(detail["reports"]) == 1
    assert {item["report_id"] for item in detail["observations"]} == {detail["reports"][0]["id"]}
    assert {item["fact_type"] for item in detail["observations"]} == {"lab"}
    assert {item["status"] for item in detail["observations"]} == {"review"}
    assert {item["source"] for item in detail["observations"]} == {"ocr"}
    assert {item["model_version"] for item in detail["observations"]} == {OCR_NAME}
    summary = client.get(f"/api/patients/{patient}/summary").json()
    assert summary["documents"][0]["review_count"] == 2 and len(summary["results"]) == 2
    by_display = {result["display"]: result for result in summary["results"]}
    assert by_display["HbA1c"]["points"][0]["value"] == 8.9
    assert by_display["Glucose"]["points"][0]["value"] == 126.0


def test_worker_failure_is_private_and_keeps_stored_source(client, app, settings):
    class Failing:
        def read(self, path):
            raise OcrUnavailable("PRIVATE_MEDICAL_SENTINEL")
    result = untyped(client, make_patient(client)).json()
    assert run_batch(app.state.engine, settings, ocr_engine=Failing())
    job = client.get(f"/api/jobs/{result['job_id']}").json()
    assert job["state"] == "failed" and "PRIVATE_MEDICAL_SENTINEL" not in json.dumps(job)
    assert client.get(f"/api/documents/{result['document_id']}/page/1").status_code == 200


def test_duplicate_detection_is_scoped_per_patient(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_id, bob_id = make_patient(alice), make_patient(bob, alias="Bob")
        first, second = untyped(alice, alice_id), untyped(bob, bob_id)
        assert first.status_code == second.status_code == 202
        assert first.json()["document_id"] != second.json()["document_id"]


def test_patients_cannot_read_each_others_records(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        alice_id, bob_id = make_patient(alice), make_patient(bob, alias="Bob")
        result = untyped(alice, alice_id).json()
        assert bob.get(f"/api/documents/{result['document_id']}").status_code == 404
        assert bob.get(f"/api/jobs/{result['job_id']}").status_code == 404
        assert bob.get(f"/api/patients/{alice_id}/summary").status_code == 403
        assert bob.post("/api/documents", data={"patient_id": alice_id, "consent_scope": "local"}, files={"file": ("synthetic.jpg", jpeg_bytes(text_image()), "image/jpeg")}).status_code == 403
        assert bob.get(f"/api/patients/{bob_id}/summary").json()["documents"] == []


@pytest.mark.parametrize("digital", [True, False])
def test_digital_pdf_avoids_ocr_and_scanned_pdf_uses_it(client, app, settings, digital):
    data = pdf_bytes(2) if digital else scanned_pdf_bytes()
    result = upload(client, make_patient(client), data, filename="synthetic.pdf", content_type="application/pdf").json()
    assert run_batch(app.state.engine, settings, ocr_engine=_NeverCalledOcr() if digital else _FakeOcr())
    detail = client.get(f"/api/documents/{result['document_id']}").json()
    assert detail["status"] == "done"
    assert {page["source"] for page in detail["page_text"]} == {"text_layer" if digital else "ocr"}
    assert {page["engine"] for page in detail["page_text"]} == {"text_layer" if digital else OCR_NAME}
    assert any("HbA1c" in page["text"] for page in detail["page_text"])


def test_done_reviewed_document_is_not_reprocessed_and_disposable_cache_is_removed(client, app, settings):
    result = untyped(client, make_patient(client)).json()
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr())
    detail = client.get(f"/api/documents/{result['document_id']}").json()
    observation = detail["observations"][0]
    assert client.post(f"/api/observations/{observation['id']}/review", json={"action": "accept"}).status_code == 200
    assert not run_batch(app.state.engine, settings, ocr_engine=_NeverCalledOcr())
    assert not (settings.upload_dir / ".runtime" / result["job_id"]).exists()
    again = client.get(f"/api/documents/{result['document_id']}").json()
    assert next(item for item in again["observations"] if item["id"] == observation["id"])["status"] == "auto"


def test_worker_extracts_grounded_imaging_sections(client, app, settings):
    class CtOcr:
        def read(self, path):
            return [
                OcrWord("CT CHEST WITH IV CONTRAST", [0.1, 0.05, 0.8, 0.09], 0.99),
                OcrWord("Computed tomography of the thorax.", [0.1, 0.10, 0.8, 0.14], 0.99),
                OcrWord("Findings: Both lungs show normal aeration.", [0.1, 0.20, 0.8, 0.24], 0.98),
                OcrWord("Impression: Normal CT scan of chest. No acute abnormality.", [0.1, 0.35, 0.8, 0.39], 0.98),
            ]
    result = untyped(client, make_patient(client)).json()
    assert run_batch(app.state.engine, settings, ocr_engine=CtOcr())
    detail = client.get(f"/api/documents/{result['document_id']}").json()
    assert detail["doc_type"] == "ct" and detail["status"] == "done"
    impression = next(item for item in detail["observations"] if item["label_raw"] == "Impression")
    assert "Normal CT scan" in impression["value_text"] and "Grounded prose" in impression["reason"]
    assert impression["value_num"] is None and impression["evidence_quote"] == impression["value_text"]
    assert detail["reports"][0]["category"] == "imaging"


class _FakeVlmSession:
    def __init__(self, *, timeout, on_event):
        self.on_event = on_event

    def __enter__(self):
        self.on_event("qwen_ready", duration=0.01)
        return self

    def __exit__(self, *args):
        self.on_event("unloading")
        self.on_event("unloaded")


@pytest.mark.parametrize("outcome", ["success", "empty", "failure", "unavailable"])
def test_worker_qwen_events_and_private_failures(client, app, settings, monkeypatch, outcome):
    result = untyped(client, make_patient(client)).json()
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: outcome != "unavailable")
    monkeypatch.setattr(vlm, "VlmSession", _FakeVlmSession)
    monkeypatch.setattr(model_stages, "psutil", type("P", (), {"virtual_memory": staticmethod(lambda: type("M", (), {"available": 8 * 1024**3})())}))
    def infer(path, page, **kwargs):
        progress = client.get(f"/api/jobs/{result['job_id']}").json()
        assert progress["stage"] == "qwen" and progress["current_page"] == 1 and progress["completed_pages"] == 0
        if outcome == "failure":
            raise RuntimeError("PRIVATE_MEDICAL_SENTINEL")
        return [_field("126", engine=vlm.VLM_ENGINE_NAME)] if outcome == "success" else []
    monkeypatch.setattr(vlm, "extract_page_vlm", infer)
    assert run_batch(app.state.engine, replace(settings, vlm_enabled=True), ocr_engine=_FakeOcr())
    job = client.get(f"/api/jobs/{result['job_id']}").json()
    assert job["state"] == "done"
    events = [event["event"] for event in job["events"]]
    assert "qwen_disabled" not in events
    if outcome == "success":
        assert events.index("qwen_page") < events.index("cross_checked") < events.index("saving") < events.index("done")
    else:
        assert events[-1] == "done" and job["verification_state"] == "unavailable"
        detail = client.get(f"/api/documents/{result['document_id']}").json()
        assert all(field["status"] == "review" for field in detail["observations"])
        assert any("OCR-only" in field["reason"] for field in detail["observations"])
    assert "PRIVATE_MEDICAL_SENTINEL" not in json.dumps(job)


def test_failed_save_never_announces_done_or_publishes_partial_facts(client, app, settings, monkeypatch):
    result = untyped(client, make_patient(client)).json()
    def fail(*args):
        raise RuntimeError("PRIVATE_SAVE_FAILURE")
    monkeypatch.setattr(publication, "_rows", fail)
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr())
    job = client.get(f"/api/jobs/{result['job_id']}").json()
    assert job["state"] == "failed" and all(event["event"] != "done" for event in job["events"])
    assert client.get(f"/api/documents/{result['document_id']}").json()["observations"] == []

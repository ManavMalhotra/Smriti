import io
import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import text

from smriti.candidates import Candidate
from smriti.config import Settings
from smriti.preprocess import redact_page_for_cloud
from smriti.vlm import extract_window_with_gemini

pytestmark = pytest.mark.unit
pytest.importorskip("google.genai", reason="Install requirements-cloud.txt to test the optional SDK")
pytest.importorskip("rapidfuzz", reason="Install requirements-cloud.txt to test cloud redaction")


def clinical_item(**values):
    return {"source_page": 25, "bbox_2d": [200, 100, 300, 600], "report_date": "2026-04-08",
        "event_date": "2026-04-08", "category": "lab_result", "organ_system": "blood_immunity",
        "title": "Hemoglobin", "value_num": 9.1, "value_text": "9.1 g/dL", "unit": "g/dL",
        "ref_min": 12., "ref_max": 16., "abnormal_flag": "low", "regimen_type": None,
        "facility_or_doctor": None, "confidence_note": "verified_printed", **values}


def fake_gemini(monkeypatch, items, calls):
    from google import genai
    class Client:
        def __init__(self, **kwargs):
            self.models = self
            calls.append(kwargs)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text=json.dumps({"items": items}))
    monkeypatch.setattr(genai, "Client", Client)


def jpeg(page=25):
    return redact_page_for_cloud(np.full((1000, 1000, 3), 255, np.uint8), [], set(), False, page)


def test_gemini_dates_or_regimens_and_duplicate_source_anchors(monkeypatch):
    items = [clinical_item(), clinical_item(source_page=38),
             clinical_item(event_date="2096-02-03", value_num=10., value_text="10 g/dL"),
             clinical_item(category="procedure_surgery", title="Right Mastectomy + ALND", value_num=None,
                value_text="Completed", event_date="2025-09-09", organ_system="oncology_surgeries", regimen_type="completed_procedure"),
             clinical_item(category="medication", title="Valcivir OR Acyclovir", value_num=None,
                value_text="1g OR 800mg", regimen_type="alternative_or", confidence_note="deciphered_handwriting")]
    calls, outcomes = [], []
    fake_gemini(monkeypatch, items, calls)
    fields = extract_window_with_gemini([jpeg(), jpeg(38)], [25, 38], "PRIVATE PATIENT NAME",
        settings=Settings(gemini_api_key="synthetic-key"), on_outcome=outcomes.append)
    assert outcomes == ["sent"] and len(fields) == 4
    assert all(isinstance(field, Candidate) for field in fields)
    assert fields[0].bbox == [.1, .2, .6, .3]
    assert [a["page_num"] for a in fields[0].clinical_metadata["source_anchors"]] == [25, 38]
    assert fields[1].clinical_metadata["event_date"] == "2026-02-03"
    assert fields[1].clinical_metadata["original_event_date"] == "2096-02-03"
    assert fields[1].clinical_metadata["date_needs_review"]
    assert fields[2].clinical_metadata["event_date"] == "2025-09-09"
    assert fields[3].clinical_metadata["regimen_type"] == "alternative_or"
    assert calls[1]["model"] == "gemini-3.8-flash"
    assert calls[1]["config"].thinking_config.thinking_level == "HIGH"
    assert "PRIVATE PATIENT NAME" not in str(calls)
    assert calls[1]["contents"][1].inline_data.mime_type == "image/jpeg"


@pytest.mark.parametrize("change", [{"source_page": 999}, {"event_date": "not-a-date"}, {"bbox_2d": [-1, 0, 300, 600]}, {"value_num": float("inf")}])
def test_malformed_model_output_is_offline_fallback(monkeypatch, change):
    fake_gemini(monkeypatch, [clinical_item(**change)], [])
    outcomes = []
    assert extract_window_with_gemini([jpeg()], [25], "", settings=Settings(gemini_api_key="fake"), on_outcome=outcomes.append) == []
    assert outcomes == ["failed"]


def test_missing_key_demo_and_raw_pdf_never_call_sdk(monkeypatch):
    calls = []
    fake_gemini(monkeypatch, [], calls)
    for settings in [Settings(), Settings(profile="demo", gemini_api_key="fake"), Settings(gemini_api_key="fake")]:
        assert extract_window_with_gemini([b"%PDF-raw"], [25], "", settings=settings) == []
    assert calls == []


def test_local_or_medication_is_not_split_into_two_daily_drugs():
    from smriti.extract import _extract_medications
    from smriti.ocr import OcrWord
    drugs = _extract_medications([OcrWord("Tab. Valcivir 1g OR Acyclovir 800mg SOS", [.1, .1, .9, .2], .9)])
    assert len(drugs) == 1 and "OR" in drugs[0].brand_raw and "SOS" in drugs[0].brand_raw


def test_cloud_regimen_cannot_override_explicit_or_as_scheduled(monkeypatch):
    fake_gemini(monkeypatch, [clinical_item(category="medication", value_num=None,
        title="Valcivir OR Acyclovir", value_text="1g OR 800mg", regimen_type="scheduled")], [])
    field = extract_window_with_gemini([jpeg()], [25], "", settings=Settings(gemini_api_key="fake"))[0]
    assert field.clinical_metadata["regimen_type"] == "alternative_or"


@pytest.mark.integration
def test_snapshot_and_master_timeline_keep_event_dates_and_source_anchors(app):
    from smriti.candidates import clinical_candidate
    from smriti.summary import build_summary
    from smriti.vlm import ExtractedClinicalItem
    from tests.test_summary import _patient_with_document

    items = [clinical_item(source_page=1), clinical_item(source_page=1, event_date="2025-09-09",
        category="procedure_surgery", title="Right Mastectomy + ALND", value_num=None, value_text="Completed"),
        clinical_item(source_page=1, category="diagnosis_allergy", title="Allergy: Sulpha drugs", value_num=None, value_text="Reported"),
        clinical_item(source_page=1, category="diagnosis_allergy", title="No known allergies", value_num=None, value_text="None")]
    with app.state.engine.begin() as conn:
        _patient_with_document(conn, "d-history", doc_date="2026-04-08")
        conn.execute(text("UPDATE document SET doc_type = 'discharge_summary', report_date = '2026-04-08' WHERE id = 'd-history'"))
        for index, item in enumerate(items):
            field = clinical_candidate(ExtractedClinicalItem.model_validate(item))
            conn.execute(text("""INSERT INTO observation (id, document_id, analyte_id, label_raw, value_num, value_text,
                unit_raw, ref_low, ref_high, bbox_json, page, engine, status, fact_type, clinical_json, created_at)
                VALUES (:id, 'd-history', :analyte, :title, :number, :value, :unit, :low, :high, :bbox,
                    1, :engine, 'review', :fact, :clinical, '2026-04-08')"""),
                {"id": f"clinical-{index}", "analyte": field.analyte_id, "title": field.label_raw,
                 "number": field.value_num, "value": field.value_text, "unit": field.unit_raw,
                 "low": field.ref_low, "high": field.ref_high, "bbox": json.dumps(field.bbox),
                 "engine": field.engine, "fact": "lab" if index == 0 else "diagnosis" if index >= 2 else "note",
                 "clinical": json.dumps(field.clinical_metadata)})
    with app.state.engine.connect() as conn:
        summary = build_summary(conn, "p-units")
    assert len(summary.clinical_snapshot["allergies"]) == 1
    surgery = summary.clinical_snapshot["major_procedures"][0]
    assert surgery["event_date"] == "2025-09-09" and surgery["is_backdated_from_summary"]
    assert surgery["page_num"] == 1 and surgery["bbox_2d"] == [200, 100, 300, 600]
    assert summary.organ_groups["blood_immunity"][0]["series"][0]["ref_min"] == 12


@pytest.mark.integration
@pytest.mark.parametrize("approved", [True, False])
def test_consent_pause_resume_source_masks_and_atomic_publication(monkeypatch, app, client, settings, approved):
    from smriti import model_stages
    from smriti.coordinator import Coordinator
    from tests.factory import make_patient, upload, jpeg_bytes, text_image
    from tests.test_preparation import inline_supervisor

    settings = replace(settings, gemini_api_key="fake")
    app.state.settings = settings
    patient = make_patient(client)
    uploaded = upload(client, patient, jpeg_bytes(text_image()), consent_scope="local_plus_projection").json()
    original = model_stages.prepare_cloud_pages
    monkeypatch.setattr(model_stages, "prepare_cloud_pages", lambda engine, settings, row, scratch, _: original(engine, settings, row, scratch, "discharge_summary"))
    calls = []
    fake_gemini(monkeypatch, [clinical_item(source_page=1)], calls)
    # Synthetic printed text images need a local OCR seam, never a real model.
    class Ocr:
        name = "rapidocr:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec@onnx+cpu"
        def _load(self):
            pass
        def read(self, path, *, debug):
            from smriti.ocr import OcrWord
            return [OcrWord("Hemoglobin 9.1 g/dL 12-16", [.1, .4, .6, .45], .99)]
    monkeypatch.setattr("smriti.ocr.RapidOcrOnnxEngine", Ocr)
    with Coordinator(app.state.engine, settings, supervisor=inline_supervisor) as controller:
        assert not controller.process_batch()
        assert not controller.process_batch()  # No repeated processing while awaiting consent.
    preview = client.get(f"/api/documents/{uploaded['document_id']}/redaction-preview")
    assert preview.status_code == 200 and preview.headers["cache-control"] == "no-store"
    assert preview.json()["pages"][0]["page_num"] == 1
    assert client.get(f"/api/jobs/{uploaded['job_id']}").json()["status"] == "awaiting_cloud_consent"
    assert not calls
    response = client.post(f"/api/documents/{uploaded['document_id']}/consent", json={"approved": approved, "extra_redaction_boxes": {"1": [[600, 500, 800, 700]]}})
    assert response.status_code == 201
    with Coordinator(app.state.engine, settings, supervisor=inline_supervisor) as controller:
        assert controller.process_batch()
    assert client.get(f"/api/jobs/{uploaded['job_id']}").json()["state"] == "done"
    if approved:
        sent = calls[1]["contents"][1].inline_data.data
        pixels = np.asarray(Image.open(io.BytesIO(sent)))
        h, w = pixels.shape[:2]
        assert np.all(pixels[int(h * .7), int(w * .6)] == 0)
        summary = client.get(f"/api/patients/{patient}/summary").json()
        assert summary["organ_groups"]["blood_immunity"][0]["series"][0]["engine"] == "gemini-3.8-flash-high"
        with app.state.engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM observation WHERE clinical_json IS NOT NULL AND status = 'review'")).scalar_one() == 1
            assert conn.execute(text("SELECT outcome FROM egress")).scalar_one() == "sent"
    else:
        assert not calls
    assert not (settings.upload_dir / ".runtime" / uploaded["job_id"]).exists()
    make_patient(client, alias="Other owner")
    assert client.get(f"/api/documents/{uploaded['document_id']}/redaction-preview").status_code == 404
    assert client.post(f"/api/documents/{uploaded['document_id']}/consent", json={"approved": True}).status_code == 404

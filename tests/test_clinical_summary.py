from __future__ import annotations

from datetime import date
import pytest
from sqlalchemy import text

from smriti.clinical_summary import (
    is_valid_medication_name,
    synthesize_patient_summary_offline,
    get_or_synthesize_summary,
)
from smriti.models import StandardizedClinicalSummary

pytestmark = pytest.mark.integration


def test_is_valid_medication_name_filters_analytes():
    assert is_valid_medication_name("Tab. Pantop 40mg")
    assert is_valid_medication_name("Inj. Endoxan")
    assert is_valid_medication_name("Cap. Ultracet")
    assert not is_valid_medication_name("Triglycerides 204.0 mg/dL")
    assert not is_valid_medication_name("Protein")
    assert not is_valid_medication_name("Globulin")
    assert not is_valid_medication_name("ESTIMATED")
    assert not is_valid_medication_name("Total Bilirubin")
    assert not is_valid_medication_name("")


def test_synthesize_patient_summary_avoids_unlinked_ocr_claims(app):
    engine = app.state.engine
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO patient (id, alias, username, password_hash, sex, dob, created_at)
                VALUES ('p-test-1', 'test_user', 'test_user', 'hash', 'F', '1978-05-12', '2025-01-01')
                ON CONFLICT DO NOTHING
            """)
        )
        conn.execute(
            text("""
                INSERT INTO document (id, patient_id, doc_type, capture_type, doc_date, collection_date, page_count, status, content_hash, image_path, created_at)
                VALUES ('doc-test-1', 'p-test-1', 'discharge_summary', 'printed', '2026-05-20', '2026-05-20', 2, 'done', 'hash1', 'doc-test-1', '2026-05-20')
                ON CONFLICT DO NOTHING
            """)
        )
        conn.execute(
            text("""
                INSERT INTO page_text (document_id, page, text, engine, source, model_version, created_at)
                VALUES ('doc-test-1', 1, 'Final Diagnosis: Carcinoma Right Breast. No h/o DM, HTN, Asthma. Known allergy: Allergic to Sulpha Drugs. Family history: Nil. Underwent Right Mastectomy and Axillary Lymph Node Dissection in Sep 2025. Adjuvant chemotherapy completed. Radiotherapy completed in May 2026.', 'rapidocr', 'ocr', 'v1', '2026-05-20')
                ON CONFLICT DO NOTHING
            """)
        )
        conn.execute(
            text("""
                INSERT INTO medication (id, patient_id, brand_raw, dose, freq, source_doc_id, reported_at, status)
                VALUES ('med-1', 'p-test-1', 'Tab. Pantop', '40mg', 'OD', 'doc-test-1', '2026-05-20', 'reported_ongoing'),
                       ('med-2', 'p-test-1', 'Triglycerides', '204 mg', NULL, 'doc-test-1', '2026-05-20', 'reported_ongoing')
                ON CONFLICT DO NOTHING
            """)
        )

    with engine.connect() as conn:
        summary = synthesize_patient_summary_offline(conn, 'p-test-1')

    assert isinstance(summary, StandardizedClinicalSummary)
    assert summary.patient_name == "test_user"
    assert summary.gender == "F"
    assert summary.hypertension is None
    assert summary.chronic_conditions == []
    assert summary.year_wise_history == []
    assert summary.concise_history_summary is None
    assert summary.current_medications == []
    today = date.today()
    expected_age = today.year - 1978 - ((today.month, today.day) < (5, 12))
    assert summary.age == expected_age


def test_clinical_summary_api_endpoints(client, app):
    # Register and sign in a patient
    reg = client.post(
        "/api/auth/register",
        json={
            "alias": "P-API",
            "sex": "F",
            "username": "api-summary-user",
            "password": "Password123!",
        },
    )
    assert reg.status_code == 201
    patient_id = reg.json()["id"]

    # 1. GET /api/patients/{patient_id}/clinical-summary
    resp = client.get(f"/api/patients/{patient_id}/clinical-summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hypertension"] is None
    assert "year_wise_history" in data
    assert "current_medications" in data

    # 2. POST /api/patients/{patient_id}/clinical-summary/refresh
    resp2 = client.post(f"/api/patients/{patient_id}/clinical-summary/refresh")
    assert resp2.status_code == 200
    assert resp2.json()["hypertension"] is None

    # 3. POST /api/patients/{patient_id}/cloud-consent
    resp3 = client.post(f"/api/patients/{patient_id}/cloud-consent", json={"approved": True})
    assert resp3.status_code == 200
    assert resp3.json()["approved"] is True

    # 4. GET /api/patients/{patient_id}/summary also contains standardized_summary
    resp4 = client.get(f"/api/patients/{patient_id}/summary")
    assert resp4.status_code == 200
    assert "standardized_summary" in resp4.json()
    assert resp4.json()["standardized_summary"] is not None

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.ocr import OcrWord
from tests.staged_runtime import run_batch
from tests.factory import jpeg_bytes, make_patient, text_image, upload

pytestmark = pytest.mark.integration


class _FakeOcr:
    name = "fake-ocr"

    def read(self, _path):
        return [
            OcrWord("HbA1c 8.9 % 4.0-6.0", [0.1, 0.10, 0.8, 0.14], 0.98),
            OcrWord("Glucose 126 mg/dL 70-100", [0.1, 0.20, 0.8, 0.24], 0.97),
        ]


def _processed_document(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type=None)
    assert uploaded.status_code == 202, uploaded.text
    body = uploaded.json()
    assert run_batch(app.state.engine, settings, ocr_engine=_FakeOcr()) is True
    detail = client.get(f"/api/documents/{body['document_id']}").json()
    return patient_id, body["document_id"], detail


def _audit_rows(app, observation_id):
    with app.state.engine.connect() as conn:
        return conn.execute(
            text("SELECT field, old, new FROM audit WHERE entity_id = :id ORDER BY ts"),
            {"id": observation_id},
        ).all()


def test_accept_updates_summary_and_audit(client, app, settings):
    patient_id, document_id, detail = _processed_document(client, app, settings)
    observation = next(
        item for item in detail["observations"] if item["analyte_id"] == "hba1c"
    )

    response = client.post(
        f"/api/observations/{observation['id']}/review",
        json={"action": "accept"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["observation"]["status"] == "auto"
    assert body["observation"]["reason"] == "Accepted during review."
    assert body["summary"]["documents"][0]["id"] == document_id
    assert body["summary"]["documents"][0]["review_count"] == 1
    by_display = {result["display"]: result for result in body["summary"]["results"]}
    assert by_display["HbA1c"]["points"][0]["status"] == "auto"
    assert by_display["Glucose"]["points"][0]["status"] == "review"

    audit = _audit_rows(app, observation["id"])
    assert ("status", "review", "auto") in [tuple(row) for row in audit]

    again = client.post(
        f"/api/observations/{observation['id']}/review",
        json={"action": "accept"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_reviewed"


def test_correct_replaces_value_and_keeps_original_in_audit(client, app, settings):
    _patient_id, _document_id, detail = _processed_document(client, app, settings)
    observation = next(
        item for item in detail["observations"] if item["analyte_id"] == "hba1c"
    )

    response = client.post(
        f"/api/observations/{observation['id']}/review",
        json={"action": "correct", "value_num": "9.10", "unit_norm": "%"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["observation"]["value_num"] == "9.1"
    assert body["observation"]["value_text"] == "9.1"
    assert body["observation"]["status"] == "auto"
    by_display = {result["display"]: result for result in body["summary"]["results"]}
    assert by_display["HbA1c"]["points"][0]["value"] == 9.1

    audit = [tuple(row) for row in _audit_rows(app, observation["id"])]
    assert ("value_num", "8.9", "9.1") in audit
    assert ("status", "review", "auto") in audit


def test_reject_removes_value_from_results(client, app, settings):
    _patient_id, _document_id, detail = _processed_document(client, app, settings)
    observation = next(
        item for item in detail["observations"] if item["analyte_id"] == "glucose"
    )

    response = client.post(
        f"/api/observations/{observation['id']}/review",
        json={"action": "reject", "reason": "Not this patient's row"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["observation"]["status"] == "rejected"
    displays = {result["display"] for result in body["summary"]["results"]}
    assert "Glucose" not in displays
    assert body["summary"]["documents"][0]["review_count"] == 1


def test_correct_rejects_out_of_range_values(client, app, settings):
    patient_id, _document_id, detail = _processed_document(client, app, settings)
    observation = next(
        item for item in detail["observations"] if item["analyte_id"] == "hba1c"
    )

    for raw in ("1e400", "1e999999"):
        response = client.post(
            f"/api/observations/{observation['id']}/review",
            json={"action": "correct", "value_num": raw},
        )
        assert response.status_code == 400, response.text
        assert response.json()["error"]["field"] == "value_num"

    summary = client.get(f"/api/patients/{patient_id}/summary")
    assert summary.status_code == 200, summary.text


def test_unmapped_field_cannot_be_accepted(client, app, settings):
    patient_id = make_patient(client, alias="P-01")
    uploaded = upload(client, patient_id, jpeg_bytes(text_image()), doc_type=None)
    body = uploaded.json()

    class _UnknownOcr:
        name = "fake-ocr"

        def read(self, _path):
            return [OcrWord("Some assay 42", [0.1, 0.1, 0.8, 0.14], 0.98)]

    assert run_batch(app.state.engine, settings, ocr_engine=_UnknownOcr()) is True
    detail = client.get(f"/api/documents/{body['document_id']}").json()
    observation = detail["observations"][0]
    assert observation["analyte_id"] is None

    response = client.post(
        f"/api/observations/{observation['id']}/review",
        json={"action": "accept"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "unmapped"


def test_review_is_scoped_to_the_owning_patient(app, settings):
    with TestClient(app) as alice:
        _patient_id, _document_id, detail = _processed_document(alice, app, settings)
        observation_id = detail["observations"][0]["id"]

    with TestClient(app) as bob:
        make_patient(bob, alias="Bob")
        response = bob.post(
            f"/api/observations/{observation_id}/review",
            json={"action": "accept"},
        )
        assert response.status_code == 404


def test_accept_prose_observation(client, app):
    patient_id = make_patient(client, alias="P-01")
    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO document
                    (id, patient_id, doc_type, capture_type, image_path,
                     page_count, content_hash, status, created_at)
                VALUES
                    ('d-ct', :patient_id, 'ct', 'printed', 'img-ct',
                     1, 'hash-ct', 'done', '2026-10-25T00:00:00Z')
                """
            ),
            {"patient_id": patient_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, label_raw, value_num, value_text,
                     bbox_json, page, engine, status, reason, created_at)
                VALUES
                    ('o-ct', 'd-ct', NULL, 'Impression', NULL, 'Normal CT brain.',
                     '[0.1,0.2,0.3,0.4]', 1, 'test', 'review', 'Grounded prose',
                     '2026-10-25T00:00:00Z')
                """
            )
        )

    response = client.post(
        "/api/observations/o-ct/review",
        json={"action": "accept"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["observation"]["status"] == "auto"
    assert body["observation"]["value_text"] == "Normal CT brain."
    assert body["observation"]["reason"] == "Accepted during review."


def test_correct_prose_observation_uses_text_value(client, app):
    patient_id = make_patient(client, alias="P-01")
    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO document
                    (id, patient_id, doc_type, capture_type, image_path,
                     page_count, content_hash, status, created_at)
                VALUES
                    ('d-ct2', :patient_id, 'ct', 'printed', 'img-ct2',
                     1, 'hash-ct2', 'done', '2026-10-25T00:00:00Z')
                """
            ),
            {"patient_id": patient_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, label_raw, value_num, value_text,
                     bbox_json, page, engine, status, reason, fact_type, created_at)
                VALUES
                    ('o-ct2', 'd-ct2', NULL, 'Impression', NULL, 'Normal CT brain.',
                     '[0.1,0.2,0.3,0.4]', 1, 'test', 'review', 'Grounded prose',
                     'impression', '2026-10-25T00:00:00Z')
                """
            )
        )

    response = client.post(
        "/api/observations/o-ct2/review",
        json={"action": "correct", "value_text": "No acute abnormality."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["observation"]["value_text"] == "No acute abnormality."
    assert body["observation"]["value_num"] is None
    assert body["observation"]["status"] == "auto"

    with app.state.engine.connect() as conn:
        audit_rows = [
            tuple(row)
            for row in conn.execute(
                text(
                    "SELECT field, old, new FROM audit "
                    "WHERE entity_id = 'o-ct2' ORDER BY ts"
                )
            )
        ]
    assert ("value_text", "Normal CT brain.", "No acute abnormality.") in audit_rows

from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.app import create_app


def _count(app, table: str) -> int:
    with app.state.engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def test_create_patient(client, app):
    response = client.post("/api/patients", json={"alias": "P-01", "sex": "F"})
    assert response.status_code == 201

    body = response.json()
    assert body["alias"] == "P-01"
    assert body["sex"] == "F"
    assert _count(app, "patient") == 1
    assert _count(app, "audit") == 1


def test_delete_patient_erases_rows_and_files(client, app, settings):
    patient_id = client.post("/api/patients", json={"alias": "P-01"}).json()["id"]

    page_dir = settings.upload_dir / "abc123"
    page_dir.mkdir(parents=True)
    (page_dir / "page_1.webp").write_bytes(b"page")

    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO document
                    (id, patient_id, doc_type, capture_type, image_path,
                     page_count, content_hash, status, created_at)
                VALUES
                    ('d1', :patient_id, 'lab_report', 'printed', 'abc123',
                     1, 'hash-d1', 'done', '2026-10-23T00:00:00Z')
                """
            ),
            {"patient_id": patient_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, value_num, bbox_json, page,
                     engine, status, created_at)
                VALUES
                    ('o1', 'd1', 'hemoglobin', '13.2', '[0.1,0.2,0.3,0.4]', 1,
                     'test', 'review', '2026-10-23T00:00:00Z')
                """
            )
        )

    response = client.delete(f"/api/patients/{patient_id}")
    assert response.status_code == 204
    assert not page_dir.exists()
    assert _count(app, "patient") == 0
    assert _count(app, "document") == 0
    assert _count(app, "observation") == 0

    with app.state.engine.connect() as conn:
        deleted = conn.execute(
            text("SELECT COUNT(*) FROM audit WHERE field = 'deleted'")
        ).scalar_one()
    assert deleted == 1


def test_delete_unknown_patient_returns_404(client):
    response = client.delete("/api/patients/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_demo_profile_is_read_only(settings):
    demo_app = create_app(replace(settings, profile="demo"))
    with TestClient(demo_app) as demo_client:
        response = demo_client.post("/api/patients", json={"alias": "P-01"})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_read_only"

        health = demo_client.get("/api/health").json()
        assert health == {"status": "ok", "profile": "demo"}


def test_validation_error_uses_contract_shape(client):
    response = client.post("/api/patients", json={})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["field"] == "alias"

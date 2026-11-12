from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.app import create_app

pytestmark = pytest.mark.integration


def _count(app, table: str) -> int:
    with app.state.engine.connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def test_register_patient_creates_account_and_session(client, app):
    response = client.post(
        "/api/auth/register",
        json={
            "alias": "P-01",
            "sex": "F",
            "username": "patient-one",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert body["alias"] == "P-01"
    assert body["sex"] == "F"
    assert body["username"] == "patient-one"
    assert _count(app, "patient") == 1
    assert _count(app, "audit") == 1
    assert client.get("/api/auth/me").json()["id"] == body["id"]


def test_first_registration_claims_a_legacy_patient(client, app):
    with app.state.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO patient (id, alias, created_at) "
                "VALUES ('legacy-1', 'hm', '2026-10-20T00:00:00Z')"
            )
        )

    response = client.post(
        "/api/auth/register",
        json={
            "alias": "P-01",
            "username": "patient-one",
            "password": "test-password-123",
        },
    )
    assert response.status_code == 201
    assert response.json()["id"] == "legacy-1"
    assert _count(app, "patient") == 1
    assert client.get("/api/patients/legacy-1/summary").status_code == 200


def test_duplicate_username_is_rejected_case_insensitively(client):
    payload = {
        "alias": "P-01",
        "username": "Patient.One",
        "password": "test-password-123",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 201
    duplicate = client.post(
        "/api/auth/register",
        json={**payload, "username": "patient.one"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "username_taken"


def test_login_and_logout(client):
    payload = {
        "alias": "P-01",
        "username": "patient-one",
        "password": "test-password-123",
    }
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    bad = client.post(
        "/api/auth/login",
        json={"username": "patient-one", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/auth/login",
        json={"username": "patient-one", "password": "test-password-123"},
    )
    assert good.status_code == 200
    assert good.json()["alias"] == "P-01"
    assert client.get("/api/auth/me").status_code == 200


def test_delete_patient_erases_rows_and_files(client, app, settings):
    patient_id = client.post(
        "/api/auth/register",
        json={
            "alias": "P-01",
            "username": "patient-one",
            "password": "test-password-123",
        },
    ).json()["id"]

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
        conn.execute(
            text(
                """
                INSERT INTO stage_artifact
                    (content_hash, page, stage, model_version, artifact_json, created_at)
                VALUES
                    ('hash-d1', 1, 'ocr', 'test@1.0', '[]', '2026-10-23T00:00:00Z')
                """
            )
        )

    response = client.delete(f"/api/patients/{patient_id}")
    assert response.status_code == 204
    assert not page_dir.exists()
    assert _count(app, "patient") == 0
    assert _count(app, "document") == 0
    assert _count(app, "observation") == 0
    assert _count(app, "stage_artifact") == 0

    with app.state.engine.connect() as conn:
        deleted = conn.execute(
            text("SELECT COUNT(*) FROM audit WHERE field = 'deleted'")
        ).scalar_one()
    assert deleted == 1


def test_delete_another_patient_is_forbidden(client):
    own = client.post(
        "/api/auth/register",
        json={
            "alias": "P-01",
            "username": "patient-one",
            "password": "test-password-123",
        },
    ).json()
    response = client.delete("/api/patients/does-not-exist")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert client.get(f"/api/patients/{own['id']}/summary").status_code == 200


def test_demo_profile_is_read_only(settings):
    demo_app = create_app(replace(settings, profile="demo"))
    with TestClient(demo_app) as demo_client:
        response = demo_client.post(
            "/api/auth/register",
            json={
                "alias": "P-01",
                "username": "patient-one",
                "password": "test-password-123",
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "demo_read_only"

        health = demo_client.get("/api/health").json()
        assert health == {"status": "ok", "profile": "demo"}


def test_validation_error_uses_contract_shape(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "patient-one", "password": "test-password-123"},
    )
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["field"] == "alias"


@pytest.mark.parametrize(
    "changes, field, message",
    [
        ({"username": "ab"}, "username", "3–32 characters"),
        ({"username": "has spaces"}, "username", "letters, numbers"),
        ({"password": "short"}, "password", "8–128 characters"),
        ({"alias": "   "}, "alias", "patient alias"),
    ],
)
def test_registration_validation_is_actionable_and_private(client, changes, field, message):
    payload = {"alias": "Synthetic", "username": "synthetic-user", "password": "private-test-password"}
    response = client.post("/api/auth/register", json={**payload, **changes})
    assert response.status_code == 400
    error = response.json()["error"]
    assert error["field"] == field
    assert message in error["message"]
    assert "private-test-password" not in response.text
    assert "input" not in error


def test_registration_validates_normalized_username_and_alias(client):
    response = client.post(
        "/api/auth/register",
        json={"alias": "  Synthetic  ", "username": "  synthetic-user  ", "password": " password with spaces "},
    )
    assert response.status_code == 201
    assert response.json()["username"] == "synthetic-user"
    assert response.json()["alias"] == "Synthetic"
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "synthetic-user", "password": " password with spaces "}).status_code == 200

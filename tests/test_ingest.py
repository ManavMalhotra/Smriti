from __future__ import annotations

import json

from PIL import Image
from sqlalchemy import text

from tests.factory import (
    exif_gps_jpeg,
    handwritten_image,
    jpeg_bytes,
    make_patient,
    pdf_bytes,
    text_image,
    upload,
)


def _row(app, sql: str, params: dict | None = None):
    with app.state.engine.connect() as conn:
        return conn.execute(text(sql), params or {}).first()


def _count(app, sql: str, params: dict | None = None) -> int:
    with app.state.engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar_one()


def test_upload_creates_queued_document_and_job(client, app, settings):
    patient_id = make_patient(client)
    response = upload(client, patient_id, jpeg_bytes(text_image()))
    assert response.status_code == 202

    body = response.json()
    assert body["pages"] == 1
    assert body["status"] == "queued"
    assert body["job_id"]

    document = _row(
        app,
        "SELECT id, capture_type, page_count, quality_score, quality_json, "
        "status, image_path FROM document WHERE id = :id",
        {"id": body["document_id"]},
    )
    assert document[1] == "printed"
    assert document[2] == 1
    assert document[3] > 0
    assert document[5] == "queued"

    quality_payload = json.loads(document[4])
    assert quality_payload["pages"][0]["steps"][0] == "exif_strip"
    assert quality_payload["thresholds"]["min_short_edge"] == 1000

    consent = _row(
        app,
        "SELECT scope, version FROM consent WHERE document_id = :id",
        {"id": body["document_id"]},
    )
    assert consent == ("local", "1.0")

    job = _row(
        app,
        "SELECT state, page, total FROM jobs WHERE id = :id",
        {"id": body["job_id"]},
    )
    assert job == ("queued", 0, 1)

    page_path = settings.upload_dir / document[6] / "page_1.webp"
    assert page_path.is_file()
    with Image.open(page_path) as stored:
        assert stored.format == "WEBP"


def test_reupload_is_idempotent(client, app):
    patient_id = make_patient(client)
    data = jpeg_bytes(text_image())

    first = upload(client, patient_id, data)
    second = upload(client, patient_id, data)
    assert first.status_code == 202
    assert second.status_code == 409

    duplicate = second.json()
    assert duplicate["duplicate"] is True
    assert duplicate["document_id"] == first.json()["document_id"]
    assert _count(app, "SELECT COUNT(*) FROM document") == 1
    assert _count(app, "SELECT COUNT(*) FROM jobs") == 1


def test_exif_is_stripped_and_orientation_applied(client, app, settings):
    patient_id = make_patient(client)
    response = upload(client, patient_id, exif_gps_jpeg(text_image()))
    assert response.status_code == 202

    document = _row(
        app,
        "SELECT id, image_path, quality_json FROM document WHERE id = :id",
        {"id": response.json()["document_id"]},
    )
    page_path = settings.upload_dir / document[1] / "page_1.webp"
    with Image.open(page_path) as stored:
        assert stored.size == (1600, 1200)
        assert len(stored.getexif()) == 0
    assert "rotate" in json.loads(document[2])["pages"][0]["steps"]


def test_pdf_is_split_into_pages(client, app, settings):
    patient_id = make_patient(client)
    response = upload(
        client,
        patient_id,
        pdf_bytes(3),
        filename="report.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 202
    assert response.json()["pages"] == 3

    document = _row(
        app,
        "SELECT image_path, page_count FROM document WHERE id = :id",
        {"id": response.json()["document_id"]},
    )
    assert document[1] == 3
    for page in range(1, 4):
        assert (settings.upload_dir / document[0] / f"page_{page}.webp").is_file()

    job = _row(
        app,
        "SELECT total FROM jobs WHERE id = :id",
        {"id": response.json()["job_id"]},
    )
    assert job[0] == 3


def test_capture_type_is_derived_server_side(client, app):
    patient_id = make_patient(client)

    printed = upload(client, patient_id, jpeg_bytes(text_image()))
    handwritten = upload(
        client,
        patient_id,
        jpeg_bytes(handwritten_image()),
        capture_type="printed",  # must be ignored
    )
    assert printed.status_code == 202
    assert handwritten.status_code == 202

    printed_doc = _row(
        app,
        "SELECT capture_type FROM document WHERE id = :id",
        {"id": printed.json()["document_id"]},
    )
    handwritten_doc = _row(
        app,
        "SELECT capture_type FROM document WHERE id = :id",
        {"id": handwritten.json()["document_id"]},
    )
    assert printed_doc[0] == "printed"
    assert handwritten_doc[0] == "handwritten"


def test_low_resolution_is_rejected_without_a_job(client, app, settings):
    patient_id = make_patient(client)
    image = text_image(width=600, height=800, lines=8, font_size=14, line_gap=30)
    response = upload(client, patient_id, jpeg_bytes(image))
    assert response.status_code == 422

    error = response.json()["error"]
    assert error["code"] == "quality_rejected"
    assert "Short edge" in error["message"]

    document = _row(
        app,
        "SELECT id, status, page_count, quality_json FROM document "
        "ORDER BY created_at DESC LIMIT 1",
    )
    assert document[1] == "rejected_quality"
    assert document[2] == 1
    assert json.loads(document[3])["pages"][0]["failure"]
    assert _count(app, "SELECT COUNT(*) FROM jobs") == 0

    image_path = _row(
        app, "SELECT image_path FROM document WHERE id = :id", {"id": document[0]}
    )[0]
    assert not (settings.upload_dir / image_path).exists()


def test_unsupported_file_type_is_rejected(client, app):
    patient_id = make_patient(client)
    response = upload(client, patient_id, b"not an image", filename="note.txt")
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_type"
    assert _count(app, "SELECT COUNT(*) FROM document") == 0


def test_document_page_and_job_endpoints(client, app):
    patient_id = make_patient(client)
    response = upload(
        client,
        patient_id,
        jpeg_bytes(text_image()),
        doc_date="2026-09-01",
        collection_date="2026-08-30",
    )
    document_id = response.json()["document_id"]
    job_id = response.json()["job_id"]

    document = client.get(f"/api/documents/{document_id}")
    assert document.status_code == 200
    body = document.json()
    assert body["doc_type"] == "lab_report"
    assert body["capture_type"] == "printed"
    assert body["doc_date"] == "2026-09-01"
    assert body["collection_date"] == "2026-08-30"
    assert body["page_count"] == 1
    assert body["consent"]["scope"] == "local"
    assert body["egress"] == []
    assert body["pages"] == [
        {"page": 1, "url": f"/api/documents/{document_id}/page/1"}
    ]

    page = client.get(f"/api/documents/{document_id}/page/1")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/webp"
    assert page.content[:4] == b"RIFF"

    missing = client.get(f"/api/documents/{document_id}/page/2")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    job = client.get(f"/api/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json() == {
        "id": job_id,
        "state": "queued",
        "page": 0,
        "total": 1,
        "error": None,
    }


def test_consent_endpoint_updates_scope_and_audits(client, app):
    patient_id = make_patient(client)
    document_id = upload(client, patient_id, jpeg_bytes(text_image())).json()[
        "document_id"
    ]

    response = client.post(
        f"/api/documents/{document_id}/consent",
        json={"scope": "local_plus_projection", "version": "1.1"},
    )
    assert response.status_code == 201
    assert response.json()["scope"] == "local_plus_projection"
    assert response.json()["version"] == "1.1"

    document = client.get(f"/api/documents/{document_id}").json()
    assert document["consent"]["scope"] == "local_plus_projection"
    assert _count(app, "SELECT COUNT(*) FROM audit WHERE entity = 'consent'") == 2


def test_consent_for_unknown_document_returns_404(client):
    make_patient(client)
    response = client.post(
        "/api/documents/missing/consent",
        json={"scope": "local", "version": "1.0"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_patient_delete_removes_uploaded_pages(client, app, settings):
    patient_id = make_patient(client)
    document_id = upload(client, patient_id, jpeg_bytes(text_image())).json()[
        "document_id"
    ]
    image_path = _row(
        app, "SELECT image_path FROM document WHERE id = :id", {"id": document_id}
    )[0]
    page_dir = settings.upload_dir / image_path
    assert page_dir.is_dir()

    response = client.delete(f"/api/patients/{patient_id}")
    assert response.status_code == 204
    assert not page_dir.exists()
    assert _count(app, "SELECT COUNT(*) FROM document") == 0
    assert _count(app, "SELECT COUNT(*) FROM jobs") == 0

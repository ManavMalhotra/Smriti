import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.job_progress import record_progress
from tests.factory import make_patient, pdf_bytes, upload

pytestmark = pytest.mark.integration


def test_job_progress_is_additive_private_and_deleted_with_document(client, app):
    patient_id = make_patient(client)
    result = upload(client, patient_id, pdf_bytes(1), filename="report.pdf", content_type="application/pdf").json()
    job_id = result["job_id"]
    old = client.get(f"/api/jobs/{job_id}").json()
    assert old["state"] == "queued"
    assert old["stage"] == "queued"
    assert [event["event"] for event in old["events"]] == ["intake_accepted", "preparing", "prepared"]
    assert old["support_id"] == job_id
    assert set(old["logging"]) == {"file", "terminal"}
    assert all(set(sink) == {"available", "degraded"} for sink in old["logging"].values())
    with app.state.engine.begin() as conn:
        record_progress(conn, job_id, "started")
        record_progress(conn, job_id, "qwen_reading", model="vlm:qwen3-vl-4b@q4_k_m+cuda", page=1, completed=0, total=1)
    progress = client.get(f"/api/jobs/{job_id}").json()
    assert progress["model"] == "vlm:qwen3-vl-4b@q4_k_m+cuda"
    assert progress["stage"] == "qwen"
    assert progress["current_page"] == 1
    assert progress["completed_pages"] == 0
    assert progress["stage_total"] == 1
    assert progress["page"] == 0
    assert len(progress["events"]) == len(old["events"]) + 2
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET error_code = 'qwen_port_busy' WHERE job_id = :id"), {"id": job_id})
    assert client.get(f"/api/jobs/{job_id}").json()["error_code"] == "qwen_port_busy"
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET error_code = 'PRIVATE_ERROR_SENTINEL' WHERE job_id = :id"), {"id": job_id})
    assert "PRIVATE_ERROR_SENTINEL" not in client.get(f"/api/jobs/{job_id}").text
    with TestClient(app) as other:
        make_patient(other, alias="Other")
        assert other.get(f"/api/jobs/{job_id}").status_code == 404
    with app.state.engine.begin() as conn:
        conn.execute(text("DELETE FROM submissions WHERE job_id = :id"), {"id": job_id})
        conn.execute(text("DELETE FROM document WHERE id = :id"), {"id": result["document_id"]})
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_jobs_list_is_compact_owner_scoped_and_includes_legacy_and_pending(client, app):
    patient_id = make_patient(client)
    result = upload(client, patient_id, pdf_bytes(1), filename="PRIVATE-FILENAME.pdf", content_type="application/pdf").json()
    _pending_submission(app, patient_id)
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET requested_doc_type = 'lab_report' WHERE job_id = 'pending'"))
        # A legacy job with no runtime submission must remain discoverable, without being recovered.
        conn.execute(text("DELETE FROM submissions WHERE job_id = :id"), {"id": result["job_id"]})
        record_progress(conn, result["job_id"], "qwen_reading", page=1, completed=0, total=1)
    response = client.get("/api/jobs")
    assert response.status_code == 200
    rows = response.json()["jobs"]
    assert {row["id"] for row in rows} == {"pending", result["job_id"]}
    pending = next(row for row in rows if row["id"] == "pending")
    assert pending["document_id"] is None and pending["total"] is None
    assert pending["doc_type"] == "lab_report"
    assert all("events" not in row and "progress_json" not in row for row in rows)
    assert "PRIVATE" not in response.text
    with TestClient(app) as other:
        make_patient(other, alias="Other")
        assert other.get("/api/jobs").json()["jobs"] == []
    with app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs WHERE id = :id"), {"id": result["job_id"]}).scalar_one() == "queued"


def test_job_listing_paginates_active_separately_from_terminal_history(client, app):
    patient_id = make_patient(client)
    first = upload(client, patient_id, pdf_bytes(1), content_type="application/pdf").json()
    second = upload(client, patient_id, pdf_bytes(2), content_type="application/pdf").json()
    _pending_submission(app, patient_id)
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'done' WHERE id = :id"), {"id": first["job_id"]})
        record_progress(conn, first["job_id"], "done")
    page = client.get("/api/jobs?limit=1").json()
    assert page["has_more"] is True and len(page["jobs"]) == 1
    assert page["jobs"][0]["id"] == "pending"
    assert client.get("/api/jobs?limit=1&offset=1").json()["jobs"][0]["id"] == second["job_id"]
    assert client.get("/api/jobs?scope=recent").json()["jobs"][0]["id"] == first["job_id"]
    for query in ("limit=0", "limit=51", "offset=-1", "scope=all"):
        assert client.get("/api/jobs?" + query).status_code == 400


def test_failed_preparation_list_uses_safe_error_and_unknown_totals(client, app):
    patient_id = make_patient(client)
    _pending_submission(app, patient_id)
    with app.state.engine.begin() as conn:
        record_progress(conn, "pending", "intake_failed", error_code="source_missing")
        conn.execute(text("UPDATE submissions SET error_code = 'PRIVATE_ERROR' WHERE job_id = 'pending'"))
    response = client.get("/api/jobs?scope=recent")
    row = response.json()["jobs"][0]
    assert row["state"] == "failed" and row["error_code"] == "preparation_failed"
    assert row["total"] is None and row["total_pages"] is None
    assert "PRIVATE" not in response.text


def _pending_submission(app, patient_id):
    with app.state.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO stage_batches (id, state, owner_token, owner_pid,
                owner_created_at, membership_json, telemetry_json, created_at, updated_at)
            VALUES ('private-batch', 'preparing', 'PRIVATE-OWNER-SENTINEL', 123, 123.5,
                '["pending", "PRIVATE-OTHER-JOB-SENTINEL"]',
                '{"private":"PRIVATE-BATCH-SENTINEL"}', '2026-01-01', '2026-01-01')
        """))
        conn.execute(text("""
            INSERT INTO submissions (job_id, patient_id, content_hash, spool_path,
                spool_bytes, consent_scope, consent_version, consent_granted_at,
                requested_doc_date, preparation_manifest_json, batch_id, batch_position,
                created_at, updated_at)
            VALUES ('pending', :patient_id, 'private-hash', 'PRIVATE-SPOOL-SENTINEL.raw',
                123, 'local', 'v1', '2026-01-01', 'PRIVATE-DATE-SENTINEL',
                '{"private":"PRIVATE-MANIFEST-SENTINEL"}', 'private-batch', 0,
                '2026-01-01', '2026-01-01')
        """), {"patient_id": patient_id})


def test_pending_and_preparing_job_has_unknown_counts_and_private_intake(client, app):
    patient_id = make_patient(client)
    _pending_submission(app, patient_id)
    pending = client.get("/api/jobs/pending")
    assert pending.status_code == 200
    assert {key: pending.json()[key] for key in ("id", "state", "page", "stage", "document_id", "total", "total_pages", "error", "error_code")} == {
        "id": "pending", "state": "queued", "page": 0, "stage": "pending_intake",
        "document_id": None, "total": None, "total_pages": None, "error": None, "error_code": None,
    }
    assert "PRIVATE-" not in pending.text
    with app.state.engine.begin() as conn:
        assert record_progress(conn, "pending", "intake_accepted")
        assert record_progress(conn, "pending", "preparing")
    preparing = client.get("/api/jobs/pending").json()
    assert preparing["state"] == "running"
    assert preparing["stage"] == "preparing"
    assert preparing["stage_total"] is None
    assert preparing["total"] is None
    with TestClient(app) as other:
        make_patient(other, alias="Other")
        assert other.get("/api/jobs/pending").status_code == 404


def test_deferred_rejection_is_pollable_without_document_or_sensitive_error(client, app):
    patient_id = make_patient(client)
    _pending_submission(app, patient_id)
    with app.state.engine.begin() as conn:
        record_progress(conn, "pending", "intake_accepted")
        record_progress(conn, "pending", "intake_rejected", error_code="page_limit", elapsed=2)
    response = client.get("/api/jobs/pending")
    assert response.status_code == 200
    assert response.json()["state"] == "failed"
    assert response.json()["error_code"] == "page_limit"
    assert response.json()["error"]
    assert response.json()["document_id"] is None
    assert response.json()["finished_at"] is not None
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET error_code = 'PRIVATE-ERROR-SENTINEL' WHERE job_id = 'pending'"))
    response = client.get("/api/jobs/pending")
    assert "PRIVATE-" not in response.text
    assert response.json()["error_code"] == "preparation_failed"


def test_same_public_job_resolves_promoted_progress_without_reset(client, app):
    from tests.staged_runtime import prepare_response

    patient_id = make_patient(client)
    response = client.post("/api/documents", data={"patient_id": patient_id, "consent_scope": "local"}, files={"file": ("synthetic.pdf", pdf_bytes(1), "application/pdf")})
    job_id = response.json()["job_id"]
    with app.state.engine.begin() as conn:
        record_progress(conn, job_id, "preparing")
    before = client.get(f"/api/jobs/{job_id}").json()
    prepared = prepare_response(client, response).json()
    with app.state.engine.begin() as conn:
        record_progress(conn, job_id, "started")
    after = client.get(f"/api/jobs/{job_id}").json()
    assert after["id"] == before["id"]
    assert after["document_id"] == prepared["document_id"]
    assert after["total"] == after["total_pages"] == 1
    assert after["started_at"] == before["started_at"]
    assert after["events"][:2] == before["events"]
    assert after["events"][-1]["sequence"] == len(after["events"])
    with app.state.engine.begin() as conn:
        conn.execute(text("DELETE FROM submissions WHERE job_id = :id"), {"id": job_id})
        conn.execute(text("DELETE FROM document WHERE id = :id"), {"id": prepared["document_id"]})
        assert record_progress(conn, job_id, "preparing") is False
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def _failed(client, app, patient_id):
    result = upload(client, patient_id, pdf_bytes(1), filename="report.pdf", content_type="application/pdf").json()
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'failed', error = 'boom' WHERE id = :id"), {"id": result["job_id"]})
        conn.execute(text("UPDATE document SET status = 'failed' WHERE id = :id"), {"id": result["document_id"]})
    return result


def test_retry_requeues_failed_and_stuck_queued_jobs(client, app):
    patient_id = make_patient(client)
    result = _failed(client, app, patient_id)
    job_id = result["job_id"]
    assert client.post(f"/api/jobs/{job_id}/retry").json() == {"id": job_id, "state": "queued"}
    assert client.get(f"/api/jobs/{job_id}").json()["state"] == "queued"
    with app.state.engine.connect() as conn:
        # a retried job must be re-admittable: the coordinator only freezes batch_id IS NULL
        assert conn.execute(text("SELECT batch_id FROM submissions WHERE job_id = :id"),
                            {"id": job_id}).scalar() is None
    # a job still queued is retryable again, but a running one is not
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 200
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'running' WHERE id = :id"), {"id": job_id})
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 404
    with TestClient(app) as other:
        make_patient(other, alias="Other")
        assert other.post(f"/api/jobs/{job_id}/retry").status_code == 404


def test_delete_removes_failed_job_document_and_is_owner_scoped(client, app):
    patient_id = make_patient(client)
    result = _failed(client, app, patient_id)
    job_id, document_id = result["job_id"], result["document_id"]
    with TestClient(app) as other:
        make_patient(other, alias="Other")
        assert other.delete(f"/api/jobs/{job_id}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/documents/{document_id}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


def test_delete_refuses_a_job_that_is_not_failed(client, app):
    patient_id = make_patient(client)
    result = upload(client, patient_id, pdf_bytes(1), filename="report.pdf", content_type="application/pdf").json()
    assert client.delete(f"/api/jobs/{result['job_id']}").status_code == 409

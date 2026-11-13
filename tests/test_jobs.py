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
    for query in ("limit=0", "limit=51", "offset=-1", "scope=invalid"):
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
    assert client.get(f"/api/jobs/{job_id}").json()["stage"] == "queued"
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


def test_all_and_failed_lists_keep_processing_failures_discoverable(client, app):
    patient_id = make_patient(client)
    result = _failed(client, app, patient_id)
    _pending_submission(app, patient_id)
    assert {row['id'] for row in client.get('/api/jobs?scope=all').json()['jobs']} == {result['job_id'], 'pending'}
    assert [row['id'] for row in client.get('/api/jobs?scope=failed').json()['jobs']] == [result['job_id']]


@pytest.mark.parametrize('target', ['ocr_target', 'rules_target', 'verification_target', 'publication_target'])
def test_retry_after_each_stage_failure_rebuilds_scratch_and_publishes_once(client, app, target):
    import json
    from smriti.coordinator import Coordinator
    from smriti.runtime import StageResult
    from tests.test_preparation import inline_supervisor

    patient_id = make_patient(client)
    result = upload(client, patient_id, pdf_bytes(1), content_type='application/pdf').json()
    job = result['job_id']
    def fail_stage(name, context, **options):
        if name.endswith(':' + target):
            return StageResult('timeout', True, -1, 0, job_id=job)
        return inline_supervisor(name, context, **options)
    with Coordinator(app.state.engine, app.state.settings, supervisor=fail_stage) as controller:
        assert controller.process_batch()
    assert client.get(f'/api/jobs/{job}').json()['state'] == 'failed'
    with app.state.engine.connect() as conn:
        before = json.loads(conn.execute(text('SELECT preparation_manifest_json FROM submissions WHERE job_id = :id'), {'id': job}).scalar_one())
    assert before['processing']['cleanup'] == 'confirmed'
    assert client.post(f'/api/jobs/{job}/retry').status_code == 200
    progress = client.get(f'/api/jobs/{job}').json()
    assert progress['stage'] == 'queued' and progress['failure_context'] is None and progress['finished_at'] is None
    assert progress['events'][-1]['event'] == 'retry_queued'
    with app.state.engine.connect() as conn:
        after = json.loads(conn.execute(text('SELECT preparation_manifest_json FROM submissions WHERE job_id = :id'), {'id': job}).scalar_one())
    assert 'processing' not in after and before['identity'] == after['identity']
    with Coordinator(app.state.engine, app.state.settings, supervisor=inline_supervisor) as controller:
        controller.recover()
        assert controller.process_batch()
    assert client.get(f'/api/jobs/{job}').json()['state'] == 'done'
    with app.state.engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM document')).scalar_one() == 1
        assert conn.execute(text('SELECT COUNT(*) FROM page_text')).scalar_one() == 1


@pytest.mark.parametrize('blocker,code', [('batch', 'job_active'), ('cleanup', 'cleanup_failed'),
                                       ('consent', 'consent_revoked'), ('results', 'results_exist')])
def test_retry_preserves_failed_state_when_safety_fences_block_it(client, app, blocker, code):
    import json
    from smriti.processing_store import update_processing

    patient = make_patient(client)
    result = _failed(client, app, patient)
    job, document = result['job_id'], result['document_id']
    if blocker == 'cleanup':
        update_processing(app.state.engine, job, cleanup='failed', rules_ready=True)
    else:
        with app.state.engine.begin() as conn:
            if blocker == 'batch':
                conn.execute(text("""INSERT INTO stage_batches (id, state, owner_token, owner_pid, owner_created_at,
                    membership_json, created_at, updated_at) VALUES ('active-batch', 'processing', 'owner', 1, 1,
                    :members, '2026-01-01', '2026-01-01')"""), {'members': json.dumps([job])})
                conn.execute(text("UPDATE submissions SET batch_id = 'active-batch', batch_position = 0 WHERE job_id = :id"), {'id': job})
            elif blocker == 'consent':
                conn.execute(text("UPDATE consent SET revoked_at = '2026-01-01' WHERE document_id = :id"), {'id': document})
            else:
                conn.execute(text("""INSERT INTO page_text (document_id, page, text, engine, created_at)
                    VALUES (:id, 1, 'SYNTHETIC saved reading', 'human_entry', '2026-01-01')"""), {'id': document})
    response = client.post(f'/api/jobs/{job}/retry')
    assert response.status_code == 409 and response.json()['error']['code'] == code
    assert client.get(f'/api/jobs/{job}').json()['state'] == 'failed'
    assert not client.get('/api/documents').json()['documents'][0]['retryable']
    if blocker == 'results':
        with app.state.engine.connect() as conn:
            assert conn.execute(text('SELECT text FROM page_text WHERE document_id = :id'), {'id': document}).scalar_one() == 'SYNTHETIC saved reading'


@pytest.mark.parametrize('mode,status', [('demo', 403), ('paused', 503)])
def test_retry_respects_demo_and_closed_admission(client, app, mode, status):
    from dataclasses import replace

    patient = make_patient(client)
    result = _failed(client, app, patient)
    if mode == 'demo':
        app.state.settings = replace(app.state.settings, profile='demo')
    else:
        app.state.service.accepting = False
    assert client.post(f"/api/jobs/{result['job_id']}/retry").status_code == status


@pytest.mark.parametrize('previous,next_status', [('completed', 'awaiting'), ('approved', 'awaiting'), ('declined', 'declined')])
def test_retry_requires_fresh_cloud_mask_approval_but_preserves_decline(client, app, previous, next_status):
    patient = make_patient(client)
    result = _failed(client, app, patient)
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE consent SET scope = 'local_plus_projection' WHERE document_id = :id"), {'id': result['document_id']})
        conn.execute(text("""INSERT INTO cloud_consent (document_id, status, extra_boxes_json, updated_at)
            VALUES (:id, :status, '{}', '2026-01-01')"""), {'id': result['document_id'], 'status': previous})
    assert client.post(f"/api/jobs/{result['job_id']}/retry").status_code == 200
    with app.state.engine.connect() as conn:
        assert conn.execute(text('SELECT status FROM cloud_consent WHERE document_id = :id'), {'id': result['document_id']}).scalar_one() == next_status

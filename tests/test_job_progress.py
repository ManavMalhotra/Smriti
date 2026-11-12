import json
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from smriti.job_progress import read_progress, record_progress
from smriti.job_progress import progress_transaction

pytestmark = pytest.mark.integration


@pytest.fixture
def job_engine(app):
    engine = app.state.engine
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO patient (id, alias, created_at) VALUES ('p', 'Synthetic', '2026-01-01')"))
        conn.execute(text("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('d', 'p', 'other', 'printed', 'd', 1, 'hash', 'queued', '2026-01-01')"))
        conn.execute(text("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('j', 'd', 'queued', 1, '2026-01-01')"))
    return engine


def test_progress_order_and_bounded_history(job_engine):
    with job_engine.begin() as conn:
        record_progress(conn, "j", "started")
        for _ in range(502):
            record_progress(conn, "j", "ocr_reading", model="test-ocr", page=1, completed=0)
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert len(progress["events"]) == 500
    assert progress["events_truncated"] == 3
    assert progress["events"][-1]["sequence"] == 503
    assert progress["stage"] == "ocr"
    assert progress["started_at"] is not None
    assert progress["finished_at"] is None
    assert progress["current_page"] == 1
    assert progress["completed_pages"] == 0


def test_deleted_job_is_not_recreated(job_engine):
    with job_engine.begin() as conn:
        conn.execute(text("DELETE FROM document WHERE id = 'd'"))
        assert record_progress(conn, "j", "started") is False
        assert conn.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one() == 0


def test_committed_progress_only_and_latest_failure_survive_omitted_history(job_engine):
    events = []
    engine = job_engine.execution_options(progress_report=lambda event, **fields: events.append((event, fields)))
    with pytest.raises(RuntimeError):
        with progress_transaction(engine) as conn:
            record_progress(conn, "j", "done")
            raise RuntimeError("synthetic rollback")
    assert events == []
    with progress_transaction(engine) as conn:
        record_progress(conn, "j", "started")
        record_progress(conn, "j", "operation_failed", model="PRIVATE_SENTINEL", error_type="PRIVATE_SENTINEL")
        for _ in range(501):
            record_progress(conn, "j", "saving")
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert progress["latest_failure"]["event"] == "operation_failed"
    assert all(event["event"] != "operation_failed" for event in progress["events"])
    assert "PRIVATE_SENTINEL" not in json.dumps(progress) + json.dumps(events)


def test_publication_failure_stage_and_total_wall_elapsed_are_not_previous_stage_or_save_time(job_engine):
    with job_engine.begin() as conn:
        record_progress(conn, "j", "started")
        record_progress(conn, "j", "cross_checked")
        record_progress(conn, "j", "failed", failed_stage="saving")
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert progress["failure_context"] == {"stage": "saving", "model": None, "current_page": None}
    assert progress["events"][-1]["stage"] == "saving"
    assert progress["elapsed_seconds"] is not None


def test_broken_delivery_cannot_rollback_progress_and_recovery_keeps_intake_time(job_engine):
    engine = job_engine.execution_options(progress_report=lambda *args, **fields: (_ for _ in ()).throw(RuntimeError("PRIVATE_SENTINEL")))
    with progress_transaction(engine) as conn:
        record_progress(conn, "j", "started")
        started = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())["started_at"]
        record_progress(conn, "j", "recovered")
        record_progress(conn, "j", "done")
    with engine.connect() as conn:
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert progress["stage"] == "done" and progress["started_at"] == started


def test_only_committed_ocr_completion_changes_legacy_page_counter(job_engine):
    with progress_transaction(job_engine) as conn:
        record_progress(conn, "j", "page_read", page=1, completed=1, total=2)
        record_progress(conn, "j", "qwen_reading", page=2, completed=0, total=2)
        assert conn.execute(text("SELECT page FROM jobs WHERE id = 'j'")).scalar_one() == 1
    with pytest.raises(RuntimeError):
        with progress_transaction(job_engine) as conn:
            record_progress(conn, "j", "cache_hit", page=2, completed=2, total=2)
            raise RuntimeError("synthetic rollback")
    with job_engine.connect() as conn:
        assert conn.execute(text("SELECT page FROM jobs WHERE id = 'j'")).scalar_one() == 1


def test_model_failure_code_and_http_status_survive_cleanup_and_forward_after_commit(job_engine):
    forwarded = []
    engine = job_engine.execution_options(progress_report=lambda event, **fields: forwarded.append(fields))
    with progress_transaction(engine) as conn:
        record_progress(conn, "j", "qwen_reading", page=1, total=1)
        record_progress(conn, "j", "operation_failed", failed_stage="qwen", error_code="qwen_http_error", http_status=400)
        record_progress(conn, "j", "unloading")
        record_progress(conn, "j", "unloaded")
        record_progress(conn, "j", "failed", failed_stage="qwen")
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert progress["failure_context"] == {"stage": "qwen", "model": None, "current_page": 1, "code": "qwen_http_error", "status": 400}
    assert forwarded[1]["code"] == "qwen_http_error" and forwarded[1]["status"] == 400
    with job_engine.begin() as conn:
        with pytest.raises(ValueError):
            record_progress(conn, "j", "operation_failed", error_code="PRIVATE_SENTINEL")
        with pytest.raises(ValueError):
            record_progress(conn, "j", "operation_failed", error_code="qwen_http_error", http_status="PRIVATE_SENTINEL")


def test_snapshot_terminal_and_private_metadata(job_engine):
    with job_engine.begin() as conn:
        record_progress(conn, "j", "started")
        with pytest.raises(TypeError):
            record_progress(conn, "j", "failed", text="PRIVATE MEDICAL SENTINEL")
        with pytest.raises(ValueError):
            record_progress(conn, "j", "untrusted-message")
        record_progress(conn, "j", "failed", error_type="TimeoutError", elapsed=2.5)
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one())
    assert progress["finished_at"] is not None
    assert progress["elapsed_seconds"] == 2.5
    assert progress["events"][-1]["level"] == "error"
    assert "PRIVATE MEDICAL SENTINEL" not in json.dumps(progress)
    assert read_progress(None)["events"] == []


def test_verification_survives_truncation_and_resets_on_resume(job_engine):
    with job_engine.begin() as conn:
        record_progress(conn, "j", "started")
        record_progress(conn, "j", "qwen_disabled")
        for _ in range(501):
            record_progress(conn, "j", "saving")
        raw = conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one()
        progress = read_progress(raw)
        assert progress["verification_state"] == "skipped"
        assert not any(event["event"] == "qwen_disabled" for event in progress["events"])
        record_progress(conn, "j", "recovered")
        record_progress(conn, "j", "started")
        record_progress(conn, "j", "qwen_loading")
        record_progress(conn, "j", "qwen_skipped", page=2)
        record_progress(conn, "j", "cross_checked")
        raw = conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one()
        assert read_progress(raw)["verification_state"] == "partial"


def test_failure_keeps_model_and_page_before_cleanup(job_engine):
    with job_engine.begin() as conn:
        record_progress(conn, "j", "qwen_reading", model="vlm:qwen3-vl-4b@q4_k_m+cuda", page=2)
        record_progress(conn, "j", "operation_failed", error_type="TimeoutError")
        record_progress(conn, "j", "unloading", model="vlm:qwen3-vl-4b@q4_k_m+cuda")
        record_progress(conn, "j", "unloaded", model="vlm:qwen3-vl-4b@q4_k_m+cuda")
        record_progress(conn, "j", "failed", error_type="TimeoutError")
        raw = conn.execute(text("SELECT progress_json FROM jobs WHERE id = 'j'")).scalar_one()
        assert read_progress(raw)["failure_context"] == {"stage": "qwen", "model": "vlm:qwen3-vl-4b@q4_k_m+cuda", "current_page": 2}


@pytest.fixture
def submission_engine(app):
    engine = app.state.engine
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO patient (id, alias, created_at) VALUES ('p', 'Synthetic', '2026-01-01')"))
        conn.execute(text("INSERT INTO submissions (job_id, patient_id, content_hash, spool_path, spool_bytes, consent_scope, consent_version, consent_granted_at, created_at, updated_at) VALUES ('s', 'p', 'hash', 's.raw', 123, 'local', 'v1', '2026-01-01', '2026-01-01', '2026-01-01')"))
    return engine


def test_submission_progress_is_bounded_and_unknown_total(submission_engine):
    with submission_engine.begin() as conn:
        assert record_progress(conn, "s", "intake_accepted")
        started = read_progress(conn.execute(text("SELECT progress_json FROM submissions")).scalar_one())["started_at"]
        for _ in range(502):
            assert record_progress(conn, "s", "preparing")
        progress = read_progress(conn.execute(text("SELECT progress_json FROM submissions")).scalar_one())
        assert len(progress["events"]) == 500
        assert progress["events_truncated"] == 3
        assert progress["events"][-1]["sequence"] == 503
        assert progress["started_at"] == started
        assert progress["stage_total"] is None
        assert record_progress(conn, "s", "intake_accepted") is False


@pytest.mark.parametrize("event, code, state", [
    ("intake_rejected", "invalid_format", "rejected"),
    ("intake_failed", "preparation_timeout", "failed"),
    ("intake_cancelled", "cancelled", "cancelled"),
])
def test_submission_terminal_progress_cannot_restart(submission_engine, event, code, state):
    with submission_engine.begin() as conn:
        record_progress(conn, "s", "intake_accepted")
        record_progress(conn, "s", "preparing")
        assert record_progress(conn, "s", event, error_code=code, elapsed=1.5)
        before = conn.execute(text("SELECT state, error_code, progress_json FROM submissions")).first()
        assert before[0:2] == (state, code)
        assert read_progress(before[2])["elapsed_seconds"] == 1.5
        assert record_progress(conn, "s", "preparing") is False
        assert conn.execute(text("SELECT state, error_code, progress_json FROM submissions")).first() == before
        conn.execute(text("DELETE FROM submissions WHERE job_id = 's'"))
        assert record_progress(conn, "s", "intake_accepted") is False
        assert conn.execute(text("SELECT COUNT(*) FROM submissions")).scalar_one() == 0


def test_submission_progress_rejects_unsafe_or_premature_metadata(submission_engine):
    with submission_engine.begin() as conn:
        for event, metadata in [
            ("intake_rejected", {"error_code": "PRIVATE MEDICAL SENTINEL"}),
            ("preparing", {"total": 1}),
            ("preparing", {"model": "PRIVATE MEDICAL SENTINEL"}),
            ("preparing", {"error_code": "invalid_format"}),
            ("qwen_loading", {}),
        ]:
            with pytest.raises(ValueError):
                record_progress(conn, "s", event, **metadata)
        assert conn.execute(text("SELECT progress_json FROM submissions")).scalar_one() is None


@pytest.mark.parametrize("action", ["delete", "promote", "other_progress"])
def test_submission_write_losing_race_does_not_resurrect_or_overwrite(submission_engine, monkeypatch, action):
    engine = submission_engine
    with engine.begin() as conn:
        record_progress(conn, "s", "intake_accepted")
    with engine.begin() as conn:
        execute = conn.execute

        def raced_execute(statement, parameters):
            result = execute(statement, parameters)
            if "SELECT progress_json" not in str(statement):
                return result
            row = result.first()
            with engine.begin() as rival:
                if action == "delete":
                    rival.execute(text("DELETE FROM submissions WHERE job_id = 's'"))
                elif action == "promote":
                    rival.execute(text("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('d', 'p', 'other', 'printed', 'd', 1, 'hash', 'queued', '2026-01-01')"))
                    rival.execute(text("INSERT INTO jobs (id, document_id, state, total, progress_json, ts) SELECT job_id, 'd', 'queued', 1, progress_json, '2026-01-01' FROM submissions WHERE job_id = 's'"))
                    rival.execute(text("UPDATE submissions SET state = 'promoted', document_id = 'd', total_pages = 1 WHERE job_id = 's'"))
                else:
                    assert record_progress(rival, "s", "preparing")
            return SimpleNamespace(first=lambda: row)

        monkeypatch.setattr(conn, "execute", raced_execute)
        assert record_progress(conn, "s", "preparing") is False
    with engine.connect() as conn:
        if action == "delete":
            assert conn.execute(text("SELECT COUNT(*) FROM submissions")).scalar_one() == 0
        elif action == "promote":
            assert conn.execute(text("SELECT state FROM submissions")).scalar_one() == "promoted"
            assert len(read_progress(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())["events"]) == 1
        else:
            assert len(read_progress(conn.execute(text("SELECT progress_json FROM submissions")).scalar_one())["events"]) == 2

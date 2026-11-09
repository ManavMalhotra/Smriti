from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti import model_stages, ocr, preparation
from smriti.processing_store import cleanup_processing, read_page, reconcile_processing, submission
from smriti.spool import SpoolError
from tests.test_preparation import inline_supervisor, submit
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


def prepared(spool_db, settings, pages=1):
    job = submit(spool_db, settings, pages)
    assert preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor).success
    return job, {"settings": preparation.settings_context(settings), "members": [{"job_id": job, "start": 1, "end": pages}], "backend": "rapid"}


def test_text_only_window_never_loads_ocr_and_commits_private_pages(monkeypatch, spool_db, settings):
    job, context = prepared(spool_db, settings, 2)
    monkeypatch.setattr(ocr.RapidOcrOnnxEngine, "_load", lambda *args: pytest.fail("No OCR for usable text"))
    model_stages.ocr_target(context, lambda *args, **kwargs: None)
    row = submission(spool_db, job)
    assert read_page(settings, row, "ocr", 2)["source"] == "text_layer"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT page FROM jobs")).scalar_one() == 2
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM page_text")).scalar_one() == 0
    reconcile_processing(spool_db, settings, job)
    assert cleanup_processing(spool_db, settings, job)
    assert (settings.upload_dir / job / "page_2.webp").exists()
    assert not (settings.upload_dir / ".runtime" / job).exists()
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())["reserved_bytes"] == 0


def test_rapid_initialization_failure_leaves_fallback_to_another_stage(monkeypatch, spool_db, settings):
    job, context = prepared(spool_db, settings)
    original = model_stages.validate_source
    monkeypatch.setattr(model_stages, "validate_source", lambda *args: {**original(*args), "words_sha256": None})
    monkeypatch.setattr(ocr.RapidOcrOnnxEngine, "_load", lambda *args: (_ for _ in ()).throw(RuntimeError("PRIVATE")))
    monkeypatch.setattr(ocr.PaddleOcrEngine, "_load", lambda *args: pytest.fail("Fallback must be another child"))
    with pytest.raises(SpoolError, match="ocr_initialization_failed"):
        model_stages.ocr_target(context, lambda *args, **kwargs: None)


def test_cleanup_failure_keeps_charge_and_never_removes_canonical_source(monkeypatch, spool_db, settings):
    from pathlib import Path

    job, context = prepared(spool_db, settings)
    model_stages.ocr_target(context, lambda *args, **kwargs: None)
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path.name.startswith("ocr_"):
            raise PermissionError("PRIVATE")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", locked)
        assert not cleanup_processing(spool_db, settings, job)
    with spool_db.connect() as conn:
        manifest = json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())
    assert manifest["processing"]["cleanup"] == "failed" and manifest["reserved_bytes"] > 0
    assert cleanup_processing(spool_db, settings, job)
    assert (settings.upload_dir / job / "page_1.webp").exists()


def test_qwen_windows_preserve_global_counts_empty_first_page_and_lifecycle(monkeypatch, spool_db, settings):
    from smriti import vlm

    settings = replace(settings, vlm_enabled=True, max_workset_pages=2)
    job, context = prepared(spool_db, settings, 3)
    contexts = [{**context, "members": [{"job_id": job, "start": start, "end": end}]} for start, end in ((1, 2), (3, 3))]
    events, requests, sessions = [], [], []

    class Session:
        def __init__(self, timeout, on_event):
            self.callback = on_event
            sessions.append(self)

        def __enter__(self):
            self.callback("qwen_ready", duration=1.25)
            return self

        def __exit__(self, *args):
            self.callback("unloading")
            self.callback("unloaded")

    def extract(path, page, **kwargs):
        requests.append(page)
        assert kwargs["session"] is sessions[-1]
        return []

    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    monkeypatch.setattr(model_stages, "psutil", type("P", (), {"virtual_memory": staticmethod(lambda: type("M", (), {"available": 8 * 1024**3})())}))
    monkeypatch.setattr(vlm, "VlmSession", Session)
    monkeypatch.setattr(vlm, "extract_page_vlm", extract)
    original = model_stages._progress
    def progress(engine, owner, event, **fields):
        events.append((event, fields))
        original(engine, owner, event, **fields)
    monkeypatch.setattr(model_stages, "_progress", progress)
    for window in contexts:
        model_stages.qwen_target(window, lambda *args, **kwargs: None)
    assert requests == [1, 2, 3] and len(sessions) == 2
    assert [(fields["page"], fields["completed"], fields["total"]) for event, fields in events if event == "qwen_page"] == [(1, 1, 3), (2, 2, 3), (3, 3, 3)]
    assert [fields["duration"] for event, fields in events if event == "qwen_ready"] == [1.25, 1.25]
    assert [event for event, _ in events].count("unloaded") == 2
    model_stages.qwen_target(contexts[-1], lambda *args, **kwargs: None)
    assert requests == [1, 2, 3] and len(sessions) == 2


def test_handwritten_qwen_window_never_starts_a_model(monkeypatch, spool_db, settings):
    from smriti import vlm

    job, context = prepared(spool_db, settings)
    original = model_stages.validate_source
    monkeypatch.setattr(model_stages, "validate_source", lambda *args: {**original(*args), "capture_type": "handwritten"})
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: pytest.fail("No model for handwriting"))
    model_stages.qwen_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
    assert progress["events"][-1]["event"] == "qwen_skipped"
    assert progress["current_page"] == 1 and progress["completed_pages"] == 0


@pytest.mark.parametrize("changes", [{"engine": "OTHER"}, {"model_version": "OLD"}, {"source": "unknown"}])
def test_cached_ocr_identity_cannot_claim_another_engine(spool_db, settings, changes):
    from smriti.processing_store import artifact_path

    job, context = prepared(spool_db, settings)
    model_stages.ocr_target(context, lambda *args, **kwargs: None)
    path = artifact_path(settings, job, "ocr", 1)
    data = json.loads(path.read_bytes())
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        read_page(settings, submission(spool_db, job), "ocr", 1)


def test_changed_source_image_is_not_sent_to_any_model(monkeypatch, spool_db, settings):
    from smriti import vlm

    job, context = prepared(spool_db, settings)
    (settings.upload_dir / job / "page_1.webp").write_bytes(b"UNOWNED_MODIFICATION")
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: pytest.fail("No model for changed source"))
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        model_stages.qwen_target(context, lambda *args, **kwargs: None)


def test_unavailable_qwen_failure_names_qwen_not_previous_extraction(monkeypatch, spool_db, settings):
    from smriti import vlm
    from smriti.job_progress import record_progress

    job, context = prepared(spool_db, settings)
    with spool_db.begin() as conn:
        record_progress(conn, job, "extracting")
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: False)
    with pytest.raises(SpoolError, match="qwen_unavailable"):
        model_stages.qwen_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
    assert progress["failure_context"] == {"stage": "qwen", "model": vlm.VLM_ENGINE_NAME, "current_page": 1, "code": "qwen_unavailable"}
    assert progress["events"][-1]["stage"] == "qwen"


def test_qwen_refuses_to_launch_below_the_free_memory_floor(monkeypatch, spool_db, settings):
    from dataclasses import replace

    from smriti import model_stages, vlm

    job, context = prepared(spool_db, replace(settings, vlm_min_available_bytes=5 * 1024**3))
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    monkeypatch.setattr(
        model_stages,
        "psutil",
        type("P", (), {"virtual_memory": staticmethod(lambda: type("M", (), {"available": 2 * 1024**3})())}),
    )
    monkeypatch.setattr(vlm, "VlmSession", lambda **kwargs: pytest.fail("Never spawn below the RAM floor"))
    with pytest.raises(SpoolError, match="qwen_unavailable"):
        model_stages.qwen_target(context, lambda *args, **kwargs: None)


def test_qwen_http_failure_is_durable_before_model_cleanup(monkeypatch, spool_db, settings):
    from smriti import vlm

    job, context = prepared(spool_db, settings)
    stopped = []
    monkeypatch.setattr(model_stages, "psutil", type("P", (), {"virtual_memory": staticmethod(lambda: type("M", (), {"available": 8 * 1024**3})())}))

    class Session:
        def __init__(self, timeout, on_event):
            self.callback = on_event

        def __enter__(self):
            return self

        def __exit__(self, *args):
            stopped.append(True)
            self.callback("unloaded")

    def fail(*args, **kwargs):
        raise vlm.VlmError("qwen_http_error", http_status=413)

    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    monkeypatch.setattr(vlm, "VlmSession", Session)
    monkeypatch.setattr(vlm, "extract_page_vlm", fail)
    forwarded = []
    with pytest.raises(vlm.VlmError) as failed:
        model_stages.qwen_target(context, lambda event, **fields: forwarded.append(fields))
    assert failed.value.job_id == job and stopped == [True]
    with spool_db.connect() as conn:
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
    assert progress["failure_context"]["code"] == "qwen_http_error"
    assert progress["failure_context"]["status"] == 413
    assert progress["failure_context"]["current_page"] == 1
    assert any(event.get("code") == "qwen_http_error" and event.get("status") == 413 for event in forwarded)


@pytest.mark.parametrize("changes", [{"outcome": "other"}, {"error_code": "PRIVATE"}, {"model_version": "OTHER"},
                                   {"fields": [{}]}, {"image_sha256": "wrong"}, {"identity": {}}])
def test_unavailable_page_cannot_bypass_artifact_validation(spool_db, settings, changes):
    from smriti.processing_store import artifact_path, save_page
    from smriti.vlm import VLM_ENGINE_NAME

    job, _ = prepared(spool_db, settings)
    row = submission(spool_db, job)
    save_page(spool_db, settings, row, "qwen", 1, fields=[], model_version=VLM_ENGINE_NAME,
              outcome="unavailable", error_code="timeout")
    path = artifact_path(settings, job, "qwen", 1)
    data = json.loads(path.read_bytes())
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        read_page(settings, row, "qwen", 1)


def test_cached_unavailable_page_never_launches_qwen_or_claims_read_success(monkeypatch, spool_db, settings):
    from smriti import vlm
    from smriti.processing_store import save_page

    job, context = prepared(spool_db, settings)
    row = submission(spool_db, job)
    save_page(spool_db, settings, row, "qwen", 1, fields=[], model_version=vlm.VLM_ENGINE_NAME,
              outcome="unavailable", error_code="timeout")
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: pytest.fail("Do not retry unavailable pages"))
    model_stages.qwen_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
    assert progress["events"][-1]["event"] == "qwen_unavailable_page"
    assert progress["completed_pages"] == 1 and progress["verification_state"] == "partial"

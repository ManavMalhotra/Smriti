from __future__ import annotations

import json
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti.coordinator import CleanupBlocked, Coordinator
from smriti.runtime import StageResult
from tests.test_preparation import inline_supervisor, submit
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


def test_frozen_fifo_batch_no_late_replacement_and_atomic_completion(spool_db, settings):
    first = submit(spool_db, settings, 1)
    late = []
    calls = []

    def supervise(target, context, **options):
        calls.append((target, context, options))
        if not late:
            late.append(submit(spool_db, settings, 2))
        return inline_supervisor(target, context, **options)

    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT membership_json FROM stage_batches")).scalar_one()) == [first]
        assert conn.execute(text("SELECT state FROM jobs WHERE id = :id"), {"id": first}).scalar_one() == "done"
        assert conn.execute(text("SELECT state FROM submissions WHERE job_id = :id"), {"id": late[0]}).scalar_one() == "pending_intake"
    assert all(options["job_name"] for _, _, options in calls)
    assert not (settings.upload_dir / ".runtime" / first).exists()
    assert (settings.upload_dir / first / "page_1.webp").exists()


def test_exclusive_controller_lock_even_when_idle(spool_db, settings):
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        assert not controller.process_batch()
        with pytest.raises(OSError):
            with Coordinator(spool_db, settings):
                pytest.fail("Second coordinator cannot start")
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        assert not controller.process_batch()


def test_cleanup_failure_fences_next_stage_and_recovery(spool_db, settings):
    job = submit(spool_db, settings)
    calls = []

    def blocked(target, context, **kwargs):
        calls.append(target)
        return StageResult("cleanup_failed", False, None, .1)

    with Coordinator(spool_db, settings, supervisor=blocked) as controller:
        with pytest.raises(CleanupBlocked):
            controller.process_batch()
    assert len(calls) == 1 and (settings.spool_dir / f"{job}.raw").exists()
    with Coordinator(spool_db, settings, supervisor=inline_supervisor, recover_tree=lambda *args: False) as controller:
        with pytest.raises(CleanupBlocked):
            controller.process_batch()
    with Coordinator(spool_db, settings, supervisor=inline_supervisor, recover_tree=lambda *args: True) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"


def test_later_window_failure_keeps_sources_and_does_not_publish_partial_facts(spool_db, settings):
    settings = replace(settings, max_workset_pages=1)
    job = submit(spool_db, settings, 2)
    stages = []

    def fail_later(target, context, **options):
        stages.append(target)
        if target.endswith("ocr_target") and context["members"][0]["start"] == 2:
            return StageResult("timeout", True, -1, 0, job_id=job)
        return inline_supervisor(target, context, **options)

    with Coordinator(spool_db, settings, supervisor=fail_later) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "failed"
        for table in ("observation", "page_text", "report"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
    assert not any(stage.endswith("rules_target") for stage in stages)
    assert (settings.upload_dir / job / "page_2.webp").exists()


def test_committed_done_after_controller_interruption_never_republishes(spool_db, settings):
    job = submit(spool_db, settings)

    def interrupted(target, context, **options):
        result = inline_supervisor(target, context, **options)
        if target.endswith("publication_target"):
            raise RuntimeError("PRIVATE synthetic crash after final commit")
        return result

    with Coordinator(spool_db, settings, supervisor=interrupted) as controller:
        with pytest.raises(CleanupBlocked):
            controller.process_batch()
    def no_processing(*args, **kwargs):
        pytest.fail("Done document cannot be processed again")

    with Coordinator(spool_db, settings, supervisor=no_processing, recover_tree=lambda *args: True) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"
        assert conn.execute(text("SELECT COUNT(*) FROM report")).scalar_one() == 1
    assert not (settings.upload_dir / ".runtime" / job).exists()


def test_long_document_windows_stay_consecutive_and_cursor_storage_is_bounded(monkeypatch, spool_db, settings):
    from smriti import coordinator, preparation

    settings = replace(settings, vlm_enabled=True)
    first = submit(spool_db, settings, 1)
    assert preparation.prepare_submission(spool_db, settings, first, supervisor=inline_supervisor).success
    second = submit(spool_db, settings, 2)
    assert preparation.prepare_submission(spool_db, settings, second, supervisor=inline_supervisor).success
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE document SET page_count = 1001 WHERE image_path = :job"), {"job": first})
        conn.execute(text("UPDATE submissions SET total_pages = 1001 WHERE job_id = :job"), {"job": first})
        conn.execute(text("UPDATE jobs SET total = 1001 WHERE id = :job"), {"job": first})
    monkeypatch.setattr(coordinator, "page_metadata", lambda *args: {"words_sha256": None, "capture_type": "printed"})
    calls, largest = [], []

    def schedule_only(target, context, **options):
        calls.append((target, context.get("members"), context.get("job_id")))
        with spool_db.connect() as conn:
            largest.append(conn.execute(text("SELECT length(checkpoints_json) FROM stage_batches")).scalar_one())
        if target.endswith("publication_target"):
            with spool_db.begin() as conn:
                conn.execute(text("UPDATE jobs SET state = 'done' WHERE id = :job"), {"job": context["job_id"]})
        return StageResult("ok", True, 0, 0)

    with Coordinator(spool_db, settings, supervisor=schedule_only) as controller:
        assert controller.process_batch()
    ocr = [members for target, members, _ in calls if target.endswith("ocr_target")]
    qwen = [members for target, members, _ in calls if target.endswith("qwen_target")]
    assert len(ocr) == len(qwen) == 52
    assert ocr[0] == [{"job_id": first, "start": 1, "end": 20}]
    assert ocr[50] == [{"job_id": first, "start": 1001, "end": 1001}]
    assert ocr[51] == [{"job_id": second, "start": 1, "end": 2}]
    assert all(sum(item["end"] - item["start"] + 1 for item in members) <= 20 for members in ocr + qwen)
    first_publish = next(i for i, (target, _, job) in enumerate(calls) if target.endswith("publication_target") and job == first)
    second_ocr = next(i for i, (target, members, _) in enumerate(calls) if target.endswith("ocr_target") and members[0]["job_id"] == second)
    assert first_publish < second_ocr and max(largest) < 2048


def test_attributed_capacity_failure_continues_other_frozen_member(spool_db, settings):
    first, second = submit(spool_db, settings, 1), submit(spool_db, settings, 2)
    failed = False
    def supervise(target, context, **options):
        nonlocal failed
        if target.endswith("ocr_target") and not failed:
            failed = True
            return StageResult("capacity_exhausted", True, -1, 0, job_id=first)
        return inline_supervisor(target, context, **options)

    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        states = dict(conn.execute(text("SELECT id, state FROM jobs")).all())
        assert states == {first: "failed", second: "done"}
        assert conn.execute(text("SELECT COUNT(*) FROM report")).scalar_one() == 1


def test_fallback_is_a_separate_owned_attempt_only_after_initialization_failure(spool_db, settings):
    job = submit(spool_db, settings)
    attempts = []
    def supervise(target, context, **options):
        if target.endswith("ocr_target"):
            attempts.append((context["backend"], options["job_name"]))
            if context["backend"] == "rapid":
                return StageResult("ocr_initialization_failed", True, -1, 0, job_id=job)
        return inline_supervisor(target, context, **options)

    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    assert [backend for backend, _ in attempts] == ["rapid", "paddle"]
    assert attempts[0][1] != attempts[1][1]


def test_revocation_between_rules_and_publication_cannot_create_clinical_rows(spool_db, settings):
    job = submit(spool_db, settings)
    def supervise(target, context, **options):
        result = inline_supervisor(target, context, **options)
        if target.endswith("rules_target"):
            with spool_db.begin() as conn:
                conn.execute(text("UPDATE consent SET revoked_at = '2026-11-06'"))
        return result

    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        for table in ("observation", "report", "page_text"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_locked_final_cleanup_retries_without_reprocessing_done(monkeypatch, spool_db, settings):
    from smriti import coordinator

    job = submit(spool_db, settings)
    original = coordinator.cleanup_processing
    def locked(*args):
        return False

    with monkeypatch.context() as scoped:
        scoped.setattr(coordinator, "cleanup_processing", locked)
        with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
            with pytest.raises(CleanupBlocked):
                controller.process_batch()
    with Coordinator(spool_db, settings, supervisor=lambda *args, **kw: pytest.fail("No reprocessing")) as controller:
        assert controller.process_batch()
    assert original is coordinator.cleanup_processing
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"
        assert json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())["reserved_bytes"] == 0


def test_connected_progress_ranges_measurements_and_commit_failure_are_truthful(monkeypatch, spool_db, settings):
    from smriti import publication
    from tests.test_app_diagnostics import CaptureDiagnostics

    settings = replace(settings, max_workset_pages=1)
    job = submit(spool_db, settings, 2)
    diagnostics = CaptureDiagnostics(settings)
    monkeypatch.setattr(publication, "_rows", lambda *args: (_ for _ in ()).throw(RuntimeError("PRIVATE_SAVE_SENTINEL")))
    with Coordinator(spool_db, settings, supervisor=inline_supervisor, diagnostics=diagnostics) as controller:
        assert controller.process_batch()
    events = diagnostics.events
    assert any(event["event"] == "page_read" and event["page"] == 2 for event in events)
    assert any(event["event"] == "window_started" and event["window_start"] == 2 for event in events)
    assert any(event["event"] == "stage_measurement" and event["coverage"] == "unavailable" and event["observed_peak"] is None for event in events)
    assert not any(event["event"] == "done" for event in events)
    assert any(event["event"] == "failed" and event["job_id"] == job for event in events)
    with spool_db.connect() as conn:
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
        assert progress["failure_context"]["stage"] == "saving"
    assert "PRIVATE_SAVE_SENTINEL" not in json.dumps(events)


def test_opted_in_parser_crash_retention_survives_coordinator_cleanup(spool_db, settings):
    from tests.test_app_diagnostics import CaptureDiagnostics

    settings = replace(settings, debug_retain_failed_spool=True)
    job = submit(spool_db, settings)
    diagnostics = CaptureDiagnostics(settings)
    def crash(target, context, **options):
        return StageResult("crash", True, 17, 0)
    with Coordinator(spool_db, settings, supervisor=crash, diagnostics=diagnostics) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        state = conn.execute(text("SELECT spool_cleanup_state FROM submissions")).scalar_one()
    assert state == "debug_retained" and (settings.spool_dir / f"{job}.raw").is_file()
    assert any(event["event"] == "spool_debug_retained" and event["cleanup_outcome"] == "not_required" for event in diagnostics.events)
    assert not any(event["event"] == "spool_deleted" for event in diagnostics.events)


def test_qwen_failure_retains_valid_readings_freezes_missing_pages_and_continues_fifo(spool_db, settings):
    from dataclasses import asdict
    from smriti.processing_store import read_page, save_page, submission
    from smriti.vlm import VLM_ENGINE_NAME
    from tests.test_worker import _field

    settings = replace(settings, vlm_enabled=True)
    first, second = submit(spool_db, settings, 3), submit(spool_db, settings, 1)
    failed = False
    snapshots = {}
    def supervise(target, context, **options):
        nonlocal failed
        if target.endswith("qwen_target"):
            if not failed:
                failed = True
                row = submission(spool_db, first)
                save_page(spool_db, settings, row, "qwen", 1, fields=[asdict(_field("92", engine=VLM_ENGINE_NAME))], model_version=VLM_ENGINE_NAME)
                return StageResult("qwen_http_error", True, -1, 0, job_id=first)
            for member in context["members"]:
                row = submission(spool_db, member["job_id"])
                for page in range(member["start"], member["end"] + 1):
                    if read_page(settings, row, "qwen", page) is None:
                        assert member["job_id"] == second
                        save_page(spool_db, settings, row, "qwen", page, fields=[], model_version=VLM_ENGINE_NAME)
            return StageResult("ok", True, 0, 0)
        if target.endswith("verification_target"):
            row = submission(spool_db, context["job_id"])
            snapshots[row["job_id"]] = [read_page(settings, row, "qwen", page) for page in range(1, row["page_count"] + 1)]
        return inline_supervisor(target, context, **options)
    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    assert snapshots[first][0]["fields"][0]["value_num"] == "92"
    assert all(item["outcome"] == "unavailable" and item["error_code"] == "qwen_http_error" for item in snapshots[first][1:])
    assert "outcome" not in snapshots[second][0]
    with spool_db.connect() as conn:
        assert dict(conn.execute(text("SELECT id, state FROM jobs")).all()) == {first: "done", second: "done"}
        progress = json.loads(conn.execute(text("SELECT progress_json FROM jobs WHERE id=:id"), {"id": first}).scalar_one())
        assert progress["verification_state"] == "partial"
        assert conn.execute(text("SELECT COUNT(*) FROM page_text")).scalar_one() == 4


def test_interrupted_degradation_decision_resumes_without_retrying_model(monkeypatch, spool_db, settings):
    from smriti import coordinator, vlm
    from smriti.processing_store import submission

    settings = replace(settings, vlm_enabled=True)
    job = submit(spool_db, settings, 3)
    original = coordinator.save_page
    def interrupted(*args, **kwargs):
        if args[3:5] == ("qwen", 2):
            raise RuntimeError("PRIVATE marker write interruption")
        return original(*args, **kwargs)
    def supervise(target, context, **options):
        if target.endswith("qwen_target"):
            return StageResult("timeout", True, -1, 0, job_id=job)
        return inline_supervisor(target, context, **options)
    with monkeypatch.context() as scoped:
        scoped.setattr(coordinator, "save_page", interrupted)
        with Coordinator(spool_db, settings, supervisor=supervise) as controller:
            with pytest.raises(RuntimeError, match="interruption"):
                controller.process_batch()
    assert submission(spool_db, job)["manifest"]["processing"]["qwen_unavailable_reason"] == "timeout"
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: pytest.fail("Durable decision prevents model retry"))
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        controller.recover()
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"


@pytest.mark.parametrize("status", ["timeout", "memory_limit", "stage_exception", "qwen_port_busy"])
def test_degraded_document_never_reschedules_a_failing_qwen_child(spool_db, settings, status):
    settings = replace(settings, vlm_enabled=True)
    job = submit(spool_db, settings)
    calls = []
    def supervise(target, context, **options):
        if target.endswith("qwen_target"):
            calls.append(target)
            assert len(calls) == 1, "Do not retry a degraded document even if the child always fails"
            return StageResult(status, True, -1, 0, job_id=job)
        return inline_supervisor(target, context, **options)
    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        assert controller.process_batch()
    assert len(calls) == 1
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"


@pytest.mark.parametrize("status,confirmed", [("timeout", False), ("prepared_artifact_invalid", True), ("capacity_exhausted", True), ("cancelled", True)])
def test_qwen_cleanup_corruption_capacity_and_cancel_do_not_degrade(spool_db, settings, status, confirmed):
    settings = replace(settings, vlm_enabled=True)
    job = submit(spool_db, settings)
    def supervise(target, context, **options):
        if target.endswith("qwen_target"):
            return StageResult(status, confirmed, -1, 0, job_id=job)
        return inline_supervisor(target, context, **options)
    with Coordinator(spool_db, settings, supervisor=supervise) as controller:
        if not confirmed:
            with pytest.raises(CleanupBlocked):
                controller.process_batch()
        else:
            assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM observation")).scalar_one() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM report")).scalar_one() == 0
        manifest = json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())
        assert "qwen_unavailable_reason" not in manifest.get("processing", {})

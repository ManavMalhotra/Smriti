from __future__ import annotations

import os
import ctypes
import json
import multiprocessing
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from smriti.config import SPOOL_CHUNK_BYTES, Settings, load_settings
from smriti import runtime

pytestmark = pytest.mark.unit


def test_non_page_helper_checkpoint_has_no_invented_page():
    runtime._validate_message({"event": "checkpoint", "count": 100})
    with pytest.raises(ValueError):
        runtime._validate_message({"event": "checkpoint", "page": 0})


def test_progress_ipc_rejects_unknown_sensitive_fields():
    runtime._validate_message({"event": "progress", "progress_event": "page_read", "job_id": "a" * 32, "page": 21})
    with pytest.raises(ValueError):
        runtime._validate_message({"event": "progress", "progress_event": "page_read", "job_id": "a" * 32, "engine": "PRIVATE_SENTINEL"})
    with pytest.raises(ValueError):
        runtime._validate_message({"event": "progress", "progress_event": "page_read", "job_id": "PRIVATE_SENTINEL"})


@pytest.mark.skipif(os.name != "nt", reason="Windows owned recovery")
def test_named_job_recovery_only_terminates_owned_tree(tmp_path):
    import uuid

    name = uuid.uuid4().hex
    job = runtime.WindowsJob(name=name)
    owned = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        job.assign(owned.pid)
        with pytest.raises(OSError, match="already exists"):
            runtime.WindowsJob(name=name)
        assert runtime.recover_stage_job(name, .5)
        owned.wait(timeout=3)
        assert unrelated.poll() is None
    finally:
        job.close()
        for process in (owned, unrelated):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
    assert runtime.recover_stage_job(name, .5)
    assert not runtime.recover_stage_job("unowned")


def test_runtime_defaults_and_window_budgets():
    settings = Settings()
    assert settings.max_batch_submissions == 10
    assert settings.max_workset_pages == 20
    assert not hasattr(settings, "max_pages")
    assert settings.max_spoolers == 2
    assert SPOOL_CHUNK_BYTES == 1024 * 1024
    assert settings.spool_capacity_bytes == 20 * settings.max_upload_bytes + 2 * 65536
    assert settings.max_request_bytes == settings.max_upload_bytes + 65536
    assert settings.debug_retain_failed_spool is False
    assert settings.preparation_timeout_seconds == 300
    assert settings.ocr_timeout_seconds(20) == 60 + 120 * 20
    assert settings.vlm_request_seconds == 240
    assert settings.vlm_timeout_seconds(20) == 30 + 240 * 20 + 60
    assert settings.cleanup_wait_seconds * 2 <= 10
    assert 1 <= settings.ram_sample_seconds <= 2
    assert settings.gpu_poll_seconds >= 2
    assert settings.gpu_query_timeout_seconds == 3
    assert replace(settings, max_upload_bytes=10).spool_capacity_bytes == 200 + 2 * 65536


@pytest.mark.parametrize("changes", [
    {"max_batch_submissions": 0}, {"max_batch_submissions": 11},
    {"max_workset_pages": 21},
    {"max_workset_pages": 0},
    {"max_upload_bytes": -1}, {"max_pixels": 0}, {"max_spoolers": 3},
    {"max_batch_submissions": True},
    {"debug_retain_failed_spool": "1"},
    {"preparation_timeout_seconds": 0}, {"ocr_page_seconds": float("inf")},
    {"worker_poll_seconds": float("nan")},
    {"ocr_page_seconds": 1e308}, {"vlm_request_seconds": 1e308},
    {"vlm_startup_seconds": 29}, {"vlm_request_seconds": 119},
    {"cleanup_wait_seconds": 6}, {"ram_sample_seconds": 0.5},
    {"ram_sample_seconds": 2.1}, {"gpu_poll_seconds": 1.9},
    {"gpu_query_timeout_seconds": 3.1},
    {"active_output_bytes": 0}, {"min_free_disk_bytes": -1},
    {"max_page_text_bytes": True}, {"max_page_words": 1.5},
    {"max_artifact_bytes": 0}, {"native_memory_bytes": 0},
    {"inspection_timeout_seconds": float("nan")}, {"helper_timeout_seconds": 0},
    {"log_file_bytes": 1}, {"log_event_bytes": 4097}, {"log_queue_events": 513},
    {"log_backups": 6}, {"log_max_age_days": 8}, {"log_shutdown_seconds": 2.1},
])
def test_invalid_runtime_settings_fail_before_work(changes):
    with pytest.raises(ValueError):
        Settings(**changes)


@pytest.mark.parametrize("pages", [-1, 21, 1.5, True])
def test_stage_deadlines_reject_invalid_worksets(pages):
    for budget in (Settings().ocr_timeout_seconds, Settings().vlm_timeout_seconds):
        with pytest.raises(ValueError):
            budget(pages)


def test_runtime_environment_is_loaded_once_and_uses_isolated_spool(monkeypatch, tmp_path):
    monkeypatch.setenv("SMRITI_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setenv("SMRITI_MAX_PAGES", "12")
    monkeypatch.setenv("SMRITI_MAX_WORKSET_PAGES", "15")
    monkeypatch.setenv("SMRITI_MAX_BATCH_SUBMISSIONS", "8")
    monkeypatch.setenv("SMRITI_PREPARATION_TIMEOUT_SECONDS", "310")
    monkeypatch.setenv("SMRITI_RAM_SAMPLE_SECONDS", "1.5")
    monkeypatch.setenv("DEBUG_RETAIN_FAILED_SPOOL", "1")
    settings = load_settings()
    assert settings.spool_dir == tmp_path / "spool"
    assert not hasattr(settings, "max_pages")
    assert settings.max_workset_pages == 15
    assert settings.max_batch_submissions == 8
    assert settings.preparation_timeout_seconds == 310
    assert settings.ram_sample_seconds == 1.5
    assert settings.debug_retain_failed_spool is True
    monkeypatch.setenv("DEBUG_RETAIN_FAILED_SPOOL", "0")
    assert settings.debug_retain_failed_spool is True
    assert load_settings().debug_retain_failed_spool is False
    assert not (tmp_path / "spool").exists()


def test_window_is_independent_of_document_and_resource_bounds(monkeypatch, tmp_path):
    settings = Settings(max_workset_pages=3)
    assert settings.max_workset_pages == 3
    assert settings.active_output_bytes == 2 * 1024**3
    assert settings.min_free_disk_bytes == 1024**3
    assert settings.max_page_text_bytes == 1024**2
    assert settings.max_page_words == 100_000
    assert settings.max_artifact_bytes == 16 * 1024**2
    assert settings.native_memory_bytes == 6 * 1024**3
    assert settings.inspection_timeout_seconds == settings.helper_timeout_seconds == 300
    monkeypatch.setenv("SMRITI_LOG_DIR", str(tmp_path / "private-logs"))
    monkeypatch.setenv("SMRITI_ACTIVE_OUTPUT_BYTES", "123456")
    monkeypatch.setenv("SMRITI_NATIVE_MEMORY_BYTES", "654321")
    settings = load_settings()
    assert settings.log_dir == tmp_path / "private-logs"
    assert settings.active_output_bytes == 123456
    assert settings.native_memory_bytes == 654321
    assert not settings.log_dir.exists()


@pytest.mark.parametrize("flag", ["true", "yes", "on", "", "2"])
def test_debug_raw_retention_requires_explicit_one(monkeypatch, flag):
    monkeypatch.setenv("DEBUG_RETAIN_FAILED_SPOOL", flag)
    with pytest.raises(ValueError, match="DEBUG_RETAIN_FAILED_SPOOL"):
        load_settings()


def test_pinned_psutil_can_inspect_current_process():
    import psutil

    assert psutil.__version__ == "7.2.2"
    process = psutil.Process()
    assert process.pid == os.getpid()
    assert process.create_time() > 0
    assert process.memory_info().rss > 0
    if os.name == "nt":
        assert process.memory_info().private >= 0


windows_stage = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object supervision")


@pytest.mark.parametrize("message", [
    [], {"event": []}, {"event": "unknown"}, {"event": "ready", "secret": "private"},
    {"event": "page_started", "page": True}, {"event": "page_started", "page": 0},
    {"event": "page_finished", "page": 1, "count": -1},
    {"event": "failed", "code": "private-exception"}, {"event": "ok", "page": 1},
])
def test_stage_ipc_rejects_untrusted_fields(message):
    with pytest.raises(ValueError):
        runtime._validate_message(message)


@pytest.mark.parametrize("message", [
    {"event": "failed", "code": "timeout", "job_id": "../private"},
    {"event": "failed", "code": "timeout", "job_id": 123},
    {"event": "ready", "job_id": "a" * 32},
])
def test_failure_owner_is_bounded_and_only_allowed_on_failure(message):
    with pytest.raises(ValueError):
        runtime._validate_message(message)


@windows_stage
def test_real_spawn_failure_preserves_only_safe_owner_and_code(capfd):
    result = runtime.run_stage("tests.runtime_targets:owned_error", {"job_id": "a" * 32}, timeout_seconds=10)
    assert result.status == "capacity_exhausted" and result.job_id == "a" * 32
    assert result.cleanup_confirmed
    assert "PRIVATE_FAILURE_CONTENT" not in repr(result) + "".join(capfd.readouterr())


@pytest.mark.parametrize("kwargs", [
    {"timeout_seconds": 0}, {"timeout_seconds": float("inf")},
    {"timeout_seconds": True}, {"cleanup_wait_seconds": 6},
    {"request_timeout_seconds": float("nan")},
])
def test_stage_deadlines_validate_before_launch(kwargs):
    with pytest.raises(ValueError):
        runtime.run_stage("tests.runtime_targets:simple", {}, **{"timeout_seconds": 10, **kwargs})


def test_stage_context_is_bounded_before_launch():
    with pytest.raises(ValueError, match="byte boundary"):
        runtime.run_stage("tests.runtime_targets:simple", {"large": "x" * runtime.MAX_CONTEXT_BYTES}, timeout_seconds=10)
    with pytest.raises(ValueError, match="invalid"):
        runtime.run_stage("untrusted/path.py", {}, timeout_seconds=10)


@windows_stage
def test_stage_real_spawn_success_and_cpu_environment(tmp_path):
    marker = tmp_path / "cpu.json"
    result = runtime.run_stage("tests.runtime_targets:cpu_check", {"marker": str(marker)},
                               timeout_seconds=10, cpu_only=True)
    assert result.success, result
    assert result.cleanup_confirmed
    assert [event["event"] for event in result.events] == ["ready", "page_started", "page_finished"]
    assert result.events[-1] == {"event": "page_finished", "page": 21, "count": 4}
    assert json.loads(marker.read_text()) == {"cpu_only": True, "runtime_loaded": False}


@windows_stage
def test_stage_reported_ok_survives_interpreter_finalization_failure():
    result = runtime.run_stage("tests.runtime_targets:exit_120_after_ok", {}, timeout_seconds=10)
    assert result.status == "ok" and result.cleanup_confirmed
    assert result.exit_code == 120
    assert result.success


@windows_stage
def test_stage_exception_and_native_output_are_private(capfd):
    sentinel = "PRIVATE_SYNTHETIC_MEDICAL_PASSWORD_SENTINEL"
    result = runtime.run_stage("tests.runtime_targets:error", {"sentinel": sentinel}, timeout_seconds=10)
    assert result.status == "stage_exception", result
    assert result.cleanup_confirmed and not result.success
    assert sentinel not in repr(result)
    assert sentinel not in "".join(capfd.readouterr())


@windows_stage
def test_stage_invalid_producer_metadata_is_not_forwarded():
    result = runtime.run_stage("tests.runtime_targets:bad_report", {"sentinel": "PRIVATE_SENTINEL"}, timeout_seconds=10)
    assert result.status == "stage_exception" and result.cleanup_confirmed
    assert "PRIVATE_SENTINEL" not in repr(result)


@windows_stage
def test_stage_history_and_ipc_are_bounded():
    result = runtime.run_stage("tests.runtime_targets:burst", {"pages": 1000}, timeout_seconds=10)
    assert result.success, result
    assert len(result.events) == runtime.MAX_STAGE_EVENTS
    assert result.events_truncated == 1000 - runtime.MAX_STAGE_EVENTS
    assert result.events[-1]["page"] == 1000


@windows_stage
def test_stage_request_deadline_stops_native_hang(tmp_path):
    result = runtime.run_stage("tests.runtime_targets:native_hang", {"marker": str(tmp_path / "started")},
                               timeout_seconds=10, request_timeout_seconds=0.2, cleanup_wait_seconds=0.5)
    assert result.status == "timeout" and result.cleanup_confirmed
    assert not result.success
    assert result.duration_seconds < 5


@windows_stage
def test_stage_native_memory_limit_is_enforced():
    result = runtime.run_stage("tests.runtime_targets:allocate", {"bytes": 256 * 1024 * 1024},
                               timeout_seconds=10, memory_limit_bytes=128 * 1024 * 1024)
    assert result.status in {"memory_limit", "crash"}, result
    assert result.cleanup_confirmed and not result.success


def _wait_marker(marker: Path, timeout=10):
    deadline = time.monotonic() + timeout
    while not marker.is_file():
        if time.monotonic() >= deadline:
            raise AssertionError("Synthetic process did not publish its identity")
        time.sleep(0.02)


def _identities_gone(marker: Path):
    import psutil
    identities = json.loads(marker.read_text())
    deadline = time.monotonic() + 5
    while True:
        survivors = []
        for pid, created in identities.values():
            try:
                process = psutil.Process(pid)
                if process.create_time() == created and process.is_running():
                    survivors.append(pid)
            except psutil.Error:
                pass
        if not survivors:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"Owned synthetic process identities survived: {survivors}")
        time.sleep(0.02)


@windows_stage
@pytest.mark.parametrize("mode, expected", [("normal", "ok"), ("crash", "crash"), ("hang", "timeout")])
@pytest.mark.integration
def test_stage_root_child_grandchild_are_reaped(tmp_path, mode, expected):
    marker = tmp_path / "tree.json"
    result = runtime.run_stage("tests.runtime_targets:process_tree", {"marker": str(marker), "mode": mode},
                               timeout_seconds=2 if mode == "hang" else 10, cleanup_wait_seconds=0.5)
    assert result.status == expected, result
    assert result.cleanup_confirmed
    assert marker.is_file()
    _identities_gone(marker)


@windows_stage
@pytest.mark.integration
def test_stage_cancel_reaps_the_tree(tmp_path):
    marker = tmp_path / "cancel-tree.json"
    stop = threading.Event()

    def cancel_when_started():
        _wait_marker(marker)
        stop.set()

    cancel = threading.Thread(target=cancel_when_started, daemon=True)
    cancel.start()
    result = runtime.run_stage("tests.runtime_targets:process_tree", {"marker": str(marker), "mode": "hang"},
                               timeout_seconds=15, stop=stop, cleanup_wait_seconds=0.5)
    cancel.join(timeout=1)
    assert result.status == "cancelled" and result.cleanup_confirmed
    _identities_gone(marker)


@windows_stage
def test_assignment_failure_never_imports_or_executes_target(monkeypatch, tmp_path):
    marker = tmp_path / "never-started"

    def refuse_assignment(self, pid):
        raise OSError("synthetic assignment refusal")

    monkeypatch.setattr(runtime.WindowsJob, "assign", refuse_assignment)
    result = runtime.run_stage("tests.runtime_targets:simple", {"marker": str(marker)},
                               timeout_seconds=10, cleanup_wait_seconds=0.5)
    assert result.status == "assignment_failed" and result.cleanup_confirmed, result
    assert not marker.exists()


@windows_stage
def test_cleanup_failure_cannot_be_success(monkeypatch):
    monkeypatch.setattr(runtime, "_cleanup", lambda *_: False)
    result = runtime.run_stage("tests.runtime_targets:simple", {}, timeout_seconds=10, cleanup_wait_seconds=0.2)
    assert result.status == "cleanup_failed" and not result.cleanup_confirmed
    assert not result.success


@windows_stage
def test_controller_eof_aborts_bootstrap_without_importing_target(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe()
    marker = tmp_path / "never-imported"
    payload = json.dumps({"marker": str(marker)}).encode()
    process = ctx.Process(target=runtime._stage_entry, args=(child, "tests.runtime_targets:simple", payload, True))
    process.start()
    child.close()
    parent.close()
    try:
        process.join(timeout=5)
        assert process.exitcode == 0
        assert not marker.exists()
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        process.close()


@windows_stage
@pytest.mark.integration
def test_abrupt_controller_exit_closes_job_and_kills_descendants(tmp_path):
    marker = tmp_path / "abrupt-tree.json"
    controller = subprocess.Popen([
        sys.executable, "-c", "from tests.runtime_targets import controller; import sys; controller(sys.argv[1])", str(marker),
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_marker(marker)
        controller.terminate()
        controller.wait(timeout=5)
        _identities_gone(marker)
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=5)


@windows_stage
def test_job_handle_cannot_be_inherited():
    job = runtime.WindowsJob()
    try:
        api = runtime._kernel32()
        get_flags = api.GetHandleInformation
        get_flags.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ctypes.wintypes.DWORD)]
        get_flags.restype = ctypes.wintypes.BOOL
        flags = ctypes.wintypes.DWORD()
        assert get_flags(job.handle, ctypes.byref(flags))
        assert flags.value & 1 == 0
    finally:
        job.close()


@pytest.mark.integration
def test_coordinator_lock_rejects_another_process_and_releases(tmp_path):
    db_path = tmp_path / "isolated.db"
    marker = tmp_path / "lock-result"
    with runtime.CoordinatorLock(db_path) as lock:
        assert not os.get_inheritable(lock.fd)
        subprocess.run([
            sys.executable, "-c", "from tests.runtime_targets import try_lock; import sys; try_lock(sys.argv[1],sys.argv[2])",
            str(db_path), str(marker),
        ], check=True, timeout=10, capture_output=True)
        assert marker.read_text() == "busy"
    assert lock.path.exists()
    with runtime.CoordinatorLock(db_path):
        pass


def test_coordinator_lock_preserves_existing_file_content(tmp_path):
    db_path = tmp_path / "isolated.db"
    lock_path = db_path.with_suffix(".coordinator.lock")
    lock_path.write_bytes(b"keep-existing-content")
    with runtime.CoordinatorLock(db_path):
        pass
    assert lock_path.read_bytes() == b"keep-existing-content"

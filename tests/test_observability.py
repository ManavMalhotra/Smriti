from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import replace

import pytest

from smriti.observability import Diagnostics, JsonlWriter, safe_event, terminal_line
from smriti.private_paths import check_path, private_directory

pytestmark = pytest.mark.unit
windows = pytest.mark.skipif(os.name != "nt", reason="Windows owned sink processes")


def test_private_event_registry_drops_untrusted_fields_before_serialization():
    secret = "SECRET_MEDICAL_PASSWORD\nC:/sensitive-path"
    payload = safe_event("stage_finished", component="runtime", job_id=str(uuid.uuid4()), page=21, total=39,
                         duration_ms=123.4, exit_code=-1, code="timeout", cleanup_outcome="confirmed",
                         prompt=secret, error=secret, engine=secret, patient_id=secret, request_id=secret,
                         stage_attempt_id=secret, count=True, rss_bytes=float("nan"), samples=10**1000)
    event = json.loads(payload)
    assert secret not in payload.decode()
    assert "prompt" not in event and "engine" not in event and "request_id" not in event
    assert "count" not in event and "rss_bytes" not in event and "samples" not in event
    assert event["page"] == 21 and event["total"] == 39
    assert event["code"] == "timeout" and event["cleanup_outcome"] == "confirmed"
    assert len(payload) + 1 <= 4096
    assert safe_event(secret) is None
    assert safe_event("done", max_bytes=10) is None
    assert "\x1b" not in terminal_line(payload)
    assert "page=21" in terminal_line(payload)


def test_unknown_measurement_is_null_not_zero():
    event = json.loads(safe_event("stage_finished", vram_used_bytes=None))
    assert event["vram_used_bytes"] is None


def test_unstarted_health_reports_unavailable_not_success(settings):
    health = Diagnostics(settings).health()
    assert set(health) == {"file", "terminal"}
    assert all(not sink["available"] and sink["last_write_ms"] is None for sink in health.values())


def test_narrow_address_and_ua_fields_drop_untrusted_content():
    event = json.loads(safe_event("model_endpoint_not_found", host="::1%PRIVATE_SENTINEL", port=65536,
                                 ua_fingerprint="PRIVATE_SENTINEL", ua_family="PRIVATE_SENTINEL", route="/PRIVATE_SENTINEL"))
    assert "PRIVATE_SENTINEL" not in json.dumps(event)
    assert not {"host", "port", "ua_fingerprint", "ua_family", "route"} & event.keys()


@windows
@pytest.mark.integration
def test_owned_child_progress_reaches_both_sinks_with_actual_engine_and_global_page(settings, capfd):
    from smriti.runtime import run_stage

    job_id = uuid.uuid4().hex
    with Diagnostics(settings) as diagnostics:
        def received(message):
            fields = dict(message)
            fields.pop("event")
            diagnostics.emit(fields.pop("progress_event"), **fields)
        result = run_stage("tests.runtime_targets:progress", {"job_id": job_id}, timeout_seconds=15,
                           cpu_only=True, on_event=received)
        assert result.success
        wait_written(diagnostics)
    contents = (settings.log_dir / "smriti.jsonl").read_text()
    event = json.loads(contents.splitlines()[0])
    assert event["job_id"] == job_id and event["page"] == 21 and event["total"] == 39
    assert event["engine"] == "vlm:qwen3-vl-4b@q4_k_m+cuda"
    assert "page=21" in "".join(capfd.readouterr())


def test_jsonl_rotation_bounds_and_unrelated_file_preservation(settings):
    settings = replace(settings, log_file_bytes=4096, log_backups=2)
    private_directory(settings.log_dir)
    unrelated = settings.log_dir / "keep.txt"
    unrelated.write_text("keep")
    writer = JsonlWriter(settings)
    for page in range(100):
        writer.write(safe_event("page_read", page=page, total=100))
    assert unrelated.read_text() == "keep"
    paths = list(settings.log_dir.glob("smriti.jsonl*"))
    assert len(paths) == 3 and all(path.stat().st_size <= 4096 for path in paths)
    events = [json.loads(line) for path in reversed(writer.paths()) for line in path.read_bytes().splitlines()]
    assert events[-1]["page"] == 99


def test_retention_runs_at_startup_and_preserves_unowned_names(settings):
    private_directory(settings.log_dir)
    owned = settings.log_dir / "smriti.jsonl.1"
    owned.write_bytes(safe_event("done") + b"\n")
    past = time.time() - 8 * 86400
    os.utime(owned, (past, past))
    unrelated = settings.log_dir / "smriti.jsonl.not-ours"
    unrelated.write_bytes(b"keep")
    JsonlWriter(settings)
    assert not owned.exists() and unrelated.read_bytes() == b"keep"


def test_unrelated_active_file_is_not_deleted_or_overwritten(settings):
    private_directory(settings.log_dir)
    path = settings.log_dir / "smriti.jsonl"
    path.write_bytes(b"PRIVATE_USER_WORK")
    with pytest.raises(ValueError):
        JsonlWriter(settings)
    assert path.read_bytes() == b"PRIVATE_USER_WORK"


def test_private_paths_reject_hard_links(tmp_path):
    source = tmp_path / "keep"
    source.write_text("keep")
    linked = tmp_path / "linked"
    os.link(source, linked)
    with pytest.raises(ValueError, match="multiple links"):
        check_path(linked)
    assert source.read_text() == "keep"


@windows
def test_private_directory_has_protected_user_and_system_acl(tmp_path):
    path = tmp_path / "private"
    private_directory(path)
    quoted = str(path).replace("'", "''")
    result = subprocess.run(["powershell", "-NoProfile", "-Command",
                             f"$a=Get-Acl -LiteralPath '{quoted}'; "
                             "[pscustomobject]@{protected=$a.AreAccessRulesProtected;rules=@($a.Access).Count}|ConvertTo-Json"],
                            capture_output=True, check=True, timeout=10)
    acl = json.loads(result.stdout)
    assert acl["protected"] and acl["rules"] == 2


@windows
def test_private_directory_rejects_junction_escape(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    junction = tmp_path / "junction"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(target)],
                   capture_output=True, check=True, timeout=10)
    try:
        with pytest.raises(ValueError, match="reparse"):
            private_directory(junction / "logs")
        assert not (target / "logs").exists()
    finally:
        junction.rmdir()


def wait_written(diagnostics, count=1, timeout=10):
    deadline = time.monotonic() + timeout
    while diagnostics.health()["file"]["written"] < count:
        assert time.monotonic() < deadline, diagnostics.health()
        time.sleep(0.02)


@windows
def test_real_writers_are_exclusive_idempotent_and_private(settings):
    with Diagnostics(settings) as diagnostics:
        diagnostics.start()
        assert len(diagnostics.sinks) == 2
        assert diagnostics.emit("done", job_id=str(uuid.uuid4()), prompt="PRIVATE_SENTINEL")
        wait_written(diagnostics)
        with pytest.raises(OSError):
            Diagnostics(settings).start()
    assert all(sink["process"].exitcode is not None for sink in diagnostics.sinks.values())
    assert diagnostics.lock is None
    assert "PRIVATE_SENTINEL" not in (settings.log_dir / "smriti.jsonl").read_text()
    diagnostics.close()
    assert not diagnostics.emit("done")
    with Diagnostics(settings) as again:
        again.emit("done")
        wait_written(again)


@windows
def test_dead_file_sink_does_not_stop_terminal_or_processing(settings):
    with Diagnostics(settings) as diagnostics:
        process = diagnostics.sinks["file"]["process"]
        process.terminate()
        process.join(timeout=5)
        diagnostics.emit("stage_finished", code="timeout", cleanup_outcome="confirmed")
        deadline = time.monotonic() + 10
        while diagnostics.health()["terminal"]["written"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert diagnostics.health()["file"]["dropped"]["info"] >= 1


@windows
def test_failed_file_write_has_independent_health_and_no_payload_dump(settings):
    private_directory(settings.log_dir)
    (settings.log_dir / "smriti.jsonl").mkdir()
    with Diagnostics(settings) as diagnostics:
        diagnostics.emit("done", error="PRIVATE_SENTINEL")
        deadline = time.monotonic() + 10
        while diagnostics.health()["file"]["failures"] < 1:
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert diagnostics.health()["file"]["last_write_ms"] is None
        assert diagnostics.health()["file"]["written"] == 0


def test_disk_full_is_counted_without_fallback_output(monkeypatch, settings, capfd):
    import errno
    import queue
    from smriti import observability

    private_directory(settings.log_dir)
    messages = queue.Queue()
    messages.put(safe_event("done", secret="PRIVATE_SENTINEL"))
    messages.put(None)
    metrics = [0] * 4

    class Connection:
        def recv_bytes(self, _):
            return b"go"

        def close(self):
            pass

    def full(*_):
        raise OSError(errno.ENOSPC, "PRIVATE_SENTINEL")

    monkeypatch.setattr(observability, "_silence_runtime_output", lambda: None)
    monkeypatch.setattr(JsonlWriter, "write", full)
    observability._sink_entry(Connection(), messages, metrics, settings, False)
    assert metrics[1] == 0 and metrics[2] == 1 and metrics[3] == 0
    assert "PRIVATE_SENTINEL" not in "".join(capfd.readouterr())


@windows
@pytest.mark.integration
def test_abrupt_controller_exit_reaps_both_sink_processes(tmp_path):
    from tests.test_runtime_stages import _identities_gone, _wait_marker

    marker = tmp_path / "identities.json"
    controller = subprocess.Popen([sys.executable, "-c",
        "from tests.observability_targets import abrupt_controller; import sys; abrupt_controller(sys.argv[1],sys.argv[2])",
        str(tmp_path / "logs"), str(marker)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_marker(marker)
        controller.terminate()
        controller.wait(timeout=5)
        _identities_gone(marker)
    finally:
        if controller.poll() is None:
            controller.kill()
            controller.wait(timeout=5)


@windows
@pytest.mark.integration
def test_real_blocked_terminal_cannot_stall_file_or_shutdown(tmp_path):
    marker = tmp_path / "evidence.json"
    process = subprocess.Popen([sys.executable, "-c",
        "from tests.observability_targets import blocked_terminal; import sys; blocked_terminal(sys.argv[1],sys.argv[2])",
        str(tmp_path / "logs"), str(marker)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Deliberately never drain stdout: the terminal writer fills the real OS pipe.
        process.wait(timeout=25)
        assert process.returncode == 0
        evidence = json.loads(marker.read_text())
        assert evidence["file_written"] >= 100
        assert evidence["terminal_dropped"] > 0
        assert evidence["emit_seconds"] < 5
        assert evidence["close_seconds"] < 2.5
        assert evidence["all_exited"] and evidence["lock_released"]
        assert evidence["file_written"] > evidence["terminal_written"]
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()


def test_blocked_terminal_target_closes_owned_sinks_on_readiness_failure(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from tests import observability_targets

    diagnostics = Mock()
    diagnostics.start.return_value = diagnostics
    diagnostics.health.return_value = {"file": {"available": False}}
    monkeypatch.setattr(observability_targets, "Diagnostics", Mock(return_value=diagnostics))
    monkeypatch.setattr(observability_targets.time, "monotonic", Mock(side_effect=[0, 11, 12, 13]))
    with pytest.raises(AssertionError, match="did not start"):
        observability_targets.blocked_terminal(str(tmp_path / "logs"), str(tmp_path / "evidence.json"))
    diagnostics.close.assert_called_once()

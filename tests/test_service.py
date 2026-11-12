import threading
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti import service
from smriti.coordinator import Coordinator, CoordinatorStopped
from smriti.runtime import StageResult
from tests.test_preparation import inline_supervisor, submit
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


class Diagnostics:
    def __init__(self):
        self.events = []

    def emit(self, event, **fields):
        self.events.append((event, fields))


def test_confirmed_pause_leaves_running_work_resumable(spool_db, settings):
    job = submit(spool_db, settings)
    stop = threading.Event()
    def stopped(target, context, **options):
        stop.set()
        return StageResult("cancelled", True, -1, 0)
    with Coordinator(spool_db, settings, stop=stop, supervisor=stopped) as controller:
        with pytest.raises(CoordinatorStopped):
            controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM submissions")).scalar_one() == "preparing"
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs WHERE id = :job"), {"job": job}).scalar_one() == "done"


def test_idle_service_owns_lock_and_confirms_shutdown(spool_db, settings):
    settings = replace(settings, worker_enabled=True)
    diagnostics = Diagnostics()
    worker = service.Service(spool_db, settings, diagnostics).start()
    try:
        assert worker.accepting
        second = service.Service(spool_db, settings, diagnostics).start()
        assert not second.accepting
        assert second.pause()
    finally:
        assert worker.pause()
    assert not worker.thread.is_alive()
    with Coordinator(spool_db, settings):
        pass


def test_unconfirmed_shutdown_keeps_admission_closed(spool_db, settings):
    worker = service.Service(spool_db, settings, Diagnostics())
    class Stuck:
        def join(self, timeout):
            assert timeout <= 28

        def is_alive(self):
            return True
    worker.thread = Stuck()
    assert not worker.pause() and not worker.accepting


def test_transient_worker_error_validates_before_reopening_and_diagnostic_failure_is_safe(spool_db, settings):
    from unittest.mock import MagicMock, Mock

    diagnostics = Diagnostics()
    worker = service.Service(spool_db, settings, diagnostics)
    worker.accepting = True
    calls, waits = [], []
    worker.stop_event.wait = lambda delay: waits.append(delay) or worker.stop_event.is_set()
    def process():
        calls.append("process")
        if len(calls) == 1:
            raise RuntimeError("PRIVATE")
        assert worker.accepting
        worker.stop_event.set()
        return True
    def recover():
        assert not worker.accepting
        assert not any(event == "worker_recovered" for event, _ in diagnostics.events)
        calls.append("recover")
    controller = MagicMock(process_batch=Mock(side_effect=process), recover=Mock(side_effect=recover))
    worker._loop(controller)
    assert calls == ["process", "recover", "process"] and waits == [1]
    assert [event for event, _ in diagnostics.events] == ["worker_retrying", "worker_recovered"]
    assert not worker.accepting
    controller.__exit__.assert_called_once()
    diagnostics.emit = Mock(side_effect=RuntimeError("PRIVATE diagnostic sink"))
    worker._emit("worker_failed")


@pytest.mark.parametrize("recovery_fails", [False, True])
def test_worker_stops_after_ten_consecutive_failures_with_bounded_backoff(spool_db, settings, recovery_fails):
    from unittest.mock import MagicMock

    diagnostics = Diagnostics()
    worker = service.Service(spool_db, settings, diagnostics)
    waits = []
    worker.stop_event.wait = lambda delay: waits.append(delay) or False
    controller = MagicMock()
    controller.process_batch.side_effect = RuntimeError("PRIVATE")
    if recovery_fails:
        controller.recover.side_effect = RuntimeError("PRIVATE")
    worker._loop(controller)
    assert waits == [1, 2, 4, 8, 16, 30, 30, 30, 30]
    assert diagnostics.events[-1] == ("worker_failed", {"component": "service", "code": "controller_error", "attempt": 10})
    assert controller.process_batch.call_count == (1 if recovery_fails else 10)
    assert controller.recover.call_count == 9 and not worker.accepting
    if recovery_fails:
        assert not any(event == "worker_recovered" for event, _ in diagnostics.events)
    controller.__exit__.assert_called_once()


def test_cleanup_fence_stops_immediately_without_retry(spool_db, settings):
    from unittest.mock import MagicMock
    from smriti.coordinator import CleanupBlocked

    worker = service.Service(spool_db, settings, Diagnostics())
    controller = MagicMock()
    controller.process_batch.side_effect = CleanupBlocked("Unconfirmed owned cleanup")
    worker._loop(controller)
    controller.recover.assert_not_called()
    assert not worker.accepting and worker.diagnostics.events[-1][0] == "worker_failed"


def test_pause_during_recovery_never_reopens_admission(spool_db, settings):
    from unittest.mock import MagicMock

    worker = service.Service(spool_db, settings, Diagnostics())
    controller = MagicMock()
    controller.process_batch.side_effect = RuntimeError("PRIVATE")
    worker.stop_event.wait = lambda delay: False
    controller.recover.side_effect = worker.stop_event.set
    worker._loop(controller)
    assert not worker.accepting
    assert not any(event == "worker_recovered" for event, _ in worker.diagnostics.events)
    assert controller.process_batch.call_count == 1


def test_recovery_rejects_corruption_before_announcing_recovered(spool_db, settings):
    from smriti.coordinator import CleanupBlocked, StageInterrupted
    from smriti.processing_store import artifact_path

    job = submit(spool_db, settings)
    def interrupt(target, context, **options):
        result = inline_supervisor(target, context, **options)
        if target.endswith("ocr_target"):
            raise RuntimeError("PRIVATE interruption")
        return result
    diagnostics = Diagnostics()
    with Coordinator(spool_db, settings, supervisor=interrupt, recover_tree=lambda *args: True, diagnostics=diagnostics) as controller:
        with pytest.raises(StageInterrupted):
            controller.process_batch()
        artifact_path(settings, job, "ocr", 1).write_bytes(b"CORRUPT")
        with pytest.raises(CleanupBlocked, match="artifacts"):
            controller.recover()
    assert not any(event == "recovered" for event, _ in diagnostics.events)


def test_pause_interrupts_artifact_revalidation_before_recovered(monkeypatch, spool_db, settings):
    from smriti import coordinator
    from smriti.coordinator import StageInterrupted

    submit(spool_db, settings, 2)
    def interrupt(target, context, **options):
        result = inline_supervisor(target, context, **options)
        if target.endswith("ocr_target"):
            raise RuntimeError("PRIVATE interruption")
        return result
    diagnostics = Diagnostics()
    with Coordinator(spool_db, settings, supervisor=interrupt, recover_tree=lambda *args: True, diagnostics=diagnostics) as controller:
        with pytest.raises(StageInterrupted):
            controller.process_batch()
        original = coordinator.validate_source
        checked = []
        def pause(*args):
            checked.append(args[-1])
            controller.stop.set()
            return original(*args)
        monkeypatch.setattr(coordinator, "validate_source", pause)
        with pytest.raises(CoordinatorStopped):
            controller.recover()
    assert checked == [1]
    assert not any(event == "recovered" for event, _ in diagnostics.events)

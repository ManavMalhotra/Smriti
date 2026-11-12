"""One local coordinator lifetime; pause confirms exit before erasure or engine disposal."""

import threading

from smriti.coordinator import CleanupBlocked, Coordinator, CoordinatorStopped, StageInterrupted

MAX_WORKER_FAILURES = 10


class Service:
    def __init__(self, engine, settings, diagnostics):
        self.engine, self.settings, self.diagnostics = engine, settings, diagnostics
        self.guard = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.accepting = False

    def _emit(self, event, **fields):
        try:
            self.diagnostics.emit(event, component="service", **fields)
        except Exception:
            pass  # A broken diagnostic sink must not stop owned cleanup or recovery.

    def start(self):
        with self.guard:
            if self.thread is not None and self.thread.is_alive():
                return self
            if not self.settings.worker_enabled or self.settings.demo:
                self.accepting = not self.settings.demo
                return self
            self.stop_event = threading.Event()
            controller = Coordinator(self.engine, self.settings, stop=self.stop_event, diagnostics=self.diagnostics)
            try:
                controller.__enter__()
                controller._load_or_freeze()
                controller._recover_intake()
            except Exception:
                if controller.held:
                    controller.__exit__(None, None, None)
                self.accepting = False
                self._emit("worker_failed", code="controller_error")
                return self
            self.accepting = True
            self.thread = threading.Thread(target=self._loop, args=(controller,), name="smriti-coordinator", daemon=True)
            self.thread.start()
            return self

    def _loop(self, controller):
        failures = 0
        recovering = False
        try:
            while not self.stop_event.is_set():
                try:
                    if recovering:
                        controller.recover()
                        with self.guard:
                            if self.stop_event.is_set():
                                break
                            self.accepting = True
                        self._emit("worker_recovered", attempt=failures)
                        recovering = False
                    if not controller.process_batch():
                        self.stop_event.wait(self.settings.worker_poll_seconds)
                    failures = 0
                except CoordinatorStopped:
                    break
                except Exception as exc:
                    with self.guard:
                        self.accepting = False
                    failures += 1
                    if (isinstance(exc, CleanupBlocked) and not isinstance(exc, StageInterrupted)
                            or failures >= MAX_WORKER_FAILURES):
                        self._emit("worker_failed", code="controller_error", attempt=failures)
                        break
                    delay = min(2 ** (failures - 1), 30)
                    self._emit("worker_retrying", code="controller_error", attempt=failures, duration_ms=delay * 1000)
                    if self.stop_event.wait(delay):
                        break
                    recovering = True
        finally:
            with self.guard:
                self.accepting = False
            controller.__exit__(None, None, None)

    def pause(self):
        with self.guard:
            self.accepting = False
            self.stop_event.set()
            thread = self.thread
        if thread is not None:
            # Join outside the guard so recovery can observe pause without deadlocking.
            thread.join(timeout=4 * self.settings.cleanup_wait_seconds + self.settings.gpu_query_timeout_seconds + 5)
            return not thread.is_alive()
        return True

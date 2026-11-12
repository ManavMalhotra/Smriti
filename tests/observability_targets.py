"""Synthetic sink pressure, isolated from application startup and medical data."""

import json
import time
import uuid
from pathlib import Path

from smriti.config import Settings
from smriti.observability import Diagnostics


def abrupt_controller(log_dir, marker):
    import psutil

    diagnostics = Diagnostics(Settings(log_dir=Path(log_dir), worker_enabled=False)).start()
    identities = {}
    for name, sink in diagnostics.sinks.items():
        process = psutil.Process(sink["process"].pid)
        identities[name] = [process.pid, process.create_time()]
    Path(marker).write_text(json.dumps(identities))
    time.sleep(60)


def blocked_terminal(log_dir, marker):
    settings = Settings(log_dir=Path(log_dir), log_queue_events=32, worker_enabled=False)
    diagnostics = Diagnostics(settings).start()
    try:
        deadline = time.monotonic() + 10
        while not all(s["available"] for s in diagnostics.health().values()):
            if time.monotonic() >= deadline:
                raise AssertionError("Synthetic sinks did not start")
            time.sleep(0.02)
        emit_seconds = 0
        for page in range(10_000):
            started = time.monotonic()
            diagnostics.emit("page_read", job_id=str(uuid.uuid4()), page=page, total=10_000)
            emit_seconds += time.monotonic() - started
            if page % 50 == 0:
                time.sleep(0.005)
        deadline = time.monotonic() + 10
        while diagnostics.health()["file"]["written"] < 100:
            if time.monotonic() >= deadline:
                raise AssertionError("Synthetic file sink did not write")
            time.sleep(0.02)
        health = diagnostics.health()
    finally:
        # Failed pressure assertions must not hang interpreter exit joining blocked children.
        started = time.monotonic()
        diagnostics.close()
        close_seconds = time.monotonic() - started
    Path(marker).write_text(json.dumps({
        "file_written": health["file"]["written"], "terminal_written": health["terminal"]["written"],
        "terminal_dropped": sum(health["terminal"]["dropped"].values()),
        "emit_seconds": emit_seconds, "close_seconds": close_seconds,
        "all_exited": all(s["process"].exitcode is not None for s in diagnostics.sinks.values()),
        "lock_released": diagnostics.lock is None,
    }))

"""Importable synthetic spawn targets; no application creation, models or user data."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def simple(context, report):
    if "marker" in context:
        Path(context["marker"]).write_text("executed", encoding="utf-8")
    report("ready")
    report("page_started", page=21)
    report("page_finished", page=21, count=4)


def progress(context, report):
    report("progress", progress_event="page_read", job_id=context["job_id"], page=21,
           total=39, sequence=1, engine="vlm:qwen3-vl-4b@q4_k_m+cuda", stage="qwen")


def cpu_check(context, report):
    Path(context["marker"]).write_text(json.dumps({
        "cpu_only": os.environ.get("CUDA_VISIBLE_DEVICES") == "",
        "runtime_loaded": any(name in sys.modules for name in ("torch", "paddle", "onnxruntime")),
    }), encoding="utf-8")
    simple({}, report)


def error(context, report):
    print(context["sentinel"])
    print(context["sentinel"], file=sys.stderr)
    raise RuntimeError(context["sentinel"])


def owned_error(context, report):
    error = RuntimeError("PRIVATE_FAILURE_CONTENT")
    error.code = "capacity_exhausted"
    error.job_id = context["job_id"]
    raise error


def native_hang(context, report):
    report("page_started", page=21)
    if "marker" in context:
        Path(context["marker"]).write_text("executed", encoding="utf-8")
    ctypes.WinDLL("kernel32").Sleep(60_000)


def allocate(context, report):
    report("ready")
    buffer = bytearray(context["bytes"])
    assert len(buffer) == context["bytes"]


def exit_120_after_ok(context, report):
    # Reproduces CPython's finalization-failure exit status after the ok message.
    import atexit
    atexit.register(os._exit, 120)


def burst(context, report):
    for page in range(1, context["pages"] + 1):
        report("checkpoint", page=page, count=1)


def bad_report(context, report):
    report("checkpoint", page=1, secret=context["sentinel"])


def process_tree(context, report):
    child_code = (
        "import json,os,pathlib,subprocess,sys,time; import psutil; "
        "leaf=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "p=psutil.Process(); q=psutil.Process(leaf.pid); "
        "pathlib.Path(sys.argv[1]).write_text(json.dumps({'root':[int(sys.argv[2]),float(sys.argv[3])],"
        "'child':[p.pid,p.create_time()],'leaf':[q.pid,q.create_time()]})); time.sleep(60)"
    )
    import psutil
    process = psutil.Process()
    subprocess.Popen([sys.executable, "-c", child_code, context["marker"],
                      str(process.pid), str(process.create_time())],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 8
    while not Path(context["marker"]).is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Synthetic child did not start")
        time.sleep(0.02)
    report("ready")
    if context["mode"] == "crash":
        os._exit(7)
    if context["mode"] == "hang":
        ctypes.WinDLL("kernel32").Sleep(60_000)


def controller(marker):
    from smriti.runtime import run_stage
    run_stage("tests.runtime_targets:process_tree", {"marker": marker, "mode": "hang"},
              timeout_seconds=60, cleanup_wait_seconds=1)


def try_lock(db_path, marker):
    from smriti.runtime import CoordinatorLock
    try:
        with CoordinatorLock(Path(db_path)):
            result = "acquired"
    except OSError:
        result = "busy"
    Path(marker).write_text(result, encoding="utf-8")

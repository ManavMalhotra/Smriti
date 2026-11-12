"""Windows-owned stage trees. Targets import only after Job Object assignment."""

from __future__ import annotations

import ctypes
import importlib
import json
import logging
import math
import multiprocessing
import os
import re
import stat
import time
import uuid
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

import psutil

MAX_CONTEXT_BYTES = 64 * 1024
MAX_MESSAGE_BYTES = 4096
MAX_STAGE_EVENTS = 64
# shortcut: at most 256 owned processes per stage, revisit only for a measured runtime requiring more.
MAX_STAGE_PROCESSES = 256
_TARGET = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*\Z")
_REPORT_EVENTS = {"ready", "page_started", "page_finished", "checkpoint", "progress"}
FAILURE_CODES = {"stage_exception", "memory_limit", "timeout", "io_error", "invalid_format", "password_protected",
                  "pixel_limit", "rejected_quality", "capacity_exhausted", "source_missing",
                  "prepared_artifact_invalid", "cancelled", "ocr_initialization_failed", "ocr_unavailable",
                  "qwen_unavailable", "qwen_port_busy", "qwen_session_inactive", "qwen_request_failed", "qwen_empty", "cleanup_failed",
                  "qwen_http_error", "qwen_connection_failed", "qwen_server_exited", "qwen_transfer_failed",
                  "qwen_response_invalid", "qwen_output_invalid"}
QWEN_OPERATIONAL_FAILURES = {code for code in FAILURE_CODES if code.startswith("qwen_")} | {
    "timeout", "memory_limit", "stage_exception", "crash",
}


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t), ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "reads", "writes", "other", "read_bytes", "write_bytes", "other_bytes",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits), ("io", _IoCounters),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("user_time", ctypes.c_int64), ("kernel_time", ctypes.c_int64),
        ("period_user_time", ctypes.c_int64), ("period_kernel_time", ctypes.c_int64),
        ("page_faults", wintypes.DWORD), ("total_processes", wintypes.DWORD),
        ("active_processes", wintypes.DWORD), ("terminated_processes", wintypes.DWORD),
    ]


class _ProcessIds(ctypes.Structure):
    _fields_ = [
        ("assigned", wintypes.DWORD), ("count", wintypes.DWORD),
        ("ids", ctypes.c_size_t * MAX_STAGE_PROCESSES),
    ]


def _kernel32():
    if os.name != "nt":
        raise OSError("Windows Job Objects are required for stage execution")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
        "OpenJobObjectW": ([wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
        "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
        "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
        "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        "IsProcessInJob": ([wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
        "TerminateProcess": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "SetStdHandle": ([wintypes.DWORD, wintypes.HANDLE], wintypes.BOOL),
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes = args
        function.restype = result
    return api


def _checked(value):
    if not value:
        raise ctypes.WinError(ctypes.get_last_error())
    return value


class WindowsJob:
    """Only this process holds the non-inheritable kill-on-close handle."""

    def __init__(self, memory_limit_bytes: int | None = None, *, name: str | None = None):
        if memory_limit_bytes is not None and (type(memory_limit_bytes) is not int or memory_limit_bytes < 1):
            raise ValueError("Stage memory limit must be a positive integer")
        if name is not None and (not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{32}", name)):
            raise ValueError("Invalid owned job name")
        self.api = _kernel32()
        self.handle = _checked(self.api.CreateJobObjectW(None, f"Local\\SmritiStage-{name}" if name else None))
        if name is not None and ctypes.get_last_error() == 183:
            self.close()
            raise OSError("Owned stage name already exists")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000 | 0x8  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
        limits.basic.active_process_limit = MAX_STAGE_PROCESSES
        if memory_limit_bytes is not None:
            limits.basic.flags |= 0x200  # JOB_MEMORY, includes native allocations and descendants.
            limits.job_memory = memory_limit_bytes
        try:
            _checked(self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    def assign(self, pid: int) -> None:
        handle = _checked(self.api.OpenProcess(0x100 | 0x1 | 0x1000, False, pid))
        try:
            _checked(self.api.AssignProcessToJobObject(self.handle, handle))
        finally:
            self.api.CloseHandle(handle)

    def active_count(self) -> int:
        accounting = _Accounting()
        _checked(self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None))
        return accounting.active_processes

    def process_ids(self) -> tuple[int, ...]:
        ids = _ProcessIds()
        _checked(self.api.QueryInformationJobObject(self.handle, 3, ctypes.byref(ids), ctypes.sizeof(ids), None))
        if ids.count > MAX_STAGE_PROCESSES or ids.assigned > MAX_STAGE_PROCESSES:
            raise RuntimeError("Owned process count exceeds the stage boundary")
        return tuple(ids.ids[:ids.count])

    def process_memory(self, pid: int):
        handle = _checked(self.api.OpenProcess(0x1000, False, pid))
        try:
            owned = wintypes.BOOL()
            _checked(self.api.IsProcessInJob(handle, self.handle, ctypes.byref(owned)))
            if not owned.value:
                raise OSError("Measurement process is no longer owned")
            # Holding the handle prevents Windows from recycling this process identity during the read.
            return psutil.Process(pid).memory_info()
        finally:
            self.api.CloseHandle(handle)

    def terminate_members(self) -> None:
        processes = []
        for pid in self.process_ids():
            try:
                process = psutil.Process(pid)
                processes.append((len(process.parents()), pid))
            except psutil.Error:
                continue
        for _, pid in sorted(processes, reverse=True):
            handle = self.api.OpenProcess(0x1 | 0x1000, False, pid)
            if not handle:
                continue
            try:
                owned = wintypes.BOOL()
                # Membership is checked on the open handle, never on a potentially reused PID.
                _checked(self.api.IsProcessInJob(handle, self.handle, ctypes.byref(owned)))
                if owned.value:
                    _checked(self.api.TerminateProcess(handle, 1))
            finally:
                self.api.CloseHandle(handle)

    def terminate(self) -> None:
        _checked(self.api.TerminateJobObject(self.handle, 1))

    def close(self) -> None:
        if self.handle is not None:
            handle, self.handle = self.handle, None
            _checked(self.api.CloseHandle(handle))


class CoordinatorLock:
    """Nonblocking OS lock beside the database; existing files are never deleted."""

    def __init__(self, db_path: Path):
        self.path = Path(db_path).with_suffix(".coordinator.lock")
        self.fd: int | None = None

    def __enter__(self):
        if self.fd is not None:
            raise RuntimeError("Coordinator lock is already held")
        for path in (self.path, *self.path.parents):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Coordinator lock path must not contain reparse points")
        if os.name == "nt":
            import msvcrt
            api = _kernel32()
            handle = api.CreateFileW(str(self.path.absolute()),
                                     0x80000000 | 0x40000000, 0x1 | 0x2, None, 4, 0x00200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self.fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
            except BaseException:
                api.CloseHandle(handle)
                raise
        else:
            self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.set_inheritable(self.fd, False)
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Coordinator lock must be a regular non-reparse file")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _validate_message(message: dict) -> None:
    if isinstance(message, dict) and message.get("event") == "progress":
        from smriti.observability import safe_event

        fields = {key: value for key, value in message.items() if key not in {"event", "progress_event"}}
        payload = safe_event(message.get("progress_event"), **fields)
        if payload is None or not isinstance(fields.get("job_id"), str):
            raise ValueError("Invalid progress message")
        clean = json.loads(payload)
        if any(key not in clean or clean[key] != value for key, value in fields.items()):
            raise ValueError("Unsafe progress message")
        return
    if not isinstance(message, dict) or set(message) - {"event", "page", "count", "code", "job_id"}:
        raise ValueError("Invalid stage message")
    event = message.get("event")
    if not isinstance(event, str) or event not in _REPORT_EVENTS | {"ok", "failed"}:
        raise ValueError("Unknown stage event")
    for key in ("page", "count"):
        if key in message and (type(message[key]) is not int or not 0 <= message[key] <= 2**63 - 1):
            raise ValueError("Invalid stage count")
    if (event in {"page_started", "page_finished"} or "page" in message) and message.get("page", 0) < 1:
        raise ValueError("Stage page must be positive")
    if event == "failed":
        if not isinstance(message.get("code"), str) or message["code"] not in FAILURE_CODES:
            raise ValueError("Unknown stage failure")
        if "job_id" in message and (not isinstance(message["job_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", message["job_id"])):
            raise ValueError("Invalid failure owner")
    elif "code" in message:
        raise ValueError("Failure code requires a failed stage")
    if event != "failed" and "job_id" in message:
        raise ValueError("Failure owner requires a failed stage")
    if event in {"ok", "failed"} and ("page" in message or "count" in message):
        raise ValueError("Terminal messages cannot contain stage counts")


def _send_message(connection, message: dict) -> None:
    _validate_message(message)
    payload = json.dumps(message, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Stage message exceeds its byte boundary")
    connection.send_bytes(payload)


def _silence_runtime_output() -> None:
    with open(os.devnull, "w") as sink:
        for fd in (1, 2):
            os.dup2(sink.fileno(), fd)
    if os.name == "nt":
        import msvcrt
        api = _kernel32()
        for constant, fd in ((-11, 1), (-12, 2)):
            _checked(api.SetStdHandle(constant & 0xFFFFFFFF, msvcrt.get_osfhandle(fd)))
    logging.disable(logging.CRITICAL)


def _stage_entry(connection, target: str, context_bytes: bytes, cpu_only: bool) -> None:
    try:
        _silence_runtime_output()
        # No target import, runtime or descendant is allowed before the controller grants execution.
        if connection.recv_bytes(2) != b"go":
            return
        if cpu_only:
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
        module, name = target.split(":")
        task = getattr(importlib.import_module(module), name)

        def report(event: str, **counts):
            if event not in _REPORT_EVENTS:
                raise ValueError("Targets cannot publish a terminal stage outcome")
            _send_message(connection, {"event": event, **counts})

        task(json.loads(context_bytes), report)
        _send_message(connection, {"event": "ok"})
    except (EOFError, BrokenPipeError):
        return
    except BaseException as exc:
        known = getattr(exc, "code", None)
        code = (known if isinstance(known, str) and known in FAILURE_CODES else
                "memory_limit" if isinstance(exc, MemoryError) else
                "timeout" if isinstance(exc, TimeoutError) else
                "io_error" if isinstance(exc, OSError) else "stage_exception")
        try:
            message = {"event": "failed", "code": code}
            job_id = getattr(exc, "job_id", None)
            if isinstance(job_id, str) and re.fullmatch(r"[0-9a-f]{32}", job_id):
                message["job_id"] = job_id
            _send_message(connection, message)
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


@dataclass(frozen=True)
class StageResult:
    status: str
    cleanup_confirmed: bool
    exit_code: int | None
    duration_seconds: float
    events: tuple[dict, ...] = ()
    events_truncated: int = 0
    telemetry: dict | None = None
    job_id: str | None = None

    @property
    def success(self) -> bool:
        # ok is sent after the target returns; a later nonzero exit only means
        # interpreter finalization failed, not that durable stage work failed.
        return self.status == "ok" and self.cleanup_confirmed


def _cleanup(job: WindowsJob, wait_seconds: float) -> bool:
    try:
        deadline = time.monotonic() + wait_seconds
        while job.active_count():
            job.terminate_members()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.05, remaining))
        if not job.active_count():
            return True
    except (OSError, psutil.Error):
        pass
    try:
        job.terminate()
        deadline = time.monotonic() + wait_seconds
        while job.active_count():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.05, remaining))
        return True
    except OSError:
        return False


def recover_stage_job(name, wait_seconds=5):
    """Reopen a durable random Job Object name; never infer descendant ownership from PIDs."""
    if (not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{32}", name)
            or type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or not 0 < wait_seconds <= 5):
        return False
    api = _kernel32()
    handle = api.OpenJobObjectW(0x4 | 0x8, False, f"Local\\SmritiStage-{name}")
    if not handle:
        return ctypes.get_last_error() == 2
    job = WindowsJob.__new__(WindowsJob)
    job.api, job.handle = api, handle
    try:
        return _cleanup(job, wait_seconds)
    finally:
        job.close()


def sampler_job_name(stage_name):
    return uuid.uuid5(uuid.NAMESPACE_URL, f"smriti-stage:{stage_name}:gpu").hex if stage_name else None


def run_stage(
    target: str, context: dict, *, timeout_seconds: float,
    stop=None, cpu_only: bool = False, cleanup_wait_seconds: float = 5,
    request_timeout_seconds: float | None = None, memory_limit_bytes: int | None = None,
    telemetry_settings=None, job_name=None, on_event=None,
) -> StageResult:
    """Run a trusted importable target; private payloads never enter returned diagnostics."""
    if not isinstance(target, str) or not _TARGET.fullmatch(target) or not isinstance(context, dict):
        raise ValueError("Stage target/context is invalid")
    for value in (timeout_seconds, cleanup_wait_seconds, request_timeout_seconds):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError("Stage deadlines must be finite and positive")
    if cleanup_wait_seconds > 5:
        raise ValueError("Each cleanup wait must be at most five seconds")
    payload = json.dumps(context, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > MAX_CONTEXT_BYTES:
        raise ValueError("Stage context exceeds its byte boundary")
    started = time.monotonic()
    if stop is not None and stop.is_set():
        return StageResult("cancelled", True, None, 0)
    job = WindowsJob(memory_limit_bytes, name=job_name)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=True)
    process = ctx.Process(target=_stage_entry, args=(child, target, payload, cpu_only), name="smriti-stage")
    status = "crash"
    events = deque(maxlen=MAX_STAGE_EVENTS)
    event_count = 0
    terminal = None
    failure_job_id = None
    request_page = None
    request_deadline = None
    cleanup_confirmed = False
    assigned = False
    telemetry = None
    try:
        process.start()
        child.close()
        try:
            job.assign(process.pid)
            assigned = True
        except OSError:
            status = "assignment_failed"
        else:
            if telemetry_settings is not None:
                from smriti.runtime_telemetry import StageTelemetry
                telemetry = StageTelemetry(telemetry_settings)
                telemetry.job_name = sampler_job_name(job_name)
                telemetry.begin(job)
            parent.send_bytes(b"go")
            deadline = started + timeout_seconds
            while True:
                now = time.monotonic()
                if stop is not None and stop.is_set():
                    status = "cancelled"
                    break
                if now >= deadline or (request_deadline is not None and now >= request_deadline):
                    status = "timeout"
                    break
                if telemetry is not None:
                    telemetry.tick(job)
                try:
                    readable = parent.poll(min(0.05, deadline - now))
                except (BrokenPipeError, EOFError):
                    # Windows reports a normally closed named pipe during poll, not only recv.
                    process.join(timeout=min(0.05, max(0, deadline - time.monotonic())))
                    if process.exitcode is not None:
                        status = terminal or "crash"
                        break
                    continue
                if readable:
                    try:
                        message = json.loads(parent.recv_bytes(MAX_MESSAGE_BYTES))
                        _validate_message(message)
                    except EOFError:
                        process.join(timeout=min(0.05, max(0, deadline - time.monotonic())))
                        if process.exitcode is not None:
                            status = terminal or "crash"
                            break
                        continue
                    except (OSError, ValueError, TypeError):
                        status = "invalid_ipc"
                        break
                    event = message["event"]
                    if terminal is not None:
                        status = "invalid_ipc"
                        break
                    if event in {"ok", "failed"}:
                        terminal = "ok" if event == "ok" else message["code"]
                        failure_job_id = message.get("job_id")
                        if request_page is not None:
                            terminal = "invalid_ipc" if event == "ok" else terminal
                    else:
                        events.append(message)
                        event_count += 1
                        if on_event is not None:
                            on_event(message)
                    if event == "page_started":
                        if request_page is not None:
                            status = "invalid_ipc"
                            break
                        request_page = message["page"]
                        if request_timeout_seconds is not None:
                            request_deadline = time.monotonic() + request_timeout_seconds
                    elif event == "page_finished":
                        if request_page != message["page"]:
                            status = "invalid_ipc"
                            break
                        request_page = request_deadline = None
                elif process.exitcode is not None:
                    status = terminal or "crash"
                    break
    except BaseException:
        status = "controller_error"
        raise
    finally:
        parent.close()
        child.close()
        cleanup_deadline = time.monotonic() + 2 * cleanup_wait_seconds
        if process.pid is not None:
            if not assigned:
                # An unassigned bootstrap cannot create descendants: it has never received "go".
                if process.exitcode is None:
                    process.terminate()
                process.join(timeout=cleanup_wait_seconds)
            cleanup_confirmed = _cleanup(job, cleanup_wait_seconds)
            if not cleanup_confirmed:
                status = "cleanup_failed"
        else:
            cleanup_confirmed = True
        if telemetry is not None:
            telemetry.finish(job)
            cleanup_confirmed = cleanup_confirmed and telemetry.cleanup_confirmed
            if not cleanup_confirmed:
                status = "cleanup_failed"
        job.close()
        if process.pid is not None:
            process.join(timeout=max(0, cleanup_deadline - time.monotonic()))
            cleanup_confirmed = cleanup_confirmed and process.exitcode is not None
            if not cleanup_confirmed:
                status = "cleanup_failed"
        exit_code = process.exitcode
        if process.pid is None or exit_code is not None:
            process.close()
    return StageResult(status, cleanup_confirmed, exit_code, time.monotonic() - started,
                       tuple(events), max(0, event_count - len(events)),
                        telemetry.summary() if telemetry is not None else None, failure_job_id)

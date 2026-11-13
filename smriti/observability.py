"""Best-effort private diagnostics. A blocked sink cannot block its producer or peer."""

from __future__ import annotations

import json
import ipaddress
import logging
import math
import multiprocessing
import queue
import re
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from smriti.config import Settings
from smriti.job_progress import EVENTS
from smriti.private_paths import check_path, private_directory
from smriti.runtime import CoordinatorLock, FAILURE_CODES, WindowsJob, _silence_runtime_output

REGISTRY = {name: (level, message) for name, (_, level, message) in EVENTS.items()}
REGISTRY.update({
    "service_started": ("info", "Local service started"),
    "service_stopped": ("info", "Local service stopped"),
    "request_finished": ("info", "Request completed"),
    "request_failed": ("error", "Request failed"),
    "validation_failed": ("warning", "Malformed request"),
    "stage_started": ("info", "Supervised stage started"),
    "stage_finished": ("info", "Supervised stage exited"),
    "stage_measurement": ("info", "Observed stage memory; sampled, not an absolute peak"),
    "window_started": ("info", "Processing source range"),
    "spool_deleted": ("info", "Ephemeral source deleted"),
    "spool_debug_retained": ("warning", "Ephemeral source retained by the crash-debug opt-in"),
    "spool_cleanup_failed": ("error", "Ephemeral source deletion failed"),
    "processing_deleted": ("info", "Private processing artifacts deleted"),
    "processing_cleanup_failed": ("error", "Private processing artifact deletion failed"),
    "capacity_exhausted": ("error", "Processing capacity exhausted"),
    "logging_degraded": ("warning", "Diagnostic delivery is degraded"),
    "worker_failed": ("error", "Worker operation failed"),
    "worker_retrying": ("warning", "Worker interrupted; admission closed during recovery"),
    "worker_recovered": ("info", "Saved processing state validated; worker resumed"),
    "model_unavailable": ("warning", "Local model is unavailable"),
    "model_endpoint_not_found": ("warning", "Model endpoint requested on the application server; caller is unidentified"),
    "service_warning": ("warning", "Local service reported a warning"),
    "service_error": ("error", "Local service reported an error"),
})
_ID = re.compile(r"[0-9a-f]{32}\Z|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_VOCABULARY = {
    "component": {"http", "service", "intake", "preparation", "worker", "runtime", "logging", "ocr", "qwen"},
    "stage": {"pending_intake", "preparing", "inspection", "ocr_loading", "ocr", "classification", "extraction", "qwen_loading", "qwen", "cross_check", "cleanup", "saving", "done", "failed", "queued"},
    "engine": {"pdf-text", "rapidocr:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec@onnx+cpu", "paddle:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec", "vlm:glm-ocr-0.9b@q8_0+cuda", "vlm:qwen3-vl-4b@q4_k_m+cuda", "local_rules", "demo"},
    "method": {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"},
    "code": FAILURE_CODES | {"ok", "crash", "invalid_ipc", "assignment_failed", "controller_error", "disk_error", "unavailable"},
    "cleanup_outcome": {"confirmed", "unconfirmed", "not_required"},
    "metric": {"tree_rss_bytes", "tree_private_bytes", "system_used_bytes", "device_vram_used_bytes", "device_vram_free_bytes"},
    "coverage": {"sampled", "partial", "unavailable"},
    "reason": {"nvidia_smi_unavailable_or_timeout", "process_measurement_unavailable"},
    "ua_family": {"python-requests", "httpx", "curl", "browser", "other", "unavailable"},
    "route": {"/health", "/api/health", "/api/auth/register", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
              "/api/documents", "/api/documents/{document_id}", "/api/documents/{document_id}/consent",
              "/api/documents/{document_id}/page/{page_number}", "/api/jobs", "/api/jobs/{job_id}",
              "/api/patients/{patient_id}", "/api/patients/{patient_id}/summary", "/api/patients/{patient_id}/timeline",
              "/api/observations/{observation_id}/review", "/api/reports/{report_id}", "/v1/models", "unmatched"},
}
_NUMBERS = {"page", "total", "count", "window_start", "window_end", "window_index", "attempt", "sequence", "status", "duration_ms", "dropped", "failures", "rss_bytes", "private_bytes", "system_used_bytes", "vram_used_bytes", "vram_free_bytes", "samples", "missing", "before", "observed_peak", "after"}

_VOCABULARY["stage"].add("awaiting_cloud_consent")
_VOCABULARY["engine"].add("gemini-3.8-flash-high")
_VOCABULARY["route"].add("/api/documents/{document_id}/redaction-preview")
_VOCABULARY["route"].add("/api/jobs/{job_id}/retry")
_VOCABULARY["route"].add("/api/patients/{patient_id}/clinical-summary")
_VOCABULARY["route"].add("/api/patients/{patient_id}/clinical-summary/refresh")
_VOCABULARY["route"].add("/api/patients/{patient_id}/cloud-consent")
_VOCABULARY["route"].add("/api/system/gemini-status")


def safe_engine(value):
    if not isinstance(value, str):
        return None
    base = value.removesuffix("+local-rules:line-rules@1.0+cpu")
    return value if base in _VOCABULARY["engine"] | {"text_layer"} or re.fullmatch(r"pymupdf:[0-9]+(?:\.[0-9]+){1,3}", base) else None


def safe_event(event: str, *, max_bytes: int = 4096, **fields) -> bytes | None:
    if not isinstance(event, str) or event not in REGISTRY:
        return None
    level, message = REGISTRY[event]
    entry = {"schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
             "level": level, "event": event, "message": message}
    for key, value in fields.items():
        if key in {"request_id", "job_id", "stage_attempt_id", "batch_id"}:
            if isinstance(value, str) and _ID.fullmatch(value):
                entry[key] = value
        elif key in _VOCABULARY:
            if key == "engine" and safe_engine(value) is not None:
                entry[key] = value
            elif isinstance(value, str) and value in _VOCABULARY[key]:
                entry[key] = value
        elif key == "host" and isinstance(value, str) and (value == "localhost" or re.fullmatch(r"[0-9a-fA-F:.]{1,45}", value)):
            try:
                entry[key] = "localhost" if value == "localhost" else str(ipaddress.ip_address(value))
            except ValueError:
                pass
        elif key == "port" and type(value) is int and 1 <= value <= 65535:
            entry[key] = value
        elif key == "ua_fingerprint" and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{16}", value):
            entry[key] = value
        elif key in _NUMBERS:
            if type(value) in (int, float) and 0 <= value <= 2**63 - 1 and math.isfinite(value):
                entry[key] = value
            elif value is None:
                entry[key] = None
        elif key == "exit_code" and (value is None or type(value) is int and -(2**31) <= value <= 2**32 - 1):
            entry[key] = value
    encoded = json.dumps(entry, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return encoded if len(encoded) + 1 <= max_bytes else None


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_BLUE = "\033[94m"
ANSI_MAGENTA = "\033[95m"
ANSI_CYAN = "\033[96m"
ANSI_DIM = "\033[2m"

_LAST_HW_CHECK = 0.0
_CACHED_HW = None


def get_hardware_status() -> dict:
    global _LAST_HW_CHECK, _CACHED_HW
    now = time.monotonic()
    if _CACHED_HW is not None and (now - _LAST_HW_CHECK) < 3.0:
        return _CACHED_HW

    status = {
        "ram_total_gb": 8.0,
        "ram_free_gb": 4.0,
        "ram_used_gb": 4.0,
        "vram_total_gb": 4.0,
        "vram_free_gb": 3.9,
        "vram_used_gb": 0.1,
        "gpu_name": "NVIDIA GTX 1650",
    }
    try:
        import psutil
        m = psutil.virtual_memory()
        status["ram_total_gb"] = round(m.total / (1024**3), 1)
        status["ram_free_gb"] = round(m.available / (1024**3), 1)
        status["ram_used_gb"] = round((m.total - m.available) / (1024**3), 1)
    except Exception:
        pass

    try:
        import subprocess
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free,memory.used", "--format=csv,nounits,noheader"],
            timeout=1,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if out:
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 4:
                status["gpu_name"] = parts[0]
                status["vram_total_gb"] = round(float(parts[1]) / 1024, 1)
                status["vram_free_gb"] = round(float(parts[2]) / 1024, 1)
                status["vram_used_gb"] = round(float(parts[3]) / 1024, 1)
            elif len(parts) >= 3:
                status["vram_total_gb"] = round(float(parts[0]) / 1024, 1)
                status["vram_free_gb"] = round(float(parts[1]) / 1024, 1)
                status["vram_used_gb"] = round(float(parts[2]) / 1024, 1)
    except Exception:
        pass

    _CACHED_HW = status
    _LAST_HW_CHECK = now
    return status


def print_startup_banner(port: int = 8000) -> None:
    hw = get_hardware_status()
    ram_total = hw["ram_total_gb"]
    ram_free = hw["ram_free_gb"]
    ram_used = hw["ram_used_gb"]
    gpu_name = hw["gpu_name"]
    vram_total = hw["vram_total_gb"] or 4.0
    vram_free = hw["vram_free_gb"] or 3.9

    banner = [
        f"{ANSI_CYAN}{ANSI_BOLD}╔══════════════════════════════════════════════════════════════════╗{ANSI_RESET}",
        f"{ANSI_CYAN}{ANSI_BOLD}║                SMRITI · CLINICAL LOCAL ENGINE                   ║{ANSI_RESET}",
        f"{ANSI_CYAN}{ANSI_BOLD}╚══════════════════════════════════════════════════════════════════╝{ANSI_RESET}",
        f"  {ANSI_GREEN}● URL:{ANSI_RESET}         http://127.0.0.1:{port}/",
        f"  {ANSI_CYAN}● System RAM:{ANSI_RESET}  {ram_used:.1f} GB used / {ram_total:.1f} GB total ({ram_free:.1f} GB free)",
        f"  {ANSI_CYAN}● GPU VRAM:{ANSI_RESET}    {gpu_name}: {vram_free:.1f} GB free / {vram_total:.1f} GB total",
    ]
    if ram_free < 3.0:
        banner.append(
            f"  {ANSI_YELLOW}{ANSI_BOLD}⚠️  HIGH RAM USAGE DETECTED ({ram_used:.1f} GB used). Close Chrome/background apps now for maximum GPU/OCR speed!{ANSI_RESET}"
        )
    banner.append("")
    sys.stdout.write("\n".join(banner) + "\n")
    sys.stdout.flush()


def terminal_line(payload: bytes) -> str:
    event = json.loads(payload)
    event_name = event.get("event", "")
    level = event.get("level", "info").lower()
    ts = event.get("timestamp", "")
    time_part = ts[11:19] if len(ts) >= 19 else ts
    msg = event.get("message", "")

    # Stage metadata mapping
    stage_map = {
        "pending_intake": ("1", "Intake"),
        "preparing": ("1", "Intake/Prep"),
        "inspection": ("1", "Inspection"),
        "ocr_loading": ("2", "OCR Init"),
        "ocr": ("2", "RapidOCR"),
        "classification": ("3", "Classification"),
        "extraction": ("3", "Extraction"),
        "qwen_loading": ("4", "VLM Loading"),
        "qwen": ("4", "GLM/Qwen VLM"),
        "cross_check": ("4", "Cross-Check"),
        "saving": ("5", "Publication"),
        "done": ("5", "Complete"),
    }

    job_id = event.get("job_id")
    page = event.get("page")
    total = event.get("total")
    stage = event.get("stage")

    hw = get_hardware_status()
    ram_str = f"RAM: {hw['ram_used_gb']:.1f} GB"
    vram_str = f"GPU VRAM: {hw['vram_used_gb']:.1f}/{hw['vram_total_gb'] or 4.0:.1f} GB"

    # Color code selection
    if level == "error" or "failed" in event_name or "error" in event_name:
        color = ANSI_RED
    elif level == "warning" or "unavailable" in event_name or "skipped" in event_name:
        color = ANSI_YELLOW
    elif event_name in {"intake_accepted", "preparing", "prepared", "inspection", "window_started"}:
        color = ANSI_CYAN
    elif event_name in {"ocr_reading", "page_read", "ocr_finished", "qwen_reading", "qwen_page", "cross_check", "cross_checked", "extracting", "saving", "done", "checkpoint"}:
        color = ANSI_GREEN
    else:
        color = ANSI_RESET

    # Detailed progress bar for active jobs
    if job_id and (page or stage):
        stage_num, stage_label = stage_map.get(stage, ("?", stage or "Processing"))
        page_str = f"Page {page}/{total or '?'}" if page else f"Stage {stage_num}/5"
        pct_str = f" ({(page * 100 // total):d}%)" if page and total and total > 0 else ""
        short_job = job_id[:8]
        duration = event.get("duration_ms")
        speed_str = f" | Speed: {duration / 1000:.1f}s/page" if duration else ""
        bar = f"{color}{ANSI_BOLD}[JOB #{short_job}] [Stage {stage_num}/5: {stage_label}] {page_str}{pct_str} | {ram_str} | {vram_str}{speed_str}{ANSI_RESET} : {msg}\n"
        return bar

    context = " ".join(f"{key}={value}" for key, value in event.items()
                       if key not in {"schema_version", "timestamp", "level", "message", "event"})
    return f"{color}{time_part} {level.upper():5} [{event_name}]{ANSI_RESET} {context}: {msg}\n"


class SafeLogHandler(logging.Handler):
    """Never format arbitrary application/library/Uvicorn messages or exception data."""
    def __init__(self, diagnostics=None):
        super().__init__()
        self.diagnostics = diagnostics

    def emit(self, record):
        if self.diagnostics is not None and record.levelno >= logging.WARNING:
            self.diagnostics.emit("service_error" if record.levelno >= logging.ERROR else "service_warning", component="service")


@contextmanager
def sanitized_logging(diagnostics):
    handler = SafeLogHandler(diagnostics)
    loggers = [logging.getLogger(name) for name in (None, "uvicorn", "uvicorn.error", "uvicorn.access")]
    loggers.extend(logger for logger in logging.root.manager.loggerDict.copy().values()
                   if isinstance(logger, logging.Logger) and logger not in loggers)
    previous = [(logger, logger.handlers[:], logger.propagate, logger.level) for logger in loggers]
    for logger in loggers:
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
    try:
        yield
    finally:
        for logger, handlers, propagate, level in previous:
            logger.handlers, logger.propagate = handlers, propagate
            logger.setLevel(level)


class JsonlWriter:
    def __init__(self, settings: Settings):
        self.path = settings.log_dir / "smriti.jsonl"
        self.limit = settings.log_file_bytes
        self.backups = settings.log_backups
        self.max_age = settings.log_max_age_days * 86400
        self.maintain()

    def paths(self):
        return [self.path, *(self.path.with_name(f"smriti.jsonl.{index}") for index in range(1, self.backups + 1))]

    def maintain(self) -> None:
        paths = self.paths()
        now = time.time()
        for path in paths:
            check_path(path)
            if path.exists() and not path.is_file():
                raise ValueError("Log targets must be regular files")
            first_timestamp = None
            if path.exists() and path.stat().st_size:
                with path.open("rb") as source:
                    first = source.readline(4097)
                entry = json.loads(first)
                if not isinstance(entry, dict) or entry.get("schema_version") != 1 or entry.get("event") not in REGISTRY:
                    raise ValueError("Existing log target is not application-owned")
                first_timestamp = datetime.fromisoformat(entry["timestamp"]).timestamp()
            if path.exists() and (now - path.stat().st_mtime > self.max_age
                                  or first_timestamp is not None and now - first_timestamp > self.max_age
                                  or path.stat().st_size > self.limit):
                path.unlink()

    def write(self, payload: bytes) -> None:
        if len(payload) + 1 > self.limit:
            raise ValueError("Log record exceeds the file bound")
        self.maintain()
        paths = self.paths()
        size = self.path.stat().st_size if self.path.exists() else 0
        if size + len(payload) + 1 > self.limit:
            paths[-1].unlink(missing_ok=True)
            for index in range(len(paths) - 1, 0, -1):
                if paths[index - 1].exists():
                    paths[index - 1].replace(paths[index])
        with self.path.open("ab") as output:
            output.write(payload + b"\n")


def _sink_entry(connection, messages, metrics, settings, terminal: bool):
    try:
        if not terminal:
            _silence_runtime_output()
        if connection.recv_bytes(2) != b"go":
            return
        writer = None if terminal else JsonlWriter(settings)
        metrics[0] = 1
        while True:
            payload = messages.get()
            if payload is None:
                break
            try:
                if terminal:
                    sys.stdout.write(terminal_line(payload))
                    sys.stdout.flush()
                else:
                    writer.write(payload)
                metrics[1] += 1
                metrics[0] = 1
                metrics[3] = int(time.time() * 1000)
            except (OSError, ValueError):
                metrics[2] += 1
                metrics[0] = 2
        metrics[0] = 3
    except BaseException:
        metrics[2] += 1
        metrics[0] = 2
    finally:
        connection.close()


class Diagnostics:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.sinks = {}
        self.job = None
        self.lock = None
        self.closed = False
        self.guard = threading.Lock()
        self.last_notice = 0.0

    def start(self):
        if self.job is not None or self.closed:
            return self
        private_directory(self.settings.log_dir)
        self.lock = CoordinatorLock(self.settings.log_dir / "smriti-log-writer")
        self.lock.__enter__()
        try:
            self.job = WindowsJob()
            ctx = multiprocessing.get_context("spawn")
            for name in ("file", "terminal"):
                messages = ctx.Queue(maxsize=self.settings.log_queue_events)
                metrics = ctx.Array("q", 4, lock=False)
                parent, child = ctx.Pipe()
                process = ctx.Process(target=_sink_entry, args=(child, messages, metrics, self.settings, name == "terminal"),
                                      name=f"smriti-log-{name}")
                sink = {"process": process, "queue": messages, "metrics": metrics, "accepted": 0, "dropped": {}}
                self.sinks[name] = sink
                try:
                    process.start()
                    child.close()
                    self.job.assign(process.pid)
                    parent.send_bytes(b"go")
                finally:
                    parent.close()
                    child.close()
            return self
        except BaseException:
            self.close()
            raise

    def _deliver(self, payload, level):
        for sink in self.sinks.values():
            try:
                if not sink["process"].is_alive():
                    raise queue.Full
                sink["queue"].put_nowait(payload)
                sink["accepted"] += 1
            except (queue.Full, OSError, ValueError):
                sink["dropped"][level] = sink["dropped"].get(level, 0) + 1

    def emit(self, event: str, **fields) -> bool:
        payload = safe_event(event, max_bytes=self.settings.log_event_bytes, **fields)
        if payload is None:
            return False
        with self.guard:
            if self.closed:
                return False
            self._deliver(payload, REGISTRY[event][0])
            now = time.monotonic()
            if now - self.last_notice >= 10 and any(sum(s["dropped"].values()) + s["metrics"][2] for s in self.sinks.values()):
                self.last_notice = now
                notice = safe_event("logging_degraded", component="logging",
                                    dropped=sum(sum(s["dropped"].values()) for s in self.sinks.values()),
                                    failures=sum(s["metrics"][2] for s in self.sinks.values()))
                self._deliver(notice, "warning")
        return True

    def health(self) -> dict:
        with self.guard:
            health = {name: {"available": not self.closed and sink["metrics"][0] == 1 and sink["process"].is_alive(),
                           "written": sink["metrics"][1], "failures": sink["metrics"][2],
                           "dropped": dict(sink["dropped"]), "last_write_ms": sink["metrics"][3] or None,
                           "unconfirmed": max(0, sink["accepted"] - sink["metrics"][1] - sink["metrics"][2]),
                           "crash_loss": "unavailable"}
                    for name, sink in self.sinks.items()}
            for name in ("file", "terminal"):
                health.setdefault(name, {"available": False, "written": 0, "failures": 0, "dropped": {},
                                         "last_write_ms": None, "unconfirmed": 0, "crash_loss": "unavailable"})
            return health

    def close(self):
        with self.guard:
            if self.closed:
                return
            self.closed = True
        deadline = time.monotonic() + self.settings.log_shutdown_seconds
        flush_deadline = deadline - self.settings.log_shutdown_seconds / 4
        for sink in self.sinks.values():
            try:
                sink["queue"].put_nowait(None)
            except (queue.Full, OSError, ValueError):
                pass
        for sink in self.sinks.values():
            process = sink["process"]
            if process.pid is not None:
                process.join(timeout=max(0, flush_deadline - time.monotonic()))
                if process.is_alive():
                    process.terminate()
            sink["queue"].cancel_join_thread()
            sink["queue"].close()
        if self.job is not None:
            self.job.close()
            self.job = None
        # A killed/stalled writer keeps the exclusive lock until its exit is confirmed.
        confirmed = True
        for sink in self.sinks.values():
            process = sink["process"]
            if process.pid is not None:
                process.join(timeout=max(0, deadline - time.monotonic()))
                confirmed = confirmed and process.exitcode is not None
        if confirmed and self.lock is not None:
            self.lock.__exit__(None, None, None)
            self.lock = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()

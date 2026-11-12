"""Observed, bounded stage summaries; unavailable measurements never become zero."""

from __future__ import annotations

import math
import subprocess
import threading
import time

import psutil

from smriti.config import Settings

GPU_UNAVAILABLE = "nvidia_smi_unavailable_or_timeout"
MAX_GPU_OUTPUT_BYTES = 8192


class Measurement:
    def __init__(self):
        self.before = self.peak = self.after = None
        self.samples = self.missing = 0

    def observe(self, value, phase):
        if value is None:
            self.missing += 1
        else:
            self.samples += 1
            self.peak = value if self.peak is None else max(self.peak, value)
        if phase in ("before", "after"):
            setattr(self, phase, value)

    def summary(self, reason):
        return {"before": self.before, "observed_peak": self.peak, "after": self.after,
                "samples": self.samples, "missing": self.missing,
                "coverage": "unavailable" if not self.samples else "partial" if self.missing else "sampled",
                "reason": reason if self.missing or not self.samples else None}


def parse_gpu_output(payload: bytes) -> tuple[int, int] | None:
    if len(payload) > MAX_GPU_OUTPUT_BYTES:
        return None
    try:
        lines = payload.decode("ascii").strip().splitlines()
        if not 1 <= len(lines) <= 64:
            return None
        used = free = 0
        for line in lines:
            parts = line.split(",")
            if len(parts) != 2:
                return None
            values = [float(part.strip()) for part in parts]
            if any(not math.isfinite(value) or not 0 <= value <= 2**40 for value in values):
                return None
            used += int(values[0] * 1024**2)
            free += int(values[1] * 1024**2)
        return used, free
    except (UnicodeError, ValueError):
        return None


def gpu_query(context, report):
    # The supervisor owns both this bootstrap and nvidia-smi; a stalled read is killed tree-wide.
    process = subprocess.Popen(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                                "--format=csv,noheader,nounits"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        payload = process.stdout.read(MAX_GPU_OUTPUT_BYTES + 1)
        if len(payload) > MAX_GPU_OUTPUT_BYTES:
            return
        if process.wait() == 0:
            values = parse_gpu_output(payload)
            if values is not None:
                report("checkpoint", page=1, count=values[0])
                report("checkpoint", page=2, count=values[1])
    finally:
        process.stdout.close()


def tree_memory(job) -> tuple[int | None, int | None]:
    rss = private = 0
    try:
        for pid in job.process_ids():
            info = job.process_memory(pid)
            rss += info.rss
            if not hasattr(info, "private"):
                private = None
            elif private is not None:
                private += info.private
        return rss, private
    except (psutil.Error, OSError, RuntimeError):
        return None, None


class StageTelemetry:
    def __init__(self, settings: Settings, *, gpu_target="smriti.runtime_telemetry:gpu_query"):
        self.settings = settings
        self.gpu_target = gpu_target
        self.values = {name: Measurement() for name in ("tree_rss_bytes", "tree_private_bytes", "system_used_bytes", "device_vram_used_bytes", "device_vram_free_bytes")}
        self.stop = threading.Event()
        self.thread = None
        self.guard = threading.Lock()
        self.last_ram = self.last_gpu = float("-inf")
        self.cleanup_confirmed = True
        self.job_name = None

    def _ram(self, job, phase):
        rss, private = tree_memory(job)
        try:
            system = psutil.virtual_memory().used
        except (psutil.Error, OSError):
            system = None
        self.values["tree_rss_bytes"].observe(rss, phase)
        self.values["tree_private_bytes"].observe(private, phase)
        self.values["system_used_bytes"].observe(system, phase)
        self.last_ram = time.monotonic()

    def _gpu(self, phase):
        from smriti.runtime import run_stage

        self.last_gpu = time.monotonic()
        used = free = None
        try:
            result = run_stage(self.gpu_target, {}, timeout_seconds=self.settings.gpu_query_timeout_seconds,
                               cleanup_wait_seconds=min(1, self.settings.cleanup_wait_seconds), stop=self.stop,
                               cpu_only=True, memory_limit_bytes=128 * 1024**2, job_name=self.job_name)
            self.cleanup_confirmed = self.cleanup_confirmed and result.cleanup_confirmed
            if not result.cleanup_confirmed:
                self.stop.set()
            if result.success:
                counts = {event["page"]: event.get("count") for event in result.events if event["event"] == "checkpoint"}
                if set(counts) == {1, 2}:
                    used, free = counts[1], counts[2]
        except Exception:
            pass
        with self.guard:
            self.values["device_vram_used_bytes"].observe(used, phase)
            self.values["device_vram_free_bytes"].observe(free, phase)

    def begin(self, job):
        self._ram(job, "before")
        self._gpu("before")

        def sample_gpu():
            while not self.stop.wait(max(0, self.settings.gpu_poll_seconds - (time.monotonic() - self.last_gpu))):
                self._gpu("during")

        self.thread = threading.Thread(target=sample_gpu, name="smriti-gpu-sampler", daemon=True)
        self.thread.start()

    def tick(self, job):
        if time.monotonic() - self.last_ram >= self.settings.ram_sample_seconds:
            self._ram(job, "during")

    def finish(self, job):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=2 * min(1, self.settings.cleanup_wait_seconds) + 1)
            self.cleanup_confirmed = self.cleanup_confirmed and not self.thread.is_alive()
        self._ram(job, "after")
        remaining = max(0, self.settings.gpu_poll_seconds - (time.monotonic() - self.last_gpu))
        if self.cleanup_confirmed and remaining <= 2:
            # Post-query cannot overlap a prior query or run faster than the approved interval.
            time.sleep(remaining)
            self.stop = threading.Event()
            self._gpu("after")
            self.stop.set()
        else:
            with self.guard:
                self.values["device_vram_used_bytes"].observe(None, "after")
                self.values["device_vram_free_bytes"].observe(None, "after")

    def summary(self):
        with self.guard:
            return {"metrics": {name: value.summary(GPU_UNAVAILABLE if name.startswith("device_") else "process_measurement_unavailable")
                                for name, value in self.values.items()},
                    "sampler_cleanup_confirmed": self.cleanup_confirmed,
                    "scope": "operator_only", "peak_kind": "observed_samples_not_absolute_peak"}

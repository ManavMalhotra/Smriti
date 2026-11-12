from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import psutil
import pytest

from smriti import runtime, runtime_telemetry as telemetry

pytestmark = pytest.mark.unit
windows = pytest.mark.skipif(os.name != "nt", reason="Windows owned GPU-query supervision")


@pytest.mark.parametrize("payload", [b"", b"N/A, 1", b"nan, 1", b"inf, 1", b"-1, 2", b"1, 2, 3", b"\xff", b"1,2\n" * 65, b"x" * 8193])
def test_invalid_or_oversized_driver_output_is_unavailable(payload):
    assert telemetry.parse_gpu_output(payload) is None


def test_driver_metrics_are_device_wide_and_numeric_only():
    assert telemetry.parse_gpu_output(b"100, 200\n50, 250\n") == (150 * 1024**2, 450 * 1024**2)


def test_summary_has_constant_storage_and_truthful_missing_samples():
    metric = telemetry.Measurement()
    metric.observe(None, "before")
    for value in range(100_000):
        metric.observe(value, "during")
    metric.observe(None, "after")
    summary = metric.summary("unavailable")
    assert summary == {"before": None, "observed_peak": 99999, "after": None, "samples": 100_000,
                       "missing": 2, "coverage": "partial", "reason": "unavailable"}
    assert len(vars(metric)) == 5


def test_tree_ram_distinguishes_rss_private_and_vanishing_members():
    class Job:
        def process_ids(self):
            return (1, 2)

        def process_memory(self, pid):
            return SimpleNamespace(rss=pid * 100, private=pid * 200)

    assert telemetry.tree_memory(Job()) == (300, 600)
    job = Job()
    job.process_memory = lambda _: SimpleNamespace(rss=100)
    assert telemetry.tree_memory(job) == (200, None)
    job.process_memory = lambda _: (_ for _ in ()).throw(psutil.NoSuchProcess(1))
    assert telemetry.tree_memory(job) == (None, None)
    job.process_ids = lambda: ()
    assert telemetry.tree_memory(job) == (0, 0)  # An actually empty owned tree, not missing measurement.


def test_ram_ticks_do_not_exceed_approved_interval(monkeypatch, settings):
    clock = [0.0]
    monkeypatch.setattr(telemetry.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(telemetry, "tree_memory", lambda _: (10, 20))
    monkeypatch.setattr(telemetry.psutil, "virtual_memory", lambda: SimpleNamespace(used=30))
    sampler = telemetry.StageTelemetry(settings)
    sampler._ram(None, "before")
    clock[0] = 0.99
    sampler.tick(None)
    assert sampler.values["tree_rss_bytes"].samples == 1
    clock[0] = 1.0
    sampler.tick(None)
    assert sampler.values["tree_rss_bytes"].samples == 2
    assert sampler.values["system_used_bytes"].peak == 30


def test_sampler_queries_are_sequential_and_peak_is_only_observed(monkeypatch, settings):
    sampler = telemetry.StageTelemetry(settings)
    sampler.job_name = runtime.sampler_job_name("a" * 32)
    calls = []
    lock = threading.Lock()

    def query(target, context, **kwargs):
        assert kwargs["job_name"] == sampler.job_name
        assert lock.acquire(blocking=False), "Overlapping GPU queries"
        try:
            calls.append(time.monotonic())
            return runtime.StageResult("ok", True, 0, 0, ({"event": "checkpoint", "page": 1, "count": 12},
                                                        {"event": "checkpoint", "page": 2, "count": 34}))
        finally:
            lock.release()

    monkeypatch.setattr(runtime, "run_stage", query)
    monkeypatch.setattr(telemetry, "tree_memory", lambda _: (10, 20))
    sampler.begin(None)
    sampler.finish(None)
    assert len(calls) == 2 and calls[1] - calls[0] >= 2
    result = sampler.summary()
    assert result["metrics"]["device_vram_used_bytes"]["after"] == 12
    assert result["scope"] == "operator_only"
    assert result["peak_kind"] == "observed_samples_not_absolute_peak"
    assert not sampler.thread.is_alive()


def test_sampler_name_is_stable_separate_and_recoverable():
    import re

    name = runtime.sampler_job_name("a" * 32)
    assert re.fullmatch(r"[0-9a-f]{32}", name)
    assert name == runtime.sampler_job_name("a" * 32)
    assert name != "a" * 32 and name != runtime.sampler_job_name("b" * 32)
    assert runtime.sampler_job_name(None) is None


@windows
@pytest.mark.integration
def test_owned_query_timeout_is_private_and_cleanup_confirmed(settings):
    sampler = telemetry.StageTelemetry(replace(settings, gpu_query_timeout_seconds=0.2, cleanup_wait_seconds=0.5),
                                       gpu_target="tests.runtime_targets:native_hang")
    sampler._gpu("before")
    summary = sampler.summary()
    assert sampler.cleanup_confirmed
    metric = summary["metrics"]["device_vram_used_bytes"]
    assert metric["before"] is None and metric["coverage"] == "unavailable"
    assert metric["reason"] == telemetry.GPU_UNAVAILABLE


@windows
def test_stage_integration_has_real_ram_no_real_gpu_query(monkeypatch, settings):
    class Sampler(telemetry.StageTelemetry):
        def __init__(self, settings):
            super().__init__(settings, gpu_target="tests.runtime_targets:simple")

    monkeypatch.setattr(telemetry, "StageTelemetry", Sampler)
    result = runtime.run_stage("tests.runtime_targets:simple", {}, timeout_seconds=10,
                               telemetry_settings=settings, cleanup_wait_seconds=0.5)
    assert result.success, result
    metrics = result.telemetry["metrics"]
    assert metrics["tree_rss_bytes"]["before"] > 0
    assert metrics["tree_private_bytes"]["before"] > 0
    assert metrics["tree_rss_bytes"]["after"] == 0
    assert metrics["device_vram_used_bytes"]["before"] is None
    assert "PRIVATE" not in json.dumps(result.telemetry)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.eval_0d import CROPS_FILE_B2, GT_FILE_B1, run_benchmark

pytestmark = pytest.mark.unit


def test_eval_harness_detects_missing_b1_without_fabrication():
    """Assert absence of B1 file and verify harness explicitly flags BLOCKED_ON_B1."""
    if not GT_FILE_B1.exists():
        assert not GT_FILE_B1.exists(), "B1 GT file should not exist until supplied by user"
        res = run_benchmark()
        assert res["status"] == "BLOCKED_ON_B1"
        assert "Waiting for user-supplied 40 numeric ground truth fields" in res["message"]


@pytest.mark.system
@pytest.mark.skipif(
    not GT_FILE_B1.exists(),
    reason="Skipped by design: Waiting for user-supplied B1 GT (data/eval/ground_truth_b1_40.json) per ARCHITECTURE COMPLIANCE ORDER v3",
)
def test_pinned_gt_step0d():
    res = run_benchmark()
    assert res["peak_vram_mb"] == 0.0
    assert res["sec_per_page"] < 30.0

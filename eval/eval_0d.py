"""Step 0d Benchmark and Metric Harness.

Governed by ARCHITECTURE COMPLIANCE ORDER v3.
Evaluates RapidOCR ONNX backend on CPU (4 threads) in:
- Mode FULL (page-level detection + recognition)
- Mode REC-ONLY (batched 16-32 cell crops without detection or angle classifier)

Blocked on user-supplied inputs B1 (40 GT fields) and B2 (100 cell crops).
Normalization rules are written ONLY after the first error histogram is generated.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_use_onednn"] = "0"

from smriti.ocr import RapidOcrOnnxEngine

GT_FILE_B1 = Path(__file__).resolve().parents[1] / "data" / "eval" / "ground_truth_b1_40.json"
CROPS_FILE_B2 = Path(__file__).resolve().parents[1] / "data" / "eval" / "cell_crops_b2_100.json"


def levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev[j + 1] + 1
            deletions = curr[j] + 1
            subs = prev[j] + (c1 != c2)
            curr.append(min(insertions, deletions, subs))
        prev = curr
    return prev[-1]


def evaluate_raw_fields(recognized_tokens: list[str], fields: list[dict]):
    all_text = " \n ".join(recognized_tokens)
    all_text_lower = all_text.lower()

    exact_matches = 0
    total_dist = 0
    total_chars = 0
    digit_errors = 0
    error_histogram: dict[str, int] = {}
    field_results = {}

    for item in fields:
        name = item["id"]
        target = item["target"]
        ftype = item.get("type", "unknown")
        target_lower = target.lower()

        found = False
        best_sub = ""
        best_dist = 9999

        if target_lower in all_text_lower:
            found = True
            best_dist = 0
            best_sub = target
        else:
            w_len = len(target)
            for i in range(len(all_text) - w_len + 1):
                sub = all_text[i : i + w_len]
                d = levenshtein(sub.lower(), target_lower)
                if d < best_dist:
                    best_dist = d
                    best_sub = sub
            if best_dist == 0:
                found = True

        if found:
            exact_matches += 1
        else:
            err_key = f"mismatch: target '{target}' vs found '{best_sub}'"
            error_histogram[err_key] = error_histogram.get(err_key, 0) + 1

        dist = min(best_dist, len(target))
        total_dist += dist
        total_chars += len(target)

        target_digits = "".join(c for c in target if c.isdigit())
        sub_digits = "".join(c for c in best_sub if c.isdigit())
        if target_digits != sub_digits:
            d_err = levenshtein(target_digits, sub_digits)
            digit_errors += d_err
            error_histogram["digit_error"] = error_histogram.get("digit_error", 0) + d_err

        field_results[name] = {
            "target": target,
            "type": ftype,
            "exact_raw": found,
            "best_match": best_sub,
            "dist": dist,
        }

    cer = total_dist / max(1, total_chars)
    return {
        "exact_matches_raw": exact_matches,
        "total_fields": len(fields),
        "exact_ratio_raw": exact_matches / max(1, len(fields)),
        "cer": cer,
        "digit_errors": digit_errors,
        "error_histogram": error_histogram,
        "field_results": field_results,
    }


def analyze_token_fusion(words: list[str]) -> int:
    fusion_count = 0
    patterns = [
        re.compile(r"\d{2}-[A-Za-z]{3}-\d{4}\d{2}:\d{2}"),  # date+time
        re.compile(r"\d+%[a-zA-Z]+"),  # 85%on
        re.compile(r"[A-Z]{12,}"),  # long caps
        re.compile(r"\d+cells/[^\s]+"),
    ]
    for w in words:
        for p in patterns:
            if p.search(w):
                fusion_count += 1
                break
    return fusion_count


def evaluate_line_order(words) -> dict:
    inversions = 0
    total_pairs = 0
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        total_pairs += 1
        if w2.bbox[1] < w1.bbox[1] - 0.02 and w2.bbox[0] < w1.bbox[0]:
            inversions += 1
    inversion_rate = inversions / max(1, total_pairs)
    return {
        "total_transitions": total_pairs,
        "line_inversions": inversions,
        "line_order_score": 1.0 - inversion_rate,
    }


def run_benchmark(sample_pages: list[Path] | None = None):
    if not GT_FILE_B1.exists():
        return {
            "status": "BLOCKED_ON_B1",
            "message": "Waiting for user-supplied 40 numeric ground truth fields in data/eval/ground_truth_b1_40.json",
        }

    fields = json.loads(GT_FILE_B1.read_text(encoding="utf-8"))
    proc = psutil.Process()

    engine = RapidOcrOnnxEngine()
    engine._load()

    if sample_pages is None:
        sample_pages = [
            Path("data/test_ds_2.jpg"),
            Path("data/test_ds_1.jpg"),
            Path("data/uploads/5ee47bdffadc4c2ee248a9b81df397e6264cc93e68f8e05487057f04ec389133/page_1.webp"),
            Path("data/eval/pages/HM_2024_ADMISSION/page_01.png"),
        ]

    # Mode FULL: page-level detection + recognition
    all_tokens = []
    page_times = []
    total_words_list = []

    for p in sample_pages:
        if not p.exists():
            continue
        t0 = time.perf_counter()
        words = engine.read(p, debug=True)
        dur = time.perf_counter() - t0
        page_times.append(dur)
        total_words_list.extend(words)
        for w in words:
            all_tokens.append(w.text)

    full_field_metrics = evaluate_raw_fields(all_tokens, fields)
    fusion_count = analyze_token_fusion(all_tokens)
    line_metrics = evaluate_line_order(total_words_list)

    # Persist the error histogram to eval/out/error_histogram_0d.json
    out_dir = Path(__file__).resolve().parents[1] / "eval" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    hist_file = out_dir / "error_histogram_0d.json"
    hist_file.write_text(
        json.dumps(full_field_metrics["error_histogram"], indent=2),
        encoding="utf-8",
    )

    # Mode REC-ONLY: 100 cell crops with p50/p95 measurement
    crop_metrics = {"status": "BLOCKED_ON_B2", "message": "Waiting for user-supplied B2 cell crops"}
    if CROPS_FILE_B2.exists():
        crops_data = json.loads(CROPS_FILE_B2.read_text(encoding="utf-8"))
        crop_images = []
        crop_expected = []
        for item in crops_data:
            cpath = Path(item["image_path"])
            if cpath.exists():
                crop_images.append(Image.open(cpath))
                crop_expected.append(item.get("expected", ""))

        if crop_images:
            latencies = []
            exact_matches = 0
            # Batched REC-ONLY mode (16 crops per call)
            chunk_size = 16
            for i in range(0, len(crop_images), chunk_size):
                chunk = crop_images[i : i + chunk_size]
                chunk_exp = crop_expected[i : i + chunk_size]
                t0 = time.perf_counter()
                rec_res = engine.read_crops(chunk, batch_size=chunk_size)
                elapsed_ms = (time.perf_counter() - t0) * 1000
                per_crop_ms = elapsed_ms / len(chunk)
                for (rec_t, _), exp in zip(rec_res, chunk_exp):
                    latencies.append(per_crop_ms)
                    if exp and rec_t.strip().lower() == exp.strip().lower():
                        exact_matches += 1

            crop_metrics = {
                "crops_count": len(crop_images),
                "crop_p50_ms": float(np.percentile(latencies, 50)),
                "crop_p95_ms": float(np.percentile(latencies, 95)),
                "crop_exact_match": f"{exact_matches}/{len(crop_images)} ({exact_matches/len(crop_images)*100:.1f}%)",
            }

    peak_ram_mb = proc.memory_info().rss / (1024 * 1024)

    report = {
        "engine": engine.name,
        "runtime": "onnxruntime-cpu (4 threads)",
        "sec_per_page": (sum(page_times) / len(page_times)) if page_times else 0.0,
        "peak_ram_mb": peak_ram_mb,
        "peak_vram_mb": 0.0,
        "raw_fields_exact": f"{full_field_metrics['exact_matches_raw']}/{full_field_metrics['total_fields']} ({full_field_metrics['exact_ratio_raw']*100:.1f}%)",
        "cer": round(full_field_metrics["cer"], 4),
        "digit_errors": full_field_metrics["digit_errors"],
        "token_fusions": fusion_count,
        "line_order_score": round(line_metrics["line_order_score"], 4),
        "error_histogram": full_field_metrics["error_histogram"],
        "crops": crop_metrics,
    }
    report_file = out_dir / "report_0d.json"
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    out = run_benchmark()
    print(json.dumps(out, indent=2))

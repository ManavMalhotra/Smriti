"""Parser bake-off benchmark runner.

Evaluates candidate document parsers on medical documents, measuring latency,
host RAM usage, and GPU VRAM footprint against the 8 GB RAM / GTX 1650 (4 GB VRAM) hardware budget.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.bakeoff import REGISTRY, BaseParserAdapter, get_adapter  # noqa: E402

# Hardware budgets for GTX 1650 (4 GB VRAM) and 8 GB RAM PC:
# - Process RAM budget: 2000 MB (leaves 5+ GB for OS, browser, and background apps)
# - GPU VRAM budget: 3500 MB (leaves ~596 MB buffer for display/WDDM on 4 GB card)
MAX_ALLOWED_PROCESS_RAM_MB = 2000.0
MAX_ALLOWED_VRAM_MB = 3500.0


def run_benchmark(
    manifest_path: str | Path,
    engine_name: str,
    *,
    limit: int | None = None,
    doc_id: str | None = None,
    doc_type: str | None = None,
) -> dict:
    manifest_file = Path(manifest_path)
    if not manifest_file.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_file}")

    with open(manifest_file, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    adapter: BaseParserAdapter = get_adapter(engine_name)
    available, reason = adapter.is_available()

    pages_to_run = []
    for doc in manifest.get("documents", []):
        if doc_id and doc["doc_id"] != doc_id:
            continue
        if doc_type and doc.get("doc_type") != doc_type:
            continue
        for page in doc.get("pages", []):
            pages_to_run.append(
                {
                    "doc_id": doc["doc_id"],
                    "doc_type": doc.get("doc_type", "other"),
                    "page_number": page["page_number"],
                    "image_path": Path(page["image_path"]),
                }
            )

    if limit and limit > 0:
        pages_to_run = pages_to_run[:limit]

    results = []
    latencies = []
    process_rams = []
    system_rams = []
    gpu_vrams = []
    errors = 0

    print(
        f"Starting bake-off: engine='{adapter.name}' on {len(pages_to_run)} page(s) "
        f"(available: {available} - {reason})"
    )

    for idx, item in enumerate(pages_to_run, start=1):
        if not available:
            record = {
                "doc_id": item["doc_id"],
                "page_number": item["page_number"],
                "doc_type": item["doc_type"],
                "status": "unavailable",
                "error": reason,
                "latency_s": 0.0,
                "word_count": 0,
                "process_ram_mb": 0.0,
                "system_ram_mb": 0.0,
                "gpu_vram_mb": 0.0,
            }
            results.append(record)
            continue

        res = adapter.parse_page(item["image_path"])
        record = {
            "doc_id": item["doc_id"],
            "page_number": item["page_number"],
            "doc_type": item["doc_type"],
            "status": res.status,
            "latency_s": res.latency_s,
            "word_count": res.word_count,
            "process_ram_mb": res.peak_process_ram_mb,
            "system_ram_mb": res.peak_system_ram_mb,
            "gpu_vram_mb": res.peak_gpu_vram_mb,
            "error": res.error,
        }
        results.append(record)

        if res.status == "success":
            latencies.append(res.latency_s)
            process_rams.append(res.peak_process_ram_mb)
            system_rams.append(res.peak_system_ram_mb)
            gpu_vrams.append(res.peak_gpu_vram_mb)
            print(
                f"  [{idx}/{len(pages_to_run)}] {item['doc_id']} p{item['page_number']}: "
                f"{res.latency_s:.2f}s | {res.word_count} words | "
                f"Proc RAM: {res.peak_process_ram_mb:.0f} MB | VRAM: {res.peak_gpu_vram_mb:.0f} MB"
            )
        else:
            errors += 1
            print(
                f"  [{idx}/{len(pages_to_run)}] {item['doc_id']} p{item['page_number']}: "
                f"{res.status} ({res.error})"
            )

    success_count = len(latencies)
    mean_lat = round(statistics.mean(latencies), 3) if latencies else 0.0
    median_lat = round(statistics.median(latencies), 3) if latencies else 0.0
    max_lat = round(max(latencies), 3) if latencies else 0.0
    max_proc_ram = round(max(process_rams), 1) if process_rams else 0.0
    max_sys_ram = round(max(system_rams), 1) if system_rams else 0.0
    max_vram = round(max(gpu_vrams), 1) if gpu_vrams else 0.0

    vram_pass = max_vram <= MAX_ALLOWED_VRAM_MB
    proc_ram_pass = max_proc_ram <= MAX_ALLOWED_PROCESS_RAM_MB

    summary = {
        "engine": adapter.name,
        "available": available,
        "availability_note": reason,
        "total_pages_evaluated": len(pages_to_run),
        "success_count": success_count,
        "error_count": errors,
        "latency": {
            "mean_s": mean_lat,
            "median_s": median_lat,
            "max_s": max_lat,
        },
        "resources": {
            "peak_process_ram_mb": max_proc_ram,
            "peak_system_ram_mb": max_sys_ram,
            "peak_gpu_vram_mb": max_vram,
            "max_allowed_vram_mb": MAX_ALLOWED_VRAM_MB,
            "max_allowed_process_ram_mb": MAX_ALLOWED_PROCESS_RAM_MB,
            "vram_budget_pass": vram_pass,
            "proc_ram_budget_pass": proc_ram_pass,
            "hardware_budget_pass": vram_pass and proc_ram_pass,
        },
        "page_results": results,
    }

    return summary


def print_summary_table(summary: dict) -> None:
    res = summary["resources"]
    lat = summary["latency"]

    print("\n" + "=" * 68)
    print(f"BAKE-OFF SUMMARY: {summary['engine'].upper()}")
    print("=" * 68)
    print(f"Status              : {'Available' if summary['available'] else 'Unavailable'}")
    if not summary["available"]:
        print(f"Note                : {summary['availability_note']}")
    print(f"Pages Evaluated     : {summary['total_pages_evaluated']}")
    print(f"Successful Parses   : {summary['success_count']}")
    print(f"Errors              : {summary['error_count']}")
    print(f"Latency (Mean)      : {lat['mean_s']} s / page")
    print(f"Latency (Median)    : {lat['median_s']} s / page")
    print(f"Latency (Max)       : {lat['max_s']} s / page")
    print(f"Peak Process RAM    : {res['peak_process_ram_mb']} MB / {res['max_allowed_process_ram_mb']} MB")
    print(f"Peak System RAM     : {res['peak_system_ram_mb']} MB (ambient)")
    print(f"Peak GPU VRAM       : {res['peak_gpu_vram_mb']} MB / {res['max_allowed_vram_mb']} MB")
    print(
        f"Hardware Fit        : "
        f"{'PASS (Fits GTX 1650 & 8GB RAM)' if res['hardware_budget_pass'] else 'FAIL (Exceeds budget)'}"
    )
    print("=" * 68 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run parser bake-off benchmark")
    parser.add_argument(
        "--manifest",
        default="data/eval/manifest.json",
        help="Path to evaluation manifest JSON",
    )
    parser.add_argument(
        "--engine",
        default="paddleocr",
        choices=list(REGISTRY.keys()) + ["all"],
        help="Engine adapter to benchmark (default: paddleocr)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of pages to process",
    )
    parser.add_argument(
        "--doc",
        default=None,
        help="Filter to a specific doc_id",
    )
    parser.add_argument(
        "--doc-type",
        default=None,
        help="Filter by document type (e.g. ct, discharge_summary, pathology)",
    )
    parser.add_argument(
        "--out",
        default="eval/out/bakeoff_report.json",
        help="Path to write output report JSON",
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    engines = list(REGISTRY.keys()) if args.engine == "all" else [args.engine]
    full_report = {}

    for eng in engines:
        summary = run_benchmark(
            args.manifest,
            eng,
            limit=args.limit,
            doc_id=args.doc,
            doc_type=args.doc_type,
        )
        full_report[eng] = summary
        print_summary_table(summary)

    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(full_report, handle, indent=2)

    print(f"Bake-off report saved to {out_path.resolve()}")


if __name__ == "__main__":
    main()

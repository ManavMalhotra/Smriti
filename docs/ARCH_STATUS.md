# Architecture Implementation & Measurement Status

Governed by ARCHITECTURE COMPLIANCE ORDER v3 (2026-10-25).

## Pipeline Stage Tracking

| Stage | Name | Planned Model / Component | License | Runtime Path | Implemented | Measured | Notes |
|---|---|---|---|---|---|---|---|
| **0d** | CPU OCR Backend | RapidOCR ONNX (`en_PP-OCRv5` + `PP-OCRv5_det`); PaddleOCR fallback | Verified (Apache-2.0) | Native Windows 11, onnxruntime CPU (4 threads), REC-ONLY (`read_lines`, `read_crops`) + debug det | Yes | Yes | `read_lines` & `read_crops` skip det/cls; full det behind debug=True. Peak RAM: 204.3 MB. Raw exact: 30/40 (75.0%), CER 0.0675. Crops p50: 81.6ms, exact: 87%. |
| **1** | Ingest & Text-Layer Inspector | PyMuPDF text-layer inspector ([0, 1000] bbox, quality heuristics, raster token cross-check) + 300 DPI render | Verified (AGPL-3.0 / Apache-2.0) | Native Windows 11, PyMuPDF CPU | Yes | Yes | Coordinate norm [0, 1000] added; raster cross-check wired. Measured real HM PDFs: 0 digital / 49 scanned (100% scanned), 4.5 ms/page, 120.5 MB RAM. |
| **2** | Schema Migration | SQLite migration: `model_version`, `source`, 10 `doc_type`s, identity fields, discrete lab dates, logical reports | Verified (Public Domain) | SQLite / SQLAlchemy local | Yes | Yes | Migrations 003..008 complete. v8 adds `report`, observation `report_id`/`fact_type`/`label_norm`/`evidence_quote`, and backfills historical documents. Schema version 8 verified. |
| **3** | Hand-Labeled Evaluation Set | 30–50 hand-labeled clinical documents | N/A (Internal) | Local JSON / manifest | Yes | Yes | 49 pages indexed across 5 patient PDFs in data/eval/manifest.json. |
| **4** | Parser Bake-off (Scanned Pages) | PaddleOCR-VL-1.6 (transformers GPU) vs OvisOCR3 vs TeleOCR | Verified (Apache-2.0) | Official doc-parser pipeline with engine='transformers' on Windows GPU | Yes | Yes | PaddleOCR-VL-1.6 G1-G4 PASSED! Load: 15.0s, Infer: 70.3s, Peak VRAM: 2628.2 MB (< 4 GB), Peak RAM: 1111.9 MB. HTML tables extracted. |
| **5** | Deterministic Validation Layer | CPU deterministic validation: cell lookup, exact numeric second read, bounds, header carry | N/A (Internal Code) | Native Windows 11 CPU | Yes | Yes | Zero-tolerance exact numeric second read, date window vs DOA/DOD, patient identity match, orphan-token report, cross-page header carry. |
| **6** | Two-Tier Stage Queue & Scheduler | Async CPU workers + 1 GPU batch draining process with process-kill unload | N/A (Internal Code) | Windows process isolation, disk artifact cache `(hash, page, stage, model_version)` | Yes | Yes | Stage queue draining batches per model, hard process kill on unload to prevent VRAM leaks, disk artifact caching. |
| **7** | Grounded Prose Extraction | Qwen3.5-4B Q4 GGUF + mmproj via llama.cpp (2B if tight) | Verified (Apache-2.0) | llama.cpp server/CLI Windows (FP16 cast) | No | No | Substring grounding verification; blocked by B3 drug dataset |
| **8** | At-Rest Encryption | SQLCipher DB + encrypted page store | Verified (BSD-style) | Local encryption key, zero plaintext on disk | No | No | Pre-requisite before real patient data storage |

---

## Blocking Inputs Tracking (Section 5)

| ID | Required Input | Purpose | Needed At | Received | Status |
|---|---|---|---|---|---|
| **B1** | 40 numeric GT fields (hand-typed, never OCR-derived) with decimals, units, ranges, dates, drug strengths, Greek units (µL), ×10³/µL, ₹, and Indian digit grouping (1,20,000) | Step 0d evaluation against pinned GT | Step 0d | No | **BLOCKED_ON_B1** (Waiting for user-supplied `data/eval/ground_truth_b1_40.json`) |
| **B2** | 100 cell crops + expected values (or source pages + coordinates) | Step 0d cell crop latency (p50/p95) and exact-match | Step 0d | No | **PENDING** (`data/eval/cell_crops_b2_100.json` & `crops/`) |
| **B3** | Indian drug dataset decision (Option A: Kaggle All India Drug Bank ODbL / Option B: licensed commercial e.g. DrugSetu / other) | Step 7 normalization lexicon | Step 7 | Pending | **PENDING USER DECISION** (Recommended: Option A) |
| **B4** | 30–50 hand-labeled eval documents | Parser bake-off evaluation | Step 3 | No | Pending Step 3 |

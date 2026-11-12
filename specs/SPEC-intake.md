# SPEC-intake

| | |
|---|---|
| Module | `intake` |
| Status | Original Phase 1 contracts/plan/checklist and subsequent long-PDF requirements approved on 2026-11-05; revised long-PDF plan awaiting review; runtime not yet connected |
| Depends on | — |
| SRS | FR-ING-01…11, FR-JOB-01…08, FR-RUN-01…04, NFR-18, DR-07; `docs/SRS.md` v1.3 |
| Files | `smriti/ingest.py`, `smriti/preprocess.py`, `smriti/quality.py`, `smriti/handwriting.py`, `api/routers/documents.py`, `api/routers/jobs.py` |

Approved amendment (2026-11-05): the user approved removing document page-count rejection. [SPEC-runtime-stages.md §8](SPEC-runtime-stages.md#8-approved-long-pdf-requirements-amendment--2026-11-05) requires bounded internal windows, complete-document preparation/publication, disk accounting and preserved context. The original gate record below is historical; changed implementation/storage details in `tasks/plan.md` §13 await review and are not implemented.

## 1. Objective

Accept a bounded private upload spool with ownership/consent and a durable pending job identity, then prepare canonical quality-checked pages in an isolated background stage before OCR. HTTP intake establishes only basic supported-type/byte limits; background preparation establishes readable format, page count, dimensions, EXIF stripping, and geometry. Downstream inference may consume only validated durable normalized pages. The approved execution/privacy contract is [SPEC-runtime-stages.md](SPEC-runtime-stages.md), with proposed implementation steps in `tasks/plan.md` §12.

## 2. Commands

Existing synthetic regression commands; new runtime checks are planned in `tasks/plan.md` §12. Do not start the live application to validate these documentation changes: startup applies migrations and may admit stored jobs. Historical preview/rebuild CLI sketches are not implemented in `smriti/ingest.py`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_quality.py -q
git diff --check
```

## 3. Structure

```
smriti/
  ingest.py        bounded spool → submission; isolated preparation → pages/manifest → document + consent + same-ID job
  stage.py         frozen submissions → sequential preparation → short whole-document worksets / long-document page windows; supervised barriers
  preprocess.py    pure geometry: EXIF rotate, perspective warp, deskew, CLAHE, upscale
  quality.py       short edge, Laplacian variance, aspect ratio, blank/duplicate page
  handwriting.py   detector; sets capture_type server-side
data/uploads/<content_hash>/page_<n>.webp
data/spool/<application-generated-id>      restricted ephemeral raw bytes, not served/backed up
tests/fixtures/intake/{clean,skewed,shadowed,compressed,handwritten}/
```

Pipeline order is declared once, in `preprocess.PIPELINE`, and recorded per page so the applied steps are reproducible:

```
EXIF strip → rotate → rasterise (PDF, 300 DPI) → perspective (if quad found)
→ deskew → CLAHE → upscale to ≥1500 px long edge → pHash duplicate check
```

## 4. Code style

- Every function in `preprocess.py` is pure: `ndarray → ndarray`, no I/O, no logging, no config reads. Composition and side effects live in `ingest.py`.
- `capture_type` is derived from `handwriting.detect()` and written by the server. It is never read from the request body.
- Keep `IngestError(code, message, page)` for known validation outcomes. The API maps immediate basic-boundary errors to HTTP; isolated preparation records later deterministic failures in the job API. The supervisor handles unexpected crashes/timeouts and cleanup separately, without exposing arbitrary exception text.
- `Decimal` for nothing here — this module deals in pixels and floats only.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_preprocess_order` asserts `PIPELINE` matches the recorded steps | preprocessing is auditable |
| Unit | `test_deskew_estimate` on 5 synthetic rotations ±7° | deskew accuracy ≤ 0.5° |
| Unit | `test_quality_gate` confusion matrix over the 5-doc fixture set | reject rate sanity, no clean doc rejected |
| Integration | same bytes uploaded twice → one active submission/spool; after preparation one document/job/source set | FR-ING-05 idempotency, including duplicate races |
| Integration | upload with EXIF GPS → private raw spool inaccessible to static/backup; normalized pages have no EXIF; raw removed after preparation | FR-ING-11 / GPS lifetime bounded |
| Integration | PDF 3 pages → HTTP pending total null; preparation yields 3 durable page files and same-ID job with `total=3` | FR-ING-04, FR-JOB-08 |
| Integration | success/deterministic rejects remove raw; crash retention only with explicit debug flag; locked file and both commit/unlink windows recover truthfully | FR-ING-11; actual `spool_deleted_at` |
| Integration | deferred preparation creates document/consent/job atomically, preserving consent grant/owner; failure creates none | FR-ING-01/09, DR-07 |
| Integration | ≤10 frozen submissions; 15+15 and 14+12 stay separate; 39 pages yield internal 20+19 with one document/job and no late admissions | FR-RUN-01 |
| System (synthetic) | spawned Windows parent/grandchild cleanup, bounded RAM/GPU samplers, fake VLM while HTTP only spools | FR-RUN-02…04, NFR-18; not real hardware evidence |

Quality thresholds are config values, not constants in code, and are recorded with each document (FR-ING-06).

## 6. Boundaries

- **Never** trust `capture_type` from the client. SI-01's gate must not be user-selectable (FR-ING-02).
- **Always** limit raw bytes to the approved restricted ephemeral spool (including parser/partial-file handling). Commit preparation or deterministic rejection, close handles, immediately unlink, and record actual removal; failed cleanup remains recoverable and blocks further expensive admission. Only unexpected parser/renderer crashes with explicit `DEBUG_RETAIN_FAILED_SPOOL=1` may retain raw. No permanent original archive/download; normalized images contain no EXIF/GPS/camera thumbnails.
- **Never** decode, render, normalize, or OCR in the HTTP upload path. Background intake normalizes/checks pages; OCR/clinical interpretation remain downstream.
- **Never** accept a page that fails a hard quality gate — reject with a re-shoot message, do not degrade (ASM-05).
- **Never** store raw/normalized uploads in the served static root. Normalized sources stay in `data/uploads/`; approved raw staging stays only in restricted `data/spool/`, excluded from backups/exports/git.
- **Never** run more than one coordinator or overlap expensive stage trees. Supervised disposable children are permitted; Windows Job Objects/recursive verified tree cleanup replace parent-only termination.

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-ING-01 | Planned pending-submission and successful deferred document-promotion tests in `tests/test_ingest.py` |
| FR-ING-02 | `test_capture_type_is_derived` — server detection, client value ignored |
| FR-ING-03 | `test_quality_gate_rejects_low_res` / `..._blurred` |
| FR-ING-04 | `test_pdf_pages_split`, `test_deskew_applied` |
| FR-ING-05 | `test_reupload_is_idempotent` |
| FR-ING-06 | `test_preprocessing_recorded` |
| FR-ING-07 | `test_two_dates_stored_separately` |
| FR-ING-08 | `test_upload_returns_202_with_job` |
| FR-ING-09 | Planned submission-consent/promotion/revocation tests |
| FR-ING-11 | Planned ephemeral-spool deletion, debug-crash-only retention, locked-file and restart recovery tests |
| FR-JOB-01 | `test_job_progress_shape` |
| FR-JOB-02 | `test_retry_does_not_duplicate` |
| FR-JOB-03 | `test_partial_failure_leaves_no_charted_rows` |
| FR-JOB-04 | frontend poll test in `web/` |
| FR-JOB-08 | Planned pending/preparing/null-total, terminal rejection, same-ID promotion, historical compatibility API/UI tests |
| FR-RUN-01…04, NFR-18 | Planned stage/telemetry tests and gates in `tasks/plan.md` §12 |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-ING-02 | Delete client-supplied `capture_type`; replace with server-side detection. |
| FR-ING-04 | Add perspective correction and upscale (camera captures). |
| FR-RED-03 | Historical move of EXIF stripping to intake. Approved v1.2 exception permits raw bytes only in an ephemeral private spool; durable normalized sources are EXIF-free. |
| new FR-ING-09 | Historical per-document upload consent; v1.2 records consent on submission before preparation and atomically transfers it at deferred document creation. |

### Approved Phase 1 gates — 2026-11-05

1. **Strictly ephemeral spool:** `data/spool/` excluded from static serving/backups; delete after durable success or deterministic failure, record `spool_deleted_at` only on confirmed removal. Crash-only debug retention opt-in; permanent archival rejected.
2. **Additive operational staging:** `submissions`/`stage_batches` without fake clinical documents; defer document/consent/job creation until preparation succeeds. Pending/preparing APIs expose null document/page totals with truthful stages; preserve positive existing counts and historical fields.
3. **Telemetry:** pinned `psutil`, no `pynvml`; 1–2s RSS/private-bytes/system RAM sampling; streamed `nvidia-smi -l 2` or ≥2s polling with 3s query/stall deadlines, bounded reader cleanup, and null/unavailable reasons.
4. **Original whole-document admission (historical):** freeze ≤10 submissions, prepare one at a time, reject >20-page uploads, then pack ≤20-page whole-document worksets without planned lifecycle splitting. The subsequently approved long-PDF requirements replace the upload cap/lifecycle rule: no page-count rejection, ≤20 internal windows, one document/job and complete-document semantics/publication. Short-document packing and frozen membership remain.

These approvals supersede conflicting historical intake wording only for Phase 1. They do not authorize runtime implementation, live migration/restart, or real-record processing. Other model/quality decisions stay unchanged.

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Actual blur threshold value | Week 3, on 20 real docs | Start at Laplacian variance 100, tune once |
| 2 | Accept HEIC from iPhones? | Week 3 | Reject with "convert to JPEG" |
| 3 | Does CLAHE help or hurt on real scans? | Week 2 A/B | Drop it; deskew + upscale carry the gain |

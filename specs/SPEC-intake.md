# SPEC-intake

| | |
|---|---|
| Module | `intake` |
| Status | Draft for review |
| Depends on | — |
| SRS | FR-ING-01…08, FR-JOB-01…04 |
| Files | `smriti/ingest.py`, `smriti/preprocess.py`, `smriti/quality.py`, `smriti/handwriting.py`, `api/routers/documents.py`, `api/routers/jobs.py` |

## 1. Objective

Turn an upload into a canonical, quality-checked page-image series and a queued job, before any OCR runs. Intake is the only module that touches untrusted bytes, so it is the only place where file type, dimensions, EXIF, and page geometry are established. Everything downstream may assume a clean page.

## 2. Commands

```bash
uvicorn smriti.main:app --reload
pytest tests/test_ingest.py tests/test_quality.py -q
python -m smriti.ingest --preview samples/hand_01.jpg --out .cache/preview
python -m smriti.ingest --rebuild-fixtures      # regenerate the 5-document mini set
```

## 3. Structure

```
smriti/
  ingest.py        upload → document row → pages on disk → job row
  preprocess.py    pure geometry: EXIF rotate, perspective warp, deskew, CLAHE, upscale
  quality.py       short edge, Laplacian variance, aspect ratio, blank/duplicate page
  handwriting.py   detector; sets capture_type server-side
data/uploads/<content_hash>/page_<n>.webp
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
- One error type: `IngestError(code, message, page)`. The API maps codes to HTTP; nothing else catches exceptions.
- `Decimal` for nothing here — this module deals in pixels and floats only.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_preprocess_order` asserts `PIPELINE` matches the recorded steps | preprocessing is auditable |
| Unit | `test_deskew_estimate` on 5 synthetic rotations ±7° | deskew accuracy ≤ 0.5° |
| Unit | `test_quality_gate` confusion matrix over the 5-doc fixture set | reject rate sanity, no clean doc rejected |
| Integration | same bytes uploaded twice → one `document` row, one file | FR-ING-05 idempotency |
| Integration | upload with EXIF GPS → stored file has no EXIF | A-02 / GPS leak closed |
| Integration | PDF 3 pages → 3 page files, `total=3` | FR-ING-04 |

Quality thresholds are config values, not constants in code, and are recorded with each document (FR-ING-06).

## 6. Boundaries

- **Never** trust `capture_type` from the client. SI-01's gate must not be user-selectable. (Contradicts FR-ING-02 — see delta below.)
- **Never** write the original uploaded bytes anywhere. Re-encode, then discard the input buffer. No GPS, no camera make, no thumbnail in EXIF.
- **Never** OCR, normalise, or interpret in this module.
- **Never** accept a page that fails a hard quality gate — reject with a re-shoot message, do not degrade (ASM-05).
- **Never** store uploads inside the served static root (NFR-06) or outside `data/uploads/`.
- **Never** run more than one worker; the claim loop is single-writer (A-07).

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-ING-01 | `test_upload_creates_queued_document` |
| FR-ING-02 | **Superseded.** `test_capture_type_is_derived` — client value ignored |
| FR-ING-03 | `test_quality_gate_rejects_low_res` / `..._blurred` |
| FR-ING-04 | `test_pdf_pages_split`, `test_deskew_applied` |
| FR-ING-05 | `test_reupload_is_idempotent` |
| FR-ING-06 | `test_preprocessing_recorded` |
| FR-ING-07 | `test_two_dates_stored_separately` |
| FR-ING-08 | `test_upload_returns_202_with_job` |
| FR-JOB-01 | `test_job_progress_shape` |
| FR-JOB-02 | `test_retry_does_not_duplicate` |
| FR-JOB-03 | `test_partial_failure_leaves_no_charted_rows` |
| FR-JOB-04 | frontend poll test in `web/` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-ING-02 | Delete client-supplied `capture_type`; replace with server-side detection. |
| FR-ING-04 | Add perspective correction and upscale (camera captures). |
| FR-RED-03 | Move EXIF strip from egress to intake — it must happen before the file is ever stored. |
| new FR-ING-09 | Capture a `consent` row per document at upload; no row, no processing. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Actual blur threshold value | Week 3, on 20 real docs | Start at Laplacian variance 100, tune once |
| 2 | Accept HEIC from iPhones? | Week 3 | Reject with "convert to JPEG" |
| 3 | Does CLAHE help or hurt on real scans? | Week 2 A/B | Drop it; deskew + upscale carry the gain |

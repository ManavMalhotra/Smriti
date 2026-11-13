# API Contract

Status: v1.6. The auth, bounded upload/review, job/list, patient-summary, patient-timeline, observation-review, report-correction, and fenced erase-all endpoints are implemented. Sections marked **contract-only** are frozen shapes for later phases and are not served yet. Live rollout and hardware/clinical acceptance remain separately gated.

Base path: `/api`. All requests and responses are JSON except the upload (`multipart/form-data`) and the page-image response (`image/webp`).

---

## 1. Conventions

- **Every route except `/auth/register`, `/auth/login`, `/auth/logout`, and `/health` requires a patient session.** The session is an `HttpOnly`, `SameSite=Strict` cookie named `smriti_session`; the token is stored hashed in SQLite.
- **A patient can only access their own records.** Patient-id routes return `403` for another patient; document, page, and job routes return `404` to avoid confirming existence.
- **Local HTTP only by default.** The cookie is not `Secure`; terminate TLS and enable `Secure` before exposing the app beyond localhost.
- **Bounded document review.** Detail/source reads use page/result ranges; patient summary/timeline are not a general pagination redesign.
- **Every observation-bearing response includes provenance.** A value without `document_id`, `page`, and `bbox` is a contract violation (SRS §3.5.1).
- **Errors** are always:

```json
{ "error": { "code": "quality_rejected", "message": "Short edge 640 px is below 1000 px.", "field": "file" } }
```

| Code | HTTP | Meaning |
|---|---|---|
| `validation_error` | 400 | Malformed request |
| `unauthorized` | 401 | No session cookie |
| `session_expired` | 401 | Session missing or expired |
| `invalid_credentials` | 401 | Wrong username or password |
| `forbidden` | 403 | Another patient's record |
| `consent_required` | 403 | No consent row for this document |
| `demo_read_only` | 403 | Write attempted in `demo` profile |
| `not_found` | 404 | Unknown id |
| `duplicate` | 409 | Same patient's content hash already ingested |
| `username_taken` | 409 | Username already exists (case-insensitive) |
| `too_large` | 413 | Upload exceeds the byte limit |
| `quality_rejected` | 422 | Quality gate rejected the upload |
| `too_many_pages` | 422 | PDF exceeds the page limit |
| `invalid_file` | 422 | Empty, corrupt, or unsupported file |
| `page_too_large` | 422 | Rendered page exceeds the pixel limit |
| `too_many_attempts` | 429 | Login throttled |
| `ingest_failed` | 500 | Ingestion failed |

- **Ids** are opaque UUID strings. No endpoint accepts a filename.

---

## 2. Accounts

### `POST /api/auth/register`

```json
{
  "alias": "P-01",
  "username": "patient-one",
  "password": "at-least-8-characters",
  "sex": "F",
  "dob": null
}
```

`201` → `{ "id": "…", "alias": "P-01", "username": "patient-one", "sex": "F", "dob": null, "created_at": "…" }`

Sets the session cookie. `username` is 3–32 characters (`A-Z a-z 0-9 . _ -`), unique case-insensitively; `alias` is the only display identifier. No real name is accepted.

On a v1 database, the first registration claims the sole patient with no username so existing local records remain reachable. If more than one unowned patient exists, a new patient is created and the old records are not automatically exposed.

### `POST /api/auth/login`

```json
{ "username": "patient-one", "password": "…" }
```

`200` → the same patient object; sets the session cookie. `401 invalid_credentials`; `429 too_many_attempts` after five failures in five minutes for that username.

### `POST /api/auth/logout`

`204`. Deletes the session row and clears the cookie.

### `GET /api/auth/me`

`200` → the signed-in patient object. `401 unauthorized` or `401 session_expired`.

---

## 3. Patients

### `GET /api/patients/{id}/summary`

Requires the signed-in patient's own id. `403 forbidden` otherwise.

Seven keys, no more. Frozen in week 2; validated in CI against `web/src/fixtures/summary.json` (NFR-12).

```json
{
  "patient": {
    "id": "…", "alias": "P-01", "sex": "F", "dob": null
  },
  "coverage": {
    "first_date": "2021-03-04",
    "last_date": "2026-09-12",
    "quarters": [
      { "q": "2021-Q1", "documents": 2 },
      { "q": "2021-Q2", "documents": 0 }
    ],
    "gaps": [
      { "from": "2022-04-01", "to": "2023-07-01", "months": 15,
        "text": "No data for 15 months" }
    ]
  },
  "problems": [
    { "id": "…", "label": "Type 2 diabetes", "source_doc_id": "…" }
  ],
  "medications": [
    { "id": "…", "brand_raw": "Metformin", "salt": null, "dose": "500 mg",
      "freq": "BD", "state": "prescribed", "source_doc_id": "…",
      "reported_at": null }
  ],
  "results": [
    {
      "analyte_id": "hba1c",
      "display": "HbA1c",
      "unit": "%",
      "ref_low": 4.0,
      "ref_high": 5.6,
      "points": [
        { "date": "2025-11-02", "value": 8.9, "flag_printed": "H",
          "observation_id": "…", "document_id": "…", "page": 1,
          "bbox": [0.61, 0.42, 0.78, 0.47], "status": "auto" }
      ],
      "excluded": [
        { "document_id": "…", "reason": "plausibility_bound" }
      ]
    }
  ],
  "pending": [
    { "kind": "directive", "id": "…", "text": "R/V after 2 weeks",
      "action_type": "review", "due_date": "2025-11-16",
      "anchor_event": "collection_date", "state": "open" }
  ],
  "documents": [
    { "id": "…", "doc_type": "lab_report", "doc_date": "2025-11-02",
      "collection_date": "2025-11-02", "page_count": 2, "status": "done",
      "review_count": 2 }
  ]
}
```

Rules the fixture enforces:

- `results[].points[].bbox` is always present and always length 4.
- `excluded` exists even when empty — a rejection is never invisible (`FR-TIM-09`).
- `medications[].state` is never merged; the same drug may appear three times.
- `pending` contains no item whose `due_date` was already past at extraction.
- `coverage.gaps[].text` states a duration, never an interpretation.
- `results[].points[].status` is `auto` or `review`; rejected points are omitted.
- `documents[].review_count` counts observations still awaiting review.

**Additive clinical extension:** In addition to the baseline seven keys, the response includes `clinical_snapshot`, `organ_groups`, `medications_timeline`, `master_timeline`, and `standardized_summary` (`StandardizedClinicalSummary`), providing an end-to-end longitudinal picture.

### `GET /api/patients/{id}/clinical-summary`

Requires the signed-in patient's own id. Returns the cached or newly synthesized `StandardizedClinicalSummary`.

```json
{
  "patient_name": "parv",
  "age": 47,
  "gender": "F",
  "hypertension": {
    "name": "Hypertension",
    "status": "negative",
    "details": "Documented as no history of hypertension across admissions.",
    "source_doc_id": null
  },
  "chronic_conditions": [
    {
      "name": "Diabetes Mellitus",
      "status": "negative",
      "details": "Documented negative (no history of DM).",
      "source_doc_id": null
    },
    {
      "name": "Allergy: Allergic to Sulpha Drugs",
      "status": "active",
      "details": "Documented drug allergy to Allergic to Sulpha Drugs.",
      "source_doc_id": null
    }
  ],
  "genetic_family_history": "Documented as not significant; no familial hereditary patterns reported.",
  "past_history": "Trucut Biopsy (Right Breast Lump) confirmed Invasive Ductal Carcinoma. Right Modified Radical Mastectomy & Axillary Lymph Node Dissection (pT2(m) pN3a, ER/PR+, HER2-). Adjuvant Chemotherapy completed.",
  "ongoing_treatment": "Completed External Beam Radiotherapy (40 Gy in 15 fractions). Active oncology follow-up and maintenance therapy.",
  "year_wise_history": [
    {
      "year": 2025,
      "title": "Diagnosis, Mastectomy & Chemotherapy Initiation",
      "summary": "Trucut biopsy confirmed IDC. Underwent Right Mastectomy and ALND...",
      "category": "surgery",
      "source_doc_id": "…",
      "exact_date": "2025-09-24"
    },
    {
      "year": 2026,
      "title": "Chemotherapy Completion & External Beam Radiotherapy",
      "summary": "Final chemo completed. External Beam Radiotherapy delivered...",
      "category": "radiotherapy",
      "source_doc_id": "…",
      "exact_date": "2026-05-27"
    }
  ],
  "current_medications": [
    {
      "brand_name": "Inj. Endoxan",
      "dose": "600mg",
      "freq": null,
      "indication": "Chemotherapy (Alkylating agent)",
      "report_date": "2026-09-14",
      "source_doc_id": "…",
      "is_latest_report": true
    },
    {
      "brand_name": "Tab. Pantop",
      "dose": "40mg",
      "freq": "OD",
      "indication": "Gastroprotection (PPI)",
      "report_date": "2026-09-14",
      "source_doc_id": "…",
      "is_latest_report": true
    }
  ],
  "concise_history_summary": "47-year-old F patient with confirmed Carcinoma Right Breast...",
  "generated_at": "2026-11-10T11:17:42Z",
  "model_id": "local-rules:summary@1.0",
  "is_cloud_generated": false
}
```

Key guarantees:
- Non-medication lab analytes (e.g., Triglycerides, Protein, Globulin, eGFR) are strictly excluded from `current_medications`.
- Medications are bounded to the patient's latest clinical report date.
- Letterhead and hospital boilerplate are stripped to prevent timeline hallucinations.

### `POST /api/patients/{id}/clinical-summary/refresh`

Requires the signed-in patient's own id. Query parameter: `use_cloud` (boolean, default `false`).
Forces synthesis of the clinical summary. When `use_cloud=true` is requested and cloud consent is approved with a configured Gemini API key, synthesis escalates to `gemini-3.8-flash-high` with `thinking_level="high"` before falling back to offline rules.

### `POST /api/patients/{id}/cloud-consent`

Requires the signed-in patient's own id.

```json
{
  "approved": true
}
```

Records patient-level cloud consent preference in the immutable `audit` ledger. Returns `{ "patient_id": "…", "approved": true, "updated_at": "…" }`.

**Current implementation limits:** `problems` is populated from primary diagnoses; `pending` is populated from directives persisted by the worker. Directive grammar is rules-first and covers common printed phrasings; reminder UI, supersession, and directive evaluation are not implemented. `results` includes observations with `status='review'` so extracted data is visible; the UI marks those points `Review`. They are not clinically validated. P3 normalisation/safety gates are not implemented. The default evaluation fixture is synthetic, so no accuracy claim is made.

### `GET /api/patients/{id}/timeline`

Requires the signed-in patient's own id. Returns logical reports newest first; a report is one timeline item and may contain several searchable facts. Rejected reports and observations are omitted.

Optional query parameters: `category` (`lab`, `imaging`, `prescription`, `discharge`, `pathology`, `other`), `from` and `to` (`YYYY-MM-DD`). Date filters compare `report_date`; undated reports are returned only when no date filter is supplied.

```json
{
  "patient_id": "…",
  "reports": [
    {
      "id": "…", "document_id": "…", "category": "imaging",
      "report_type": "ct", "report_date": "2024-03-02",
      "facility_name": "…", "title": "…", "summary": "…",
      "page_start": 1, "page_end": 2, "status": "auto", "reason": null,
      "review_count": 1,
      "facts": [
        { "id": "…", "report_id": "…", "document_id": "…",
          "fact_type": "impression", "label_raw": "Impression",
          "label_norm": "impression", "value_num": null,
          "value_text": "No acute abnormality.", "unit_norm": null,
          "page": 1, "bbox": [0.1, 0.2, 0.9, 0.3],
          "status": "review", "reason": "Grounded prose extraction…",
          "evidence_quote": "No acute abnormality." }
      ]
    }
  ]
}
```

`400 validation_error` when `from` is after `to`.

### `DELETE /api/patients/{id}`

Requires the signed-in patient's own id. Fences admission/consent, confirms owned processing has stopped and cleans raw/debug/scratch/source files before deleting account/submission/clinical rows in the final transaction. `204` clears the session cookie. Existing append-only audit remains. `503 cleanup_failed` means erasure is incomplete; retry metadata remains and processing stays paused. Irreversible. `403 demo_read_only` in the demo profile.

---

## 4. Documents

### `GET /api/documents?limit=20&offset=0&filter=All`

Owner-only, bounded upload inventory independent of clinical summaries. Includes every retained prepared document (queued, processing, failed, rejected-quality or completed), plus accepted submissions that have not produced a document yet. Returns `documents`, `has_more`, `offset`, and `limit` (1–50). Optional `filter` applies `All`, `Prescriptions`, `Lab reports`, `Scans & discharge`, or `Needs review` before pagination.

Each row includes its stable `id`, nullable `document_id`, nullable `job_id`/`job_state`, document metadata/status, nullable `page_count` and `retryable`. Pending uploads use the submission/job id and unknown page count; no fake clinical document is created. Prepared failed documents remain openable. Raw paths, hashes and processing manifests are not returned. Documents fetches this inventory on entry/refresh and polls nonterminal rows; all pages are accessible through pagination.

### `POST /api/jobs/{id}/retry`

Retries that requested optional cloud extraction require fresh mask approval; an explicit prior decline stays declined. Retrying never automatically resends an approved cloud payload.

Requeues an owner's failed or unassigned queued prepared job, without re-uploading or creating a second document. Requires live admission/consent, released batch membership, confirmed scratch cleanup and no existing clinical results. Clears obsolete scratch readiness/degradation flags, retains canonical sources, appends `retry_queued` to history, and resets current progress. Active ownership or unconfirmed cleanup returns 409; paused service returns 503; demo writes are forbidden. Successfully published or manually entered results are never replaced. Failed preparation with no retained prepared source requires a new upload.

### `POST /api/documents`

Requires the session cookie. `multipart/form-data`:

| Field | Type | Required |
|---|---|---|
| `patient_id` | string | yes — must be the signed-in patient |
| `file` | binary | yes |
| `doc_type` | `lab_report` \| `prescription` \| `pharmacy` \| `discharge_summary` \| `ct` \| `mri` \| `xray` \| `pathology` \| `radiology` \| `other` | no |
| `doc_date` | ISO date | no |
| `collection_date` | ISO date | no |
| `consent_scope` | `local` \| `local_plus_projection` | yes |

Omit `doc_type` (or send `other`) to let the local worker classify the document. **No `capture_type` field.** It is derived server-side (`FR-ING-02`).

When `doc_date` or `collection_date` is omitted, the worker extracts a labelled date from the local OCR text. Supplied values are preserved; date-of-birth lines are never used.

`202`:

```json
{ "document_id": null, "job_id": "…", "pages": null, "status": "pending_intake" }
```

HTTP validates metadata/type/actual byte limits and spools bounded chunks; it does not decode, render or invoke models. Preparation/quality failures are deferred to the same public job. PDFs have no page-count admission cap; internal windows are at most 20 pages. Storage, decoded-input, native-memory and time capacity failures remain possible.

`409 duplicate` → `{ "document_id": "…", "job_id": "…", "status": "done", "duplicate": true, "doc_type": "lab_report", "page_count": 2 }`. A pending duplicate instead has null document/counts and the existing pending `job_id`, which the client polls.

Duplicates are scoped to the signed-in patient: the content hash includes the patient id, so the same bytes can exist for two patients without being returned as each other's duplicate.

Deferred quality rejection creates no document or clinical facts; `GET /api/jobs/{id}` returns failed with `error_code: "rejected_quality"` and null document/counts. Raw input and partial preparation are cleaned. `503 service_unavailable` or storage/capacity errors can reject intake before acceptance. Unknown multipart fields (including `capture_type`) are rejected, not used as trusted classification.

`403 demo_read_only` when `SMRITI_PROFILE=demo`.

### `POST /api/documents/{id}/consent`

Requires ownership.

```json
{ "scope": "local_plus_projection", "version": "1.0" }
```

`201` → consent row. Uploads already write a consent row from `consent_scope`; this endpoint records a later change. A document without consent is never queued.

**Cloud redaction review approval (`CloudConsentCreate`):**
```json
{
  "approved": true,
  "extra_redaction_boxes": {
    "1": [[120, 340, 180, 220, "name", "mask-1"]]
  }
}
```
Masks are `[x,y,width,height,label,id]` in 0–1000 page coordinates. `approved` must be a JSON boolean. Approval must include an entry for every reviewed page, including pages with no masks. The saved approval is required before Gemini egress.

### `GET /api/documents/{id}/redaction-preview`

Requires ownership. Optional `offset=0`. Returns at most 20 local source-page previews with editable mask proposals awaiting cloud approval:

```json
{
  "total": 2,
  "pages": [
    { "page_num": 1, "jpeg_base64": "…", "sha256": "…",
      "masks": [[120, 340, 180, 220, "name", "mask-1"]] }
  ]
}
```

Responses include `Cache-Control: no-store`. These previews stay local; Gemini receives newly encoded images only after the saved approval and final masks are applied.

### `GET /api/documents/{id}`

Requires ownership.

Optional `page` (positive source page) and `offset` (nonnegative result-range offset). Documents over 20 pages default to page one; smaller documents retain the bounded whole-document shape. Observations/reports/medications/egress arrays contain at most 100 entries, with `detail_page`, `offset`, and `has_more` for navigation; page text/source links are also bounded. Oversized strings/response capacity return `413 detail_capacity`, never silently truncate clinical content. Cross-owner reads remain `404`.

```json
{
  "id": "…",
  "patient_id": "…",
  "doc_type": "lab_report",
  "doc_type_confidence": 0.91,
  "capture_type": "printed",
  "doc_date": "2025-11-02",
  "collection_date": "2025-11-02",
  "lab_name": null,
  "page_count": 2,
  "quality_score": 0.91,
  "status": "done",
  "processed_at": "…",
  "created_at": "…",
  "consent": { "scope": "local", "granted_at": "…", "revoked_at": null },
  "egress": [
    {
      "id": "…",
      "payload_sha256": "…",
      "model_id": "gemini-3.8-flash-high",
      "prompt_version": "redacted-clinical@1",
      "schema_version": "window@1",
      "outcome": "sent",
      "reason": null,
      "ts": "2026-11-10T12:00:00Z"
    }
  ],
  "page_text": [{ "page": 1, "text": "…", "engine": "paddle" }],
  "reports": [
    { "id": "…", "category": "imaging", "report_type": "ct",
      "report_date": "2024-03-02", "facility_name": "…", "title": "…",
      "summary": "…", "page_start": 1, "page_end": 2, "status": "auto",
      "reason": null, "model_version": "report-segmenter@1.0",
      "created_at": "…", "fact_count": 4, "review_count": 4 }
  ],
  "observations": [
    { "id": "…", "document_id": "…", "report_id": "…",
      "analyte_id": "hba1c", "label_raw": "HbA1c", "label_norm": "hba1c",
      "fact_type": "lab", "evidence_quote": null,
      "value_num": "8.9", "value_text": "8.9", "unit_raw": "%",
      "unit_norm": null, "ref_low": "4", "ref_high": "6",
      "flag_printed": "H", "bbox": [0.1, 0.2, 0.3, 0.4], "page": 1,
      "engine": "paddle:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec+local-rules:line-rules@1.0+cpu",
      "confidence": 0.667,
      "status": "review", "reason": "Extracted locally; review required.",
      "mapping_rule": "exact", "created_at": "…" }
  ],
  "medications": [],
  "pages": [{ "page": 1, "url": "/api/documents/…/page/1" }]
}
```

Extracted observations are written as `review`; the review endpoint moves them to `auto` or `rejected`. Prose facts (impression, findings, diagnosis, recommendation) use `value_text`; numeric lab facts keep `value_num`. Handwritten documents produce no numeric observations.

### `GET /api/documents/{id}/page/{n}`

Requires ownership. Binary `image/webp`. `404` when the document, page, or stored image is missing. A processing failure retains prepared source images; a preparation rejection has no document/image link. `Cache-Control: private, max-age=3600`.

---

## 5. Jobs

### `GET /api/jobs?scope=active&limit=20&offset=0`

Requires a patient session; returns only the signed-in owner's jobs. `scope` is `active` (API default: queued/running, oldest submission first), `all` (all retained jobs), `failed` (processing/preparation failures), or `recent` (done/failed). Other scopes use newest submission first and paginate independently. Queue defaults to All so failed uploads remain discoverable, with Active/Failed/Recent filters. `limit` defaults to 20, range 1–50; `offset` defaults to 0, range 0–2147483647. Invalid query values return the house `400 validation_error` response.

```json
{
  "jobs": [{
    "id": "…", "state": "running", "document_id": "…", "doc_type": "lab_report",
    "total": 73, "total_pages": 73, "created_at": "2026-11-07T10:00:00+00:00",
    "stage": "qwen", "model": "vlm:qwen3-vl-4b@q4_k_m+cuda",
    "current_page": 3, "completed_pages": 2, "stage_total": 59,
    "started_at": "2026-11-07T10:00:00+00:00", "finished_at": null,
    "elapsed_seconds": null, "error_code": null,
    "activity": "Qwen3-VL is reading page independently"
  }],
  "has_more": false, "offset": 0, "limit": 20
}
```

The compact list excludes event history, medical text, filenames/paths, private spool/batch data and logging/measurement payloads. Pending/preparing submissions have null document links and totals; deferred failures remain in Recent. Historical jobs without submissions are discoverable but are not recovered/requeued by either GET endpoint. Only a selected job fetches its bounded detailed history from the endpoint below. Offset pages are live snapshots, not a frozen cursor.

### `GET /api/jobs/{id}`

Requires ownership.

```json
{
  "id": "…", "state": "running", "page": 2, "total": 2, "error": null,
  "stage": "qwen", "model": "vlm:qwen3-vl-4b@q4_k_m+cuda",
  "current_page": 1, "completed_pages": 0, "stage_total": 2,
  "started_at": "2026-11-05T10:00:00+00:00",
  "updated_at": "2026-11-05T10:00:08+00:00",
  "finished_at": null, "elapsed_seconds": null,
  "verification_state": "running", "failure_context": null,
  "events_truncated": 0,
  "events": [{
    "sequence": 1, "timestamp": "2026-11-05T10:00:08+00:00",
    "event": "qwen_reading", "stage": "qwen", "level": "info",
    "message": "Qwen3-VL is reading page independently",
    "model": "vlm:qwen3-vl-4b@q4_k_m+cuda", "page": 1
  }]
}
```

`state ∈ queued | running | done | failed`. Original fields are unchanged: `page` counts completed OCR/text-layer pages, not overall processing. The additive snapshot reports the actual stage, engine, current page, and stage-specific completed/total pages; unknown values are null. OCR completion does not imply extraction or verification completion. Stages are `queued`, `ocr_loading`, `ocr`, `classification`, `extraction`, `qwen_loading`, `qwen`, `cross_check`, `cleanup`, `saving`, and `done`.

Events are ordered by increasing sequence and contain code-owned operational messages, never document text, values, prompts, raw model responses, credentials, or private file paths. Optional event metadata includes `model`, `page`, `count`, `duration_seconds`, `error_type`, safe failure `code`, and HTTP failure `status`; levels are `info`, `success`, `warning`, and `error`. The latest 500 events are retained, with `events_truncated` counting older omitted events. Current snapshot state is independent of retained history. `verification_state` is null (unknown/not yet started), `running`, `skipped`, `partial` (handwritten or unavailable pages), `unavailable` (no independent fields; OCR-only review), or `compared`; it describes readings, not medical correctness or approval. Recovery clears per-attempt verification and failure context while retaining ordered history. `recovering` activity precedes validated `recovered`; admission stays closed during recovery. Successful list/detail polls are not logged; failed polls retain safe diagnostics.

UTC timestamps mark real boundaries; terminal `elapsed_seconds` spans intake-to-finish wall time, including queue/recovery waits. Per-operation `duration_seconds` uses monotonic timing, including publication duration on `done`. A failed job includes a safe short error, safe `error_code` where available and `failure_context` containing `stage`, `model`, and `current_page` from the failing operation, even if cleanup ran afterward. Prepared sources remain stored. Historical jobs without saved telemetry return null snapshot fields, empty `events`, and zero truncation; no history is fabricated.

Qwen failures additionally retain `failure_context.code` and, for `qwen_http_error`, integer `status` (400–599). Specific categories are `qwen_http_error`, `qwen_connection_failed`, `qwen_server_exited` (exit directly observed when the connection fails, not an OOM diagnosis), `qwen_transfer_failed`, `qwen_response_invalid` (invalid response envelope), and `qwen_output_invalid` (invalid model array/items or nonfinite numeric value). Existing timeout/request/capacity categories remain. Response bodies, raw exception text and server stdout/stderr are never retained. A valid JSON array, optionally fenced, may be `[]`; malformed output is a failed reading, not successful emptiness. Under approved §13.9, operational failures after confirmed shutdown freeze missing printed-page outcomes, retain valid readings/OCR and publish once for review. `qwen_unavailable_page`, `verification_partial`, and `verification_unavailable` distinguish this from complete independent comparison. Unmatched OCR fields retain confidence and explicit OCR-only review provenance. Missing unexplained/corrupt artifacts, capacity/consent failures and unconfirmed cleanup remain blocking.

`current_page` is the original source page. During Qwen reading, `completed_pages / stage_total` counts resolved eligible printed-page outcomes, including durable unavailable outcomes; these can differ from source-page totals. Partial progress says “resolved,” not that unavailable pages were read. After a terminal failure, later stages display “Not reached,” not “Waiting.”

Pending/preparing jobs keep null `document_id`, `total_pages`, `total` and stage counts until durable preparation promotes the same ID and ordered history. Additive `support_id`, durable `latest_failure`, and per-sink `logging.{file,terminal}.{available,degraded}` expose diagnosis without global counters, batch membership or shared memory measurements. File/terminal logs and shared measurements are not downloadable through the job API.

The intake view uses one non-overlapping polling loop, scheduling two seconds after completion. It preserves the last snapshot and retries transient GET failures; it stops on terminal jobs, missing resources, expired/forbidden sessions, or unmount. Done provides a review link without automatically downloading document detail; bounded detail is fetched only in the review journey. Uploads are never automatically retried.

Bulk intake uses the existing `POST /api/documents` once per file, with one POST in flight. Each file keeps its own outcome and document/job links; duplicate 409 responses do not create jobs. Consent is recorded per accepted file; optional type/date overrides apply to the selection. Only failed upload requests offer explicit retry. Unsent file selections do not survive navigation/reload; accepted server jobs continue independently and remain discoverable in Queue.

Client hash routes are `#/summary`, `#/intake`, `#/queue`, and `#/documents/<id>?page=N` (page 1 omits the query). Hash changes/back/forward and refresh load the addressed view; unknown routes default to Summary and invalid page numbers to 1. Document page controls update the URL. Leaving Intake with unsent files asks for confirmation. Queue polls the compact Active page every two seconds after completion without overlapping requests, fetching at most one selected detailed history. Recent is idle until selection/navigation/Refresh; terminal details and expired sessions stop polling. Navigation aborts outstanding reads. Transient failures retain last progress; Recent offers manual Refresh. Opening a document from Queue provides “Back to queue.” These routes do not bypass session/ownership checks or add automatic retry/recovery.

---

## 6. Review

Requires the session cookie. The owning patient may review a field; another patient gets `404`. The demo profile returns `403 demo_read_only`.

### `POST /api/observations/{id}/review`

```json
{ "action": "correct", "value_num": "13.4", "unit_norm": "g/dL", "reason": "OCR read 13.2" }
```

| Action | Body | Result |
|---|---|---|
| `accept` | — | `status=auto`, audit row |
| `correct` | `value_num` for numeric facts, or `value_text` for prose facts; optional `unit_norm` | `status=auto`, original retained in audit (DR-03) |
| `reject` | optional `reason` | `status=rejected`, never charted |

`200` → the updated observation plus the recomputed seven-key summary (`FR-REV-05`):

```json
{
  "observation": { "id": "…", "status": "auto", "value_num": "13.4", "…": "…" },
  "summary": { "patient": {}, "coverage": {}, "problems": [], "medications": [],
               "results": [], "pending": [], "documents": [] }
}
```

Numeric `accept` and `correct` require a mapped analyte and a finite decimal; it is stored canonically (`9.10` → `9.1`). Prose facts use `value_text` and can be accepted or corrected without an analyte. Unmapped numeric fields can only be rejected. Handwritten fields return `409 handwriting_review_required` until the handwriting flow exists. A second review returns `409 already_reviewed`. Every action writes `audit` rows for `status`, and for changed `value_num`/`value_text`/`unit_norm`.

### `PATCH /api/reports/{id}`

Requires ownership. Corrects report-level metadata; facts keep their own review endpoint. Send any subset of:

```json
{ "report_date": "2024-03-03", "category": "imaging",
  "title": "CT chest", "facility_name": "…", "summary": "…" }
```

`200` → `{ "report": { "id": "…", "status": "auto", "…": "…" } }`. Every changed field writes an `audit` row. A report with no date, or category `other`, stays in `review`. `400 validation_error` for an empty body; `404 not_found` for another patient's report.

---

## 7. Deep views, handwriting, and share — contract-only

These shapes remain frozen for later phases; no route in this section is implemented.

### `GET /api/patients/{id}/observations?analyte=hba1c`

Full series for one analyte, all points, all statuses except `rejected` (which are returned only with `?include_rejected=true`, for the audit view).

### `GET /api/patients/{id}/directives`

```json
[{
  "id": "…", "span_text": "R/V after 2 weeks", "document_id": "…",
  "action_type": "review", "timing_type": "relative",
  "time_value": 2, "time_unit": "week",
  "anchor_event": "collection_date", "anchor_date": "2025-11-02",
  "due_date": "2025-11-16", "state": "open",
  "condition_text": null, "target": "review"
}]
```

### `POST /api/medications/{id}/report`

```json
{ "status": "reported_stopped", "reported_at": "2026-01-10T00:00:00Z" }
```

Creates a new row. Never updates an existing one (`FR-MED-02`).

### `GET /api/documents/{id}/handwriting-fields`

```json
[{
  "id": "…", "page": 1, "bbox": [0.21, 0.33, 0.62, 0.38],
  "field_type": "drug", "context_text": "Tab. Telma 40 mg  1-0-0  x 30 days",
  "candidates": [
    { "value": "Telma", "score": 0.81 },
    { "value": "Telma-H", "score": 0.44 },
    { "value": "Telmik", "score": 0.39 }
  ],
  "status": "review"
}]
```

`candidates` has 0–3 entries and **no `selected` flag**. An empty array means the system abstained; the UI shows a search box.

### `POST /api/handwriting-fields/{id}/review`

```json
{ "action": "accept", "value": "Telma", "ms_to_verify": 1840 }
```

| Action | Body |
|---|---|
| `accept` | `value` (one of the candidates) |
| `correct` | `value` (free text) |
| `reject` | `reason` |
| `add` | `bbox`, `field_type`, `value` |

`200` → `{ "status": "resolved", "remaining": 3 }`.

Every action writes a row with `ms_to_verify`. No action means no state change: a field cannot leave `review` by timeout, default, or batch accept.

### `POST /api/share`

```json
{ "patient_id": "…", "ttl_minutes": 30 }
```

`201` → `{ "token": "…", "pin": "482913", "expires_at": "…" }`

The PIN is returned once and stored hashed. `ttl_minutes` is capped at 30.

### `GET /api/share/{token}?pin=482913`

`200` → the summary payload, read-only, plus `"intended_use": "Research prototype. Not for clinical use."`

`401` invalid PIN, `423` locked after five attempts, `410` expired or revoked.

Every attempt writes an audit row (`FR-SHR-04`).

---

## 8. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 23 Oct 2026 | Initial frozen contract: 15 endpoints, seven-key summary payload |
| 1.1 | 23 Oct 2026 | Add `GET /api/documents/{id}/page/{n}`; document quality-rejection semantics |
| 1.2 | 23 Oct 2026 | Per-patient accounts and session auth; optional `doc_type`; authenticated document/job/summary routes; duplicate response fields; extracted detail fields; summary API live; review/handwriting/share marked contract-only |
| 1.3 | 24 Oct 2026 | Observation review endpoint and audit; `status` on result points; `review_count` on documents; labelled date extraction; review UI and live page images |
| 1.4 | 26 Oct 2026 | Schema v8 logical reports; timeline and report-correction endpoints; report-grouped facts; text-only prose review |

# API Contract

Status: v1.3. The auth, document, job, patient-summary, observation-review, and erase-all endpoints are implemented. Sections marked **contract-only** are frozen shapes for later phases and are not served yet.

Base path: `/api`. All requests and responses are JSON except the upload (`multipart/form-data`) and the page-image response (`image/webp`).

---

## 1. Conventions

- **Every route except `/auth/register`, `/auth/login`, `/auth/logout`, and `/health` requires a patient session.** The session is an `HttpOnly`, `SameSite=Strict` cookie named `smriti_session`; the token is stored hashed in SQLite.
- **A patient can only access their own records.** Patient-id routes return `403` for another patient; document, page, and job routes return `404` to avoid confirming existence.
- **Local HTTP only by default.** The cookie is not `Secure`; terminate TLS and enable `Secure` before exposing the app beyond localhost.
- **No pagination.** 40 documents is not a paging problem.
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

**Current implementation limits:** `problems` is always `[]`; `pending` is populated from directives persisted by the worker. Directive grammar is rules-first and covers common printed phrasings; reminder UI, supersession, and directive evaluation are not implemented. `results` includes observations with `status='review'` so extracted data is visible; the UI marks those points `Review`. They are not clinically validated. P3 normalisation/safety gates are not implemented. The default evaluation fixture is synthetic, so no accuracy claim is made.

### `DELETE /api/patients/{id}`

Requires the signed-in patient's own id. Erase-all: rows and files, one transaction, one audit row. `204`; clears the session cookie. Required by the consent protocol (`docs/ethics-consent.md` §7). Irreversible. `403 demo_read_only` in the demo profile.

---

## 4. Documents

### `POST /api/documents`

Requires the session cookie. `multipart/form-data`:

| Field | Type | Required |
|---|---|---|
| `patient_id` | string | yes — must be the signed-in patient |
| `file` | binary | yes |
| `doc_type` | `lab_report` \| `prescription` \| `pharmacy` \| `other` | no |
| `doc_date` | ISO date | no |
| `collection_date` | ISO date | no |
| `consent_scope` | `local` \| `local_plus_projection` | yes |

Omit `doc_type` (or send `other`) to let the local worker classify the document. **No `capture_type` field.** It is derived server-side (`FR-ING-02`).

When `doc_date` or `collection_date` is omitted, the worker extracts a labelled date from the local OCR text. Supplied values are preserved; date-of-birth lines are never used.

`202`:

```json
{ "document_id": "…", "job_id": "…", "pages": 2, "status": "queued" }
```

`409 duplicate` → `{ "document_id": "…", "status": "done", "duplicate": true, "doc_type": "lab_report", "page_count": 2 }`

Duplicates are scoped to the signed-in patient: the content hash includes the patient id, so the same bytes can exist for two patients without being returned as each other's duplicate.

`422 quality_rejected` → the document row is kept with `status=rejected_quality`, no job is created, and no page files are stored. The message names the failing page and check.

`403 demo_read_only` when `SMRITI_PROFILE=demo`.

### `POST /api/documents/{id}/consent`

Requires ownership.

```json
{ "scope": "local_plus_projection", "version": "1.0" }
```

`201` → consent row. Uploads already write a consent row from `consent_scope`; this endpoint records a later change. A document without consent is never queued.

### `GET /api/documents/{id}`

Requires ownership.

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
  "egress": [],
  "page_text": [{ "page": 1, "text": "…", "engine": "paddle" }],
  "observations": [
    { "id": "…", "analyte_id": "hba1c", "label_raw": "HbA1c",
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

Extracted observations are written as `review`; the review endpoint moves them to `auto` or `rejected`. Handwritten documents produce no numeric observations.

### `GET /api/documents/{id}/page/{n}`

Requires ownership. Binary `image/webp`. `404` when the document, page, or stored image is missing; rejected and failed documents have no page images. `Cache-Control: private, max-age=3600`.

---

## 5. Jobs

### `GET /api/jobs/{id}`

Requires ownership.

```json
{ "id": "…", "state": "running", "page": 1, "total": 2, "error": null }
```

`state ∈ queued | running | done | failed`. The UI polls every 2 s and stops on a terminal state. A failed job includes a short error string; the document status is `failed`.

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
| `correct` | `value_num`, optional `unit_norm` | `status=auto`, original retained in audit (DR-03) |
| `reject` | optional `reason` | `status=rejected`, never charted |

`200` → the updated observation plus the recomputed seven-key summary (`FR-REV-05`):

```json
{
  "observation": { "id": "…", "status": "auto", "value_num": "13.4", "…": "…" },
  "summary": { "patient": {}, "coverage": {}, "problems": [], "medications": [],
               "results": [], "pending": [], "documents": [] }
}
```

`accept` and `correct` require a mapped analyte and a numeric value. Unmapped fields can only be rejected. Handwritten fields return `409 handwriting_review_required` until the handwriting flow exists. A second review returns `409 already_reviewed`. A corrected value must be a finite decimal; it is stored canonically (`9.10` → `9.1`). Every action writes `audit` rows for `status`, and for changed `value_num`/`unit_norm`.

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

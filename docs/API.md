# API Contract

Status: frozen at week 2. Additions permitted; breaking changes are not (SRS §5.4.4).

Base path: `/api`. All requests and responses are JSON except the upload, which is `multipart/form-data`.

---

## 1. Conventions

- **No authentication on the local API.** The deployment model is one operator on one machine. The share link has its own PIN.
- **No pagination.** 40 documents is not a paging problem.
- **Every observation-bearing response includes provenance.** A value without `document_id`, `page`, and `bbox` is a contract violation (SRS §3.5.1).
- **Errors** are always:

```json
{ "error": { "code": "quality_rejected", "message": "Short edge 640 px is below 1000 px.", "field": "file" } }
```

| Code | HTTP | Meaning |
|---|---|---|
| `validation_error` | 400 | Malformed request |
| `consent_required` | 403 | No consent row for this document |
| `demo_read_only` | 403 | Upload or write attempted in `demo` profile |
| `not_found` | 404 | Unknown id |
| `duplicate` | 409 | Content hash already ingested (returns the existing document) |
| `share_locked` | 423 | Five failed PIN attempts |
| `job_failed` | 409 | Retry required |
| `resolver_unavailable` | 200 | Document processed locally; review queue populated |

- **Ids** are opaque UUID strings. No endpoint accepts a filename.

---

## 2. Patients

### `POST /api/patients`

```json
{ "alias": "P-01", "sex": "F", "dob": null }
```

`201` → `{ "id": "…", "alias": "P-01", "created_at": "2026-10-23T09:00:00Z" }`

`alias` is the only display identifier. No endpoint accepts a real name.

### `DELETE /api/patients/{id}`

Erase-all: rows and files, one transaction, one audit row. `204`.

Required by the consent protocol (`docs/ethics-consent.md` §7). Irreversible.

---

## 3. Documents

### `POST /api/documents`

`multipart/form-data`:

| Field | Type | Required |
|---|---|---|
| `patient_id` | string | yes |
| `file` | binary | yes |
| `doc_type` | `lab_report` \| `prescription` \| `pharmacy` \| `other` | yes |
| `doc_date` | ISO date | no |
| `collection_date` | ISO date | no |
| `consent_scope` | `local` \| `local_plus_projection` | yes |

**No `capture_type` field.** It is derived server-side (`FR-ING-02`).

`202`:

```json
{ "document_id": "…", "job_id": "…", "pages": 2, "status": "queued" }
```

`409 duplicate` → `{ "document_id": "…", "status": "done", "duplicate": true }`

`403 demo_read_only` when `SMRITI_PROFILE=demo`.

### `POST /api/documents/{id}/consent`

```json
{ "scope": "local_plus_projection", "version": "1.0" }
```

`201` → consent row. Required before the job is created; a document without consent is never queued.

### `GET /api/documents/{id}`

```json
{
  "id": "…",
  "doc_type": "lab_report",
  "capture_type": "printed",
  "doc_date": "2025-11-02",
  "collection_date": "2025-11-02",
  "page_count": 2,
  "quality_score": 0.91,
  "status": "done",
  "consent": { "scope": "local", "granted_at": "…", "revoked_at": null },
  "egress": [],
  "pages": [{ "page": 1, "url": "/api/documents/…/page/1" }]
}
```

---

## 4. Jobs

### `GET /api/jobs/{id}`

```json
{ "id": "…", "state": "running", "page": 1, "total": 2, "error": null }
```

`state ∈ queued | running | done | failed`. UI polls every 2 s and stops on a terminal state.

---

## 5. Review

### `POST /api/observations/{id}/review`

```json
{ "action": "correct", "value_num": "13.4", "unit_norm": "g/dL", "reason": "OCR read 13.2" }
```

| Action | Body | Result |
|---|---|---|
| `accept` | — | `status=auto`, audit row |
| `correct` | `value_num`, optional `unit_norm` | `status=auto`, original retained (DR-03) |
| `reject` | `reason` | `status=rejected`, never charted |

`200` → the updated observation plus the recomputed summary fragment (`FR-REV-05`).

Handwritten fields are reviewed through §8, not here.

---

## 6. Summary — the frozen payload

### `GET /api/patients/{id}/summary`

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
          "bbox": [0.61, 0.42, 0.78, 0.47] }
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
      "collection_date": "2025-11-02", "page_count": 2, "status": "done" }
  ]
}
```

Rules the fixture enforces:

- `results[].points[].bbox` is always present and always length 4.
- `excluded` exists even when empty — a rejection is never invisible (`FR-TIM-09`).
- `medications[].state` is never merged; the same drug may appear three times.
- `pending` contains no item whose `due_date` was already past at extraction.
- `coverage.gaps[].text` states a duration, never an interpretation.

---

## 7. Deep views

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

---

## 8. Handwriting

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

---

## 9. Share

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

## 10. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 23 Oct 2026 | Initial frozen contract: 15 endpoints, seven-key summary payload |

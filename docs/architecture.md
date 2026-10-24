# Architecture

Status: draft. Owns runtime structure and trust boundaries, not requirements (SRS) or module contracts (specs).

---

## 1. Context

```
┌──────────────────┐        ┌──────────────────────────────────┐
│ Patient (account)│───────▶│ Smriti (local machine)           │
│                  │        │ upload · local OCR · review · UI │
└──────────────────┘        └───────────────┬──────────────────┘
                                            │ no image or OCR text
                                            │ leaves this process
                                            ▼
                            ┌──────────────────────────────────┐
                            │ Optional resolver (P6, not wired)│
                            │ typed projection only            │
                            └──────────────────────────────────┘
```

Each patient has a local account and sees only their own records. There is no clinic operator or admin role in this build. The deployment model is one machine; the current extraction path is entirely local.

The optional resolver remains a future P6 path. It is disabled by default and no extraction call uses it. If enabled, it may receive only a typed projection, never an image, OCR text, free text, date, or patient identifier.

## 2. Containers

| Container | Technology | Responsibility |
|---|---|---|
| Web app | React (JS), Vite, Tailwind, Recharts | Account gate, upload, progress, document review, summary, live source overlay |
| API | FastAPI, Pydantic v2 | HTTP contract, auth, ownership checks, validation, review, orchestration |
| Auth | `smriti/auth.py` | scrypt password hashes, hashed session tokens, cookie sessions, ownership helpers |
| Pipeline | Python modules | Local OCR, classification, rule/date extraction, review transitions, summary assembly |
| Worker | One background thread | Claims jobs from SQLite, runs OCR/classification/extraction |
| Store | SQLite v2 (WAL) + filesystem | Accounts, records, page text; page images under `data/uploads/<patient-scoped-hash>/` |
| Harness | `eval/` | Offline metrics from a frozen truth set (not implemented yet) |

One process. The worker is a thread started at app startup, not a second service. Concurrency is deliberately one.

## 3. Trust boundaries

Four boundaries, in order of importance.

### 3.1 Account boundary — each patient is isolated

- Registration creates a patient account; login issues a random session token.
- Passwords are stored as scrypt hashes. Session tokens are stored as SHA-256 hashes; the raw token exists only in the `HttpOnly`, `SameSite=Strict` cookie.
- Every patient, document, page, job, and summary route resolves the session and checks ownership. A missing session is `401`; another patient's record is `403` for patient ids and `404` for document/job ids.
- There is no operator/admin role. A patient cannot list or read another patient's records.
- This is local per-patient isolation, not clinic multi-tenancy or RBAC. There is no shared clinic workspace and no role hierarchy.
- The local app is served over HTTP, so the cookie is not `Secure`. Terminate TLS and enable `Secure` before exposing it beyond localhost.

A v1 database has no accounts. On first registration, the sole unowned patient is claimed so existing local records stay reachable. If more than one unowned patient exists, no automatic claim is made.

### 3.2 Device boundary — local extraction

```
image bytes ──▶ PaddleOCR ──▶ page_text ──▶ classifier ──▶ rules ──▶ observations
     │                                                               │
     └────────────── never leaves the device ────────────────────────┘
```

OCR, document-type classification, and field extraction run locally. The current build makes no outbound AI call and has no image or OCR-text egress path. The typed-projection resolver is future work and is not used by the extraction worker.

### 3.3 Process boundary — untrusted input

Uploads are the only untrusted bytes. They are validated (type, dimensions, decode), re-encoded, stripped of EXIF, and stored under a patient-scoped content hash. The original buffer is never written and never served.

Path traversal is prevented by addressing files by hash, never by a user-supplied name (NFR-06). Page-image and worker paths are resolved under the upload root and rejected if they escape it.

### 3.4 Presentation boundary — patient only

The UI is patient mode only. There is no clinician mode or share view in this build. Every displayed value keeps its document, page, and bounding box. The dashboard shows the source page with the extracted box; pending values are marked `Review`, and the document review screen accepts, corrects, or rejects each field.

## 4. Data flow

```
POST /api/documents (session cookie; patient_id must be the signed-in patient)
   ├─ validate type, size, decode
   ├─ consent row (required)
   ├─ patient-scoped content hash → dedupe within this patient
   ├─ quality gate → reject or accept
   ├─ EXIF strip → perspective → deskew → CLAHE → upscale
   ├─ write pages under data/uploads/<patient-scoped-hash>/
   └─ insert job(state=queued) → 202 {job_id}

worker claims job (BEGIN IMMEDIATE)
   ├─ per page: PaddleOCR → words + boxes → page_text
   ├─ classify document type from page text
   ├─ extract labelled collection/report dates from OCR text
   ├─ printed lab/other: line-based analyte rules → review observations
   ├─ printed prescription/pharmacy: medication rules → prescribed rows
   ├─ handwritten: no numeric extraction (SI-01/SI-02)
   └─ commit document status=done, processed_at, dates (user values win)

POST /api/observations/{id}/review
   ├─ accept/correct: mapped printed value → auto, audit
   ├─ reject: → rejected, audit
   └─ return updated observation + recomputed summary

GET /api/patients/{id}/summary
   └─ build the frozen seven-key payload from documents, observations,
      medications, directives, and coverage
```

A failed job marks the job and document `failed`; page text already written for earlier pages remains for diagnosis, but no observation/medication rows are committed for the failed run.

The summary includes `review` observations so extracted data is visible and marks them with `status="review"`; accepted values are `auto`, rejected values are omitted. They are not clinically validated results. P3 normalisation/safety gates are not implemented.

## 5. Runtime profiles

| Profile | Uploads | Egress | Data | Use |
|---|---|---|---|---|
| `local-gpu` | On | Off; no egress path wired | Real documents | Development and the actual study |
| `demo` | Off | Off, unconditionally | Synthetic corpus | Public URL |

`demo` is safe by construction, not by configuration discipline: registration/upload/delete return `403`, and the database is intended to be read-only.

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| PaddleOCR model unavailable | Job fails with a recorded error; document `failed`; no partial extraction rows |
| Quality gate rejects a page | Upload rejected with an actionable message; no job is created |
| Worker crashes mid-document | Job/document can be retried; extraction rows are replaced transactionally on the next run |
| Disk full | Job fails, document stays `failed`, no partial observation rows |
| SQLite locked | Single writer means this should not happen; if it does, retry once then fail loudly |
| Session expired | `401 session_expired`; the UI returns to sign-in |
| Legacy patient unowned | First registration claims it; otherwise records remain inaccessible until a claim path exists |

No failure mode guesses a value. The worker writes extracted numeric fields with `status='review'`; only an explicit patient review sets `auto` or `rejected`.

## 7. Deployment

```
Dockerfile
  build stage: npm ci && npm run build
  runtime: Python 3.11 + PaddleOCR/PaddlePaddle wheels + web/dist
  CMD uvicorn smriti.main:app --host 127.0.0.1 --port 8000
```

| Target | Notes |
|---|---|
| Local | Native venv. No Docker Desktop in development — it competes for the 8 GB (RISK-09) |
| HF Spaces (CPU, 16 GB) | Fits the measured peak; 512 MB free tiers do not |
| Oracle Always Free (ARM) | Possible, but PaddleOCR wheels on ARM are friction; not the primary target |

One worker in every profile. The first request that needs OCR loads the cached models; there is no second service.

## 8. Non-goals

No microservices, no message broker, no Redis, no Postgres, no Kubernetes, no external auth provider, no client-side storage of medical data, no clinician/admin role. Each of these would add a failure mode without adding a capability the project needs.

# Architecture

Status: draft. Owns runtime structure and trust boundaries, not requirements (SRS) or module contracts (specs).

---

## 1. Context

```
┌──────────────┐        ┌──────────────────────────────┐
│   Patient    │───────▶│  Smriti (local machine)      │
│  (owner)     │        │  upload · review · dashboard │
└──────────────┘        └───────────────┬──────────────┘
                                        │ typed projection only
                                        ▼
                        ┌──────────────────────────────┐
                        │ Optional resolver            │
                        │ local rules / self-hosted /  │
                        │ Sarvam / Gemini (synthetic)  │
                        └──────────────────────────────┘
```

The clinician and the researcher are read-only actors on the same instance. There is no multi-tenancy, no account system, and no server-side identity — the deployment model is one operator, one machine.

## 2. Containers

| Container | Technology | Responsibility |
|---|---|---|
| Web app | React (JS), Vite, Tailwind, Recharts | Upload, review, dashboard, share view |
| API | FastAPI, Pydantic v2 | HTTP contract, validation, orchestration |
| Pipeline | Python modules | OCR, assembly, normalisation, gates, directives |
| Worker | One background loop | Claims jobs from SQLite, runs the pipeline |
| Store | SQLite (WAL) + filesystem | Records; page images under `data/uploads/<sha256>/` |
| Harness | `eval/` | Offline metrics from a frozen truth set |

One process. The worker is a thread started at app startup, not a second service.

## 3. Trust boundaries

Three boundaries, in order of importance.

### 3.1 Device boundary — crossed only by a projection

```
image bytes ──▶ never crossed ──────────────────────────
OCR text    ──▶ never crossed ──────────────────────────
projection  ──▶ vocabulary tokens + numbers ──▶ resolver
```

The projection is constructed by `smriti/projection.py` from a Pydantic model. There is no dictionary path to the HTTP client, so a free-text field cannot be added by accident. A CI test monkeypatches the client and fails on any payload containing an image, base64, a date, or a string outside the vocabulary.

**This is stricter than SRS v1.0 permitted.** v1.0 allowed redacted images; v1.1 forbids all images. The stricter rule wins because it is testable.

### 3.2 Process boundary — untrusted input

Uploads are the only untrusted bytes. They are validated (type, dimensions, decode), re-encoded, stripped of EXIF, and stored under a content hash. The original buffer is never written and never served.

Path traversal is prevented by addressing files by hash, never by user-supplied name (NFR-06).

### 3.3 Presentation boundary — patient vs clinician

Same payload, different defaults. The shared view is read-only and always carries the intended-use statement. No view ever shows a value without its source path.

## 4. Data flow

```
POST /api/documents
   ├─ validate type, size, decode
   ├─ consent row (required)
   ├─ content hash → dedupe
   ├─ quality gate → reject or accept
   ├─ EXIF strip → perspective → deskew → CLAHE → upscale
   ├─ write pages under data/uploads/<sha256>/
   └─ insert job(state=queued) → 202 {job_id}

worker claims job (BEGIN IMMEDIATE)
   ├─ per page: OCR → words + boxes
   ├─ assembly → rows → candidates
   ├─ rules resolver (label, range, unit — 2 of 3)
   ├─ residual → projection → [resolver] → validated mapping
   ├─ normalise (Decimal, LOINC, unit map)
   ├─ safety gates → auto | review | rejected
   ├─ directives + medications
   └─ commit per document (transactional)
```

A failed job rolls back its document writes and leaves the document in `failed`, never partially charted (FR-JOB-03).

## 5. Runtime profiles

| Profile | Uploads | Egress | Data | Use |
|---|---|---|---|---|
| `local-gpu` | On | Off by default, per-document opt-in | Real documents | Development and the actual study |
| `demo` | Off | Off, unconditionally | Synthetic corpus | Public URL |

`demo` is safe by construction, not by configuration discipline: the upload route returns 403, the egress adapter is `Null`, and the database is read-only.

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| OCR model missing | Startup fails fast with a clear message; no silent fallback to a worse model without recording it |
| Quality gate rejects a page | Document `rejected_quality`, actionable re-shoot message, no partial processing |
| Resolver unreachable | Review queue with `resolver_unavailable`; local path continues (NFR-16) |
| Resolver returns junk | Response discarded, field goes to review (FR-EGR-06) |
| Worker crashes mid-document | Job retried; transaction rollback means no duplicates (FR-JOB-02) |
| Disk full | Job fails, document stays `failed`, no partial rows |
| SQLite locked | Single writer means this should not happen; if it does, retry once then fail loudly |

No failure mode guesses a value. The default under every error is `review` or `failed`.

## 7. Deployment

```
Dockerfile
  build stage: npm ci && npm run build
  runtime: python:3.11-slim + paddleocr wheels + web/dist
  CMD uvicorn smriti.main:app --host 0.0.0.0 --port 7860
```

| Target | Notes |
|---|---|
| Local | Native venv. No Docker Desktop in development — it competes for the 8 GB (RISK-09) |
| HF Spaces (CPU, 16 GB) | Fits the 2.2 GB measured peak; 512 MB free tiers do not |
| Oracle Always Free (ARM) | Possible, but PaddleOCR wheels on ARM are friction; not the primary target |

One worker in every profile. Concurrency is deliberately 1: the pipeline peaks near 2.2 GB and the machine has 8 GB.

## 8. Non-goals

No microservices, no message broker, no Redis, no Postgres, no Kubernetes, no auth provider, no client-side storage of medical data. Each of these would add a failure mode without adding a capability the project needs.

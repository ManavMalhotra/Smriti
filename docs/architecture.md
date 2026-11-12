# Architecture

Approved §13.9 runtime extension keeps the existing coordinator/service/page-artifact boundaries: CPU mmproj and single-slot Qwen tuning, quota-accounted identity-bound unavailable page outcomes, retained valid readings plus OCR-only review, and bounded worker recovery with admission closed until named-tree/checkpoint/source/artifact validation. No new service/dependency/schema or clinical replacement writes. Corruption, consent, capacity and unconfirmed cleanup still block publication; one final clinical transaction remains. References/limitations: `qwen-hardware.md`; actual synthetic evidence: `../tasks/todo.md`.

Status: implemented local MVP structure; synthetic verification is recorded in `tasks/todo.md`. Owns runtime structure and trust boundaries, not requirements or clinical/hardware acceptance. Live rollout remains separately gated.

---

## 1. Context

```
┌──────────────────┐        ┌──────────────────────────────────┐
│ Patient (account)│───────▶│ Smriti (local machine)           │
│                  │        │ upload · local OCR · review · UI │
└──────────────────┘        └───────────────┬──────────────────┘
                                            │ no image or OCR text
                                            │ leaves this device
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
| API | FastAPI, Pydantic v2 | Auth/ownership, bounded upload spooling, bounded review reads and review writes; no rendering/models in HTTP |
| Auth | `smriti/auth.py` | scrypt password hashes, hashed session tokens, cookie sessions, ownership helpers |
| Pipeline | Python modules | Local OCR, classification, whitespace assembly, resolution, rule/date/directive extraction, review transitions, summary assembly |
| Coordinator | One exclusive background controller | Freezes ≤10 FIFO submissions, schedules ≤20-page windows and supervised stages, validates recovery/cleanup, fences publication |
| Stage trees | Disposable Windows Job Objects | Inspection, one-page preparation, lazy CPU OCR/separate fallback, owned Qwen client/server, complete-document helpers, final save |
| Store | SQLite v11 (WAL) + private filesystem | Accounts/clinical records, operational submissions/batches/quotas; normalized sources, private spool and per-job artifacts/candidate SQLite |
| Diagnostics | Independent bounded file/terminal writer processes | Code-owned correlated events; private rotating JSONL and readable terminal lines, not medical audit or an account log API |
| Harness | `eval/` | Offline metrics on a synthetic fixture now; real truth set is external |

One local service, one exclusive coordinator even while idle, one active processing stage tree. Model libraries import only in owned children after assignment. CPU OCR exits before Qwen starts; another window/stage requires confirmed tree and sampler cleanup. HTTP remains separate from model execution. File/terminal writers are independently bounded so a stalled terminal does not block file delivery or cancellation.

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
image/PDF ──▶ spool ──▶ prepared pages ──▶ CPU OCR/text layer ──▶ private candidates + Qwen ──▶ atomic clinical save
       │                                                                                             │
       └───────────────────────────── never leaves the device ───────────────────────────────────────┘
```

OCR (RapidOCR ONNX primary with 4 intra-op threads, PaddleOCR CPU fallback, or PyMuPDF digital text-layer bypass), document-type classification, grounded prose extraction, and field extraction run locally. When configured with a Gemini API key and approved via user consent preview, narrative and complex windows escalate to `gemini-3.8-flash-high` with thinking level high, sending only locally burned masked JPEGs and logging payload hashes in the `egress` table. Cloud review is optional and leaves zero payload bodies on disk or network logs.

### 3.3 Process boundary — untrusted input

HTTP validates upload metadata/signatures and actual bounded chunks, reserving private spool capacity before durable acceptance. Raw input is ephemeral and never served. Inspection/render/decode/normalization run in supervised children, one page at a time; the 300-DPI renderer, normalization/quality/handwriting/text-layer policy and WebP parameters remain unchanged. Complete prepared sources are promoted atomically; partial output is not inference-ready. Raw input is removed after complete preparation or terminal failure; only explicitly enabled unexpected parser/renderer crash debugging retains it.

Generated submission IDs address new files; the patient-scoped incremental hash remains the dedupe identity, never a user-supplied filename. Private paths reject escapes/reparse points/hard links. Historical normalized source paths remain valid. Byte/pixel/disk/native-memory/deadline guards remain independent of page count; PDFs have no arbitrary page-count admission cap. Provisional limits are capacity guards, not measured hardware fit or arbitrary-length completion guarantees.

### 3.4 Presentation boundary — patient only

The dashboard presents both Patient Friendly and Doctor Clinical modes, centered around an executive Standardized Clinical Summary (demographics, hypertension status, chronic conditions, past surgical history, ongoing treatments, year-wise progression, and latest ongoing medications). Raw OCR diagnosis clutter and sticky header banners are eliminated in favor of clean structured components. Every displayed value keeps its document, global page and bounding box. Review uses bounded owner-scoped page/result ranges and accepts, corrects or rejects each field. Pending intake has unknown counts and no source link. Completion supplies a review link without automatically downloading full detail. Document detail surfaces full Audit & Cloud Review Logs from the `egress` table. The existing job disclosure shows chronological code-owned events, omitted-history count, latest failure and support ID; shared measurements/global logs are operator-only.

## 4. Data flow

```
POST /api/documents (session cookie; patient_id must be the signed-in patient)
   ├─ validate auth/demo/consent/metadata and actual multipart/byte bounds
   ├─ serialize owner spooling against erasure; reserve and spool bounded chunks
   ├─ incremental patient-scoped hash → same-owner duplicate convergence
   └─ durable submission → 202 {job_id, document_id:null, pages:null, status:pending_intake}

exclusive coordinator freezes ≤10 FIFO submissions (no late refill)
   ├─ owned inspection and ≤20-page preparation ranges, persisting one page at a time
   ├─ validate complete sources → atomic document/consent/same-ID job promotion → raw cleanup
   ├─ lazy short-document packing; long-document consecutive windows stay one document/job
   ├─ each OCR window: exact artifact reuse → validated PDF text layer → lazy RapidOCR CPU
   │    └─ initialization-only failure: reap primary tree, then separate PaddleOCR CPU fallback
   ├─ bounded complete-document classification, whitespace/rules/prose/metadata/reports/directives
   ├─ printed Qwen windows: one owned llama-server, unchanged flags/prompt, explicit active endpoint
   │    └─ global page/counts, per-page artifacts; handwritten skips, independent empty output/failure
   ├─ bounded complete-document cross-check and private report association
   ├─ one fenced atomic clinical save: all source text/results/links + document/job done
   └─ committed diagnostics, confirmed scratch/raw cleanup; no replacement writes to reviewed/terminal rows

POST /api/observations/{id}/review
   ├─ accept/correct: mapped printed value → auto, audit
   ├─ reject: → rejected, audit
   └─ return updated observation + recomputed summary

GET /api/patients/{id}/summary
   └─ build the frozen seven-key payload from documents, observations,
      medications, directives, and coverage
```

A preparation failure creates no document or clinical facts. Later processing failure marks job/document failed and retains complete normalized sources, but publishes no partial clinical rows; private processing scratch is cleaned. Recognized v1 checkpoints resume validated missing work only after owned-tree recovery. Unknown historical v10 checkpoint shapes remain explicitly fenced for separately approved recovery; historical jobs without submissions are not blanket-requeued. A committed terminal save remains terminal even if later checkpoint/scratch cleanup fails.

`GET /api/jobs` projects only compact owner-scoped Active/Recent snapshots with separate pagination (default 20, maximum 50); selected detail alone loads bounded history. The `#/queue` view remains reachable after client navigation/reload and does not trigger processing or recovery. Summary, Intake and source-page document routes use hash navigation; unsent upload selections remain browser-local. Active polling is nonoverlapping, Recent is user-refreshed, terminal detail/session loss stops polling, and outstanding reads abort on navigation. Safe Qwen failure code/HTTP status persist before cleanup, without storing response bodies or model runtime output; invalid model JSON is not a successful empty reading. Resource lifetimes and clinical policies are unchanged.

The summary includes `review` observations so extracted data is visible and marks them with `status="review"`; accepted values are `auto`, rejected values are omitted. They are not clinically validated results. P3 normalisation/safety gates are not implemented. The default evaluation fixture is synthetic and proves the offline harness runs; real-corpus accuracy is not measured.

## 5. Runtime profiles

| Profile | Uploads | Egress | Data | Use |
|---|---|---|---|---|
| `local-gpu` | On | Off; no egress path wired | Real documents | Development and the actual study |
| `demo` | Off | Off, unconditionally | Synthetic corpus | Public URL |

`demo` is safe by construction, not by configuration discipline: registration/upload/delete return `403`, and the database is intended to be read-only.

## 6. Failure modes

| Failure | Behaviour |
|---|---|
| OCR/model unavailable | Safe stage/engine failure; prepared sources retained, no partial clinical rows |
| Quality gate rejects a page | Same pending job becomes failed with a safe code; no document/facts; partial/raw cleanup |
| Controller/stage interrupted | Owned-tree cleanup and exact artifact validation precede resumable missing work; no replacement of reviewed/terminal records |
| Disk/memory/deadline capacity exhausted | Affected submission safely fails; no waiting on capacity its own frozen batch must release |
| Cleanup unconfirmed | Durable cleanup intent remains; admission pauses, erasure returns 503 rather than claiming success |
| File/terminal unavailable | Peer sink and processing continue; sink health/degradation is truthful, delivery is best effort |
| SQLite unavailable/locked | Stage safely fails or service pauses with cleanup metadata retained; no false committed completion |
| Session expired | `401 session_expired`; the UI returns to sign-in |
| Legacy patient unowned | First registration claims it; otherwise records remain inaccessible until a claim path exists |

No failure mode guesses a value. The worker writes extracted numeric fields with `status='review'`; only an explicit patient review sets `auto` or `rejected`.

## 7. Deployment

The implemented supervised runtime targets native Windows/Python 3.11 with the matched built React client and local model binaries. `start.ps1` launches the sanitized `python -m smriti.server` entry point; plain Uvicorn/raw library output is not the documented launch path. There is no demonstrated CPU-cloud/ARM/Linux runtime or Qwen memory-fit claim.

Before separately approved rollout, stop the live service and back up consistent SQLite/WAL plus normalized sources. Startup can migrate to v11 and start new staged submissions; implementation checks must never start this checkout against live data. Raw spool/debug originals, `.runtime` and private diagnostic logs are excluded from source backups/exports. Historical queue/checkpoint recovery requires explicit review, not guessed ownership/work completion.

Shutdown first stops admission, cancels/reaps the active stage and bounded sampler, confirms the coordinator thread has exited, then disposes SQLite and closes bounded diagnostic writers. Owner erasure uses the same fence and cleans owned files before deleting cleanup metadata; append-only audit and other owners' frozen work remain. An unconfirmed shutdown never announces released VRAM or starts a next stage.

JSONL defaults are 10 MiB/file, five backups and seven days. Each file/terminal queue is independently bounded to 512 events with a two-second shutdown budget. Events exclude clinical content, credentials, filenames/paths, prompts/responses and uncontrolled runtime output. Process/device measurements are sampled observations, not absolute peaks; unavailable values are null with a reason. Total elapsed spans intake-to-finish wall time; operation durations are monotonic. The narrow `/v1/models` 404 event records validated observed client host/port and a bounded UA family/fingerprint, not a conclusively identified caller.

## 8. Non-goals

No microservices, message broker, Redis/Postgres/Kubernetes, external auth/monitoring, distributed scheduling, HA, throughput SLA, new diagnostics dashboard or filter/export UI. No client-side medical storage or clinician/admin role. Synthetic tests do not establish clinical accuracy, arbitrary-length completion or production readiness; RT-22 hardware/corpus evaluation remains separately authorized.

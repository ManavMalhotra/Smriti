# Implementation Plan

Status: draft for review. Depends on `specs/CAPABILITY-MAP.md` and the ten module specs.
Requirements: `docs/SRS.md` v1.1. On conflict the SRS wins.

---

## 1. Architecture

One process, one URL, one database file.

```
Browser (React, JS)
   │  /api/*  +  static bundle
FastAPI (uvicorn, 1 process)
   ├── routers  ── patients, documents, jobs, review, medications, share
   ├── pipeline ── ingest → ocr → extract → normalise → checks → directives
   ├── resolver ── projection → (optional) remote call → audit
   └── worker   ── one background loop claiming jobs from SQLite
SQLite (WAL, foreign_keys=ON)   +   data/uploads/<sha256>/page_N.webp
```

No queue server, no second process, no cache server. The measured pipeline peak is ~2.2 GB, so concurrency is one and stays one.

## 2. Directory layout

```
smriti/          backend package (see module specs for file ownership)
api/routers/     HTTP layer only; no business logic
web/src/         React app; JS only (CON-06)
eval/            harness, truth set, cached responses, outputs
data/            vocab, analyte map, unit map, bounds, swing, lexicon
tests/           pytest suites, one file per SRS traceability row
docs/            SRS, supporting documents
specs/           capability map + module specs
```

## 3. Environment

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
npm --prefix web install
```

```bash
uvicorn smriti.main:app --reload          # dev
npm --prefix web run dev                  # Vite, proxies /api
pytest -q                                 # all suites
python eval/run_eval.py                   # offline, cached
```

No Docker Desktop during development — it consumes memory the pipeline needs (RISK-09). Docker is for deployment only.

## 4. Configuration

| Key | Default | Notes |
|---|---|---|
| `SMRITI_PROFILE` | `local-gpu` | `demo` disables uploads, egress, and writes |
| `SMRITI_DB_PATH` | `data/smriti.db` | |
| `SMRITI_UPLOAD_DIR` | `data/uploads` | outside the static root (NFR-06) |
| `SMRITI_RESOLVER_ENABLED` | `false` | per document as well as global (FR-EGR-05) |
| `SMRITI_RESOLVER_PROVIDER` | `local_rules` | `self_hosted`, `sarvam`, `gemini` |
| `SMRITI_OCR_MODEL` | `PP-OCRv5_mobile` | cached det/rec models; no cloud download at runtime |
| `SMRITI_QUALITY_BLUR` | `100` | Laplacian variance floor |
| `SMRITI_HWR_MARGIN` | `0.15` | below this, abstain (FR-HWR-04) |

Every key is recorded with each run (NFR-13). No key is read outside `smriti/config.py`.

## 5. Data flow

```
upload → consent row → content hash → quality gate → pages
      → OCR → candidates → rules resolver → [resolver] → normalise
      → safety gates → auto | review | rejected
      → directives + medications
      → summary payload → dashboard
```

Writes are transactional per document (FR-JOB-03). A failed job leaves no partially charted rows.

## 6. Testing

Four layers, all offline (SRS §4.3):

| Layer | Runs | Blocks |
|---|---|---|
| Unit | every commit | merge |
| Invariants SI-01…10 | every commit | merge |
| Contract (`summary.json`) | every commit | merge |
| Full evaluation | week gates only | milestone sign-off |

No test touches the network; a network call in CI is a failure.

## 7. Deployment

| Target | Config | Constraint |
|---|---|---|
| Local | `SMRITI_PROFILE=local-gpu` | 8 GB RAM, one worker |
| Public demo | `SMRITI_PROFILE=demo` | synthetic corpus, uploads off, egress off, read-only |
| Host | HF Spaces CPU (2 vCPU, 16 GB) | fits the 2.2 GB peak; 512 MB free tiers do not |

One Dockerfile, FastAPI mounting `web/dist` (CON-09, NFR-14).

## 8. Sequencing and gates

| Phase | Modules | Exit gate |
|---|---|---|
| P0 | repo, config, DB schema, CI | tests run |
| P1 | `intake` | 5-doc fixtures pass; EXIF gone |
| P2 | `extraction` | CER measured on 10 docs; probe decided |
| P3 | `normalisation`, `safety` | analyte ≥ 0.95; gate recall ≥ 0.80 |
| P4 | `medications`, `directives` | med F1 ≥ 0.80; directive spans extracted |
| P5 | `dashboard` | summary frozen; overlay works |
| P6 | `evaluation` | offline reproducibility |
| P7 | `egress` | queue shrink ≥ 30 % or deleted |
| P8 | `handwriting-assist` | week-8 gate green first |

`evaluation` starts at P2 with fixtures, not at P6. The harness skeleton must exist before there is anything worth measuring.

## 9. Cut order

Handwriting assist → clinician-view study → share link → medication depth. The end-to-end number and every safety invariant are never cut.

## 10. Definition of done

- Every FR in SRS §3.1 has a named test that passes.
- SI-01…10 have invariant tests that pass in CI.
- `eval/run_eval.py` reproduces every reported number offline from cache.
- No image or free text leaves the device.
- `docker build` produces one image that serves API and UI.

## 11. Intake experience — 2026-11-04

Status: **plan and task checklist approved by the user on 2026-11-04; implemented and locally verified on 2026-11-05**. Results and remaining hardware/evaluation obligations are recorded in `tasks/todo.md`. No live deployment occurred. This section does not reopen or replace earlier roadmap gates.

Spec index: [CAPABILITY-MAP-intake-experience.md](../specs/CAPABILITY-MAP-intake-experience.md). Requirements: FR-AUTH-01…02, FR-ING-10, FR-JOB-05…07 and the existing safety/ownership boundaries referenced by those specs.

### 11.1 Components and dependency order

```text
registration: API validation → form errors/focus → account regression gate
processing: schema v9 + progress writer → worker/VLM events → job API
                                                      → JobProgress → progress regression gate
bulk-upload: approved job API + JobProgress → multi-file intake → full verification gate
```

Registration is independent of telemetry but ships first to remove the entry blocker. Storage precedes worker instrumentation; the public contract precedes the view; bulk upload uses that view rather than duplicating it. Keep implementation sequential because the UI slices share `Intake.jsx`, CSS, and integration tests. No additional agents, runtime services, or dependencies are required.

### 11.2 Registration vertical slice

- Normalize username and alias before server constraint validation, while preserving passwords exactly. Keep existing credential length/character policies and legacy-record claiming behavior.
- At the shared validation handler, translate known account validation failures into safe field-specific messages. Preserve HTTP 400 and `error.code/message/field`; do not serialize Pydantic input objects or arbitrary validator exception text. Keep other API callers compatible.
- In `Auth.jsx`, validate the trimmed submitted values against existing constraints, show linked inline errors, and focus the first invalid field. Use structured server errors for duplicate username and validation failures. Keep valid input after errors and disable both submit and mode switching while a request is active.
- Remove decorative copy only from the touched form. Keep meaningful input labels, credential requirements, privacy information, and legacy-ownership disclosure.
- **Checkpoint:** direct API invalid/valid/duplicate/session tests and frontend validation/focus/recovery/axe tests pass; existing login, legacy-account, and App system tests remain green.

### 11.3 Durable telemetry vertical slice

- Use schema v9 with one nullable `jobs.progress_json` column, added by `009_job_progress.sql`; no existing row is rewritten or reprocessed. Update both the fresh schema and migration version. Old jobs have no event history and remain readable.
- Keep one small `smriti/job_progress.py` writer for the worker's snapshot and bounded event history. Update the existing job row inside a transaction; never insert a replacement job after deletion. A missing row ends telemetry writes rather than resurrecting data.
- The JSON snapshot stores stage-specific model/page/count fields and start/update/finish timestamps, a monotonically increasing event sequence, and the latest 500 events. Include an explicit truncation indicator; current state is independent of retained events. Reuse `jobs.stage` for current stage and keep `jobs.page` as completed OCR pages.
- Persist only at real operation boundaries. Durations use a monotonic clock; timestamps use UTC. Store operational counts and known messages, not extracted values, text, images, prompts, arbitrary exception strings, or private filesystem paths.
- **Checkpoint:** fresh schema and v8→v9 migration tests preserve account/session/document/review rows. Event order, retention, historical compatibility, and deletion/no-resurrection tests pass in temporary databases.

### 11.4 Worker and API vertical slice

- Instrument claim/recovery, OCR initialization, per-page OCR or cache/text-layer reuse, classification, rule extraction, Qwen loading/readiness/inference/skips, cross-checking, resource cleanup, saving, and terminal state at their actual boundaries.
- Extend the existing VLM lifecycle only as needed to report genuine readiness/cleanup. Ensure a failed context-manager entry cleans up a process it spawned; never stop an externally running server. Report successful unload only after process exit is verified.
- Keep handwritten numeric filtering, mandatory-Qwen behavior, extraction validation, and medical-write transactions unchanged. Derive engine names from the actual engine; do not claim PaddleOCR-VL runs on the current production OCR path.
- Emit safe failure categories with stage/model context. Remove raw metadata and raw-model-response logging from the pipeline statements touched by this slice; do not turn application console output into the UI event source.
- Add the approved snapshot/event fields to the existing ownership-checked `GET /api/jobs/{id}` response, preserving original fields. Commit done telemetry with successful medical writes; failures retain the useful last stage/page context. Recovery is an interruption event, not an invented successful stage.
- **Checkpoint:** fake-engine tests exercise cache reuse, handwriting/disabled-model skips, Qwen unavailable/startup timeout/inference failure/empty output, save failure, recovery, and done ordering. Another account receives 404. Sensitive-input sentinels never appear in exposed telemetry.

### 11.5 Processing view vertical slice

- Add `JobProgress.jsx`, consumed by intake: current activity, actual model/page, stage-specific completed-page progress, and elapsed time. When progress is unknown use an indeterminate state, not an estimated percentage.
- Use native `details/summary` for ordered timestamped technical events. Use existing CSS tokens with restrained semantic status colors and explicit severity text; no legend, explanatory layout caption, log platform, or UI kit.
- Keep history scroll/focus stable while polling. Stop elapsed-time updates at terminal timestamps, announce meaningful state changes rather than every timer tick, and preserve the last snapshot on transient connection errors.
- Use one non-overlapping polling loop per intake view with two-second scheduling, terminal-stop behavior, retry after transient failure, and cleanup on unmount. Expired sessions and missing resources are not retried forever.
- **Checkpoint:** progress/disclosure/timing/grayscale semantics, keyboard, transient-error recovery, historical-job fallback, and axe tests pass. Browser verification covers narrow widths, visible focus, contrast, and reduced motion; report any unavailable browser checks rather than claiming them passed.

### 11.6 Bulk upload vertical slice

- Replace single-file intake state with one per-file list using stable client row IDs, not filenames. File objects stay in browser memory and are not eagerly read. Pending rows show name/size and can be removed.
- Submit at most one upload POST at a time through the current endpoint; continue after file-specific failures and duplicates. Do not wait for model completion before sending the next file. Guard against double submission and stop scheduling on unmount or expired/forbidden sessions.
- Preserve a separate uploaded/job/error/progress result per file. Duplicate responses link to the existing document without creating or pretending to retry a job. Explicit upload retry uses existing duplicate detection; never automatically retry an ambiguous POST failure.
- Default to automatic type detection and no date. Label optional overrides as applying to all selected files; reset overrides and consent for a new batch. The server records consent separately for each accepted document.
- Reuse `JobProgress` for accepted jobs. Keep one-file preview/results access working; bulk rows expose document/review links without expanding all medical tables. Show factual uploaded/processed/duplicate/failed counts.
- Warn before navigation with unsent files. Do not promise background or resumable uploads; accepted server jobs continue independently. A failed extraction shows its stored document/error, not an ineffective reupload retry.
- **Checkpoint:** deferred-request tests prove sequential POSTs, mixed-batch continuation, same-name independence, explicit retry, session interruption, safe unmount, consent, overrides, review links, and single-file compatibility. Pending/active/mixed-terminal/expanded-log axe tests pass.

### 11.7 Risks and release verification

| Risk | Mitigation / release check |
|---|---|
| Existing uncommitted extraction/review work | Make scoped patches; inspect connected callers and fixtures; never revert or overwrite unrelated changes. |
| Older databases and reviewed medical data | Additive migration only; migration tests preserve rows and decisions. Do not restart or migrate the live server during implementation. A deployment requires a stopped worker and database backup. |
| Medical contents leaking through logs | Allowlisted operational events, safe failure messages, removal of touched raw-content logging, ownership tests, and sensitive-content sentinels. |
| Deleted jobs gaining telemetry again | Update-only writes with missing-row handling; no replacement job/event inserts. Existing unrelated cache-erasure audit findings are not silently declared fixed. |
| Bulk upload memory / background behavior | Sequential POSTs, no eager file reads, bounded histories, clear unsent-file navigation behavior, and one existing worker. |
| Misleading progress/model claims | Actual boundary events; stage-specific page counts; no token/GPU percent; historical data unavailable; fake-engine checks do not count as real model verification. |

Final commands from the repository root, using synthetic/temporary test data:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test
npm --prefix web run build
```

Update `docs/API.md`, `docs/data-model.md`, and relevant startup/schema references to match the implemented contract. Recheck modified-file scope and document test results and unverified hardware/browser behavior. Do not run the medical-data reset, reprocess existing documents, commit, push, install dependencies, or restart the live server as part of this plan.

After plan approval, record the focused tasks in `tasks/todo.md`, preserving its existing ledger. Each task gets explicit acceptance, a verification command, and a small file boundary before implementation starts.

## 12. Hardware-safe runtime Phase 1 — 2026-11-05

Status: **requirements/four gates, implementation plan, and focused checklist approved by the user on 2026-11-05. Implementation is in progress; verified slices and next work are recorded in `tasks/todo.md`. Only synthetic/temporary-database verification is authorized; no live migration, restart, or real-record processing has occurred for this phase.** Plan approval includes the initial spool/deadline defaults below as unmeasured guardrails, not hardware acceptance.

This section preserves the original approved baseline. The subsequent approved long-PDF requirements supersede its upload page cap and prohibition on planned document lifecycle windows. Section 13 proposes the necessary implementation revision, including changed storage/disk/deadline details; it awaits plan review. Do not implement superseded page policies or assume the original checklist approves the new mechanics. Independent RT-04 supervision remains authorized.

Authority: `docs/SRS.md` v1.2, especially FR-ING-01/09/11, FR-JOB-08, FR-RUN-01…04, NFR-02/18, DR-07. Module: [SPEC-runtime-stages.md](../specs/SPEC-runtime-stages.md); intake: [SPEC-intake.md](../specs/SPEC-intake.md).

This section supersedes the historical same-process/no-second-process and fixed ~2.2 GB sizing assumptions in §§1/7 **only for the approved local runtime**. Those old estimates do not establish current Qwen RAM/VRAM needs. Public demo, clinical rules, dashboard payload, handwritten exclusions, mandatory printed verification, prompts, model weights, renderer, current normalized WebP encoding, 300-DPI rendering and 1800px normalization cap stay unchanged. Smaller option: reuse existing page encoding, stage artifacts and coordinator loop; no archive, new queue service, clinical schema, or image-format conversion.

### 12.1 Components, dependency order, and scope

```text
operational schema + job contract → bounded HTTP spool → sequential page preparation/promotion
Windows supervisor + RAM/GPU sampler ───────────────────┘
                     → isolated CPU OCR/fallback → whole-workset owned Qwen → atomic document save
job contract → pending/preparing UI ────────────────────────┘
all slices → recovery/privacy/compatibility regressions → separately authorized hardware evaluation
```

Keep one coordinator loop using the existing background-worker entry point; never instantiate model runtimes there. Preparation and OCR use spawn-safe child targets; Qwen has a coordinator-owned server and disposable inference client within one supervised stage group. Identifiers, paths, scalar settings and resolved session URL cross process boundaries; no engines, arrays, model objects or medical payloads in IPC/progress messages. Children open/close their own SQLite connections and read/write private artifacts on disk.

| Boundary | Planned files and callers |
|---|---|
| Storage/queue | `smriti/schema.sql`, `smriti/migrations/010_runtime_stages.sql` (next version if v9 is still current), `smriti/db.py`, `smriti/stage.py`, `tests/test_db.py` |
| Intake | `api/routers/documents.py`, `smriti/ingest.py`, existing `preprocess.py`/quality/handwriting/text-layer helpers; caller fixtures in `tests/test_ingest.py`, `tests/conftest.py` |
| Supervision/telemetry | Small focused `smriti/runtime.py` supervisor and `smriti/runtime_telemetry.py` sampler, `smriti/config.py`, `requirements.txt`, planned `tests/test_runtime_stages.py`/`tests/test_runtime_telemetry.py` |
| Processing | `smriti/worker.py`, `smriti/ocr.py`, `smriti/vlm.py`, `smriti/stage.py` artifact callers; `smriti/app.py` startup/shutdown; worker/OCR/VLM/stage tests |
| Public progress/erasure | `api/routers/jobs.py`, `smriti/job_progress.py`, new-data cleanup in `api/routers/patients.py`; jobs/progress/patients tests |
| UI | `web/src/pages/Intake.jsx`, `web/src/components/JobProgress.jsx`, only needed CSS; intake/progress/App fixtures and tests |
| Final documentation | `docs/API.md`, `docs/data-model.md`, `docs/architecture.md`, `README.md`, startup/backup guidance and affected processing/bulk specs/checklist |

The following existing `process_next(..., ocr_engine=...)` callers need fixture updates: worker, directives, review, and system tests. Preserve a simple test seam for fake stage execution; real spawn tests use importable module-level synthetic targets, not unpicklable mock engine objects. Recheck all `ingest_upload`, artifact lookup, cleanup, `VlmSession`, and `extract_page_vlm` callers before coding. No production caller keeps the old in-process OCR path as a convenience fallback.

Storage/HTTP/API are sequential. Supervisor/sampler can be developed independently against synthetic targets; UI can follow the agreed response fixtures while backend processing is built. No parallel agents are required. Integration waits for both storage/preparation and supervision; no live worker is used as a development test harness.

### 12.2 Operational migration and stable job/API contract

1. Add `submissions` and `stage_batches`, without rebuilding `document`, `consent`, or `jobs`, rewriting old rows, or changing clinical CHECK constraints. Increment fresh-schema/user-version and migration metadata together; verify the next free migration number rather than overwriting a new migration someone else created.
2. A submission stores its public `job_id` (primary identity), patient FK, incremental patient-scoped hash, generated relative spool path/byte count, consent scope/version/original grant/revocation, requested date/type overrides, durable state/stage/error code, nullable document/page total, batch position, preparation manifest/progress, and spool-cleanup intent/state/timestamp. Consent/overrides are private intake data, not telemetry. Use a live-hash uniqueness constraint for pending/preparing/promoted submissions, so duplicate races converge but a rejected raw file may be explicitly resubmitted later without auto-retrying its old job.
3. A batch stores stable membership/order, coordinator token plus PID/creation identity, workset manifest/order/page sums, stage attempt/checkpoints and bounded measurement summaries. Acquire a nonblocking OS file lock beside the DB before polling (`msvcrt` on Windows), released on coordinator exit; do not delete an active lock file. This rejects a second live coordinator even while idle. Claims use one short atomic SQLite write transaction (`BEGIN IMMEDIATE` or equivalent compare-and-set) with an active-batch uniqueness guard. All coordinator writes are fenced by the owner token; do not steal a batch just because an inference exceeded a heartbeat interval. Confirm the prior owner/tree is gone before recovery.
4. Reuse `stage_artifact` for per-page preparation/OCR/VLM/rules outputs with exact model/prompt/render/preprocess identity. Store source/page and actual engine identity in the artifact envelope; read only the expected version, never the newest arbitrary entry. Full manifests/artifacts are private source data; never return raw OCR/model output in job logs. Keep bounded summaries, not a row per RAM sample or an unlimited attempt log.
5. At successful preparation, after validating complete durable files/manifest and successful preparation-child outcome, atomically insert document + per-document consent + `jobs(id = public job_id)` and set the submission's link/count and cleanup intent. Preserve original consent time and audit intent; do not invent a second consent grant. Recheck owner/consent/submission eligibility in that transaction. Do not create any clinical row on validation failure. Only the batch coordinator can admit promoted jobs, so the old job-claim loop cannot race preparation/spool cleanup.
6. `GET /api/jobs/{id}` performs ownership-checked submission/prepared-job resolution in a consistent read. Before promotion use submission progress; after promotion use existing job progress with transferred event sequence/timestamps. Keep `id/state/page/total/error/progress` and add `document_id/total_pages/stage/error_code` as needed. Pending/preparing map to existing `state: queued | running` with truthful new stages; unknown `total`, `total_pages`, `document_id` are null. Deferred rejection maps to `state: failed` plus a specific safe error code; it remains pollable without a document. Historical jobs keep existing values; null historical telemetry stays unavailable.
7. `POST /api/documents` returns 202 with stable `job_id`, null document/count fields and `stage: pending_intake`. Keep prepared-document duplicates as existing 409 responses. An active submission duplicate returns its existing job identity with `duplicate: true` and current stage/counts, not a fabricated document link or a new extraction. Update frontend handling separately for pending duplicates versus prepared duplicates.
8. Extend the existing bounded progress writer to submissions using the same event schema and update-only/no-resurrection semantics. Transfer the pending/preparing history atomically at promotion, preserving sequence numbers and the 500-event limit. Per-job responses expose only that owner's job; never serialize shared-batch membership or another patient's telemetry. Preserve positive `DocumentSummary.page_count`; pending submissions stay out of clinical summaries.

**Checkpoint A:** fresh DB and v8→v9→new-version temporary migration tests preserve accounts, sessions, consent, reviewed values/audit, existing jobs and all clinical constraints. Duplicate-claim/promotion/read races, null totals, same-ID transition, cross-account 404, historical fields, and deleted-row/no-resurrection checks pass. No migration is run against `data/smriti.db`.

### 12.3 Bounded spool, preparation, and deletion recovery

1. Replace `file.file.read(max_upload_bytes + 1)` with bounded chunk copying and incremental `sha256(patient_id + NUL + bytes)`; retain the current hash identity. Check authentication/ownership/demo/consent/override validation, declared type and actual bounded header before accepting. A header check is not PDF/image decoding. Use generated paths, exclusive creation, finalize/flush the spool before committing its pending record and returning 202. Always close `UploadFile` and raw handles on every outcome.
2. Bound the ASGI/multipart input **before** the handler's spool loop: limit actual streamed request bytes (do not trust Content-Length), fields/part sizes/file count, parser in-memory threshold, active upload slots and reserved spool bytes. Include multipart temporary copies, unfinished writes and debug-retained spools in capacity accounting. Reject capacity exhaustion before buffering more input. Approved initial defaults (unmeasured): 1 MiB copy chunks, two active spoolers, and capacity for 20 maximum-size raw files plus bounded multipart overhead; the existing 25 MiB/file limit stays unchanged. Make reservations atomic and release them only on confirmed removal. Validate restricted spool/temp paths at startup and document backup exclusion; gitignore alone is not a backup/privacy control.
3. Spawn `intake_prepare` once per frozen submission. Inspect manifest/page count first, then process one page at a time through existing render/quality/handwriting/normalization/text-layer helpers. Persist each page/sidecar atomically and release image/pixmap/NumPy references before the next page. Preserve page mapping, quality configuration, classification rules and PDF deduplication policy. No full-upload rendered/prepared-image arrays.
4. Use the existing normalized WebP encoder and source paths; no PNG migration is needed for runtime isolation. Record canonical coordinate space and preparation identity. Successful child exit plus a complete committed manifest is required before promotion. If raw bytes are gone, restart must rely on that durable manifest; missing/corrupt prepared files fail safely and require explicit resubmission, not recovery from a nonexistent archive.
5. For success, commit promotion/preparation outcome plus cleanup intent, close handles, unlink, then record `spool_deleted_at` on verified absence. For deterministic invalid format/password/page/pixel/byte/quality rejection, commit terminal submission/error then do the same unlink flow, also removing only that attempt's incomplete normalized files. Do not remove a pre-existing hash directory to win a duplicate race: verify its ownership/manifest or resolve the duplicate instead.
6. `DEBUG_RETAIN_FAILED_SPOOL` defaults to off and accepts the explicit `1` opt-in. Only unexpected parser/renderer crashes qualify; retain safe crash category and `debug_retained` state, not raw parser stderr. All other failures, including timeout/cancel/disk errors, request disconnects and duplicate races, remove owned raw/partial files. Debug retention remains quota-accounted, private and erasable.
7. Keep cleanup intent/state separate from medical/preparation outcome. A locked/missing/unlink-error case does not falsely stamp deletion. Startup and each admission boundary reconcile committed cleanup intent; after unlink-before-timestamp, verified absence permits a truthful recovery timestamp. Persistent cleanup failure blocks new expensive work and restricts further intake through quota/backpressure. Do not recompute clinical extraction to repair deletion.
8. Close the pre-commit orphan window with deterministic generated partial paths and intake-only reconciliation after confirming no live uploader owns them. Never scan/delete arbitrary user files or existing upload sources. Recovery records uncommitted normalized preparation outputs as nonreusable until validated; incomplete page attempts are safely regenerated only while the permitted raw spool exists.
9. Extend **existing owner erasure only for the new operational data**: cancel/fence its submissions, stop any affected owned stage work, confirm spool/debug/partial/artifact cleanup, and remove new associations/history without affecting other frozen members. Do not drop the last path metadata or acknowledge completed erasure while raw cleanup is unresolved. Preserve append-only audit and prevent late child/progress/promotion writes from recreating deleted records. This is not authorization to execute erasure or overhaul unrelated historical cleanup defects.

**Checkpoint B:** synthetic uploads during fake VLM work invoke no decode/renderer/OCR in HTTP; oversize/disconnect/disk-full/multipart-capacity cases are bounded and leave no accepted missing spool. Test success and every deterministic rejection, flag-off/flag-on crashes versus non-crash errors, Windows locked files, duplicate races, both commit/unlink windows, abandoned partials, static/backup exclusion, and erasure during preparation. Assert actual files and deletion timestamps, not only mock unlink calls.

### 12.4 Windows process-tree supervisor and stage telemetry

1. Implement the small common stage supervisor before integrating models. Use monotonic deadlines, bounded IPC, stop/cancel checks, child outcome/artifact validation, and distinct operation/cleanup errors. A timed-out or crashed child does not advance a successful stage checkpoint, even if it wrote some pages.
2. On Windows use standard-library `ctypes` Job Objects with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`; no extra process-control dependency. Attach Python spawn children before allowing the target to import runtimes/create descendants (startup handshake; controller EOF aborts). Create the owned server suspended/attach/resume, or use an equivalently guarded launcher, so it cannot spawn outside supervision. Job handles are non-inheritable, owned only by the coordinator, and closed on shutdown/crash. Do not launch via an unowned shell wrapper. Assignment failure is a safe stage failure, not a warning followed by execution. Test behavior under the harness's enclosing Windows job too.
3. Snapshot/track owned PID + creation identity and descendants using approved `psutil`; on error/timeout terminate children before parents, wait ≤5s for the tree, then kill remaining owned processes/close Job Object and wait ≤5s. Re-scan for newly created owned descendants; never kill a reused PID. Verify normal root exit and no surviving owned descendants, not just `poll()` on the wrapper. Recursive cleanup remains the specified alternative, but do not rely on post-crash discovery as the primary Windows guard.
4. Keep existing `start_worker` integration; make app shutdown stop admission, cancel the active stage group, confirm bounded tree/monitor/thread exit, then dispose connections. The current five-second worker-thread join alone is not sufficient evidence of model shutdown. An unconfirmed exit leaves an explicit operational failure and no new stage; no pretend VRAM-release event and no `torch.cuda.ipc_collect()` fallback in the coordinator.
5. Resolve and pin one released `psutil` version compatible with Python 3.11/Windows during authorized implementation, then run import/platform tests. No version is guessed or package installed by this plan. The approved dependency provides process/system measurements; `pynvml` is not added.
6. RAM sampling uses a bounded background sampler every 1–2s, reducing samples to before/observed peak/minimum/after plus timestamps/coverage. Private bytes use Windows `memory_info().private` if present, otherwise null with reason. Measure stage root and owned descendants; label per-process versus summed tree RSS and shared-map double counting. A sub-interval stage may have no observed child peak, not a made-up zero.
7. Prefer the simpler GPU option: pre/post `nvidia-smi` plus nonoverlapping polls scheduled at ≥2s intervals, each with a 3s timeout. Do not catch up missed polls by spawning a burst. This avoids a permanent pipe reader; if measurement proves overhead problematic, the approved alternative is one `-l 2` stream with bounded reader/buffers, first-sample/stall deadlines, and joined cleanup. Record actual mode/sample coverage. Timeouts/missing executable/unsupported or malformed readings yield null with exactly `nvidia_smi_unavailable_or_timeout`; kill/wait timed-out monitor children. Failed monitoring never prevents stage cleanup.
8. Persist bounded stage summaries in operational batch storage: stage/workset/attempt IDs, model/runtime/provider, dimensions/page counts, monotonic timing, observed process/system/GPU measures, intervals/coverage, exit code/reason and separate cleanup outcome. Do not copy samples into the 500-event UI history. Record an evidenced OOM only from a recognized safe signal; timeout is timeout. No paths/filenames, patient metadata, clinical values/text, image payloads, prompts/responses or raw stderr. Add only narrow `/v1/models` 404 observed host/port and sanitized UA-family/fingerprint diagnostics in `smriti/app.py`; this does not identify a process conclusively.

**Checkpoint C:** real synthetic Windows parent→grandchild tests cover success, native-like hang, timeout, startup failure, cancellation, abrupt coordinator termination and Job Object assignment failure. Confirm process identities disappear before the next fake stage. Fake-clock telemetry tests verify 1–2s RAM, ≥2s GPU/no overlapping query, 3s timeout/stall, null/partial coverage, bounded storage, privacy sentinels and monitor cleanup. These checks establish supervision behavior, not model VRAM consumption.

### 12.5 Frozen whole-document pipeline and unchanged clinical writes

1. Claim ≤10 submissions once and persist frozen order. Prepare them sequentially with preparation-tree/spool-cleanup barriers. Deterministic rejected members remain terminal and do not get replaced by later arrivals. Then persist the workset packing manifest: append a whole document only if its page count fits ≤20; otherwise close the current workset. Tests include 20+1, 15+15, 14+12, ten 20-page documents, mixed rejects and all-rejected batches. No bin-packing reorder or planned page split.
2. For each workset, spawn primary CPU OCR over the validated manifest. Remove coordinator `_ENGINE`/`engine_ocr` ownership and lazy-import RapidOCR/ONNX/Paddle only after child `CUDA_VISIBLE_DEVICES=""`. Keep existing ONNX CPU provider options/four threads, explicitly pass the installed Paddle CPU option, and verify actual execution providers/device. Reuse an engine within this child only. Do not load a runtime for pages already covered by valid text-layer/exact-version artifacts.
3. Preserve RapidOCR **initialization-failure** fallback, but return that outcome to the coordinator, confirm primary-tree exit, then spawn a separate Paddle CPU child. No newly invented low-confidence/page-failure fallback. Persist each page with actual primary/fallback/cache/text-layer identity; record skipped inference honestly. Close each SQLite transaction before further inference; no batch-long write locks.
4. Run unchanged classification, rule extraction, numeric handwriting exclusion, grounded prose/metadata/directive handling over bounded persisted words/text, one complete document at a time. Persist private candidate artifacts if needed to avoid holding all workset candidates through Qwen. Do not change the current whole-upload classification/routing weakness under this resource-lifetime fix; page segmentation/crop omissions are later work.
5. The coordinator creates one `VlmSession` for eligible workset verification and owns its `llama-server` and supervised inference client. Check occupied local port by connection, not only `/health == 200`; non-health servers also fail safely. Prevent startup/readiness races from accepting an unrelated listener. Inference client receives that active session's resolved URL; require the explicit endpoint in `extract_page_vlm` and update every caller/fake. No process-wide `VLM_URL` fallback, unowned server reuse, remote mode, or Ollama swap.
6. Send only one existing normalized page per request; preserve prompts/token limits/model flags and printed/handwritten eligibility. Persist per-page VLM output privately and preserve the existing per-document mandatory-result validation (empty required verification remains failure). End the client/server lifecycle and confirm tree cleanup before another expensive workset. One model failure does not become a success for other documents; retain each document's actual artifacts/outcome. Cleanup failure halts all admission.
7. Only after the full document's required artifacts and verified cleanup, run unchanged cross-check/final extraction logic and commit clinical rows + document/job done + final progress in one transaction. Preserve final-write error handling and all trust gates. Revalidate owner/job eligibility in the save transaction. Do not call the existing replacement-write helper on a terminal/reviewed/populated clinical document: migration/claim/recovery must exclude it and final-save tests must guard against overwrite. No `smriti/summary.py` or dashboard aggregation changes.
8. On interrupted **new Phase 1 batches**, confirm prior process-tree exit/owner fencing, validate exact artifact identities, and resume only missing work. Crash recovery may repeat an incomplete stage lifecycle; normal packing never plans this. A done document remains done even if the coordinator crashed before the batch checkpoint. Keep historical queued/running jobs readable and untouched during migration; deployment review must inventory/authorize any legacy nonterminal processing separately. Never blanket-requeue terminal/reviewed records or auto-retry failed verification.

**Approved initial hard deadlines (guardrails, not measured hardware capacity):** preparation 300s per submission; OCR primary/fallback separately `60s + 120s × pages requiring that engine`; VLM `30s startup + 120s × eligible pages + 60s bounded client/persistence overhead`, excluding the final ≤10s cleanup escalation. Keep the existing 30s startup and 120s request timeout; the supervisor enforces both the request wall-clock cap (using page-start/outcome metadata from the client) and workset cap even if a streamed response avoids a socket-read timeout. All deadlines are finite settings in `smriti/config.py`, recorded with the run. Do not tune DPI, page/thread/token budgets or these deadlines from conjecture; measure before proposing revisions.

**Checkpoint D:** fake-engine fixtures establish unchanged extraction/trust outcomes, fallback trigger, actual identities, no OCR/model imports in the coordinator, no overlapping stages, one normal OCR/Qwen lifecycle per whole workset, custom endpoint use, and safe busy-port handling. Failure-after-page-N preserves committed artifacts without partial chart publication; transaction-failure/recovery/owner-deletion tests protect existing reviews and preserve historical jobs. A mandatory verification failure cannot be reported as done.

### 12.6 Pending/preparing UI and API compatibility

- Add pending-intake/preparing activity to existing `JobProgress`, with null totals shown as indeterminate. Do not show “1 page”, a completed percentage, a document preview, or review links before verified promotion. Preserve concise statuses/native event disclosure, keyboard labels/focus, grayscale semantics and reduced motion; no explanatory layout captions.
- In `Intake.jsx`, keep stable client rows and the job ID while polling the pending submission. Read document ID/counts from the promoted job response instead of the initial upload response. Support active-submission duplicates as a pollable existing job, prepared duplicates as existing document links, and deterministic deferred rejection with a specific safe message and no nonexistent source link.
- Poll queued/running pending stages using the existing nonoverlapping two-second loop. Stop failed/rejected/done rows correctly; account changes/unmount clear loops. Preserve prior snapshot on transient failure and transfer elapsed time/history without resetting the job at promotion. Retry remains explicit; no automatic repeat POST after ambiguous upload failure.
- Update single-file detail/preview and bulk count fixtures, historical-job fallback, jobs/progress tests, directives/review/system fake-worker callers, and privacy fixtures. Keep input/review/source accessibility and existing clinical summary schema unchanged.

**Checkpoint E:** null-total pending/preparing → same-ID promotion → verification/save fixtures, mixed rejection/duplicates, terminal timing, reload/navigation/session expiry and transient polling recovery pass. Axe/keyboard/reduced-motion tests cover all new states; isolated synthetic browser checks at narrow/desktop sizes are required before claiming layout verification.

### 12.7 Verification commands and evidence

Run blocking checks separately in the background; do not poll unfinished commands. Only synthetic inputs and explicitly isolated temporary DB/spool/upload directories are used for implementation tests. Existing commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_db.py tests/test_ingest.py tests/test_jobs.py tests/test_job_progress.py tests/test_patients.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_ocr.py tests/test_vlm.py tests/test_directives.py tests/test_review.py tests/test_system.py -q
npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/JobProgress.unit.test.jsx src/test/App.system.test.jsx
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test
npm --prefix web run build
git diff --check
```

Planned new test command, executable only after those test files exist:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py tests/test_runtime_telemetry.py -q
```

After separate hardware/corpus authorization, add one small `scripts/benchmark_runtime.py` harness that uses the same supervisor/coordinator with an explicit external input manifest and isolated DB/spool/upload/output roots. Refuse the live paths or an already-used run directory, require writable-root containment and live-worker-off confirmation, leave real inputs untouched, and disable remote egress/debug raw retention. No medical paths/values enter emitted stage evidence; manifest source paths remain restricted input, not published logs. Proposed invocation (script/options not implemented yet):

```powershell
.\.venv\Scripts\python.exe scripts/benchmark_runtime.py --manifest "C:\Users\manav\AppData\Local\Temp\opencode\runtime-inputs.json" --run-dir "C:\Users\manav\AppData\Local\Temp\opencode\smriti-runtime-phase1" --confirm-live-worker-stopped
```

Use 3–5 user-selected representative multipage PDFs. Baseline comparison is permitted only where safe and separately approved, with identical corpus/model/image/settings; missing baseline is explicitly reported, not reconstructed. Emit actual stages, engines, pages/dimensions, timings, startup/request failures, skips, observed RAM/VRAM before/peak/after, unavailable-reason nulls and cleanup evidence. This small resource experiment cannot establish clinical accuracy, universal stability, shared GPU paging, or the cause of Qwen timeouts. B1/B2 ground-truth obligations remain open.

### 12.8 Risks, rollout, and stop conditions

| Risk | Required mitigation / stop condition |
|---|---|
| Lost original vs failed deletion | Only remove after durable success or recorded rejection; intent plus verified absence closes DB/unlink windows. Failed deletion is not success and blocks new expensive admission; debug raw is opt-in/quota-accounted. |
| Windows orphan/native hang | Pre-execution Job Object ownership, bounded escalation, PID identity checks and abrupt-controller/grandchild tests. Stop on failed assignment or unconfirmed tree exit. |
| New pending API breaks old clients | Ship null-aware frontend and backend together; retain historical fields/counts and same public job ID. Do not fabricate clinical rows for compatibility. |
| Shared-batch privacy / owner deletion | Per-owner response projection, scoped new-data erasure, fencing and update-only writes; never expose batch membership or resurrect erased data. |
| Artifact/resume or replacement-write corruption | Exact artifact identity and manifest validation; no full-document resave after done; reject terminal/reviewed/populated documents from new-path claims and final replacement writes. |
| Sampler churn/stalled driver query | ≥2s single GPU query, 3s deadline, bounded buffers/summary reduction and owned monitor shutdown; unavailable nulls do not block proper cleanup. |
| Remaining 8 GB / 4 GB constraints | Isolation removes known lifetime overlap, not a promise that Qwen fits or runs quickly. Keep current limits and record measured evidence; do not change driver/model/DPI settings to mask failures. |
| Existing uncommitted work / live queue | Scoped patches and connected tests; no reset, overwrite, commit/push, live migration/restart or old-record processing as part of implementation verification. |

Release requires a separate explicit deployment approval: stop the current worker/server, inventory nonterminal jobs and owned/unowned processes, create a consistent SQLite/WAL backup and backup of durable normalized sources **excluding raw spool/temp/debug files**, test the additive migration on a copy, and ship matched API/UI/startup settings. Historical documents/reviews remain untouched. Raw files intentionally excluded from backups are not recoverable archives; restored pending rows missing raw bytes must fail safely rather than render nonexistent originals. On rollout failure, stop new processing and investigate; do not downgrade/reset a database or discard accepted new records.

### 12.9 Review gate / next action

The user approved this plan, including its initial spool capacity/concurrency and finite deadline defaults, and then the dependency-ordered checklist in `tasks/todo.md` on 2026-11-05. Runtime implementation is authorized within that checklist; its result ledger records progress and next work using temporary databases. Model tuning, segmentation/inherited-context changes, permanent archival, history/bill/chart redesign, live deployment and real-record evaluation remain separately gated.

## 13. Long-PDF runtime revision — proposed plan, 2026-11-05

Status: **implementation authorized after the expert critique by the user's instruction to proceed until implemented (2026-11-05)**. Authority: `docs/SRS.md` v1.3 FR-RUN-01/02 and `SPEC-runtime-stages.md` §8. Section 13.7 records the critique resolutions and remaining verification; RT-01–03 results stay historical. Authorization includes the selected job/file/terminal observability work, not live deployment or hardware/clinical acceptance.

Smaller option: keep the existing coordinator, page encoder and `stage_artifact`; use bounded current-range cursors and private disk-backed candidate deduplication. No new queue service, archive, model package or automatic clinical retry. Do not simply disable the rejection while eager intake/worker paths remain.

### 13.1 Storage and compatibility first

1. Freeze a historical v10 test fixture by composing the already-frozen v9 schema and unchanged migration 010; assert the original v10 count limits before any upgrade. Add the next verified-free forward migration (`011` was unused); preserve those historical sources rather than duplicating the clinical schema. Extend only operational `submissions`/`stage_batches` constraints: positive prepared page totals without a 20-page maximum, nonnegative execution cursor without a 10-window maximum. Preserve owner/public-job checks, frozen ≤10 membership, active-coordinator guard, cleanup paths/state/timestamps and bounded JSON. Rebuilding an operational table must preserve existing rows, indexes, triggers and FKs; never rebuild clinical tables to relax positive counts.
2. Store only current window plus a compact cursor `(frozen member position, pipeline pass, next source page)` and bounded current-attempt summaries. Generate each next range lazily; keep `worksets_json` bounded rather than filling it with every future window. Recover validated old v10 workset metadata explicitly instead of inventing completed work or losing its cleanup state. Clinical done/review/populated rows are excluded from resumed writes.
3. Keep full per-page preparation metadata/quality/source/normalization identity in private versioned page artifacts/sidecars; compact submission manifests reference them and record exact source/prepared totals. Read and verify artifacts sequentially before promotion. The existing full quality payload may be streamed to durable storage, but not accumulated in Python; worker handwriting lookup reads per-page metadata. Historical quality JSON remains readable. Keep null pre-promotion public totals and same-ID consent/history transfer.
4. Candidate/report/medication deduplication and ordering use private per-submission scratch SQLite or existing page artifacts where sufficient, never partially published clinical rows. Scratch lives in application-generated private `.runtime/<submission-id>/` paths under the upload root, is quota-accounted/excluded from serving/backups, and has durable cleanup ownership. Preserve first-seen ordering and all existing keys; do not add a generic cache layer. Retain canonical normalized pages and page text; remove only owned disposable scratch after final save/terminal failure, with recoverable cleanup intent.

Checkpoint: fresh/v8/v9/v10 upgrades on temporary databases preserve accounts/sessions/reviews/audit/clinical schema and operational rows; >20 prepared pages and >10 execution windows work without oversized JSON. No migration/startup against `data/smriti.db`.

### 13.2 Proposed disk and deadline defaults

These values are **finite, unmeasured guardrails for plan review**, not measured hardware capacity or a promise that any PDF completes:

| Setting | Proposed initial value / accounting |
|---|---|
| Upload bytes/pixels | Keep 25 MiB/file and 50,000,000 pixels/page |
| Raw spool | Keep 1 MiB chunks, two spoolers, existing 20-file capacity plus bounded multipart overhead |
| Active output quota | 2 GiB across in-flight normalized pages, sidecars, private stage/candidate artifacts and output-write scratch; durable owned reservations include temporary/duplicate writes |
| Minimum free disk | 1 GiB on each filesystem being written, including the SQLite/WAL volume; independent of the active-output quota |
| Manifest inspection | 300s per submission, before any rendering; finite hard deadline |
| Preparation | 300s per consecutive range of at most the configured ≤20 pages; heartbeats/page activity cannot renew that range deadline |
| OCR | Existing `60s + 120s × pages requiring that engine` per window, separate fallback lifecycle |
| Qwen | Existing 30s startup, 120s/request and `30s + 120s × eligible pages + 60s` per window |
| Cleanup/sampling | Existing two tree-wide ≤5s waits; 1–2s RAM, ≥2s nonoverlapping GPU queries with ≤3s query deadlines |

Validate values centrally in `smriti/config.py`, independent of document page count; remove `max_pages`/`SMRITI_MAX_PAGES` as an admission setting and document the retired variable without silently treating it as a new cap. `max_workset_pages` remains a positive integer ≤20. Fixtures isolate scratch/output reservations as well as raw spool.

Reserve output bytes atomically before bounded writes and reconcile actual sizes/owned reservations on recovery. Account for output staging, SQL artifact payloads and conservative SQLite/WAL write headroom; check actual write errors too. A free-space check cannot reserve the drive against unrelated applications. Capacity exhaustion is a safe operational failure/backpressure with confirmed cleanup, not page-count rejection or silent truncation. After durable final save and disposable cleanup, release in-flight reservations; retained canonical sources/clinical data still consume physical disk and are **not** claimed as reclaimed free space. No automatic deletion of historical images/records to meet quotas.

### 13.3 Preparation and lazy scheduling

1. After safe raw spooling, run supervised manifest inspection, then spawn one supervised preparation child per bounded page range. Each range reopens the same raw path, prepares/persists one page at a time, closes handles and exits before the next range starts. This is the selected simple process mechanism; model-free startup overhead is measured later. No full-file `bytes`, rendered/prepared lists or full-page metadata list across IPC.
2. Each successful page checkpoint is durable independently, but the complete submission promotes only after every page/manifest validates and every owned range tree exits. Raw remains until complete preparation or terminal failure; a first-window checkpoint never deletes the input for later windows. On rejection/failure, clean only the current attempt's partial outputs, preserving pre-existing source paths. Confirm raw unlink under the original privacy/debug rules.
3. Freeze ≤10 submissions once, prepare sequentially and maintain cleanup barriers. Short documents retain whole-document packing in frozen order. A >window-cap document runs alone: for 39 pages at 20, OCR ranges 1–20 then 21–39, whole-document rules, Qwen ranges 1–20 then 21–39 (eligible counts may differ), final save. Do not mix another document into its last range or reset its global page counts. No late arrivals or rejected-member replacement.

Checkpoint: 21/39/41-page synthetic PDFs prepare with one stable job/document/source set; instrument live image/metadata buffers, lazy 1,000+ page scheduling, quota failures and later-window cleanup. Scheduling fixtures do not render thousands of pages or claim RAM/VRAM evidence.

### 13.4 Preserve complete-document interpretation before connecting models

Use bounded page/line reads and private intermediates, not per-window calls to document helpers. Preserve legacy helper entry points for small-fixture regression comparisons; production processing must use the bounded path, with no eager compatibility fallback.

| Helper boundary | Required preservation / verification |
|---|---|
| `classify.py` | Keyword/analyte presence counted once per document, score/tie/threshold behavior and regex boundary semantics, including numbers/units separated by whitespace across page joins |
| `metadata.py` | First valid labeled values, DOB exclusion, fallback precedence, first-eight-document-lines facility rule and first valid identifier; no restart of these rules at a window |
| `extract.py` | Carry table templates through page 20/21, preserve source page numbers/boxes, first-seen field/medication deduplication keys and order; stream candidates to scratch |
| `reports.py` / page-local prose | Continue date/facility context and exact report ranges across windows; first impression/else findings/else first section summary precedence; no window-generated clinical split |
| `directives.py` | Existing line parsing, original combined-text separators, Unicode character offsets, overlap selection and date anchors; stream output without a full combined-text/result list |
| `worker.py` cross-check/final save | Same OCR/Qwen key matching, grounding and provenance; complete-document nonempty verification validation, not per-window emptiness; one atomic clinical save from streamed validated candidates |

Do not invent a fixed overlap width for unbounded regex whitespace or logical lines. Character boundaries, line separators and pattern state must be preserved with bounded/disk-backed carry; an unresolved equivalence case blocks integration. Existing short-fixture eager helpers are reference tests only, not a production solution for long input. Document-detail API result arrays remain a separate legacy read-path scaling risk; this runtime plan does not claim every existing clinical endpoint has constant memory or redesign review pagination.

Checkpoint: equivalence fixtures around pages 20/21 cover inherited table templates, repeated medications, conflicting later dates/facilities, directive offsets, Unicode/newlines and classification matches across joins. Compare actual facts/reports/routing/provenance; no new clinical semantics or accuracy claim.

### 13.5 Integration order and revised checklist boundary

Implement the following small slices after amended-plan/checklist approval; source targets are not claims that new files exist:

| Order | Slice / main file boundary | Verification |
|---|---|---|
| 1 | v10 fixture + forward operational upgrade (`schema.sql`, `db.py`, next migration, DB tests/fixture) | `pytest tests/test_db.py -q` via repository venv |
| 2 | Window/disk/deadline settings and isolated fixtures (`config.py`, runtime tests, `conftest.py`) | `pytest tests/test_runtime_stages.py -q` |
| 3 | Continue approved RT-04/05/06/07 supervisor, telemetry and bounded HTTP foundations | Existing focused RT commands; no models/live app |
| 4 | Revise RT-08/09 preparation ranges, compact artifacts, promotion/cleanup; separately test disk reservations/scratch ownership | Intake/text-layer/jobs/runtime tests |
| 5 | Separate ≤5-file equivalence slices for classification/metadata; extraction/reports; directives/line offsets | Each helper's existing tests plus boundary fixtures before integration |
| 6 | Revise RT-10/11/12 lazy scheduling and disposable per-window OCR/Qwen lifecycles | Runtime/worker/OCR/VLM fake-adapter tests |
| 7 | Revise RT-13/14 complete-document orchestration/streamed final writes/recovery, then RT-15/16 startup/erasure | Worker/review/runtime/privacy/cleanup tests |
| 8 | Revise RT-17/18 full-document progress and finish RT-19/20/21 caller/docs/full verification | Jobs/progress/Intake/App suites, build and isolated synthetic browser checks |

RT-01–03 remain completed against their original contracts; new follow-up tasks cover changed schema/config semantics instead of rewriting their results. Keep RT-22 and deployment gate E open. No slice should span more than ~5 files; split storage/scratch/helper/orchestration work further in the revised checklist rather than hiding it in a giant RT-13 task. Observability does not add a reverse dependency from inference to logging availability.

### 13.6 Verification and approval

Use full executable focused/full commands in `SPEC-runtime-stages.md` §8.5 and §12.7 above, separately in the background. Add synthetic >10-window, later-window timeout/failure, first-empty/later-nonempty Qwen, final transaction rollback, scratch erasure, cursor recovery and no-resurrection coverage. Report actual test counts; old 340-pass evidence is not a new result. No live restart/migration or real PDF/model processing for implementation verification.

Review requested: approve the revised storage/cursor/process approach and the **2 GiB active-output quota / 1 GiB free-space reserve**. Then finalize/approve changed-contract tasks before coding. Numeric quota changes after measurement remain explicit, never silent content truncation. This plan makes no promise of improved real Qwen latency, hardware fit, arbitrary-length completion or horizontally scalable SQLite processing.

### 13.7 Post-critique implementation decisions — 2026-11-05

The user directed implementation after the critique, without another planning approval loop. The preceding review request is historical. Implement the following resolutions and verify each before connecting the dependent stage:

The user clarified this is a **college major-project MVP**, not a production-ready service. Deliver the existing upload/review journey plus safe local diagnostics. Do not add HA, distributed scheduling, external monitoring, dashboards, throughput SLAs or speculative operational controls. Resource bounds, privacy, source/review preservation, atomic writes and owned model cleanup remain necessary on the project laptop; synthetic verification is not a production or accuracy claim.

- Bound decoded page text, words, artifacts, native working memory and helper execution as well as pages/pixels. Use explicit capacity failures, never truncated clinical inputs. New numeric guards must be recorded as unmeasured and tested; retain models/prompts/DPI/quality parameters.
  - Provisional follow-up defaults: 1 MiB decoded UTF-8 page text/logical-line carry, 100,000 words/page, 16 MiB serialized artifact, 6 GiB owned native process-tree memory, 300s inspection/helper deadline. These are capacity failures, not truncation or evidence Qwen fits. Logging uses the spec's 10 MiB × active + five backups, seven days, ≤4 KiB/event, ≤512 events/sink, ≤2s shutdown. `max_pages` temporarily remains for the still-connected eager path; remove it with bounded intake, not before.
- One exclusive JSONL file writer and independently bounded terminal delivery; no shared blocking sink loop. Real blocked-pipe, abrupt-exit and bounded-shutdown tests precede integration. Sanitize Uvicorn/startup/error channels as well as application events.
- Resolve candidate/report associations and ordering in private scratch before the final transaction. Bounded bulk insertion remains one atomic clinical publication with cancellation/rollback and SQLite/WAL headroom checks. No partial clinical commits or replacement of populated/reviewed/terminal documents.
- Safety assertions are independent of legacy-equivalence tests. Correct the identified DOB-only fallback defect with a small regression test; other clinical semantics remain unchanged.
- Keep frozen first-in-first-out document order and consecutive long-document windows. This can delay later uploads; expose truthful waiting state, do not promise bounded queue wait or add interleaving.
- Use 2 GiB active-output quota / 1 GiB free-space reserve as provisional finite guards, not calibration. If a frozen submission cannot reserve capacity, fail that submission safely and continue eligible frozen members after cleanup; never wait for capacity that only this same batch can release. Account all owned temporary, SQL and scratch output through crash recovery.
- Remove automatic full-detail download at completion; add bounded owner-scoped page/detail reads for the existing review journey. Preserve source links and old small-document callers while bounding the long-document path.
- Logging's first delivery retains existing chronological activity, latest failure, omitted-history count and support ID. Multi-filter/export UI, external services and a separate dashboard are deliberately skipped.

Execution order: RT-04 supervision/lock → schema/config follow-ups and bounded telemetry/logging foundation → spool/HTTP → preparation/quota/promotion → bounded helper equivalence → lazy model windows → final save/recovery/erasure → connected API/UI/startup → full synthetic verification. Split each boundary into focused checked changes; do not mark placeholders as implementation. RT-22 and live rollout remain separately gated. No app startup against `data/smriti.db`, live migration/restart, real records/models, deletion, commit or push.

### 13.8 Approved corrective slice — 2026-11-07

The user approved adapter/private-error/Queue fixes and selected **“Finish fixes first”** before specifying smart page selection, human review and chronological medication/date enhancements. Finish only these corrections:

- RapidOCR 1.4.4's installed flat options and detector/classifier/recognizer session interfaces; retain requested cached weights, CPU providers, four intra-op threads and recognition batch one. Verify with stubs, not model initialization.
- Qwen's safe HTTP/connection/observed-server-exit/transfer/envelope/output failure categories and bounded HTTP status, propagated through committed progress/private runtime diagnostics before cleanup. Valid `[]` is distinct from malformed output; complete-document verification/failure policy remains unchanged.
- Compact owner-only Active/Recent job listing (default 20, maximum 50; separate pagination), one selected detailed history, persistent Queue plus Summary/Intake/document/source-page hash routes, unsent-file navigation guards, nonoverlap/abort/session/terminal polling and truthful source-versus-eligible-page counters. Discover legacy jobs without recovery.
- Update connected API/spec/test/result documentation; run full backend/frontend suites and production build against synthetic fixtures/temporary roots only. Browser-rendered behavior, real-model/hardware calibration and the original discarded Qwen subtype/status remain unverified.

No new dependency/schema/service, model tuning, automatic retry/recovery, OCR-only publication, clinical confidence or medication-policy change. Preserve existing source/review/account data and unrelated work. Live restart/migration, real-record/model processing, cleanup rerun, commit/push and RT-22 remain separately gated. New clinical phases require explicit specification of safe page selection after OCR, human verification separate from model certainty, date precedence and preserved prescribed/ongoing/stopped provenance.

### 13.9 Approved hardware/degradation/recovery extension — 2026-11-07

User approved the expanded scope and directed completion plus current web research. This supersedes §13.8's no-tuning/no-recovery/no-OCR-only restriction, not its privacy/data/live-rollout fences.

1. Safe diagnostics: extend existing event registry/progress/UI; suppress successful `/api/jobs` polling; no raw server output.
2. Qwen fit: requested 4096/1280/2048/240 settings, Q8 KV, CPU mmproj, six threads, no warmup, explicit single slot; preserve source bytes and input bounds.
3. Degraded verification: reuse quota-accounted identity-bound page artifacts for unavailable outcomes; freeze missing pages on operational failure after cleanup, preserve valid fields, annotate OCR-only review and reject unexplained absence/corruption.
4. Worker recovery: retain exclusive coordinator, interruptible bounded backoff/ten-failure stop, closed admission during validated recovery, truthful recovered events and pause fencing.
5. Update contracts/references/results and run focused/full synthetic backend/frontend/build checks. No dependency/model download, historical job reprocessing, live restart/migration, commit or push. Hardware fallback experiments remain manual and separately gated.

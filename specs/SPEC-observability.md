# SPEC-observability

Approved §13.9 extension: `qwen_unavailable_page`, `verification_partial`, `verification_unavailable`, `recovering`, `worker_retrying` and `worker_recovered` are code-owned bounded events. No raw server output. Successful `/api/jobs` and detail polls are suppressed; failed polls remain diagnostic. Recovery closes admission and reports recovered only after checkpoint/source/artifact validation, never on exception capture.

| | |
|---|---|
| Module | `observability` — one extension of existing job/runtime visibility, not an operator dashboard |
| Status | MVP connected in existing job view + private files + CMD/terminal panels; synthetic verification in `tasks/todo.md`, no production-readiness claim |
| Depends on | Existing ownership-checked job progress; `runtime-stages` supplies supervised stage events and measured summaries |
| Authority | SRS NFR-05/07/18, FR-JOB ownership/progress, FR-RUN privacy/cleanup; post-critique implementation direction in `tasks/plan.md` §13.7 |

## 1. Objective and assumptions

Make the college-project MVP diagnosable in the existing in-app job view, running CMD/PowerShell/IDE terminal panels and local searchable logs. Identify the failing request/job/stage/page, actual engine, duration and cleanup outcome without revealing clinical content. Users see only their own processing history, not global operational logs or another account's stage data.

Scope selected by the user: **existing job view + local files + terminal panels**. The user clarified this is a college major-project MVP, not a production-ready service. Assume local Windows deployment, standard-library logging/JSON/queues/rotation and already approved psutil/nvidia-smi measurement. Keep one processing coordinator and current ownership/consent. No new dashboard, roles, logging service, network export, Redis/Elasticsearch/Grafana installation, HA, throughput SLA or clinical schema. Test boundedness/privacy/failure handling needed on the project laptop; real hardware capacity and clinical accuracy remain unverified.

## 2. Event and privacy contract

Use one versioned, code-owned structured operational event schema across terminal/file sinks, with a safe owner-scoped projection for existing job activity. Messages come from an event registry, not interpolated model/document/request/exception text. Keep UTC timestamps and monotonic durations distinct; human terminal formatting must not change the underlying JSON event.

| Field | Contract |
|---|---|
| `schema_version`, `timestamp`, `level`, `event`, `component` | Known bounded vocabulary; UTC timestamp, severity and code-owned message |
| `request_id`, `job_id`, `stage_attempt_id` | Generated/validated opaque correlation identifiers; propagate to spawn children via bounded trusted context, never accept arbitrary incoming text as an ID |
| Private `batch_id`, window range/cursor | Operator file/terminal context only; never expose shared membership/aggregate batch history to ordinary users |
| `stage`, `engine`, provider/model version, `page`, known total | Actual trusted identities and nonnegative counts; unknown totals remain null, pages stay globally numbered across windows |
| `duration_ms`, known result/skip/failure code, `exit_reason`, `cleanup_outcome` | Finite measured values; operation failure and resource cleanup are separate, timeout is not OOM |
| Qwen failure `code`, HTTP `status` | Allowlisted HTTP/connection/observed-server-exit/transfer/envelope/output categories; only integer 400–599 for HTTP failures; no response body, headers, raw exception or server output |
| Measurement summary/availability | Existing observed before/peak/after RAM/VRAM and sampler coverage; no raw sample stream or invented zero; shared/device-wide metrics stay operator-only |
| Logging health | Detectable dropped/deferred events, sink failures and last successful write; unknown crash-loss/coverage stays unavailable, not fabricated counts |

IDs enable diagnosis but remain pseudonymous operational data: restrict local files/terminal access and do not call them anonymous. Exclude patient/account IDs, usernames/aliases, UHIDs, dates/clinical values, filenames/source hashes/paths, images/OCR text, prompts/raw responses, cookies/tokens/passwords, query strings/request bodies, raw headers and exception messages/unsanitized traceback/stderr. Debug mode does not bypass privacy. Drop unknown keys/unsafe strings **before queueing or serialization**; JSON encoding alone is not sanitization.

Log matched route templates and method/status/duration rather than raw URL paths. Generate request IDs locally and return an opaque support ID where the agreed API contract permits; unauthenticated errors never expose job ownership. Preserve the already approved narrow sanitized `/v1/models` diagnostic only; do not invent a responsible caller. Suppress/reduce successful polling/health noise without hiding failures. Fix leaking application call sites (`%s` exceptions, raw validation paths, `logger.exception`) at source rather than expecting a regex redactor to catch everything.

Third-party/Paddle/llama stdout/stderr is not safe application telemetry. Supervised model children must not inherit uncontrolled terminal/file handlers or dump raw runtime output; keep output suppressed or reduce only recognized bounded operational signals to approved event codes. Suppression must not hide a stage crash: supervisor exit/timeout/cleanup outcomes remain recorded. App-controlled exception handlers must not fall back to raw stack dumps.

## 3. Sinks, retention and failure behavior

### Terminal/CMD panels

Print concise readable lines while the app runs: timestamp, severity, component/event, job/request ID, stage/page/window where known, actual engine, elapsed duration and safe failure/cleanup codes. Show warnings/errors distinctly with text, not color alone. Use plain UTF-8 output that survives redirected stdout and Windows CMD/PowerShell/IDE terminals; avoid mandatory ANSI control sequences or a live animation/dashboard. Log model loading/readiness, range transitions, cache/fallback/skips, timeout/crash, cleanup and final save without pretending a window finished the document.

### Local files

Persist the same sanitized event as one bounded JSON object per line in private `data/logs/smriti.jsonl` (isolated root in tests), outside static serving and ordinary account downloads/exports. Local operators can tail or filter by full opaque ID/severity/event using standard PowerShell; no new viewer service. Startup/recovery must not silently delete an unrelated path or follow a log-directory escape/reparse point.

Proposed initial defaults for requirements review: **10 MiB per file, five rotated backups plus the active file, seven-day maximum age, 4 KiB maximum serialized event, 512 queued events and a ≤2s shutdown flush wait**. Bound bytes and age, including startup/rollover cleanup of application-owned files; account for one bounded record at rollover. Do not create a file per job/process or retain an unlimited attempt log. Logs are excluded from source backups/exports by default and are not a medical audit trail; document the distinct append-only clinical audit policy. These defaults are unmeasured and configurable only through validated central settings, not scattered environment reads.

### Bounded asynchronous logging

Use one exclusive local file writer for rotation, with independently bounded terminal delivery so a blocked terminal cannot stop the file sink. Spawned producers send sanitized bounded events, not arbitrary `LogRecord` objects with exception text. Standard-library facilities are preferred where they meet this contract. Multiple processes must not race separate `RotatingFileHandler`s against the same file. Initialize/shutdown only application-owned handlers idempotently; repeated app creation/tests must not duplicate output or overwrite harness/host handlers.

Producers must not block HTTP, inference or SQLite transactions on slow console/disk I/O. A full queue cannot grow memory, spawn retry threads, recursively log its failure or block indefinitely: account for detectable losses by severity and emit a rate-limited safe degradation summary when possible. Detectable errors are not silently converted to success. Critical processing outcomes remain durable in existing job/cleanup state regardless of log delivery; logs are **best-effort diagnostics**, not exactly-once durable job state. Abrupt process death may lose unflushed file events; label the gap/availability rather than promising lossless logs.

Logging sink failure/disk-full/blocked terminal must not prevent tree cancellation, raw deletion or shutdown. Keep a finite flush/join budget, report unflushed/degraded state safely when a functioning channel exists, and never dump the rejected payload via logging's fallback `handleError`/stderr path. A failed file sink may leave terminal output available (and vice versa); expose each sink's health separately where measurable. Shutdown behavior under stalled sinks needs a synthetic test before choosing writer mechanics in the implementation plan.

SQLite progress/artifact transactions remain short. Emit completion diagnostics after the corresponding durable state transition commits, not before a transaction that may roll back. Correlate events with attempt/sequence so replay/recovery can be recognized; do not claim atomic DB+file delivery. Logging does not become a prerequisite for model cleanup or clinical eligibility.

## 4. Existing job-view monitoring

Reuse `web/src/components/JobProgress.jsx` and its native “Processing details” disclosure. Keep chronological retained activity, latest warning/error and failed-operation context visible. Provide a copyable job support ID, never filesystem/global logs. Multi-filter/search/export UI and a new viewer are deliberately deferred for this MVP; standard PowerShell can filter the private JSONL file locally.

Keep existing stage/verification distinctions, full-document progress across internal windows, elapsed timing, failures/skips/cleanup and unavailable history. Retain the ≤500-event and bounded-byte history contract; show omitted-event count and unavailable history honestly. Use bounded rendered subsets if needed rather than a new dependency. No extra polling stream/SSE/websocket is needed: preserve nonoverlapping two-second owner-scoped polling, reload/navigation/session boundaries and terminal stop behavior.

The 2026-11-07 approved Queue extension reuses this progress view: owner-only compact Active/Recent listing, one selected detailed history and persistent `#/queue` navigation (`docs/API.md` §5, `SPEC-processing.md`). Qwen source pages are not eligible-page totals. Safe failure code/HTTP status stay in durable failure context after cleanup and committed diagnostic delivery; historic discarded transport/status evidence cannot be reconstructed. No global log viewer or model-output collection is added.

Global queue depths, other owners' jobs/batch telemetry, device-wide/system measurements and local logging files are operator-only terminal/file data, not additions to a patient's job API. Show only genuinely job-scoped measurements if attribution is available; otherwise omit or label unavailable. Maintain keyboard focus/native controls, text severity, AA contrast/reduced motion and no explanatory layout captions. UI activity is durable progress, not a live tail of the global log file.

## 5. Structure, style and executable checks

Affected files: one focused logging module such as `smriti/observability.py`, central `smriti/config.py`, app lifespan/request/error handling in `smriti/app.py`, existing intake/worker/OCR/text-layer/VLM/runtime event callers and `smriti/job_progress.py`, `api/routers/jobs.py`, `web/src/components/JobProgress.jsx`, associated tests and operational/startup documentation. Recheck all callers before coding; model-process/runtime integration follows their approved implementation order. `start.ps1` documentation/output may need matched logging initialization, but tests must not execute the live startup script.

Follow existing Python/JS naming and house components. Example boundary shape (illustration, not an implemented helper):

```python
with engine.begin() as conn:
    record_progress(conn, job_id, "page_read", page=page, count=word_count)
emit_event("page_read", job_id=job_id, page=page, count=word_count)
# Medical words and raw exceptions never enter the event.
```

Existing executable checks, each run separately in the background against synthetic/isolated roots:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_job_progress.py tests/test_worker.py tests/test_ocr.py tests/test_vlm.py tests/test_runtime_stages.py -q
npm --prefix web test -- src/test/JobProgress.unit.test.jsx src/test/Intake.integration.test.jsx src/test/App.system.test.jsx
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test
npm --prefix web run build
git diff --check
```

The subsequent plan must add `tests/test_observability.py` for privacy/queue/rotation/request/lifecycle cases and importable synthetic spawned producers; that new test command is not executable until implemented. Any manual tail/filter examples apply only to synthetic generated logs during verification, never reading existing medical/account files. Do not run `start.ps1`/`smriti.main` merely to inspect logs: they can migrate/start live processing.

## 6. Acceptance, boundaries and review

- Correlate synthetic upload/request → preparation ranges → OCR/fallback → Qwen → cleanup/save across real spawned fake producers and terminal/file output; nullable counts, actual engines, global page numbering and distinct operation/cleanup outcomes survive. No real model inference is needed for these tests.
- Privacy sentinels inject sensitive strings into request URLs/headers/errors, custom exception messages, malicious model/version fields, model stderr and unknown metadata. Verify absence from **all** terminal/file/queue/job surfaces and error fallback paths; unknown text must not become an event/message/ID. Another account cannot access/filter/export this job or global log data.
- Rotation/age/exclusive writer tests on Windows-safe temporary paths enforce file/record/queue bounds, startup idempotence, no per-process file growth and no unrelated-file deletion. JSONL lines parse independently; text terminals remain readable without ANSI.
- Synthetic burst and sustained-load tests exceed queue/history limits, inject slow/blocked console/file sinks and disk-full, count detectable losses, expose degradation and prove bounded producer/shutdown behavior. Record actual test rates/latency and measured queue coverage; do not claim a throughput SLA from a guessed number or fake hardware metrics.
- Failed DB commit emits no false committed completion; sink loss cannot change durable failed/done/cleanup state or stop tree reaping. Crash recovery can indicate missing/unflushed diagnostic coverage without overwriting clinical rows or fabricating history.
- UI tests cover chronological activity, copyable support ID, latest failure context, global page 21/39, history truncation/unavailability, account change, reload/nonoverlapping polling, keyboard/axe/reduced-motion and stable focus. Record isolated narrow/desktop browser evidence or explicitly leave it unverified.

**Always:** keep bounded ownership-safe logging in every sink, validate event inputs before serialization, preserve durable job/audit distinctions and cleanup, label absent/partial measurements and diagnostic delivery honestly.

**Ask first:** adding dependencies, external sinks/telemetry, admin roles/global endpoints, unrelated API fields, retention-policy changes beyond this scoped implementation and live rollout require explicit review. The user has directed this MVP implementation; `tasks/plan.md` §13.7 records post-critique decisions.

**Never:** expose raw clinical data/secrets even in CMD/debug; automatically forward logs to a service; weaken account/consent or tree cleanup; create a second global log UI; claim production readiness, lossless logging, horizontal scale, measured RAM/VRAM improvement or clinical accuracy from synthetic checks.

Implementation scope: existing-job-view + terminal + bounded JSONL, with provisional defaults and post-critique decisions in `tasks/plan.md` §13.7. Prove stalled-sink-safe shutdown and caller privacy using synthetic tests before integration. External collection, distributed scalability and filter/export UI remain deliberately skipped. No live restart/migration/model processing is authorized.

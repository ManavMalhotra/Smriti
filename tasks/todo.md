# Task List

Ordered by dependency. One task per line, one owner, one test. Do not start a phase before the previous phase's gate is green.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · **GATE** blocks the next phase.

Current slice: approved Qwen tuning, durable degraded review, bounded worker recovery and private diagnostics under `tasks/plan.md` §13.9 are complete and synthetically verified; see the 2026-11-07 ledger below. The §13.8 adapter/private-error/Queue corrections remain implemented and synthetically verified. Earlier long-PDF/private-diagnostics results remain dated historical evidence. PR-03 ethics/corpus/accuracy gates and new clinical-policy specifications remain open. No live rollout, migration, model/real-record processing, stored-job recovery, cleanup rerun, commit or push is authorized.

## Approved §13.9 extension — 2026-11-07

- [x] Safe diagnostic/progress events and successful list/detail-poll suppression, including installed FastAPI's unprefixed route templates; privacy regressions pass.
- [x] Requested Qwen launch/request tuning and bounded source-preserving resizing; adapter tests pass, 6 GiB ceiling unchanged.
- [x] Durable unavailable outcomes, valid-reading retention and OCR-only review provenance; corruption/interrupted-marker tests pass. Fully degraded documents are excluded from Qwen rescheduling, including consistently failing children.
- [x] Validated worker recovery, bounded backoff/ten-failure stop and pause/admission tests pass; broken diagnostics cannot prevent cleanup.
- [x] Current web research/primary references recorded in `docs/qwen-hardware.md`; installed flag support checked, real-model fit unverified.
- [x] Connected API/UI/docs, focused/full backend/frontend verification, production build and diff checks pass; final observed results are recorded below.

Verification evidence (temporary databases/synthetic sources/fake models only):

- Focused adapter/model/helper/coordinator/service/worker/progress/HTTP tests: **132 passed in 156.85s** using `python -m pytest -o addopts="" -q` with the eight touched modules.
- Final coordinator/service/runtime follow-up after eliminating degraded-child rescheduling and correcting the old budget expectation: **119 passed in 71.69s**.
- `npm --prefix web test`: **83 passed across 13 files in 16.92s**, after changing the existing document-image test to await actual loaded content instead of its always-present heading. An earlier concurrent run exposed that race (82 passed/1 failed); no production document-view logic was changed.
- `npm --prefix web run build`: **passed in 2.05s**, 614 modules. `git -c core.safecrlf=false diff --check`: **passed**. No line-ending normalization or unrelated cleanup was performed.
- First full backend expansion run: **703 passed, 1 failed, 1 skipped in 459.01s**; sole failure expected the superseded 120s Qwen budget. The test now asserts requested 240s and the derived bounded window budget. Subsequent complete-suite results are recorded below.
- Budget-corrected full backend rerun: **705 passed, 1 skipped in 423.35s**. This run started before the final three consistently-failing-child regressions; subsequent complete-suite results are recorded below.
- No-rescheduling full run: **707 passed, 1 failed, 1 skipped in 417.52s**; the real blocked-terminal pressure test exceeded its unchanged 25s outer deadline while another backend run overlapped. Concurrency is a possible timing contributor, not a proven cause. Isolated reproduction passed (**1 passed in 5.54s**). The synthetic helper now closes owned sinks in `finally` even when readiness/write assertions fail; a regression checks that failure path. No production shutdown deadline was relaxed. Diagnostic/HTTP/service follow-up: **34 passed in 22.35s**.
- Final complete backend suite, including the synthetic sink-cleanup regression: **709 passed, 1 skipped in 397.97s**, using `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q`, backgrounded without another overlapping backend suite. The original pressure-test timeout's cause remains unproven; the unchanged pressure/shutdown assertions passed in this final run. Only reference/ledger documentation was updated after this run.
- Web search plus fetched primary model/current/pinned runtime/Microsoft/Lenovo docs and explicitly secondary hardware corroboration are in `docs/qwen-hardware.md`; stale AMD URL/1650 Ti versus exact GPU distinctions are recorded rather than misrepresented. User-confirmed hardware is Lenovo IdeaPad Gaming 3 / Ryzen 5 5600H / GTX 1650 / 8 GB RAM / 256 GB SSD. Matching Lenovo 15ACH6 family specifications corroborate CPU/GPU/RAM offerings, not the exact SKU, available SSD space or inference fit. Model roles, unchanged CPU OCR settings and pinned quantized-V/Flash-Attention behavior are referenced; no packages or model weights were downloaded.

No live data/migration/restart/model inference/hardware calibration/stored-job reprocessing, dependency/model download, commit or push. Real-model Flash Attention/Q8 compatibility, latency, dense-text accuracy, browser-rendered behavior and RT-22 remain unverified; B1 evaluation skip requires user-provided ground truth.

### Follow-up: manual Qwen server / stale worker — 2026-11-07

- [x] Read-only diagnosis of the latest two-page job (`adfe6ebd…`): OCR completed; `qwen_port_busy` occurred before independent reading, comparison or saving. Confirmed stage shutdown, terminal failure, deleted scratch and retained normalized source. No clinical content was read or printed.
- [x] Confirmed port 8085 is held by the manually launched server. The live Smriti process started at 06:43 UTC, before the fallback/runtime source edits at 08:48–09:10 UTC; its older coordinator did not record unavailable outcomes. Current source already handles this code without relaxing ownership or reusing another process's server.
- [x] Added `qwen_port_busy` to the existing no-rescheduling/degraded-publication regression. That case plus the unowned-listener adapter regression passed: **2 passed in 5.23s**, backgrounded, temporary synthetic fixtures/fake supervision only. Final diff check passed. The earlier full-suite result remains its dated result, not a rerun including this added parameter.
- [x] Recorded user-supplied standalone startup evidence and current primary warning references in `docs/qwen-hardware.md`. Four-slot standalone startup does not validate one-slot owned inference or the 6 GiB ceiling; no image-token, model, ownership or production-code change was made.
- [ ] Live activation/retry remains separately authorized: stop the user's manual server and old Smriti process, then start the current app-managed runtime. Inspection found schema v11, no active batches and no pending/preparing/queued/running promoted submissions at that snapshot. Restart alone does not retry terminal failed jobs; identical re-upload may deduplicate, and deleted OCR scratch must not be claimed recoverable. No process stop/restart, DB mutation, stored-job reprocessing, dependency/model download, commit or push was performed.

---

## Test and maintainability slice (2026-10-24)

- [x] Register `unit`, `integration`, and `system` pytest markers in `pyproject.toml`
- [x] Mark all backend test modules; add `tests/test_system.py` for printed and handwritten journeys
- [x] Rename frontend tests to `*.unit.test.jsx`, `*.integration.test.jsx`, `*.system.test.jsx`; add npm layer scripts
- [x] Write `docs/test-plan.md`; link it from `docs/index.md` and `README.md`
- [x] Add `scripts/verify.ps1` and `scripts/verify.bat` for backend, frontend, build, and eval
- [x] Split CI into backend and frontend jobs; run frontend tests and build
- [ ] Re-run the full verification after future feature changes; update test counts in `docs/test-plan.md`

## Intake experience slice (2026-11-04)

Scope/specs, `tasks/plan.md` §11, and this checklist approved by the user. Implemented and locally verified on 2026-11-05; no live deployment or medical-data changes. Earlier roadmap gates and completed work remain unchanged.

- [x] IE-01 — Account API validation
  - Acceptance: trim username/alias before constraints, preserve passwords, safe actionable field errors, unchanged login/session/legacy ownership behavior.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_patients.py -q`
  - Files: `smriti/models.py`, `smriti/app.py`, `tests/test_patients.py`.
- [x] IE-02 — Registration form recovery
  - Acceptance: client constraint checks, linked inline errors and focus, preserved valid fields, disabled mode switching/double-submit while busy; remove decorative copy only.
  - Verify: `npm --prefix web test -- src/test/Auth.integration.test.jsx src/test/App.system.test.jsx`
  - Files: `web/src/pages/Auth.jsx`, `web/src/index.css`, `web/src/test/Auth.integration.test.jsx`.
- [x] IE-03 — Additive schema v9
  - Acceptance: nullable `jobs.progress_json` in fresh schema and migration; existing accounts, sessions, documents, and reviewed observations survive; historical telemetry remains absent.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -q`
  - Files: `smriti/schema.sql`, `smriti/db.py`, `smriti/migrations/009_job_progress.sql`, `tests/test_db.py`.
- [x] IE-04 — Bounded progress writer
  - Acceptance: atomic update-only snapshots, UTC timestamps, monotonic event sequences, 500-event window and explicit truncation; deleted jobs never recreated; operational data only.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_job_progress.py -q`
  - Files: `smriti/job_progress.py`, `tests/test_job_progress.py`.
- [x] IE-05 — Truthful VLM lifecycle
  - Acceptance: readiness and cleanup callback events reflect actual operations; startup failure cleans up only a spawned process; raw responses stay out of logs.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_vlm.py -q`
  - Files: `smriti/vlm.py`, `tests/test_vlm.py`.
- [x] IE-06 — Worker stage/page events
  - Acceptance: actual OCR/cache/text-layer/classification/extraction/Qwen/cross-check/save/recovery/failure activity; safe metadata; no done before medical transaction commit; existing handwritten/mandatory-Qwen behavior unchanged.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_job_progress.py -q`
  - Files: `smriti/worker.py`, `tests/test_worker.py`, `smriti/job_progress.py`.
- [x] IE-07 — Private additive job API
  - Acceptance: original job fields preserved; snapshot/events/truncation added; historical rows work; another account cannot read events; deleted documents remove progress.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_ingest.py tests/test_system.py -q`
  - Files: `api/routers/jobs.py`, `tests/test_jobs.py`, `tests/test_ingest.py`.
- [x] IE-08 — Reusable progress UI
  - Acceptance: concise activity, actual model/page, stage-specific progress and elapsed time; colorful severity text; accessible expandable ordered logs; stable focus and terminal timing; no invented percent.
  - Verify: `npm --prefix web test -- src/test/JobProgress.unit.test.jsx`
  - Files: `web/src/components/JobProgress.jsx`, `web/src/index.css`, `web/src/test/JobProgress.unit.test.jsx`.
- [x] IE-09 — Bulk intake and polling
  - Acceptance: removable pending files; one upload POST at a time; mixed-batch continuation and per-file identities; explicit upload retry, shared optional overrides, consent, safe navigation/session handling; truthful independent progress and review links; one-file workflow preserved.
  - Verify: `npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/App.system.test.jsx`
  - Files: `web/src/pages/Intake.jsx`, `web/src/index.css`, `web/src/test/Intake.integration.test.jsx`, `web/src/test/App.system.test.jsx`.
- [x] IE-10 — Contract and startup documentation
  - Acceptance: API response, telemetry privacy/retention, schema v9 and backup-before-deployment guidance documented without claiming real model verification.
  - Verify: compare documented responses to API tests; `git diff --check`.
  - Files: `docs/API.md`, `docs/data-model.md`, `README.md`.
- [x] IE-11 — Final verification
  - Acceptance: backend suite, frontend suite, production build, and scoped diff checks pass; browser/hardware checks are performed if safely available, otherwise explicitly reported unverified. No live restart, data reset/reprocessing, commit, or push.
  - Verify: `.\.venv\Scripts\python.exe -m pytest -q`; `npm --prefix web test`; `npm --prefix web run build`; `git diff --check` (run commands separately).
  - Files: task status/result notes only, plus scoped fixes if verification finds regressions.

### Intake verification — 2026-11-05

- Full backend suite: **206 passed, 1 skipped** (`pytest -q`; repeated with `-o addopts="" -q` to retain the summary).
- Full frontend suite: **64 passed** across 11 files, including axe checks and the batch→review App journey.
- Production build and `git diff --check`: passed. Existing Git LF/CRLF notices are warnings, not whitespace failures.
- Regressions cover sequential deferred POSTs, identical filenames, mixed outcomes, explicit and ambiguous-upload retries, consent/overrides/removal, non-overlapping polling/recovery, terminal/404/session stops, session expiry during a POST, navigation/reload warnings, account changes, and unmount cleanup. Writer tests cover truncation/resume verification and failure context before cleanup; handwriting counts are measured before filtering.
- Isolated Edge/Chromium browser replay at **390×844** and **1280×844**: no horizontal overflow, keyboard-expanded logs, visible focus, reduced-motion settings, and progress/log text contrast ≥4.5:1. Synthetic File objects and mocked API/model outcomes exercised the built UI; no real file picker, account, backend, or model inference was involved. No browser console/page errors were observed. Browser-owned processes and the temporary fixture server were closed.
- Browser Evidence export: `C:\Users\manav\AppData\Local\Temp\opencode\smriti-intake-browser-evidence.json`; narrow-screen screenshot: `C:\Users\manav\AppData\Local\Temp\opencode\smriti-intake-mobile.png` (temporary, not repository data).
- **Still open:** real Qwen inference and PaddleOCR-VL production integration; B1 ground truth (`data/eval/ground_truth_b1_40.json`) and B2 cell crops; the user's exact registration incident without its error details. Fake-engine tests and browser replay do not close these obligations or establish accuracy.
- No live migration/restart, reset, reprocessing, dependency installation, commit, or push occurred. Existing accounts, medical records, and review decisions were left untouched. Deployment still requires a stopped worker/server and a consistent database backup.

## Hardware-safe runtime Phase 1 checklist (2026-11-05)

Status: **MVP implementation connected and synthetically verified**. The user approved the original checklist on 2026-11-05, then directed the post-critique implementation under §13.7. RT-01–03 results below remain historical evidence for their original contracts; LP follow-ups implement the changed long-PDF contract. No live migration, restart or real-record/model processing is authorized.

Scope update: SRS v1.3 / runtime spec §8 and the subsequently authorized §13.7 supersede page-count admission and no-window mechanics. Internal windows remain ≤20 pages, with ≤10 frozen submissions, complete-document interpretation and one final clinical save. Observability is the existing job disclosure plus private file/terminal sinks; no dashboard or production-readiness claim. Earlier pending-approval statements in dated notes are historical, not a new approval loop.

Scope: [SPEC-runtime-stages.md](../specs/SPEC-runtime-stages.md), [SPEC-intake.md](../specs/SPEC-intake.md), [SPEC-observability.md](../specs/SPEC-observability.md), SRS v1.3, `tasks/plan.md` §13.7. Implementation owner: coding agent; approval owner: user. Dependencies are checks, not permission for parallel agents. Tests use synthetic inputs/isolated paths; blocking commands run separately in the background without polling.

- [x] **GATE RT-00 — User approves this checklist before coding.** Approved 2026-11-05 (“okay proceed”). Live deployment, legacy nonterminal-job processing, and real-record evaluation require separate authorization even after this gate.
- [x] RT-01 — Add operational staging schema
  - Depends on: RT-00.
  - Acceptance: additive `submissions`/`stage_batches` with ownership/consent, frozen membership/checkpoints, bounded telemetry, cleanup intent/state/timestamp, and nullable prepared links; same-ID promotion possible without rebuilding clinical tables or weakening positive existing counts. Fresh and upgrade paths preserve accounts/reviews/audit/jobs; no live migration.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_db.py -q`.
  - Files: `smriti/schema.sql`, `smriti/db.py`, `smriti/migrations/010_runtime_stages.sql` (confirmed next free version), `tests/test_db.py`, frozen historical `tests/fixtures/schema_v9.sql`.
  - Result: 97 database tests passed (2026-11-05, temporary databases); fresh/v8/v9 upgrade, unchanged historical rows/schema, consent/review/audit/jobs, ownership/same-ID promotion, positive clinical counts, active-batch guard, frozen membership, bounded JSON and cleanup timestamps. `git diff --check` passed (line-ending warnings only). This tests schema support, not runtime deletion/supervision or live migration.
- [x] RT-02 — Submission progress and private job contract
  - Depends on: RT-01.
  - Acceptance: update-only pending/preparing/terminal submission progress using the existing bounded event format; ownership-checked job resolution preserves historical fields, exposes null pending document/totals, safe deferred rejection, and stable public job identity. No shared-batch membership or deleted-row resurrection.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_jobs.py tests/test_job_progress.py -q`.
  - Files: `smriti/stage.py`, `smriti/job_progress.py`, `api/routers/jobs.py`, `tests/test_jobs.py`, `tests/test_job_progress.py`.
  - Result: 17 jobs/progress tests passed (2026-11-05). Pending/preparing null totals, private intake/batch fields, cross-owner 404, safe deferred errors, 500-event bounds, same-ID history/start-time transfer and deletion/promotion/competing-progress races pass. Reused `record_progress`; no new stage wrapper was needed. Promotion orchestration itself remains RT-09.
- [x] RT-03 — Runtime settings and approved measurement dependency
  - Depends on: RT-01.
  - Acceptance: centralized validated spool/page/submission limits, explicit debug-retention flag default off, finite approved deadlines and sample intervals; upload limit cannot exceed whole-workset cap. Pin one verified Python 3.11/Windows-compatible psutil release in the implementation environment; no pynvml or model/dependency upgrade.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py -q` (new config/self-check cases; no models).
  - Files: `smriti/config.py`, `requirements.txt`, `tests/test_runtime_stages.py`, `tests/conftest.py` (isolated spool root).
  - Result: all 35 config/self-check cases passed in the full backend run (2026-11-05). Budgets/caps/intervals, explicit 0/1 debug flag, finite whole-workset arithmetic and environment snapshots are validated. `psutil==7.2.2` was already installed; no installation or dependency upgrade ran. Release/Windows `cp37-abi3-win_amd64` wheel verified via https://pypi.org/pypi/psutil/json; local import/self-inspection passed on Python 3.11.17 / win32, with private-byte support. The 64 KiB multipart overhead allowance is an initial unmeasured guardrail; quota/multipart enforcement remains RT-06/07. No model/hardware measurement is claimed.
- [x] RT-04 — Spawn-safe Windows process-tree supervisor
  - Depends on: RT-03.
  - Acceptance: kill-on-close Job Objects assigned before descendant creation; non-inherited handles, startup handshake/EOF abort, identity-safe child-first terminate/kill with two tree-wide ≤5s waits, normal/crash/cancel cleanup and coordinator file lock. Failed assignment/unconfirmed tree exit prevents next-stage admission; no parent-only or torch-cache cleanup fallback.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py -q` (real synthetic parent/grandchild and abrupt-controller tests).
  - Files: `smriti/runtime.py`, `tests/test_runtime_stages.py`.
  - Result (2026-11-05): **67 runtime/config tests passed in 10.68s** after fixing Windows named-pipe EOF during `poll()`. Real isolated spawn tests verified normal/exception/crash/native-hang/cancel exits, child/grandchild disappearance, kill-on-close after abrupt controller termination, pre-import assignment refusal/EOF, non-inheritable Job Object/lock handles, native memory guard, request deadlines, bounded/private IPC and exclusive/released coordinator locking. Synthetic targets are in `tests/runtime_targets.py`; no models/live app/data were used. Supervisor integration with upload/worker remains pending; this does not remove the current page limit or establish hardware fit.
- [x] RT-05 — Bounded stage RAM/GPU telemetry
  - Depends on: RT-01, RT-03, RT-04.
  - Acceptance: 1–2s RAM/private-byte/descendant/system samples; pre/post plus nonoverlapping ≥2s nvidia-smi queries bounded at 3s. Device-wide GPU readings and sampled peaks are labeled honestly; unavailable values are null with `nvidia_smi_unavailable_or_timeout`. Summaries/storage/monitor buffers remain bounded; every exit cleans samplers; privacy sentinels exclude medical/input/raw-model content.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_telemetry.py tests/test_runtime_stages.py -q` (fake clock/driver plus synthetic sampler cleanup).
  - Files: `smriti/runtime_telemetry.py`, `smriti/runtime.py`, `smriti/stage.py`, `tests/test_runtime_telemetry.py`, `tests/test_runtime_stages.py`.
  - Result (2026-11-05): **98 telemetry/runtime tests passed in 12.00s**. Constant-size before/observed-peak/after summaries distinguish tree RSS/private/system/device-wide GPU scope, partial/unavailable nulls, 1s RAM and sequential ≥2s GPU cadence. Driver reads are bounded to 8 KiB in an owned 128 MiB query tree with ≤3s deadline; synthetic hanging queries reap safely. A real synthetic stage demonstrated positive before-RAM and confirmed empty-tree after-RAM with no real GPU query. Root membership is checked on a held Windows handle to avoid PID-reuse measurement. `run_stage(..., telemetry_settings=...)` is integrated; application/model callers and durable summary storage remain pending. No actual model/VRAM fit claim.
- [x] RT-06 — Private bounded spool helper
  - Depends on: RT-01, RT-03.
  - Acceptance: 1 MiB chunks, unchanged incremental patient-scoped hash, atomic reservations for raw/parser/partial/debug capacity, generated exclusive paths, close/finalize before durable pending acceptance, and safe duplicate convergence. Empty/oversize/disconnected/disk-full inputs clean only owned partials; no image decoding/model loading.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py -q` (chunk/reservation/file/duplicate-race cases).
  - Files: `smriti/spool.py`, `smriti/output_quota.py`, `tests/test_spool.py`.
- [x] RT-07 — Disk-only HTTP upload and multipart admission
  - Depends on: RT-02, RT-03, RT-06.
  - Acceptance: enforce actual request/part/file/field/buffer/concurrency limits before unbounded multipart buffering; private temporary files follow ephemeral controls. Preserve auth/demo/consent/override/basic-type checks. Return 202 pending job with null links/counts; active duplicates reuse that job, prepared duplicates preserve 409 behavior. HTTP invokes no decode/render/normalize/OCR, including during fake VLM work.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_jobs.py -q`.
  - Files: `smriti/app.py`, `api/routers/documents.py`, `tests/conftest.py`, `tests/test_ingest.py`, `tests/test_jobs.py`.
- [x] RT-08 — Sequential isolated page preparation
  - Depends on: RT-04, RT-06.
  - Acceptance: spawn-safe inspection and ≤20-page preparation/validation ranges persist one page at a time with unchanged 300-DPI renderer, normalization/quality/handwriting/text-layer policy and WebP encoding. No page-count admission rejection. Compact manifests/sidecars retain global source mapping and exact identities; partial output is not inference-ready.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_text_layer.py tests/test_runtime_stages.py -q`.
  - Files: `smriti/ingest.py`, `smriti/stage.py`, `tests/test_ingest.py`, `tests/test_text_layer.py`, `tests/test_runtime_stages.py`.
- [x] RT-09 — Atomic promotion and truthful ephemeral cleanup
  - Depends on: RT-02, RT-07, RT-08.
  - Acceptance: successful child outcome plus durable files/manifest atomically creates document/consent/same-ID job, preserves original consent/history and rechecks eligibility; failed preparation creates no clinical row. Success/deterministic failure immediately requests raw unlink; only explicit debug-enabled unexpected parser/renderer crash retains raw. Confirm actual removal before timestamp, recover both commit/unlink windows and locked files, and block admission on unresolved cleanup without rerunning clinical extraction.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_jobs.py tests/test_job_progress.py tests/test_runtime_stages.py -q`.
  - Files: `smriti/ingest.py`, `smriti/stage.py`, `smriti/job_progress.py`, `tests/test_ingest.py`, `tests/test_runtime_stages.py`.
- [x] **GATE A/B — Synthetic storage/null-count/intake/preparation/deletion-recovery checks pass.** No real models ran; hardware/accuracy acceptance remains open.
- [x] RT-10 — Frozen admission and bounded document windows
  - Depends on: RT-04, RT-05, RT-09.
  - Acceptance: fenced atomic ≤10-submission snapshot, sequential preparation/cleanup, lazy ≤20-page short-document packing or consecutive long-document windows in frozen order, and one exclusive coordinator even while idle. Two 15-page or 14+12-page documents stay separate; late arrivals/rejections do not refill membership. One long document completes before the next; empty batches load no models.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py tests/test_worker.py -q`.
  - Files: `smriti/stage.py`, `smriti/worker.py`, `smriti/runtime.py`, `tests/test_runtime_stages.py`, `tests/test_worker.py`.
- [x] RT-11 — Disposable CPU OCR and separate fallback
  - Depends on: RT-04, RT-10.
  - Acceptance: remove coordinator OCR singleton/local runtime ownership; lazy child imports after `CUDA_VISIBLE_DEVICES=""`, explicit CPU ONNX/Paddle configuration and existing four-thread policy. Reuse only exact-version artifacts/validated text layers; report actual engine/source. Preserve initialization-failure-only fallback in a second child after primary-tree exit, with per-page commits and no overlapping stacks.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ocr.py tests/test_worker.py tests/test_runtime_stages.py -q`.
  - Files: `smriti/ocr.py`, `smriti/worker.py`, `smriti/stage.py`, `tests/test_ocr.py`, `tests/test_worker.py`.
- [x] RT-12 — Owned VLM lifecycle and unified request endpoint
  - Depends on: RT-04, RT-10.
  - Acceptance: one owned local llama-server per eligible window, supervised client with explicit active session URL, verified tree shutdown, and specific safe request/timeout/port failures. Busy unowned ports fail without reuse/kill/global fallback. Preserve flags/prompts and 30s startup/120s request wall-clock budgets.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_vlm.py tests/test_worker.py tests/test_runtime_stages.py -q` (fake inference only).
  - Files: `smriti/vlm.py`, `smriti/runtime.py`, `smriti/worker.py`, `tests/test_vlm.py`, `tests/test_worker.py`.
- [x] RT-13 — Complete-document orchestration with unchanged rules
  - Depends on: RT-05, RT-11, RT-12.
  - Acceptance: finish a packed short-document group or complete long document before the next; persisted bounded page reads/private candidates drive equivalent complete-document classification/extraction/prose/metadata/reports/directives. Preserve mandatory printed verification, handwritten exclusions/skips and document-wide empty-result validation. Window success is not document completion.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_job_progress.py tests/test_runtime_stages.py -q`.
  - Files: `smriti/worker.py`, `smriti/stage.py`, `smriti/job_progress.py`, `tests/test_worker.py`, `tests/test_job_progress.py`.
- [x] RT-14 — Atomic final saves and review-safe crash recovery
  - Depends on: RT-09, RT-13.
  - Acceptance: full-document artifacts and confirmed cleanup precede transactional clinical writes/job-done progress; final eligibility checks exclude terminal/reviewed/populated clinical rows from replacement writes. Resume only incomplete new-phase work after owner/tree verification and exact artifact validation; done remains done after checkpoint crashes. Historical jobs remain readable and are not blanket-requeued; deletion/late-write and save-failure cases never publish partial facts.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_review.py tests/test_runtime_stages.py -q`.
  - Files: `smriti/worker.py`, `smriti/stage.py`, `tests/test_worker.py`, `tests/test_review.py`, `tests/test_runtime_stages.py`.
  - Recovery limit: only the implemented, validated v1 cursor resumes. Unknown historical v10 checkpoint shapes remain `CleanupBlocked`, with no guessed ownership/completion, termination or deletion. Explicit legacy-format recovery remains a separate live-rollout gate, not a claimed completed capability.
- [x] RT-15 — Safe app startup/shutdown and narrow 404 diagnostics
  - Depends on: RT-04, RT-05, RT-14.
  - Acceptance: start only the fenced coordinator; shutdown stops admission, cancels/reaps stage/monitor children, and confirms coordinator-thread exit before disposal. Cleanup failure is visible and blocks new work. Only `/v1/models` 404 logs observed host/port and sanitized UA family/fingerprint; no headers/bodies/clinical content dump or claim of identified caller.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py tests/test_patients.py -q` (isolated app lifecycle/privacy cases).
  - Files: `smriti/app.py`, `smriti/worker.py`, `smriti/runtime.py`, `tests/test_runtime_stages.py`, `tests/test_patients.py`.
- [x] RT-16 — Scope owner erasure to new operational data
  - Depends on: RT-09, RT-14, RT-15.
  - Acceptance: fence/cancel affected submissions, stop owned work and clean raw/debug/partial/new-artifact paths before losing cleanup metadata or acknowledging complete erasure. Remove new associations/history without exposing or altering other owners' frozen work; append-only audit and no-resurrection checks hold. Do not execute live erasure or claim unrelated historical cleanup defects fixed.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_patients.py tests/test_runtime_stages.py -q`.
  - Files: `api/routers/patients.py`, `smriti/stage.py`, `smriti/runtime.py`, `tests/test_patients.py`, `tests/test_runtime_stages.py`.
- [x] **GATE C/D — Synthetic tree/telemetry/document-wide lifecycle/trust/publication/v1-recovery/erasure checks pass.** Historical unknown cursors stay fenced; fake adapters do not establish Qwen/VRAM fit.
- [x] RT-17 — Accessible pending/preparing progress view
  - Depends on: RT-02, RT-09.
  - Acceptance: existing JobProgress shows pending/preparing with null totals as indeterminate; no fake pages/percent or reset event sequence/time at promotion. Preserve native disclosure, stable focus, grayscale status meaning, keyboard/reduced-motion behavior and terminal timing; no layout-explaining captions.
  - Verify: `npm --prefix web test -- src/test/JobProgress.unit.test.jsx`.
  - Files: `web/src/components/JobProgress.jsx`, `web/src/index.css`, `web/src/test/JobProgress.unit.test.jsx`.
- [x] RT-18 — Single/bulk intake pending-job compatibility
  - Depends on: RT-07, RT-09, RT-17.
  - Acceptance: poll stable pending IDs; adopt verified counts/document links only on promotion. Active pending duplicates poll existing jobs; prepared duplicates link existing sources. Deferred rejection has no nonexistent preview/review link; mixed files survive rejection. Preserve nonoverlapping 2s polling, session/navigation/transient-error cleanup, explicit retry and single-file workflow.
  - Verify: `npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/App.system.test.jsx`.
  - Files: `web/src/pages/Intake.jsx`, `web/src/test/Intake.integration.test.jsx`, `web/src/test/App.system.test.jsx`.
- [x] RT-19 — Finish connected caller/fixture regressions
  - Depends on: RT-14, RT-16, RT-18.
  - Acceptance: update all remaining ingestion/process_next fake-engine callers and shared fixtures to the approved staged path; real spawn targets are importable, not pickled mocks. Directives/review/system/ingestion journeys keep previous extraction and ownership behavior; no production compatibility path loads OCR in the coordinator. Fixtures never point to live DB/spool/uploads.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_directives.py tests/test_review.py tests/test_system.py -q`.
  - Files: `tests/conftest.py`, `tests/test_ingest.py`, `tests/test_directives.py`, `tests/test_review.py`, `tests/test_system.py`.
- [x] RT-20 — Implemented contract and deployment documentation
  - Depends on: RT-15, RT-16, RT-18, RT-19.
  - Acceptance: API examples, operational/clinical boundary, ephemeral cleanup/recovery, process ownership/telemetry, backup exclusions and matched-client rollout match implemented tests. Keep historical decisions labeled; no claimed model accuracy/hardware acceptance or live deployment. Processing spec points to the staged contract without inventing a new clinical pipeline.
  - Verify: compare documented examples to job/intake tests; `git diff --check`.
  - Files: `docs/API.md`, `docs/data-model.md`, `docs/architecture.md`, `README.md`, `specs/SPEC-processing.md`.
- [x] RT-21 — Full synthetic verification and result ledger
  - Depends on: RT-01…20 and gates A/B/C/D.
  - Acceptance: backend/frontend suites and production build pass; isolated synthetic browser checks cover new pending/mixed-terminal states at narrow/desktop sizes, or unavailable checks are explicitly reported. Record actual test counts/evidence and keep hardware/clinical obligations open. No live restart/migration/processing/reset, commit or push. Update only scoped regressions/result notes; unchecked work is not marked complete.
  - Verify: `.\.venv\Scripts\python.exe -m pytest -q`; `npm --prefix web test`; `npm --prefix web run build`; `git diff --check` (separate background commands); isolated synthetic browser checks.
  - Files: `tasks/todo.md` result ledger and completed-status references; any discovered regression gets a scoped fix with its own test.
- [ ] **GATE E — Code regression acceptance is not deployment or hardware acceptance.** Obtain explicit live-rollout/legacy-queue permission before startup against user data; back up consistent SQLite/WAL and normalized sources, excluding spool/temp/debug raw files, and verify migration on a copy.
- [ ] RT-22 — Separately authorized isolated hardware benchmark
  - Depends on: RT-21 **and separate hardware/corpus authorization**; blocked until then.
  - Acceptance: only then add the small shared-pipeline benchmark harness plus self-check, refusing live/reused paths and preserving source inputs. Run 3–5 approved multipage PDFs in isolated DB/spool/uploads with live worker stopped; report real stages/engines/pages/timings/failures/skips/cleanup, observed RAM/VRAM and unavailable reasons. Same-settings baseline only if safely authorized; no causal/accuracy/universal-stability claims, no B1/B2 completion claim.
  - Verify: `.\.venv\Scripts\python.exe -m pytest tests/test_runtime_benchmark.py -q` (new isolated guard/self-check tests); the separately authorized invocation in `tasks/plan.md` §12.7.
  - Files: `scripts/benchmark_runtime.py`, `tests/test_runtime_benchmark.py`, `tasks/todo.md` evidence notes.

Verification checkpoint (2026-11-05): full backend **340 passed, 1 skipped** in 96.15s, using synthetic inputs and temporary databases; RT-01–03 only are complete. Frontend/build/browser checks were not rerun (no frontend change in this slice); gates A/B/C/D/E and RT-04–22 remain open. No live app startup/migration/restart, clinical reprocessing, commit, push, or package installation occurred.

Separate user-authorized database cleanup (2026-11-05): the user requested clearing the DB and selected **Keep accounts**, with uploaded image files explicitly left untouched. Cleared medical/processing rows from `data/smriti.db` in one checked transaction: 13 documents/jobs, 17 reports, 312 observations, 29 medications, consent/page text/artifacts and non-account audit. Preserved the one account, its session, two account/auth audit rows, and exact schema v9/audit protections. Independent read-only checks confirmed empty medical tables, integrity `ok`, no FK violations and unchanged schema. No app restart, migration, image deletion, or clinical reprocessing occurred; this separate cleanup is not runtime or hardware acceptance.

Historical next step at this checkpoint was RT-04. Current connected implementation/results are recorded below; remaining accounts/images/subsequent records remain untouched, and RT-22/live deployment still require separate authorization.

### Approved long-PDF requirements / proposed plan (2026-11-05)

- User request: remove the 20-page upload limit after a 39-page PDF rejection; backend infrastructure must handle longer PDFs safely, not replace the limit with a larger arbitrary count.
- Requirements approved by the user (“okay proceed”): `docs/SRS.md` v1.3 §3.1.16 and [SPEC-runtime-stages.md §8](../specs/SPEC-runtime-stages.md#8-approved-long-pdf-requirements-amendment--2026-11-05). ≤20 internal windows, one logical document/job, one-page preparation, disk-bounded artifacts, preserved document-wide context and final atomic publication. Byte/pixel/quality/privacy/consent checks remain.
- Inspection found eager rendered/prepared-image lists in intake, document-wide words/text/candidate accumulation in the worker, `submissions.total_pages BETWEEN 1 AND 20`, and batch bookkeeping limited to 10 worksets. Removing the ingest check/config alone is not a complete safe implementation.
- Revised plan proposed in `tasks/plan.md` §13: forward operational upgrade preserving v10, lazy range cursors/private per-page artifacts, supervised preparation range children, bounded equivalent helper passes, streamed atomic final writes. Initial unmeasured defaults proposed for approval: 2 GiB active-output quota and 1 GiB minimum free disk on each written filesystem. Plan/checklist approval and changed-contract code remain pending.
- RT-01–03 stay complete against their original contracts; new follow-up schema/config tasks must not rewrite their evidence. RT-04 is independent. Split affected RT-08/09/10/13/14 and helper/config/storage/progress/scratch work into ≤5-file slices after plan approval. Earlier whole-document gate approval is not approval of the new storage/process mechanics.
- Legacy full document-detail response arrays remain an explicitly unmeasured read-path scaling risk; this runtime plan does not claim a complete clinical API pagination redesign or constant-memory behavior for every endpoint.

### Observability scope / requirements draft (2026-11-05)

- User requested scalable production-oriented logging/monitoring, selected **Job view + files**, and explicitly added CMD/terminal panels. One narrow `observability` extension consumes existing progress/runtime events; no operator dashboard, public global log API, external service, new clinical schema or horizontal-scaling claim.
- Draft requirements: [SPEC-observability.md](../specs/SPEC-observability.md). Same sanitized correlated event schema for readable terminals and bounded rotating JSONL files; owner-only job activity remains authoritative in SQLite. Bounded asynchronous logging, retention, degradation/drop visibility and privacy tests apply to every sink; terminal output is not exempt from medical-content/secret exclusion.
- Await requirements review before an observability plan/tasks/code. No dependency installation, live restart, model execution, commit or push. This combined approval/plan/spec slice changes documentation only; tests/build/hardware checks are not rerun and no production-readiness claim is made.

### Post-critique implementation authorization (2026-11-05)

The user subsequently directed implementation after the critique, without asking what to do next. Earlier pending-plan/spec approval notes above remain historical; `tasks/plan.md` §13.7 owns the selected corrections. RT-01–03 evidence is not rewritten. The connected implementation has passed final synthetic verification; no live migration/restart, real-record/model processing, cleanup rerun, dependency upgrade, commit or push is authorized.

- [x] LP-01 — Historical v10 fixture and forward operational migration; retain clinical constraints, rows, FKs, indexes and triggers.
  - Result (2026-11-05): **153 database tests passed in 10.94s**, exclusively temporary databases. Historical v10 is composed from frozen v9 + unchanged migration 010, with old 20-page/10-window rejection assertions. Migration 011 relaxes only operational page/index checks; fresh/v8/v9/v10 upgrades, same-ID 39/1001-page promotion, 100,000-window bounded metadata, active cleanup row preservation, original clinical schema/accounts/reviews/audit/FKs/objects and failed-upgrade rollback pass. Code schema is 11; live database remains untouched at 9. Upload/model paths are not connected yet, so no working long-PDF processing claim.
- [x] LP-02 — Independent window/storage/decoded-page/native-memory/helper-deadline settings; retire page-count admission.
  - Settings foundation: **82 runtime/config tests passed in 9.47s**. Bounded intake now replaces eager admission; `max_pages`/`SMRITI_MAX_PAGES` are removed, not repurposed. Retained provisional guards: 2 GiB active output, 1 GiB free disk, 1 MiB decoded page text/logical-line carry, 100,000 words/page, 16 MiB/artifact, 6 GiB native tree, 300s inspection/helper deadlines. These are unmeasured capacity guards, not hardware-fit claims.
- [x] OB-01 — Safe event validation and isolated bounded terminal/file writers; blocked-pipe, retention, degradation and shutdown tests.
  - Result (2026-11-05): **14 logging/private-path tests passed in 14.17s**. Code-owned events drop unsafe/unknown keys, strings, IDs and nonfinite measurements before queueing. Separate owned file/terminal processes, exclusive writer locking, bounded queue/record/rotation/age, user+SYSTEM protected Windows ACLs, junction/hard-link refusal, unrelated-file preservation, disk-full/dead-sink health, idempotence and abrupt-controller tree exit pass. Real blocked-pipe evidence: 10,000 synthetic emits spent **0.124s** in producer calls; file wrote 100 vs terminal 29 records, terminal counted 9,939 drops, shutdown **1.5s**, both processes exited and lock released. This is observed test evidence, not a throughput SLA. App/Uvicorn/startup/job integration remains OB-02; no live logs were read.
- [x] OB-02 — Sanitize existing application/Uvicorn/startup channels and forward committed owner-only progress; final post-edit verification passed.
- [x] LP-03 — Bounded spool/multipart admission, range preparation, output reservations and complete same-ID promotion (replaces superseded RT-08 page rejection).
- [x] LP-04 — Lazy short-document packing / long-document windows and exact-version disposable OCR/fallback/Qwen lifecycles (extends RT-10…13).
- [x] LP-05 — Bounded equivalent classification/metadata/extraction/report/directive/prose/cross-check passes; independent DOB regression.
  - Independent DOB fix: **44 tests passed in 13.29s**, after reproducing five baseline failures. Bounded helper equivalence: **121 passed**; complete-document routing/source/report/date/directive/cross-check semantics remain, including DOB exclusion and later-page context.
- [x] LP-06 — Bulk atomic final publication, fenced v1 recovery, confirmed cleanup and scoped owner erasure (extends RT-14…16); unknown historical checkpoint shapes remain explicitly fenced.
- [x] LP-07 — Pending/full-document progress, bounded detail/source review and no automatic full-detail completion fetch (extends RT-17…19).
- [x] LP-08 — Matched startup/API/deployment docs and full isolated synthetic backend/frontend/build verification (RT-20/21); rendered-browser unavailability explicitly recorded below.

The pipeline is now connected, with explicit per-submission capacity failure rather than waiting for capacity its own frozen batch must release. External logging, dashboards and filter/export UI are skipped. Hardware/deployment gates remain open even after synthetic completion.

MVP clarification: the user explicitly said this is a college major project, not a production-ready service. Keep local upload/review/logging and the safety/resource boundaries; skip HA, distributed scheduling, external monitoring, dashboards and throughput SLAs. This does not authorize live changes or turn synthetic tests into clinical/hardware evidence.

### Connected implementation and verification — 2026-11-06

- HTTP only validates/spools bounded chunks; response is `{document_id:null, job_id, pages:null, status:"pending_intake"}`. Same-owner pending duplicates retain that job; cross-owner job/detail/source reads remain 404. Model/rule/publication work runs in owned children, never an eager HTTP/controller fallback.
- Preparation metadata v2 and processing/candidate v1 retain exact identities and global pages. Scratch stays under `.runtime/<job-id>/`; private candidates/report associations precede bounded bulk insertion in one fenced atomic save. Populated/reviewed/terminal records are never replaced. The 1,001-page case tests scheduling only, not actual arbitrary-length completion.
- Isolated slices: intake/recovery **34**, preparation **19**, owned model/candidate **29**, CPU OCR **9**, standalone coordinator **23**, runtime attribution/global-count/lifecycle **110**, source/provenance **25**, bounded detail/source **30**, erasure/service/coordinator **21**, spool/multipart/ranges **31**, upload/API/privacy **8** passed. These are overlapping focused runs, not additive coverage totals.
- Migrated staged synthetic worker/review/directive/system/ingest/jobs/runtime fixtures: **136 passed in 88.02s**. Shared fixtures explicitly prepare after HTTP acceptance; no production compatibility loader was retained.
- Committed progress IPC/file/terminal, rollback, privacy, latest-failure/history, global-page and measurement regressions: **161 passed in 103.25s**. Frontend diagnostics/intake/detail: **38 passed in 9.43s**. Final full frontend: **68 passed across 11 files in 13.31s**, after fixing bounded-detail URL/asynchronous-source mocks. Final production build passed (590ms).
- Complete backend checkpoint before final diagnostics follow-ups: **633 passed, 1 skipped in 336.27s**. Follow-up diagnostics/lifecycle/page-counter/Qwen failure tests: **85 passed in 84.49s**. **Final complete backend: 643 passed, 1 skipped in 335.99s**, after shared safe failure-code, observed-client 404 and coordinator crash-retention fixes. The skipped historical step-0d test requires user-supplied B1 ground truth; that gate was not fabricated or run against real data.
- Diagnostics use independent bounded terminal/file sinks and an exclusive JSONL writer; only committed progress forwards, callback/sink failure cannot undo durable progress or prevent tree cleanup. Current page/engine/failure stage, skipped work, sampled/unavailable measurements, intake-to-finish wall time, monotonic operation/publication durations, raw/scratch cleanup and crash-only debug retention are explicit. Job API exposes only per-sink availability/degradation booleans; global counters/measurements/log files remain operator-only.
- `README.md`, `docs/API.md`, `docs/data-model.md`, `docs/architecture.md`, `docs/test-plan.md` and runtime/observability/processing specs match the staged pipeline/rollout fence. Final startup PowerShell syntax passed without execution. Final `git diff --check` passed with LF/CRLF warnings only; an additional read-only Python AST/whitespace check passed for **132 tracked/untracked source files**. No code edits followed the final complete backend run; remaining edits only recorded this evidence.
- **Current rendered-browser verification unavailable:** repository venv has neither Playwright nor Selenium; no browser automation dependency was installed. Vitest/axe checks pass but are not a visual narrow-width/contrast/reduced-motion browser replay. The earlier IE browser evidence above remains historical, not evidence for this changed runtime/client.
- **Remaining gates:** no live startup/migration/restart/cleanup rerun/real records/models/commit/push occurred. Code schema is 11; live schema intentionally remains 9. Unknown historical v10 checkpoint formats remain fenced for separately authorized recovery. RT-22 hardware/corpus/Qwen-fit/clinical-accuracy evaluation, PaddleOCR-VL integration, B1 ground truth/B2 crops and the earlier registration incident remain open. Existing accounts, images, later records/reviews and unrelated uncommitted/untracked work are preserved.

### Adapter/private-error/Queue corrective slice — 2026-11-07

Authorization: user approved the corrective scope, then selected **“Finish fixes first”** before new clinical phases; `tasks/plan.md` §13.8 and runtime spec §9 record the boundary.

- [x] RapidOCR 1.4.4 uses flat installed options, requested cached weights, existing CPU/four-thread/batch-one settings and all three real ONNX session interfaces; engine caching follows successful provider validation. Stub regression: **10 OCR tests passed**; no model initialized.
- [x] Safe Qwen HTTP/connection/observed-server-exit/transfer/envelope/output categories and integer HTTP status persist in failure context before cleanup and forward only after progress commits. Valid optionally fenced JSON arrays including `[]` are distinct from invalid envelopes/items, malformed arrays and nonfinite numbers; null unit/reference metadata remains null. Existing whole-document nonempty/mandatory-Qwen policy is unchanged.
- [x] Bounded owner-only Active/Recent listing includes pending/terminal intake and legacy jobs without recovery. No event/medical/private batch/spool payloads in the list; unknown counts stay null. Queue polls Active nonoverlapping, reads one selected detailed history, stops terminal detail/session loss, retains progress on transient failures, aborts navigation and leaves Recent idle until user action.
- [x] `#/summary`, `#/intake`, `#/queue`, and document/source-page hash navigation; refresh/back/forward, unsent-file guards and return-to-Queue links. Source page and eligible-page completion are distinct; later stages are “Not reached” after failure; terminal Intake type is no longer stuck on “Detecting…”. No persistent browser file queue or dependency was added.
- [x] Focused backend reruns: jobs/progress/model stages **36 passed**; subsequent VLM/jobs/progress/model stages **71 passed in 39.68s**. Full frontend: **83 passed across 13 files in 15.04s**. Production build passed in **1.41s**. Focused frontend initially exposed test selector/mock mismatches, corrected before the full pass; an idle same-tab Queue reset and stale page URL were also corrected with regressions.
- [x] Final full backend regression: **676 passed, 1 skipped in 372.52s** via `.\.venv\Scripts\python.exe -m pytest -o addopts="" -q`, using synthetic fixtures and isolated databases. The historical step-0d test still requires user-supplied B1 ground truth; no real-record evaluation ran. Together with the full frontend/build passes above, this closes the approved corrective implementation slice, not live/hardware/clinical acceptance.
- [x] API, requirements, processing/runtime/observability/bulk specs, README/architecture/test-plan and approved task boundary updated. No schema/model flag/prompt/DPI, isolated lifetime, frozen FIFO/capacity policy, historical recovery fence or single-final-save change.
- [x] Standard `git diff --check` passed (LF/CRLF warnings only); read-only AST/whitespace checks passed for 12 changed Python files and whitespace checks for six new frontend files. No code edits followed the full-suite/build invocations; remaining edits record contracts/evidence only.
- **Not checked / remaining gates:** rendered browser/mobile/contrast/motion, real-model reproduction/hardware fit/accuracy, live rollout and RT-22 remain open. Original Qwen request subtype/status and suppressed native output cannot be recovered; no server-exit/OOM causality is claimed. No live restart/migration/recovery/cleanup rerun, real-record/model processing, commit/push or dependency installation occurred. Existing accounts/sources/subsequent records/reviews and unrelated work remain intact.
- **Next specifications, not implemented:** smart page filtering after OCR (never preparation), a dedicated `#/review` evidence/confirmation queue with separately recorded human provenance, explicit confidence/date policy and medication reconciliation preserving prescribed/ongoing/stopped distinctions. Human verification is not a model certainty score of 1.0.

## Logical reports slice (2026-10-26)

- [x] Schema v8 `report` table; observation `report_id`, `fact_type`, `label_norm`, `evidence_quote`; migration 008 backfills existing documents
- [x] Deterministic page segmentation by detected date/facility; undated pages continue the current report
- [x] Worker persists reports, links observations, and attaches impression/findings summaries
- [x] `GET /api/patients/{id}/timeline` with category and `from`/`to` filters
- [x] `PATCH /api/reports/{id}` for date, category, title, facility, and summary correction
- [x] Text-only prose review via `value_text`; numeric lab review unchanged
- [x] Timeline panel, report panel, source-page navigation, and prose correction UI
- [x] Backend and frontend suites green; production build passes
- [x] Report title/facility editing in the UI
- [x] Timeline category and date-range controls in the UI
- [ ] Multi-type labeled evaluation set

## Week 1 — Foundation

- [x] `pyproject.toml` / `requirements.txt`: core deps pinned (fastapi, uvicorn, pydantic, sqlalchemy, python-multipart, httpx, pytest)
- [x] NumPy / OpenCV / PyMuPDF / Pillow added for P1 intake
- [x] PaddleOCR / PaddlePaddle added; RapidFuzz still deferred
- [x] `smriti/config.py`: every key from plan §4, loaded once, recorded per run; auth TTL/attempt settings added
- [x] Windows quick start: `start.ps1` + `start.bat` reuse `.venv`, skip unchanged installs/builds, and launch Uvicorn
- [x] `smriti/db.py`: SQLite WAL, `foreign_keys=ON`, schema v2 with 13 tables (SRS §3.4)
- [x] `smriti/models.py`: Pydantic v2 models for patient, document, observation, directive, medication, egress, auth payloads
- [x] `smriti/main.py`: app factory, static mount, profile switch, worker startup
- [x] Per-patient accounts: scrypt hashes, hashed session tokens, HttpOnly cookie, ownership checks
- [x] `tests/conftest.py`: temp DB, temp upload dir, loopback-only network guard
- [x] CI: pytest on push; fail on non-loopback network call
- [ ] Ethics pack submitted (OR-01)
- [~] Intended-use statement written once, used in UI, report, demo (OR-05); UI footer done, report and demo open
- [x] `docs/API.md` draft with the 15 endpoints; page-image endpoint added in P1 (16 total)
- [~] **GATE** ethics submitted; tests run (tests green; ethics pack open)

## Week 2 — Contract and probes

- [x] `web/src/fixtures/summary.json` frozen with 7 keys (FR-TIM-01) — pulled forward into P0
- [x] `tests/test_summary.py::test_contract` validates fixture against Pydantic (NFR-12) — pulled forward into P0
- [x] Vite + Tailwind + Recharts shell renders the fixture and the live summary (patient mode; Recharts lazy-loads when a result has more than one point; 38 Vitest + axe tests: 8 unit, 20 integration, 10 system)
- [x] Keyboard focus management and WCAG AA contrast on summary + intake + auth (NFR-09, pulled forward from Week 13)
- [x] Account gate: register/sign-in, signed-in patient header, sign-out
- [x] Local intake form: authenticated upload JPEG/PNG/PDF with local-only consent, automatic type detection, 2 s polling, extracted fields and page text (pulled forward from Week 6)
- [x] `POST /api/documents` + `GET /api/jobs/{id}` shapes agreed and implemented, ownership-checked
- [ ] **Probe A** — `python -m smriti.candidates --probe`: PP-OCRv6 over 10 handwritten drug lines; record output and top-3
- [ ] **Probe B** — preprocessing A/B over 20 docs: baseline vs perspective+deskew+CLAHE+upscale
- [ ] Record both probe results in `docs/evaluation.md`
- [ ] **GATE** contract locked; probe A decides handwriting design; probe B decides pipeline steps

## Week 3 — Intake

- [x] `smriti/preprocess.py`: EXIF strip, perspective, deskew, CLAHE, upscale — pure functions
- [x] `smriti/quality.py`: short edge, Laplacian, aspect ratio, blank page, duplicate-page hash
- [x] `smriti/handwriting.py`: detector; sets `capture_type` server-side (FR-ING-02)
- [x] `smriti/ingest.py`: content hash, idempotent write, page split, job row
- [x] `POST /api/documents`, `POST /api/documents/{id}/consent`
- [x] `GET /api/documents/{id}/page/{n}`, `GET /api/documents/{id}`, `GET /api/jobs/{id}`
- [x] `tests/test_ingest.py`, `tests/test_quality.py`, `tests/test_preprocess.py`; full backend suite currently 89 passed (38 unit, 49 integration, 2 system)
- [ ] 20 real documents in hand, consent rows recorded
- [~] **GATE** five synthetic fixtures pass and EXIF/GPS is stripped; 20 real documents and the quality-gate precision check are still open

## Week 4 — OCR baseline

- [x] `smriti/ocr.py`: PaddleOCR wrapper, words + normalised boxes, engine string
- [x] `smriti/classify.py`: local document-type classifier with confidence
- [x] `smriti/metadata.py`: labelled collection/report dates; DOB skipped; user values preserved
- [x] `smriti/engines.py`: versioned engine strings recorded on every field
- [x] `eval/run_eval.py` + `eval/metrics.py` (F1, CER, exact match, bootstrap CI, kappa) on a 5-doc synthetic fixture
- [x] `tests/test_eval_smoke.py`: runs offline and verifies determinism
- [ ] CER measured on 10 documents; per-template breakdown (needs real corpus)
- [~] Annotation guide v1 exists; 30-note double-annotated subset still to draw (FR-DIR-10)
- [ ] 40 documents confirmed on paper (A-03)
- [~] **GATE** synthetic harness and `eval/kappa.py` are runnable; real CER and 40-doc confirmation remain open

## Week 5 — Extraction

- [x] `smriti/assembly.py`: table regions, rows, columns, and cells from whitespace
- [x] `smriti/extract.py`: printed lab/medication rules over assembled rows → review candidates; no invented units
- [x] `smriti/resolution.py`: synonym → range → unit, 2-of-3 agreement and derived confidence
- [~] `data/analyte_map.csv`: initial analyte synonyms, units, display names; LOINC/specimen/timing open
- [ ] `data/brand_lexicon.csv`: derived from the 40 prescriptions, not invented (blocked on corpus)
- [x] Directive grammar v1: relative, absolute, conditional, and PRN patterns; no `today` anchor
- [x] `tests/test_extract.py`: line rules, bboxes, engine strings, derived confidence, review status
- [x] `tests/test_assembly.py`, `tests/test_resolution.py`: rows/cells/regions and the 2-of-3 resolver
- [x] `tests/test_directives.py`: span offsets, anchor priority, past-date handling, worker persistence
- [~] **GATE** synthetic printed document and real PaddleOCR smoke parse end to end; real-document gate remains open

## Week 6 — Review loop and first evaluation

- [x] `POST /api/observations/{id}/review` + audit rows
- [~] Review UI: field, source page, accept/correct/reject, keyboard path; printed-field review, source dialog, and mobile review cards done, handwriting candidate flow open
- [x] Upload UI + 2 s job polling (FR-JOB-04); authenticated upload/consent/page preview/polling/extracted fields/review navigation done
- [x] `tests/test_review.py`
- [ ] **M1 evaluation** on 40 docs: field F1, end-to-end, material errors
- [ ] Medication F1 baseline; lexicon coverage reported (FR-MED-05)
- [ ] **GATE** printed end-to-end measured; if < 0.85, apply RISK-05 before week 8

## Week 7 — Safety

- [ ] `smriti/checks.py`: G1…G5 with tolerances (FR-SAF-01)
- [ ] `data/bounds.csv` with a citation per row; `data/swing.csv`
- [ ] `tests/test_checks.py`: each gate pass/fail/skipped; `skipped ≠ pass`
- [ ] Injected-corruption set: 200 cases, recall per gate
- [ ] Timeline + reference bands render only accepted values
- [ ] `tests/test_invariants.py::test_rejected_never_charted`
- [ ] **GATE** gate recall ≥ 0.80, false quarantine ≤ 0.10

## Week 8 — Normalisation and the three gates

- [ ] `smriti/normalize.py`: Decimal, unit map, glucose separation, mapping_rule
- [ ] `tests/test_normalize.py`: 30 synonyms, unit round-trip, no fuzzy on printed
- [x] Source overlay: click value → live page + box (FR-TIM-06)
- [ ] **Resolver experiment**: 40 docs with resolver off vs on, count review items
- [ ] **Handwriting decision**: green only if printed end-to-end ≥ 0.85 **and** probe A survived **and** a clinician labeller exists
- [ ] **GATE 1** normalisation ≥ 0.95
- [ ] **GATE 2** resolver shrinks queue ≥ 30 % or `egress` is deleted
- [ ] **GATE 3** handwriting go/no-go recorded in the report

## Week 9 — Handwriting assist (conditional)

- [ ] `smriti/candidates.py`: weighted ranking, phonetic normalisation, abstention margin
- [ ] `FieldReview.jsx`: crop with context line, 3 candidates, no default, search, add-box
- [ ] `handwriting_field` rows written for every action with `ms_to_verify`
- [ ] `tests/test_candidates.py`: ranking, abstain, no default
- [ ] `tests/test_invariants.py::test_handwritten_never_auto`
- [ ] **GATE** no handwritten field in any state but `review`

## Week 10 — Handwriting metrics and medications

- [ ] 25 handwritten pages annotated by the clinician
- [ ] Taps, seconds, top-3, accepted-unchanged measured
- [ ] **Vigilance test**: 10 % injected wrong top-1, study mode, false-accept recorded
- [ ] Failure taxonomy written (what the model misreads and why)
- [ ] Medication extraction: three states, source + timestamp, no merge
- [ ] **GATE** false-accept ≤ 5 %; otherwise the human gate is declared ineffective and the feature is cut

## Week 11 — Directives and clinician mode

- [ ] Directive evaluation: span F1, timing accuracy, date exact
- [ ] Reminders UI: anchor shown, unknown state shown, no past notifications
- [ ] Clinician mode: citation density, print view
- [ ] **GATE** span F1 ≥ 0.75, timing ≥ 0.80, date exact ≥ 0.70

## Week 12 — Numbers frozen

- [ ] Risk–coverage curve at 100/90/80 % (FR-EVL-05)
- [ ] Bootstrap CIs, 1000 resamples, seed recorded
- [ ] Local vs resolver table (FR-EVL-08)
- [ ] `eval/run_eval.py` full offline run; `report.json` + figures
- [ ] **GATE** every reported number regenerates offline

## Week 13 — Usability and bug pass

- [ ] 5–8 participant sessions: time-to-answer vs paper folder
- [~] Keyboard-only and contrast audit (NFR-09); axe + summary/intake/review/auth pass done, clinician/share screens open
- [ ] Bug pass on the cut list
- [ ] **GATE** usability data in hand

## Week 14 — Demo

- [ ] Seeded demo DB; `SMRITI_PROFILE=demo` verified: no uploads, no egress, read-only
- [ ] 4-minute video recorded
- [ ] Rehearsal with a fallback plan (RISK-11)
- [ ] **GATE** demo runs offline from a cold start

## Week 15–16 — Report and viva

- [ ] Results chapter filled from `report.json`, never typed by hand
- [ ] Limitations section: lexicon coverage, 40-doc CI width, handwriting stratum, resolver that may not have shipped
- [ ] Viva answers prepared: why any egress at all, why not handwriting auto, why 40 documents
- [ ] **GATE** submission

## Completed Clinical Summary & Gemini 3.8 Flash High Integration

- [x] Standardized longitudinal clinical summary (`smriti/clinical_summary.py`) with structured demographics, explicit hypertension verification, chronic conditions, genetic/family history, past surgical/medical history, active treatment plan, year-wise progression, and latest ongoing medications.
- [x] Integration with `gemini-3.8-flash-high` using `thinking_level="high"` under local PII black-box redaction and user consent preview.
- [x] Analyte exclusion filter (`NON_MED_WORDS`) removing non-medication lab items (Triglycerides, Total Protein, Globulin, eGFR, Bilirubin) from medications.
- [x] Frontend cleanup: removed viewport-obstructing `position: sticky` on `.safety-bar` and replaced raw OCR diagnosis dump chips with accessible `StandardizedSummary.jsx`.
- [x] Added Audit & Cloud Review Logs section to Document Detail view displaying `egress` table audit entries.
- [x] Verified against test user `parv` (`parv:man.com123`) end-to-end; 100/100 frontend tests and all backend tests passing.

---

## Standing rules

- Every merged change updates the FR traceability row it touches.
- A threshold change is an SRS change (§5.4), never a Python edit.
- No test calls the network.
- No image or free text leaves the device, ever.

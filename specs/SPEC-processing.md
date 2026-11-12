# SPEC-processing

Approved 2026-11-07 §13.9: existing progress/Queue distinguishes `partial` (skipped/unavailable pages) and `unavailable` (no independent fields; OCR-only review). `qwen_unavailable_page`, `verification_partial`, `verification_unavailable` and recovering/recovered activity are bounded code-owned events. Unavailable outcomes count as resolved eligible pages, never successful page reads; stage labels explicitly require review. SRS FR-JOB-10 and `SPEC-runtime-stages.md` own the recovery/degradation policy. Successful list/detail polls are suppressed; failed requests remain diagnostic.

| | |
|---|---|
| Module | `processing` |
| Status | Approved 2026-11-04; implemented and locally verified 2026-11-05; real model verification open (see `tasks/todo.md`) |
| Depends on | Existing intake and worker |
| SRS | FR-JOB-01, FR-JOB-03…09 |

## 1. Objective

Answer “what is happening to my document?” at a glance, with an expandable event history for diagnosis. Use real events at pipeline boundaries, not simulated progress or an unfiltered terminal dump.

## 2. Commands

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_ingest.py tests/test_db.py tests/test_system.py -q
npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/App.system.test.jsx
npm --prefix web run build
```

## 3. Structure and interface

- `smriti/coordinator.py`, `smriti/preparation.py`, `smriti/model_stages.py`, `smriti/processing_helpers.py`, `smriti/publication.py`, `smriti/vlm.py`: actual stage/page/model lifecycle, result counts, durations, errors and cleanup. `worker.py` now retains only unchanged clinical cross-check helpers; no eager processing fallback.
- `api/routers/jobs.py`: additive progress fields on the existing ownership-checked endpoint; preserve `id`, `state`, `page`, `total`, and `error`. Compact owner-only Active/Recent listing is separately paginated and excludes history/private payloads.
- `smriti/schema.sql`, `smriti/migrations/`, `smriti/db.py`, `tests/test_db.py`: approved additive telemetry persistence; historical jobs remain valid.
- `web/src/pages/Intake.jsx`, `web/src/pages/Queue.jsx`, `web/src/components/JobProgress.jsx`, `web/src/index.css`: one reusable progress view for uploads and server-backed Queue, using existing tokens and native disclosure controls. `web/src/lib/navigation.js`/`App.jsx` own hash routes and unsent-upload guards; document page controls keep source-page URLs current.
- `tests/test_worker.py`, `tests/test_ingest.py`, `web/src/test/Intake.integration.test.jsx`, a focused `web/src/test/JobProgress.unit.test.jsx`: ordered events, compatibility, privacy, accessibility, and polling.
- `docs/API.md`, `docs/data-model.md`: public telemetry contract and storage lifecycle.

The additive contract exposes current `stage`, actual `model`, `current_page`, `completed_pages` for that stage, `started_at`, `updated_at`, `finished_at`, and ordered `events`. Events have a stable sequence, timestamp, severity (`info`, `success`, `warning`, `error`), stage, safe message, and optional page/model/duration/count metadata. Existing `page` remains completed OCR pages. Missing historical telemetry is shown as unavailable, never reconstructed as fact.

The approved long-PDF/runtime extension is owned by `SPEC-runtime-stages.md`; terminal/file privacy and bounded delivery are owned by `SPEC-observability.md`. HTTP returns unknown counts/link until same-ID preparation promotion. Internal windows retain global pages and document-wide interpretation, with one final clinical save. Completion does not fetch full detail automatically; review reads bounded page/result ranges. Support ID/latest failure/logging-degradation additions stay in the existing disclosure. Shared measurements and diagnostic files stay operator-only. Total elapsed spans intake-to-finish wall time; operation durations use monotonic clocks.

Approved 2026-11-07 fix extension: Queue remains accessible after leaving Intake/reloading through `#/queue`; Summary, Intake and document/source-page URLs are distinct. Active lists poll nonoverlapping every two seconds, Recent lists are idle until user action, and only one selected job fetches full bounded history. Preserve last progress on transient failure, abort on navigation, stop terminal detail/session polling, and never recover a legacy job merely by listing it. API query bounds and client hash formats are owned by `docs/API.md` §5. No second coordinator, queue service, dependencies or clinical-policy change.

Qwen's source page and eligible-page completion counters remain separate. Show later stages as “Not reached” after failure. Allowlisted failure code/HTTP status survive model cleanup and forward only after durable progress commits; invalid envelope/model arrays fail explicitly while valid `[]` remains a successful page read under unchanged complete-document policy. Do not retain raw responses, runtime output or exception text.

## 4. Code style and visual behavior

Write structured, allowlisted events at the actual operation, never parse console strings to discover state. Keep stage identifiers stable and user-facing text in a small explicit mapping.

```jsx
<details className="job-log">
  <summary>Processing details</summary>
  <ol>{events.map((event) => <li key={event.sequence} data-level={event.level}>{event.message}</li>)}</ol>
</details>
```

Default view: filename, status, current activity, model/page when known, stage-specific completed pages, and elapsed time. Details: timestamped events with restrained blue activity, green completion, amber warnings, and red errors; severity text and shape remain legible in grayscale. No color legend or caption explaining the layout. Keep text contrast at least 4.5:1, visible keyboard focus, wrapping on small screens, polite announcements only for meaningful state changes, and reduced-motion support. Updating events must not steal focus or scroll readers away from earlier details.

Source-based provisional diagnostics, not a rendered visual audit: **Refactoring UI 8/10** (6/8; fix inconsistent spacing and repeated explanatory metadata); **Microinteractions 6/10** (5/8; fix generic submitting states, loss of progress polling after transient errors, and unhelpful current-stage feedback). Blur, contrast, mobile, and motion behavior require browser verification; scores are not acceptance evidence.

## 5. Testing strategy

Test queued → OCR loading/reading or text-layer/cache reuse → classification/rule extraction → Qwen loading/ready/page inference → cross-check → saving → done, only for stages that execute. Cover model disabled, handwriting skips, model unavailable, startup timeout, inference failure, empty result, interrupted recovery, and save failure using fakes. Assert no completion until the final transaction commits, no successful-unload event unless cleanup succeeded, no medical/input contents in events or touched logging statements, private access, deletion cascade, bounded history, and historical-job compatibility. Frontend tests cover open/closed details, stage counts, terminal timing, transient polling recovery, keyboard focus, and axe checks. Full backend/frontend suites and production build are final gates.

## 6. Boundaries

- **Always:** retain real failure state and counts, actual model identity, ordered per-page events, and transactional medical writes. Measure durations with a monotonic clock. Persist changes at operation boundaries, not every animation tick.
- **Approved:** an additive database migration for durable job history. **Ask first:** live deployment, server restart, or any destructive migration; implementation tests use temporary databases.
- **Never:** show total document percent from OCR pages; fabricate token/GPU/memory progress; mark skips verified; ingest raw subprocess output; expose medical values, prompts, raw model replies, credentials, or absolute private paths. Remove raw metadata/model-response logging only in the pipeline statements touched by this feature.

Retain at most the latest 500 events per job, report truncation explicitly, and keep current stage independent of the retained window. Deleting the job/document removes its telemetry. Preserve the last useful progress snapshot if polling temporarily fails; distinguish lost connectivity from failed extraction.

## 7. Success criteria / traceability

| Requirement | Acceptance |
|---|---|
| FR-JOB-01,05 | Existing clients still receive the original fields; newer clients see actual model/stage/page activity, truthful elapsed time, and stage-specific progress. |
| FR-JOB-03,06 | Done appears only after saved results commit. Skips, cache reuse, loading, failures, and recovery have distinct concise messages with expandable technical context. |
| FR-JOB-04 | Poll active jobs every two seconds without overlapping loops; stop terminal jobs and clean up on navigation. Transient errors can recover without reuploading. |
| FR-JOB-07 | Other accounts cannot read telemetry; histories are bounded, private, and removed on deletion; sensitive-content regression tests pass. |
| FR-JOB-09 | Accepted jobs survive client navigation/reload in owner-only Active/Recent Queue; list/history reads and polling stay bounded, hash routes/source pages work, and listing never triggers recovery. |

## 8. Open questions

The user approved additive telemetry persistence and the 500-event retention limit on 2026-11-04. No specification questions remain. Real PaddleOCR-VL production integration and real Qwen inference are not proven by fake-engine telemetry tests; do not claim either model ran until runtime evidence exists.

The user selected “Finish fixes first” on 2026-11-07. Smart OCR-based page filtering, a dedicated `#/review` queue/verification provenance, changed confidence thresholds, visit-date policy and medication reconciliation are deferred specification work, not part of this fix. Filtering belongs after OCR, not preparation; human verification must not imply model certainty, and prescribed/ongoing/stopped states must remain distinct.

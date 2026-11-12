# SPEC-bulk-upload

| | |
|---|---|
| Module | `bulk-upload` |
| Status | Approved 2026-11-04; implemented and locally verified 2026-11-05 (see `tasks/todo.md`) |
| Depends on | `processing`, existing authenticated upload API |
| SRS | FR-ING-01, FR-ING-05, FR-ING-08…10, FR-JOB-04…07 |

## 1. Objective

Select several medical documents and upload them in one action, without losing the batch when one file is rejected. Keep each document's identity, processing outcome, and review link clear. The one-file path remains the same workflow, not a separate implementation.

## 2. Commands

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_worker.py tests/test_system.py -q
npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/App.system.test.jsx
npm --prefix web run build
```

## 3. Structure and API boundary

- `web/src/pages/Intake.jsx`: multiple-file selection, editable pending list, sequential uploads, consent, per-file state, and job polling.
- `web/src/components/JobProgress.jsx`: consume the `processing` module's contract per accepted file.
- `web/src/index.css`: compact responsive file rows and semantic status styling consistent with existing panels/buttons.
- `web/src/lib/api.js`: reuse existing requests and structured duplicate/error information.
- `web/src/test/Intake.integration.test.jsx`, `web/src/test/App.system.test.jsx`, `tests/test_ingest.py`: mixed-batch and single-file regressions.
- `api/routers/documents.py`: existing multipart endpoint remains the contract; no batch endpoint or server-side batch resource.

`POST /api/documents` runs once per file, with at most one upload request in flight. Uploading the next file does not wait for the previous model job; the existing single worker serializes processing. HTTP 202 establishes document/job identity; a duplicate HTTP 409 establishes an existing document link, not a new job. Client-only row identity must distinguish files with identical filenames.

## 4. Code style and UX

Use one list of explicit per-file state objects and the existing request helper; do not introduce a global store or configurable queue framework.

```jsx
<input id="document-files" type="file" multiple accept=".jpg,.jpeg,.png,.pdf" />
```

Before upload, show filename and size with a remove action. Start with automatic document-type detection and no date. Existing optional type/date overrides apply to all selected files and are labeled as such; they are never inferred from filenames or copied from an earlier batch. Consent covers the selected files and the server still records it per accepted document.

During upload, rows immediately show waiting, uploading, queued/processing, already stored, rejected, or failed. Filename is primary; current activity and model are secondary; timestamps and identifiers live in expandable details. Show factual batch counts, not model percentages. Each stored file has an open/review action. Reuse existing one-file previews and extracted-result access without eagerly expanding large medical tables for every batch item. Retain privacy and medical-review warnings; delete decorative “Patient,” “Signed in,” and other labels that merely explain positioning.

## 5. Testing strategy

Use deferred mocked requests to prove sequential uploads and prevention of duplicate submissions. Cover mixed success/rejection/duplicate, same filename with different bytes, remove-before-upload, consent required, shared overrides, no date by default, independent processing failures, per-file open links, and unchanged single-file upload/review. Polling failure must not reupload a file. Use axe and keyboard tests for pending, active, mixed-terminal, and expanded-log states; verify narrow-screen wrapping and reduced motion in a browser.

## 6. Boundaries

- **Always:** preserve accepted files and their IDs when another file fails; continue after file-specific rejection; stop new requests on expired/forbidden sessions; stop scheduling when unmounted or signed out. Poll independently of upload state without overlapping loops.
- **Ask first:** new upload formats, larger server limits, persistent browser queues, background uploads across navigation, or a server job-retry endpoint.
- **Never:** read every selected file into memory, upload in parallel, clear existing records, automatically retry ambiguous POST failures, or relabel a duplicate failed document as processed.

Retry is an explicit action for a failed upload request, using existing duplicate detection if acceptance was ambiguous. A failed extraction is not retried by uploading the same bytes; show its stored document and error. Unsaved selected files remain in browser memory only. Warn before leaving with files not yet sent, including hash/back/forward navigation; do not promise resumability after reload. Server-accepted jobs continue after leaving and remain discoverable in the approved owner-only `#/queue` view (`SPEC-processing.md`, `docs/API.md` §5); this is not a persistent browser upload queue.

## 7. Success criteria / traceability

| Requirement | Acceptance |
|---|---|
| FR-ING-01,08…10 | Two or more files upload with one action, one POST at a time, existing server validation, and consent recorded separately. A single file still works. |
| FR-ING-05,10 | A duplicate links to the existing record; rejected files remain actionable; successes survive and subsequent valid files still upload. |
| FR-JOB-04…07 | Each accepted job displays real progress/private details and stops polling on completion. Bulk completion distinguishes uploaded, processed, duplicate, and failed counts. |

## 8. Open questions

No extra upload infrastructure is required for this scope. Unsent file selections do not survive browser reload; accepted server jobs do. Failed-job retry and real model verification remain separate work, not hidden promises of bulk upload.

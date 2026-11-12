# Test Plan

Status: local P1/P2 plus staged long-PDF/diagnostics synthetic coverage. Current
run counts and remaining rollout/browser/hardware gates are in `tasks/todo.md`.
External corpus, ethics and clinical/quality measurements remain open.

Approved §13.9 regressions cover requested launch flags/240s budget, no-upscale source-preserving 1280px requests, bounded/corrupt input, unavailable artifact identity, valid Qwen retention, interrupted degradation-marker recovery without inference retries, OCR-only review without confidence inflation, affected/unaffected FIFO members, cleanup/capacity/consent fences, ten-failure backoff, pause/admission races, diagnostic sink failure, route-prefix poll suppression, and partial/unavailable UI. Tests use temporary databases/synthetic sources and fake model sessions only. Full suites/build and dated results are recorded in `tasks/todo.md`; no real-model fit/accuracy claim.

## Purpose

Keep a small, deterministic test pyramid that protects the trust boundary and
the user journeys without requiring a GPU, PaddleOCR, a network, or real patient
data. Tests are grouped by the boundary they cross, not by the folder they live
in.

| Layer | Question it answers | Backend | Frontend |
|---|---|---|---|
| Unit | Does one pure rule or component behave correctly? | 38 tests | 6 tests |
| Integration | Do API, database, worker, filesystem, or page boundaries fit together? | 49 tests | 18 tests |
| System | Does a complete user journey work through the app surface? | 2 tests | 10 tests |

These layer counts are the historical 2026-10-24 snapshot, not current totals.
The dated `tasks/todo.md` result ledger owns current measured counts; overlapping
focused runs are not additive coverage totals or a quality score.

## Backend layers

### Unit

Fast, isolated tests with no API, database, worker, or non-loopback network.
They cover preprocessing, quality checks, metadata dates, assembly, resolution,
printed extraction, directive grammar, and evaluation metrics.

Files: `test_preprocess.py`, `test_quality.py`, `test_metadata.py`,
`test_assembly.py`, `test_resolution.py`, `test_extract.py`,
`test_eval_smoke.py`.

Run:

```powershell
.venv\Scripts\python.exe -m pytest -m unit
```

### Integration

Tests that cross at least one boundary: FastAPI `TestClient`, a temporary
SQLite database, the local upload directory, or the worker. They use the same
app factory as production and the autouse `no_network` fixture.

Files: `test_app.py`, `test_db.py`, `test_ingest.py`, `test_patients.py`,
`test_review.py`, `test_summary.py`, `test_worker.py`,
`test_directives.py`.

`test_directives.py` contains pure grammar tests plus worker persistence tests;
it is marked `integration` because the module as a whole crosses the worker
boundary.

Run:

```powershell
.venv\Scripts\python.exe -m pytest -m integration
```

### System

Full journeys through the app surface with a fake OCR engine, a temporary
database, and a temporary upload directory:

1. Printed lab upload -> worker -> document detail -> source page -> accept,
   correct, reject -> summary -> audit rows.
2. Handwritten upload -> worker -> no numeric observations, no medications, no
   directives, and no review items.

File: `test_system.py`.

Run:

```powershell
.venv\Scripts\python.exe -m pytest -m system
```

System tests deliberately use `TestClient`, not live Uvicorn. Shared upload
fixtures explicitly prepare after pending acceptance; `tests/staged_runtime.py`
uses fake owned-stage execution, never a production eager compatibility path.
Runtime supervisor tests spawn importable synthetic targets without models.
Startup syntax/launcher sanitization are checked without executing `start.ps1`;
live startup/migration and hardware/corpus checks require separate authorization.

## Frontend layers

Frontend tests use filename suffixes so new tests are picked up without editing
a list in `package.json`:

| Suffix | Layer | Current files |
|---|---|---|
| `*.unit.test.jsx` | Unit | `CoverageStrip`, `Medications`, `Results` |
| `*.integration.test.jsx` | Integration | `Auth`, `Intake`, `DocumentDetail`, `a11y` |
| `*.system.test.jsx` | System | `App` |

Run:

```powershell
npm --prefix web run test:unit
npm --prefix web run test:integration
npm --prefix web run test:system
npm --prefix web run test
```

The frontend suite mocks `fetch`; it never calls the backend. The system test
renders the full app shell and exercises navigation and the summary/review
surface with the frozen fixture.

## One-command verification

From the repository root:

```powershell
.\scripts\verify.ps1
```

or double-click / run:

```bat
scripts\verify.bat
```

The script runs all three backend marker groups, all three frontend layers, the
production build, and the offline evaluation determinism check. A collection
hook in `tests/conftest.py` fails if any test has no layer marker, so a new
unmarked test cannot be silently skipped by the layer runs. Use
`-SkipFrontend` or `-SkipEval` for a narrower local run. It requires the `.venv`
created by `start.ps1`.

## Test data and safety

- `tests/factory.py` creates synthetic images and PDFs. No real patient data is
  committed.
- `tests/conftest.py` creates a temporary database and upload directory for each
  test, including isolated spool/log roots, and blocks non-loopback sockets.
- System tests inject a fake OCR engine. PaddleOCR itself is exercised by the
  manual smoke path, not by CI.
- The default evaluation fixture is synthetic. A perfect score proves the
  harness works, not clinical accuracy.
- No test asserts a diagnosis, treatment recommendation, or clinical threshold.

## Traceability

| Requirement area | Current coverage |
|---|---|
| FR-ING intake, consent, duplicate detection, page files | `test_ingest.py`, `test_system.py` |
| FR-EXT assembly, labels, values, units, review status | `test_assembly.py`, `test_extract.py`, `test_worker.py` |
| FR-DIR directive grammar, anchors, persistence | `test_directives.py`, `test_system.py` |
| FR-REV accept, correct, reject, audit, ownership | `test_review.py`, `test_system.py` |
| FR-TIM summary contract and source links | `test_summary.py`, `test_system.py`, `App.system.test.jsx` |
| NFR-09 keyboard and accessibility | `a11y.integration.test.jsx`, `App.system.test.jsx` |
| NFR-12 frozen summary contract | `test_summary.py` |
| SI-01/SI-02 audit and handwriting invariants | `test_db.py`, `test_system.py` |
| FR-RUN owned trees, bounded intake/windows, atomic publication/recovery/erasure | `test_runtime_stages.py`, `test_spool.py`, `test_http_intake.py`, `test_preparation.py`, `test_coordinator.py`, `test_publication.py`, `test_erasure.py`, `test_service.py` |
| Long-PDF complete-document equivalence and bounded review | `test_processing_helpers.py`, `test_model_stages.py`, `test_document_ranges.py`, `DocumentDetail.integration.test.jsx` |
| Private diagnostics, sampled/unavailable telemetry and committed progress | `test_observability.py`, `test_app_diagnostics.py`, `test_runtime_telemetry.py`, `test_job_progress.py`, `test_jobs.py`, `JobProgress.unit.test.jsx` |
| FR-JOB-09 persistent owner-only Queue/hash navigation | `test_jobs.py`, `Queue.integration.test.jsx`, `App.system.test.jsx`, `navigation.unit.test.js`: bounded separate list/history pagination, owner/legacy/null-count privacy, terminal/session/connection transitions, abort/nonoverlap, unsent-file guards and source-page URLs |
| Installed RapidOCR adapter and safe Qwen failure parsing | `test_ocr.py`, `test_vlm.py`, `test_model_stages.py`, `test_job_progress.py`: flat 1.4.4 API/three CPU sessions, transport/HTTP categories, valid empty versus malformed arrays, nonfinite values, null optional metadata, durable code/status and post-commit forwarding; no models initialized |
| Evaluation harness determinism | `test_eval_smoke.py` |

The full requirement matrix remains in `docs/SRS.md` section 4. This table only
maps the tests that exist today.

## CI gates

`.github/workflows/ci.yml` runs two jobs:

- Backend: Python 3.11, pinned requirements, full `pytest`.
- Frontend: Node 22, `npm ci`, unit, integration, and system tests, then the
  production build.

The local `scripts/verify.ps1` additionally runs the evaluation determinism
smoke. A pull request is not ready if any layer, the build, or the eval smoke
fails.

## Adding a test

Backend:

1. Put it in `tests/test_<area>.py`.
2. Mark the module (or the individual test) with `unit`, `integration`, or
   `system` in `pyproject.toml` terms.
3. Use the `client`, `app`, and `settings` fixtures for boundary tests; use
   `tmp_path` for files. Never call the network or a real OCR model.
4. Add a small assertion for the behavior, not the implementation detail.

Frontend:

1. Put it under `web/src/test/`.
2. Name it `*.unit.test.jsx`, `*.integration.test.jsx`, or
   `*.system.test.jsx`.
3. Mock `fetch` at the boundary and assert what the user can see or do.
4. Keep it deterministic: no timers longer than needed, no real backend.

## Known gaps

- The P1 ethics pack, 20 consented real documents, and quality-gate precision
  check remain external and open.
- Real-corpus field F1/CER, directive annotations/kappa, and medication lexicon
  coverage cannot be measured without the external data.
- P3 normalisation/safety, P4 medication states, P6 egress, and P7 handwriting
  review are not implemented; their tests are not written.
- CI does not run PaddleOCR, a live browser, or a live Uvicorn process. Those
  remain manual smoke checks.
- The frontend suite is component/integration heavy; it does not replace a
  real-browser accessibility or cross-device pass.
- Current runtime/client rendered-browser replay is unavailable with the
  repository tooling; historical IE screenshots do not verify these changes.
- Synthetic tests do not establish real Qwen fit/accuracy, arbitrary-length
  completion or production readiness. Unknown historical v10 cursor formats
  remain fenced; live rollout/legacy recovery and RT-22 are separately gated.

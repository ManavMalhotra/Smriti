# Smriti

Source-linked longitudinal patient records from paper medical documents.

Smriti takes the printed lab reports, prescriptions, and pharmacy slips a patient already owns and turns them into a timeline where every number can be traced back to the exact box on the exact page it came from. When a doctor wrote "review after 2 weeks", that becomes a dated follow-up — anchored on the collection date, never on today.

**Research prototype. Not a medical device. Not for clinical use.** It does not diagnose, does not recommend treatment, and does not replace a doctor.

---

## What makes it different

Most tools solve capture. Smriti's contribution is **trust and measurement**:

- Every charted value carries a document, page, and bounding box. Click it, see the source.
- Plausibility and arithmetic checks are planned for P3; when implemented, failing values will be excluded rather than hidden.
- Nothing from a handwritten page is auto-accepted: handwritten documents produce no numeric fields, and transcription review is planned for P7.
- The headline number will be measured on 40 real Indian documents with a pre-registered protocol, not estimated.

## Status

Documentation and specifications are complete. P0 (foundation) and P1 (intake) are code complete; the ethics and 20-document gates are still open. P2 is code-complete for the Week 4–6 local slice: a local OCR worker (RapidOCR by default) classifies uploaded documents, assembles printed rows and cells, resolves analyte labels with a deterministic 2-of-3 rule, extracts printed lab/medication fields and labelled dates, and turns common follow-up phrases into anchored directives. The review flow accepts, corrects, or rejects each numeric field. A real summary API feeds the dashboard, and every result links to its source page and box. Each patient has a local account and sees only their own records. The P1 gate remains open; no extraction accuracy is claimed.

| Phase | State |
|---|---|
| Requirements (SRS v1.1) | Done |
| Capability map + 10 module specs | Done |
| Implementation plan + task list | Done |
| Supporting docs | In progress |
| Code | P1 intake + per-patient accounts + Week 4–6 P2 extraction/assembly/resolution/directives + review flow + live summary; P3 normalisation/safety next |

## Repository map

```
docs/       requirements, protocol, ethics, architecture
specs/      capability map and one spec per module
tasks/      implementation plan, task list, build status, PR log
smriti/     config, schema, DB, models, auth, intake, OCR/classifier/assembly/resolver/extractor/directives, dates, worker, summary
api/        routers and error shape
tests/      100+ offline Python tests: unit, integration, and system layers
web/        Vite/React/Tailwind/Recharts shell, auth gate, intake, document review, standardized summary, 100 Vitest + axe tests
scripts/    one-command verification for backend, frontend, build, and eval
```

Start with `docs/index.md` — it lists the reading order and which document owns which decision.

## Constraints that shape the design

- **Local-first with privacy-preserving cloud review.** Local extraction runs entirely on device. Optional cloud review escalates to `gemini-3.8-flash-high` with high reasoning (`thinking_level="high"`). Egress requires explicit user preview approval of locally masked black-box JPEGs; every egress event logs its payload SHA-256 in SQLite, viewable under Audit & Cloud Review Logs. Direct identifiers are never transmitted.
- **Local-first.** OCR, classification, rule extraction, and summary assembly run locally on CPU; enabled Qwen verification uses a local model server. No outbound model API is used.
- **Per-patient accounts.** Passwords are scrypt-hashed; session tokens are stored hashed; every patient/document/job/summary route checks ownership. There is no clinic operator or admin role.
- **One worker, one database.** FastAPI + SQLite, single worker; Qwen may spawn a managed local model process. No distributed upload queue is needed.
- **Every safety invariant is tested in CI.** See SRS §3.3.

## Running it

Python 3.11 and Node 20.19+ or 22.12+ are required.

### Windows quick start

Double-click `start.bat`, or run PowerShell from the repository root:

```powershell
.\start.ps1
# use a different port if 8000 is busy
.\start.ps1 -Port 8001
```

The script creates or reuses `.venv`, installs Python packages only when `requirements.txt` changes, installs frontend packages only when the lockfile changes, rebuilds `web/dist` only when the frontend sources are newer, and then starts Uvicorn. A second run skips the install and build steps.

**Rollout gate:** the staged runtime is a college-project MVP, not production or clinical acceptance. Starting this checkout can migrate the database to v11 and start processing. Live rollout still requires separate approval; do not run startup commands against existing data merely to verify implementation.

Open `http://127.0.0.1:8000/`, create the first patient account, and select one or several JPEG, PNG, or PDF files. Uploads run one at a time; each file retains its own progress, error, duplicate link, and review action. Expand “Processing details” for actual stages, engines, page counts, timings, and severity-colored events. Only failed uploads offer retry; accepted processing jobs continue after leaving, but unsent browser files are not resumable. Open a document to accept, correct, or reject each value against its source. The API is at `http://127.0.0.1:8000/api/health`; stored pages are served at `GET /api/documents/{id}/page/{n}`.

HTTP only spools bounded chunks and returns a pending job with unknown page count. The supervised background pipeline prepares sources before showing review links. PDFs have no page-count admission cap; internal windows contain at most 20 pages, with byte/pixel/storage/memory/time guards still enforced. One upload keeps one job and one final clinical save. Document review loads bounded page/result ranges; completion does not automatically download the whole document.

Production OCR currently defaults to RapidOCR (local PaddleOCR fallback), not PaddleOCR-VL. Printed processing requires Qwen3-VL when enabled (the default) and fails on unavailable or empty model output. Offline tests disable it or use fake engines. Real Qwen inference and PaddleOCR-VL production integration remain unverified; processing telemetry is not an accuracy claim.

### Manual setup

```bash
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest
npm --prefix web install
npm --prefix web run build
.venv\Scripts\python.exe -m smriti.server --port 8000
```

Starting an older database migrates it to schema v11 and preserves existing records. Before separately approved deployment, stop the server/worker and back up consistent SQLite/WAL and durable normalized sources. Exclude raw spool, `.runtime` scratch, debug originals and diagnostics from source backups/exports. Migration 010 adds operational submissions/batches; 011 relaxes only their page/window counts without rebuilding clinical tables. Historical nonterminal jobs without new submission metadata are not automatically processed. Unknown historical v10 checkpoint shapes remain fenced for explicit validated recovery rather than guessed/requeued; recognized v1 cursors resume only validated missing work after owned-tree cleanup. Done/reviewed/populated records are never replacement-written. The first registration claims the sole unowned v1 patient; if there are several, old records are not automatically exposed.

### Local diagnostics

The sanitized launcher prints code-owned events to CMD/PowerShell/IDE terminals and writes the same events to private `data/logs/smriti.jsonl`. Defaults: 10 MiB/file, five backups, seven days, 512 queued events per independent sink, two-second shutdown budget. Logs exclude medical content, credentials, raw model output and private paths. Delivery is best effort: sink failures/drops are reported and unknown crash loss remains unavailable. Shared RAM/device-VRAM measurements are operator-only observed samples, not absolute peaks or proof Qwen fits. The existing job disclosure shows logging degradation, omitted history, latest failure and a copyable support ID.

For locally generated **synthetic** diagnostics, filter by opaque ID using standard PowerShell:

```powershell
Get-Content .\data\logs\smriti.jsonl | ForEach-Object { $_ | ConvertFrom-Json } | Where-Object job_id -eq '<support-id>'
```

Raw spool is deleted after complete durable preparation or terminal failure; crash-only debug retention is opt-in. Owner erasure fences admission, confirms owned work has stopped and cleans owned sources/scratch before deleting rows. Unconfirmed cleanup returns `503 cleanup_failed` and preserves retry metadata; existing append-only audit remains. `SMRITI_MAX_PAGES` is retired and ignored, not repurposed as another cap. Resource defaults remain provisional pending separately authorized hardware/corpus evaluation (RT-22).

Frontend (Node 20.19+ or 22.12+):

```bash
npm --prefix web install
npm --prefix web run test
npm --prefix web run build
npm --prefix web run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. `npm --prefix web run build` writes `web/dist`, which FastAPI mounts at `/`; open `http://127.0.0.1:8000/` after building. The summary view fetches the signed-in patient's live summary. Uploads and OCR stay on the device. Extracted numeric fields are review-only until the patient accepts or corrects them. The Week 4–6 slice adds engine version strings, whitespace table assembly, a deterministic resolver, rule-based directive dates, and an offline evaluation harness. P3 normalisation/safety gates, full P4 medication states/reminders, and real-corpus evaluation are not implemented yet.

Use **Queue** (`#/queue`) to find accepted uploads after leaving Upload or refreshing. Active jobs update automatically; Recent history refreshes on user action. Other views have distinct `#/summary`, `#/intake` and `#/documents/<id>?page=N` URLs. Unsent file selections stay browser-local and require confirmation before leaving; Queue does not retry or recover failed/historical jobs.

## Testing

The test plan is `docs/test-plan.md`. Tests are grouped by the boundary they cross, not by moving files around:

```powershell
# Backend layers (see tasks/todo.md for measured counts)
.venv\Scripts\python.exe -m pytest -m unit
.venv\Scripts\python.exe -m pytest -m integration
.venv\Scripts\python.exe -m pytest -m system

# Frontend: filename suffix selects the layer
npm --prefix web run test:unit
npm --prefix web run test:integration
npm --prefix web run test:system

# Everything, including the production build and eval smoke
.\scripts\verify.ps1
```

Backend system tests use a fake OCR engine, a temporary database, and a temporary upload directory; they do not require PaddleOCR or a network. Frontend tests mock `fetch`. The autouse Python fixture blocks non-loopback sockets. No real patient data is committed.

## Evaluation

The default evaluation fixture is synthetic and proves the harness runs offline; it is not a clinical accuracy result.

```bash
.venv\Scripts\python.exe eval\run_eval.py --verify-determinism
```

The harness writes `eval/out/report.json` with field F1, character error rate, end-to-end exact match, sample sizes, and fixed-seed bootstrap intervals. The real 40-document truth set and the 150-note directive annotations are external inputs and are not committed.

## Licence and data

Project code is coursework. No patient data is committed. Uploads are gitignored and never leave the machine; the current build has no outbound AI path. Local accounts isolate patients on one machine.

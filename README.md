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

Documentation and specifications are complete. P0 (foundation) and P1 (intake) are code complete; the ethics and 20-document gates are still open. P2 is code-complete for the Week 4–6 local slice: a local PaddleOCR worker classifies uploaded documents, assembles printed rows and cells, resolves analyte labels with a deterministic 2-of-3 rule, extracts printed lab/medication fields and labelled dates, and turns common follow-up phrases into anchored directives. The review flow accepts, corrects, or rejects each numeric field. A real summary API feeds the dashboard, and every result links to its source page and box. Each patient has a local account and sees only their own records. The P1 gate remains open; no extraction accuracy is claimed.

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
tests/      89 offline Python tests: unit, integration, and system layers
web/        Vite/React/Tailwind/Recharts shell, auth gate, intake, document review, 34 Vitest + axe tests
scripts/    one-command verification for backend, frontend, build, and eval
```

Start with `docs/index.md` — it lists the reading order and which document owns which decision.

## Constraints that shape the design

- **No image or OCR text ever leaves the device.** The current extraction path is entirely local. A remote resolver, when enabled in a later phase, receives only a typed projection: vocabulary tokens and numbers, with no free text, dates, identifiers, or patient linkage.
- **Local-first.** PaddleOCR, classification, rule extraction, and summary assembly run offline on CPU. The headline result does not depend on any API.
- **Per-patient accounts.** Passwords are scrypt-hashed; session tokens are stored hashed; every patient/document/job/summary route checks ownership. There is no clinic operator or admin role.
- **One process, one database.** FastAPI + SQLite, single worker. Designed for an 8 GB laptop and a free-tier host, not a cluster.
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

Open `http://127.0.0.1:8000/`, create the first patient account, and upload a JPEG, PNG, or PDF. The worker processes it locally; the intake screen polls job state and shows extracted fields. Open the document to accept, correct, or reject each value against the source page. The API is at `http://127.0.0.1:8000/api/health`; stored pages are served at `GET /api/documents/{id}/page/{n}`.

### Manual setup

```bash
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest
npm --prefix web install
npm --prefix web run build
.venv\Scripts\python.exe -m uvicorn smriti.main:app --reload
```

Starting a v1 database migrates it to schema v2 and preserves existing records. Back up `data/smriti.db` first. The first registration claims the sole unowned v1 patient; if there are several, old records are not automatically exposed.

Frontend (Node 20.19+ or 22.12+):

```bash
npm --prefix web install
npm --prefix web run test
npm --prefix web run build
npm --prefix web run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. `npm --prefix web run build` writes `web/dist`, which FastAPI mounts at `/`; open `http://127.0.0.1:8000/` after building. The summary view fetches the signed-in patient's live summary. Uploads and OCR stay on the device. Extracted numeric fields are review-only until the patient accepts or corrects them. The Week 4–6 slice adds engine version strings, whitespace table assembly, a deterministic resolver, rule-based directive dates, and an offline evaluation harness. P3 normalisation/safety gates, full P4 medication states/reminders, and real-corpus evaluation are not implemented yet.

## Testing

The test plan is `docs/test-plan.md`. Tests are grouped by the boundary they cross, not by moving files around:

```powershell
# Backend: 38 unit, 49 integration, 2 system
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

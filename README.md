# Smriti

Source-linked longitudinal patient records from paper medical documents.

Smriti takes the printed lab reports, prescriptions, and pharmacy slips a patient already owns and turns them into a timeline where every number can be traced back to the exact box on the exact page it came from. When a doctor wrote "review after 2 weeks", that becomes a dated follow-up — anchored on the collection date, never on today.

**Research prototype. Not a medical device. Not for clinical use.** It does not diagnose, does not recommend treatment, and does not replace a doctor.

---

## What makes it different

Most tools solve capture. Smriti's contribution is **trust and measurement**:

- Every charted value carries a document, page, and bounding box. Click it, see the source.
- Values that fail a plausibility or arithmetic check are never charted, and are shown as excluded rather than hidden.
- Handwriting is transcribed with human confirmation of every field. Nothing from a handwritten page is ever auto-accepted, and no numeric lab value is taken from handwriting at all.
- The headline number is measured on 40 real Indian documents with a pre-registered protocol, not estimated.

## Status

Documentation and specifications are complete. P0 (foundation) and P1 (intake) are code complete; the ethics and 20-document gates are still open. P2 is partially implemented: a local PaddleOCR worker classifies uploaded documents and extracts printed lab/medication fields into review rows, and a real summary API feeds the dashboard. Each patient has a local account and sees only their own records. The P1 gate remains open; no extraction accuracy is claimed.

| Phase | State |
|---|---|
| Requirements (SRS v1.1) | Done |
| Capability map + 10 module specs | Done |
| Implementation plan + task list | Done |
| Supporting docs | In progress |
| Code | P1 intake + per-patient accounts + local P2 extraction + live summary; review/normalisation/safety next |

## Repository map

```
docs/       requirements, protocol, ethics, architecture
specs/      capability map and one spec per module
tasks/      implementation plan, task list, build status, PR log
smriti/     config, schema, DB, models, auth, intake, OCR/classifier/extractor, worker, summary
api/        routers and error shape
tests/      52 offline Python tests with temp DB and upload dir
web/        Vite/React/Tailwind/Recharts shell, auth gate, intake, 24 Vitest + axe tests
```

Start with `docs/index.md` — it lists the reading order and which document owns which decision.

## Constraints that shape the design

- **No image or OCR text ever leaves the device.** The current extraction path is entirely local. A remote resolver, when enabled in a later phase, receives only a typed projection: vocabulary tokens and numbers, with no free text, dates, identifiers, or patient linkage.
- **Local-first.** PaddleOCR, classification, rule extraction, and summary assembly run offline on CPU. The headline result does not depend on any API.
- **Per-patient accounts.** Passwords are scrypt-hashed; session tokens are stored hashed; every patient/document/job/summary route checks ownership. There is no clinic operator or admin role.
- **One process, one database.** FastAPI + SQLite, single worker. Designed for an 8 GB laptop and a free-tier host, not a cluster.
- **Every safety invariant is tested in CI.** See SRS §3.3.

## Running it

Python 3.11 is required.

```bash
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest
npm --prefix web install
npm --prefix web run build
.venv\Scripts\python.exe -m uvicorn smriti.main:app --reload
```

Open `http://127.0.0.1:8000/`, create the first patient account, and upload a JPEG, PNG, or PDF. The worker processes it locally; the intake screen polls job state and shows extracted fields. The API is at `http://127.0.0.1:8000/api/health`; stored pages are served at `GET /api/documents/{id}/page/{n}`.

Starting a v1 database migrates it to schema v2 and preserves existing records. Back up `data/smriti.db` first. The first registration claims the sole unowned v1 patient; if there are several, old records are not automatically exposed.

Frontend (Node 20.19+ or 22.12+):

```bash
npm --prefix web install
npm --prefix web run test
npm --prefix web run build
npm --prefix web run dev
```

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. `npm --prefix web run build` writes `web/dist`, which FastAPI mounts at `/`; open `http://127.0.0.1:8000/` after building. The summary view fetches the signed-in patient's live summary. Uploads and OCR stay on the device. Extracted numeric fields are review-only; the review endpoint, P3 normalisation/safety gates, P4 medication states/directives, and evaluation are not implemented yet.

## Licence and data

Project code is coursework. No patient data is committed. Uploads are gitignored and never leave the machine; the current build has no outbound AI path. Local accounts isolate patients on one machine.

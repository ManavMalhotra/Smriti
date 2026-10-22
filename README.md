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

Documentation and specifications are complete. P0 (foundation) is code complete; the ethics gate is still open.

| Phase | State |
|---|---|
| Requirements (SRS v1.1) | Done |
| Capability map + 10 module specs | Done |
| Implementation plan + task list | Done |
| Supporting docs | In progress |
| Code | P0 foundation done; intake next |

## Repository map

```
docs/       requirements, protocol, ethics, architecture
specs/      capability map and one spec per module
tasks/      implementation plan, task list, build status, PR log
smriti/     config, schema, DB, models, app factory
api/        routers and error shape
tests/      offline tests with temp DB and upload dir
web/        frontend workspace and frozen summary fixture
```

Start with `docs/index.md` — it lists the reading order and which document owns which decision.

## Constraints that shape the design

- **No image ever leaves the device.** A remote resolver, when enabled, receives a typed projection: vocabulary tokens and numbers, with no free text, dates, identifiers, or patient linkage.
- **Local-first.** OCR, parsing, normalisation, and safety checks run offline on CPU. The headline result does not depend on any API.
- **One process, one database.** FastAPI + SQLite, single worker. Designed for an 8 GB laptop and a free-tier host, not a cluster.
- **Every safety invariant is tested in CI.** See SRS §3.3.

## Running it

Python 3.11 is required.

```bash
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m uvicorn smriti.main:app --reload
```

The API is at `http://127.0.0.1:8000/api/health`. The web workspace, OCR, and evaluation entry points arrive with later phases.

## Licence and data

Project code is coursework. No patient data is committed. Uploads are gitignored and never leave the operator's machine except as a typed projection under explicit per-document consent.

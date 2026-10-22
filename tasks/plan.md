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
| `SMRITI_OCR_MODEL` | `PP-OCRv6_small` | fallback `PP-OCRv5_mobile` |
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

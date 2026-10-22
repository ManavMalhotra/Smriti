# Build Status

Updated: 2026-10-23

Authority: `docs/SRS.md` > `specs/CAPABILITY-MAP.md` > module specs. `tasks/plan.md` owns the approach, `tasks/todo.md` owns week order, and this file owns module status and the PR record.

## Module board

| Module | Phase | State | Done |
|---|---|---|---|
| foundation | P0 | code complete, ethics gate open | 8/8 code |
| intake | P1 (week 3) | next | 0/7 |
| extraction | P2 (weeks 4–6) | blocked by intake | 0/7 |
| normalisation | P3 (week 8) | blocked | 0/4 |
| safety | P3 (week 7) | blocked | 0/4 |
| medications | P4 (week 10) | blocked | 0/3 |
| directives | P4 (week 11) | blocked | 0/4 |
| dashboard | P5 (weeks 6, 14) | blocked | 0/5 |
| egress | P6 (week 8) | blocked | 0/4 |
| handwriting-assist | P7 (weeks 9–10) | gated by week-8 decision | 0/5 |
| evaluation | P2+ (weeks 4–12) | blocked | 0/5 |

## P0 — Foundation

- [x] Python 3.11.17 environment; core web/DB/test dependencies pinned in `requirements.txt`
- [x] `smriti/config.py`: profiles, paths, resolver flag, OCR model, thresholds; environment read only here
- [x] `smriti/schema.sql`: 11 tables, indexes, `UNIQUE(content_hash)`, per-page quality, share tokens
- [x] DB invariants: audit append-only; no `auto` observation from a handwritten document (SI-01); no numeric lab value from a handwritten document (SI-02)
- [x] `smriti/db.py`: SQLite WAL, `foreign_keys=ON`, numbered schema version
- [x] `smriti/models.py`: Pydantic v2 domain models and the frozen seven-key `Summary`
- [x] `smriti/app.py` + `smriti/main.py`: app factory, lifespan, contract-shaped errors, health, optional static mount
- [x] `POST /api/patients`, `DELETE /api/patients/{id}` with cascade erase, file removal, audit row, demo read-only guard
- [x] `web/src/fixtures/summary.json`: frozen contract fixture; bbox length and `from` alias tested
- [x] `tests/`: 15 passed; non-loopback sockets blocked
- [x] CI workflow: Python 3.11, install, pytest
- [ ] Ethics pack submitted (team task, OR-01) — blocks the phase gate
- [ ] Intended-use statement in the UI, report, and demo (OR-05)
- [ ] PaddleOCR, PaddlePaddle, OpenCV, PyMuPDF, Pillow, RapidFuzz — deliberately deferred to P2 to keep P0 installable

## P1 — Intake (next)

- [ ] `smriti/preprocess.py`: EXIF strip, perspective, deskew, CLAHE, upscale; pure functions
- [ ] `smriti/quality.py`: short edge, Laplacian, aspect ratio, blank page
- [ ] `smriti/handwriting.py`: detector; `capture_type` set server-side; any doubt → `handwritten`
- [ ] `smriti/ingest.py`: content hash, idempotent write, PDF split, job row
- [ ] `POST /api/documents`, `POST /api/documents/{id}/consent`
- [ ] `GET /api/documents/{id}/page/{n}` (contract gap recorded in `docs/API.md`)
- [ ] `tests/test_ingest.py`: idempotency, EXIF gone, PDF split, 202 + job
- [ ] 20 real documents in hand, consent rows recorded
- [ ] **Gate**: 20 documents available; quality gate does not reject clean documents

## Module backlog

### Extraction

- [ ] `smriti/ocr.py`: PaddleOCR wrapper, words and normalised boxes, engine string
- [ ] `smriti/engines.py`: registry with versions
- [ ] `eval/run_eval.py` skeleton and `eval/metrics.py` (F1, CER) on a 5-doc fixture
- [ ] `smriti/assembly.py`: table regions, rows, columns
- [ ] `smriti/extract.py`: template rules → candidates
- [ ] `smriti/resolution.py`: synonym → range → unit, 2-of-3 agreement
- [ ] `POST /api/observations/{id}/review` and review UI

### Normalisation and safety

- [ ] `data/analyte_map.csv`: 30 analytes, Indian synonyms, LOINC, specimen, timing
- [ ] `smriti/normalize.py`: Decimal, unit map, glucose separation, `mapping_rule`
- [ ] `smriti/checks.py`: gates G1–G5; `skipped ≠ pass`
- [ ] `data/bounds.csv` with a citation per row; `data/swing.csv`
- [ ] Rejected values never charted; source overlay click → page + box

### Medications and directives

- [ ] `data/brand_lexicon.csv` derived from the 40 prescriptions, not invented
- [ ] Medication extraction: three never-merged states, source and timestamp
- [ ] Directive grammar: `action_type × timing_type`; anchor `collection_date → doc_date → unknown`, never today
- [ ] Reminders: anchor shown, unknown state shown, no past notifications

### Dashboard and sharing

- [ ] Vite + Tailwind + Recharts shell renders the frozen fixture
- [ ] Aggregate summary: four zones, coverage strip, gaps
- [ ] Patient and clinician modes
- [ ] Share link with PIN, expiry, attempt lock, revoke endpoint and audit

### Egress

- [ ] Typed-projection builder; allowlist vocabulary, no image, no free text
- [ ] Consent gate; refuse and log without consent
- [ ] Provider adapter, payload hash, `egress` row, kill switch
- [ ] Week-8 queue-shrink experiment; delete the module if < 30 %

### Handwriting assist

- [ ] `smriti/candidates.py`: weighted ranking, phonetic normalisation, abstention margin
- [ ] `FieldReview.jsx`: crop with context line, 3 candidates, no default, search, add-box
- [ ] `handwriting_field` row for every action with `ms_to_verify`
- [ ] Vigilance test: 10 % injected wrong top-1, false-accept recorded
- [ ] **Gate**: no handwritten field in any state but `review`; false-accept ≤ 5 %

### Evaluation

- [ ] Truth-set harness and offline reproduction
- [ ] Field F1, CER, end-to-end, material errors
- [ ] Bootstrap CIs, 1000 resamples, seed recorded
- [ ] Risk–coverage curve at 100/90/80 %
- [ ] `report.json` + figures regenerated offline

## PR log

No git remote is configured. "PR" here means a local feature branch merged into `main` with `--no-ff`; the merge commit is the review record.

| PR | Branch | Scope | Checks | State |
|---|---|---|---|---|
| PR-01 | `feat/p0-foundation` | P0 foundation: config, schema v1, models/contract, app factory, patients API, tests, CI | 15 passed | ready to merge |
| PR-02 | `feat/p1-intake` | Intake: preprocess, quality, handwriting detection, idempotent ingest, upload/consent endpoints | planned | not started |
| PR-03 | `feat/p2-extraction` | OCR, assembly, extraction, resolver, review loop, eval skeleton | planned | not started |
| PR-04 | `feat/p3-normalise-safety` | 30 analytes, unit conversion, five safety gates, source overlay | planned | not started |
| PR-05 | `feat/p4-meds-directives` | Medication states and directive timing/anchoring | planned | not started |
| PR-06 | `feat/p5-dashboard` | Summary API, zones, coverage, patient/clinician modes, share links | planned | not started |
| PR-07 | `feat/p6-egress` | Typed projection, consent gate, adapter, kill switch, queue-shrink experiment | planned | not started |
| PR-08 | `feat/p7-handwriting` | Candidate ranking, field review, vigilance measurement (conditional) | planned | not started |
| PR-09 | `feat/p8-evaluation` | Full offline evaluation, CIs, risk–coverage, report artifacts | planned | not started |

### PR-01 commits

- `c871baf` chore: pin Python 3.11 core dependencies and add CI
- `a934e17` feat(db): add schema v1 with SI-01/SI-02 and audit triggers
- `4775c56` feat(contract): add frozen seven-key summary models and fixture
- `cb67af7` feat(api): add app factory, health, and patient create/erase
- `f083189` test: cover schema invariants, erase-all, and summary contract

## Open contract decisions

- Share revoke endpoint is described in `docs/API.md` but not implemented; add with dashboard sharing.
- Page-image endpoint is missing from the endpoint list; add with intake.
- `problems` ships as `[]` in v1; no diagnosis extraction is invented.
- `handwriting.py` is claimed by both intake and handwriting-assist specs; intake owns detection, assist owns ranking.
- Review response shape is not frozen; freeze it with PR-03.

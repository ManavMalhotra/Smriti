# Build Status

Updated: 2026-10-23

Authority: `docs/SRS.md` > `specs/CAPABILITY-MAP.md` > module specs. `tasks/plan.md` owns the approach, `tasks/todo.md` owns week order, and this file owns module status and the PR record.

## Module board

| Module | Phase | State | Done |
|---|---|---|---|
| foundation | P0 | code complete, ethics gate open | 8/8 code |
| intake | P1 (week 3) | code complete + local upload UI, 20-doc gate open | 7/9 |
| extraction | P2 (weeks 4–6) | blocked by intake | 0/7 |
| normalisation | P3 (week 8) | blocked | 0/4 |
| safety | P3 (week 7) | blocked | 0/4 |
| medications | P4 (week 10) | blocked | 0/3 |
| directives | P4 (week 11) | blocked | 0/4 |
| dashboard | P5 (weeks 6, 14) | fixture shell + intake form; summary API blocked | 1/5 |
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
- [x] `tests/`: 36 passed by P1 (15 at P0 merge); non-loopback sockets blocked
- [x] CI workflow: Python 3.11, install, pytest
- [ ] Ethics pack submitted (team task, OR-01) — blocks the phase gate
- [~] Intended-use statement in the UI footer; report and demo still open (OR-05)
- [x] NumPy, OpenCV, Pillow, PyMuPDF added for P1 intake
- [ ] PaddleOCR, PaddlePaddle, RapidFuzz — deliberately deferred to P2

## P1 — Intake

- [x] `smriti/preprocess.py`: EXIF strip, perspective, deskew, CLAHE, upscale; pure functions
- [x] `smriti/quality.py`: short edge, Laplacian, aspect ratio, blank page, duplicate-page hash
- [x] `smriti/handwriting.py`: conservative server-side detector; any doubt → `handwritten`
- [x] `smriti/ingest.py`: SHA-256 idempotency, PDF split at 300 DPI, page WebP files, job row
- [x] `POST /api/documents`, `POST /api/documents/{id}/consent`, `GET /api/documents/{id}`
- [x] `GET /api/documents/{id}/page/{n}`, `GET /api/jobs/{id}`
- [x] `tests/test_preprocess.py`, `tests/test_quality.py`, `tests/test_ingest.py`
- [ ] 20 real documents in hand, consent rows recorded (team task)
- [~] **Gate**: five synthetic fixtures pass and EXIF/GPS is stripped; 20 real documents and the quality-gate precision check are still open

## Week 2 - UI shell

- [x] `web/`: Vite + React (JS) + Tailwind v4 + Vitest; Recharts is lazy-loaded only when a result has more than one point
- [x] Four zones in fixed order: header with gap + coverage, problems + current medications, results, pending + documents
- [x] Apple-minimal monochrome shell: system font, `#f5f5f7` page, white cards, thin borders, no gradients or glass
- [x] Printed flags shown verbatim; no computed "abnormal" copy
- [x] Source path panel shows document, page, and normalised bbox; fixture IDs have no page image yet
- [x] Local intake form: create patient, upload JPEG/PNG/PDF with local-only consent, queued status and page preview
- [x] 18 Vitest tests including `jest-axe`; production build served by FastAPI at `/`
- [ ] Live summary API, fixture page-image link, 2 s job polling/review UI, clinician mode, and sharing (blocked on P3/P4/P5)

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

- [x] Vite + Tailwind + Recharts shell renders the frozen fixture (patient mode; chart loads only when a result has more than one point)
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
| PR-01 | `feat/p0-foundation` | P0 foundation: config, schema v1, models/contract, app factory, patients API, tests, CI | 15 passed | merged `dca8223`, tag `p0-foundation` |
| PR-02 | `feat/p1-intake` | Intake: preprocess, quality, handwriting detection, idempotent ingest, upload/consent/page/job endpoints | 36 passed | merged `50b3b08`, tag `p1-intake` |
| PR-06a | `feat/dashboard-shell` | Week 2 fixture-only dashboard shell: Vite/React/Tailwind/Recharts, four zones, source path, Vitest + axe | 11 frontend, 36 Python, build passed | merged `80d179d`, tag `dashboard-shell` |
| PR-02a | `feat/intake-ui` | Local intake UI for P1: create patient, upload with local-only consent, queued result, page-1 preview, duplicate/error states | 18 frontend, 36 Python, build passed, live upload, 1280/390 visual checks | merged `0c0e343`, tag `intake-ui` |
| PR-03 | `feat/p2-extraction` | OCR, assembly, extraction, resolver, review loop, eval skeleton | planned | not started |
| PR-04 | `feat/p3-normalise-safety` | 30 analytes, unit conversion, five safety gates, source overlay | planned | not started |
| PR-05 | `feat/p4-meds-directives` | Medication states and directive timing/anchoring | planned | not started |
| PR-06 | `feat/p5-dashboard` | Summary API, zones, coverage, patient/clinician modes, share links | planned | not started |
| PR-07 | `feat/p6-egress` | Typed projection, consent gate, adapter, kill switch, queue-shrink experiment | planned | not started |
| PR-08 | `feat/p7-handwriting` | Candidate ranking, field review, vigilance measurement (conditional) | planned | not started |
| PR-09 | `feat/p8-evaluation` | Full offline evaluation, CIs, risk–coverage, report artifacts | planned | not started |

PR-06a is a fixture-only slice of PR-06, pulled forward so the UI contract is visible before the summary API. The full dashboard remains PR-06.

### PR-01 commits

- `c871baf` chore: pin Python 3.11 core dependencies and add CI
- `a934e17` feat(db): add schema v1 with SI-01/SI-02 and audit triggers
- `4775c56` feat(contract): add frozen seven-key summary models and fixture
- `cb67af7` feat(api): add app factory, health, and patient create/erase
- `f083189` test: cover schema invariants, erase-all, and summary contract
- `36f6594` docs: record P0 status, tick foundation tasks, and update README
- Merge: `dca8223` (tag `p0-foundation`)

### PR-02 commits

- `97a617b` chore: add intake imaging and PDF dependencies
- `c2e0c8b` feat(intake): add preprocessing, quality gate, and capture-type detection
- `bdf4a23` feat(intake): add idempotent ingestion and document/job endpoints
- `99775e6` test(intake): cover EXIF, idempotency, PDF split, quality, and endpoints
- `9e77ca3` docs(api): add page endpoint and quality rejection
- `6fe99bb` docs: record P1 status and tick week-3 tasks
- Merge: `50b3b08` (tag `p1-intake`)

### PR-06a commits

- `22bc543` feat(web): add fixture dashboard shell with four zones
- `67d5f3e` test(web): cover zone order, coverage, flags, source path, and a11y
- Merge: `80d179d` (tag `dashboard-shell`)

### PR-02a commits

- `15b3769` feat(web): add local intake form for P1 uploads
- `5f12da0` test(web): cover intake upload, errors, duplicates, and a11y
- Merge: `0c0e343` (tag `intake-ui`)

## Known limits at P1 + local UI

- Handwriting detection is a conservative heuristic, not a trained classifier; a shadowed printed page can fall back to `handwritten`.
- PDF pages are not deduplicated; a perceptual hash cannot distinguish template pages that differ by one value.
- Page files are removed after the patient-delete transaction commits; a crash between commit and unlink can leave orphan files under `data/uploads`.
- The 20-document real-corpus gate and the ethics pack are team-owned and still open.
- The summary shell renders the frozen fixture only. The intake form writes real patients and documents locally, but `GET /api/patients/{id}/summary` and patient/document list endpoints do not exist, so intake records are not shown in the summary.
- The intake form creates the patient before upload; a rejected or duplicate upload can leave an empty patient. There is no list endpoint to reuse or clean it up in the UI.
- The current patient is kept only in the intake screen's React state; returning to the summary discards it. The summary/intake switch is not a URL route, so refresh returns to the sample summary.
- The intake form sends the optional `doc_date` only; `collection_date` is not collected yet.
- Uploads stay queued because no OCR worker exists; the intake UI shows the queued state and does not poll.
- Patient mode only; job polling, review UI, clinician mode, sharing, and live source images remain in PR-06/Week 6.
- The trend chart only renders with more than one point; the fixture's single HbA1c point stays a table.
- Source paths show the normalised box, but fixture IDs are not seeded, so no page image is linked.

## Open contract decisions

- Share revoke endpoint is described in `docs/API.md` but not implemented; add with dashboard sharing.
- `problems` ships as `[]` in v1; no diagnosis extraction is invented.
- `handwriting.py` is claimed by both intake and handwriting-assist specs; intake owns detection, assist owns ranking.
- Review response shape is not frozen; freeze it with PR-03.
- The summary response is frozen as a fixture but the `GET /api/patients/{id}/summary` endpoint is not implemented; add it with PR-06 before the full dashboard.

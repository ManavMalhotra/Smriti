# Build Status

Updated: 2026-10-23

Authority: `docs/SRS.md` > `specs/CAPABILITY-MAP.md` > module specs. `tasks/plan.md` owns the approach, `tasks/todo.md` owns week order, and this file owns module status and the PR record.

## Module board

| Module | Phase | State | Done |
|---|---|---|---|
| foundation | P0 | code complete, ethics gate open | 8/8 code |
| accounts | cross-cutting | code complete; no admin/roles | 4/4 |
| intake | P1 (week 3) | code complete + authenticated local UI, 20-doc gate open | 7/9 |
| extraction | P2 (weeks 4–6) | partial: local OCR, classifier, rule extraction, worker | 3/7 |
| normalisation | P3 (week 8) | blocked | 0/4 |
| safety | P3 (week 7) | blocked | 0/4 |
| medications | P4 (week 10) | partial: printed rule extraction only | 1/3 |
| directives | P4 (week 11) | blocked | 0/4 |
| dashboard | P5 (weeks 6, 14) | fixture shell + live summary API + auth gate | 3/5 |
| egress | P6 (week 8) | blocked; no egress path wired | 0/4 |
| handwriting-assist | P7 (weeks 9–10) | gated by week-8 decision | 0/5 |
| evaluation | P2+ (weeks 4–12) | blocked | 0/5 |

The P1 ethics and 20-document gates remain open. The user explicitly asked to continue implementation while they are open; this is a recorded scope exception, not gate closure.

## P0 — Foundation

- [x] Python 3.11.17 environment; core web/DB/test dependencies pinned in `requirements.txt`
- [x] `smriti/config.py`: profiles, paths, resolver flag, OCR model, thresholds, auth TTL/attempts; environment read only here
- [x] `smriti/schema.sql`: schema v2, 13 tables, indexes, audit append-only, SI-01/SI-02
- [x] `smriti/migrations/002_auth_ocr.sql`: v1 → v2 migration preserving existing records
- [x] `smriti/db.py`: SQLite WAL, `foreign_keys=ON`, numbered schema version
- [x] `smriti/models.py`: Pydantic v2 domain models, auth payloads, extracted detail, frozen seven-key `Summary`
- [x] `smriti/app.py` + `smriti/main.py`: app factory, lifespan, worker startup, contract-shaped errors, health, optional static mount
- [x] Per-patient accounts: scrypt hashes, hashed session tokens, HttpOnly/SameSite cookie, ownership checks
- [x] `DELETE /api/patients/{id}` with cascade erase, file removal, audit row, demo read-only guard
- [x] `web/src/fixtures/summary.json`: frozen contract fixture; bbox length and `from` alias tested
- [x] `tests/`: 52 passed; non-loopback sockets blocked
- [x] CI workflow: Python 3.11, install, pytest
- [ ] Ethics pack submitted (team task, OR-01) — blocks the phase gate
- [~] Intended-use statement in the UI footer; report and demo still open (OR-05)
- [x] NumPy, OpenCV, Pillow, PyMuPDF added for P1 intake
- [x] PaddleOCR/PaddlePaddle added; cached `PP-OCRv5_mobile_det` and `en_PP-OCRv5_mobile_rec`

## P1 — Intake

- [x] `smriti/preprocess.py`: EXIF strip, perspective, deskew, CLAHE, upscale; pure functions
- [x] `smriti/quality.py`: short edge, Laplacian, aspect ratio, blank page, duplicate-page hash
- [x] `smriti/handwriting.py`: conservative server-side detector; any doubt → `handwritten`
- [x] `smriti/ingest.py`: patient-scoped SHA-256 idempotency, PDF split at 300 DPI, page WebP files, job row, actor
- [x] `POST /api/documents`, `POST /api/documents/{id}/consent`, `GET /api/documents/{id}`
- [x] `GET /api/documents/{id}/page/{n}`, `GET /api/jobs/{id}`, all ownership-checked
- [x] `tests/test_preprocess.py`, `tests/test_quality.py`, `tests/test_ingest.py`
- [ ] 20 real documents in hand, consent rows recorded (team task)
- [~] **Gate**: five synthetic fixtures pass and EXIF/GPS is stripped; 20 real documents and the quality-gate precision check are still open

## P2 — Local extraction (partial)

- [x] `smriti/ocr.py`: PaddleOCR adapter, words and normalised boxes, engine string, oneDNN workaround
- [x] `smriti/classify.py`: local document-type classifier with confidence
- [x] `smriti/analytes.py` + `data/analyte_map.csv`: initial analyte synonyms, units, display names
- [x] `smriti/extract.py`: line grouping, printed lab-field rules, printed medication rules, bbox and review status
- [x] `smriti/worker.py`: one background loop, job claim, page OCR, classification, extraction, failure state
- [x] `smriti/summary.py`: real seven-key summary from stored documents/observations/medications/directives
- [x] `tests/test_extract.py`, `tests/test_worker.py`: 12 tests; real OCR smoke-tested on a synthetic image and the existing 3-page discharge summary
- [ ] `smriti/assembly.py`: table regions, rows, columns
- [ ] `smriti/resolution.py`: synonym → range → unit, 2-of-3 agreement
- [ ] `POST /api/observations/{id}/review` and review UI
- [ ] `eval/run_eval.py` + metrics on a labelled corpus
- [ ] **Gate** one printed document parsed end to end; accuracy measured, not claimed

The current extraction is line-based, not a table model. Every numeric field is written as `review`; no clinical normalisation or safety gate runs. Handwritten documents produce no numeric fields. The existing real discharge summary is classified `other` with confidence `0.386` and `capture_type='handwritten'`, so it yields no numeric fields by design.

## Week 2 — UI shell and local intake

- [x] `web/`: Vite + React (JS) + Tailwind v4 + Vitest; Recharts is lazy-loaded only when a result has more than one point
- [x] Four zones in fixed order: header with gap + coverage, problems + current medications, results, pending + documents
- [x] Apple-minimal monochrome shell: system font, `#f5f5f7` page, white cards, thin borders, no gradients or glass
- [x] Printed flags shown verbatim; no computed "abnormal" copy
- [x] Source path panel shows document, page, and normalised bbox
- [x] Account gate: register/sign-in, signed-in patient header, sign-out
- [x] Local intake form: authenticated upload JPEG/PNG/PDF with local-only consent, automatic document-type detection, 2 s job polling, extracted fields and page text
- [x] Live summary fetch for the signed-in patient; fixture remains the contract test
- [x] NFR-09 keyboard focus on view changes, upload result, and form resets; WCAG AA text and 3:1 control borders on summary, intake, and auth
- [x] 24 Vitest tests including `jest-axe`; production build served by FastAPI at `/`
- [ ] Review UI, clinician mode, sharing, and live source-image links from the dashboard (P3/P4/P5)

## Module backlog

### Extraction

- [x] `smriti/ocr.py`: PaddleOCR wrapper, words and normalised boxes, engine string
- [x] `smriti/classify.py`: local document-type classifier
- [x] `smriti/extract.py`: line rules → review candidates
- [x] `smriti/worker.py`: local pipeline and job state
- [x] `smriti/summary.py`: real summary builder
- [ ] `smriti/engines.py`: registry with versions
- [ ] `smriti/assembly.py`: table regions, rows, columns
- [ ] `smriti/resolution.py`: synonym → range → unit, 2-of-3 agreement
- [ ] `POST /api/observations/{id}/review` and review UI
- [ ] `eval/run_eval.py` skeleton and `eval/metrics.py` (F1, CER) on a 5-doc fixture

### Normalisation and safety

- [ ] `data/analyte_map.csv`: 30 analytes, Indian synonyms, LOINC, specimen, timing
- [ ] `smriti/normalize.py`: Decimal, unit map, glucose separation, `mapping_rule`
- [ ] `smriti/checks.py`: gates G1–G5; `skipped ≠ pass`
- [ ] `data/bounds.csv` with a citation per row; `data/swing.csv`
- [ ] Rejected values never charted; source overlay click → page + box

### Medications and directives

- [ ] `data/brand_lexicon.csv` derived from the 40 prescriptions, not invented
- [~] Medication extraction: printed rule extraction writes `prescribed` rows; three never-merged states and reporting UI open
- [ ] Directive grammar: `action_type × timing_type`; anchor `collection_date → doc_date → unknown`, never today
- [ ] Reminders: anchor shown, unknown state shown, no past notifications

### Dashboard and sharing

- [x] Vite + Tailwind + Recharts shell renders the frozen fixture (patient mode; chart loads only when a result has more than one point)
- [x] Live `GET /api/patients/{id}/summary` for the signed-in patient
- [x] Account gate and per-patient isolation in the UI
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
| PR-02b | `feat/a11y-hardening` | NFR-09: focus handoff on navigation, result, reset, and patient change; WCAG 1.4.11 control borders | 18 frontend, 36 Python, build passed, manual Tab/focus and contrast check | merged `60c017c`, tag `a11y-ui` |
| PR-03a | `feat/patient-auth-ai` | Per-patient accounts, session isolation, local PaddleOCR/classifier/rule extraction, worker, real summary API, authenticated intake polling and extracted fields | 52 Python, 24 frontend, build passed, real OCR smoke test | pending merge |
| PR-03 | `feat/p2-extraction` | Full OCR assembly, resolver, review loop, eval skeleton | planned | not started |
| PR-04 | `feat/p3-normalise-safety` | 30 analytes, unit conversion, five safety gates, source overlay | planned | not started |
| PR-05 | `feat/p4-meds-directives` | Medication states and directive timing/anchoring | planned | not started |
| PR-06 | `feat/p5-dashboard` | Full summary zones, coverage, patient/clinician modes, share links | planned | not started |
| PR-07 | `feat/p6-egress` | Typed projection, consent gate, adapter, kill switch, queue-shrink experiment | planned | not started |
| PR-08 | `feat/p7-handwriting` | Candidate ranking, field review, vigilance measurement (conditional) | planned | not started |
| PR-09 | `feat/p8-evaluation` | Full offline evaluation, CIs, risk–coverage, report artifacts | planned | not started |

PR-06a is a fixture-only slice of PR-06, pulled forward so the UI contract is visible before the summary API. The full dashboard remains PR-06.

PR-02b is a pulled-forward NFR-09 slice of Week 13 for the screens that exist. The full accessibility audit still covers review, clinician, and share screens when they are built.

PR-03a is a partial P2 slice pulled forward with the account model. It does not close the P1 gate, does not implement P3/P4, and does not make accuracy claims.

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

### PR-02b commits

- `47111ce` fix(web): manage focus and meet control contrast on view changes
- Merge: `60c017c` (tag `a11y-ui`)

## Known limits at P2 partial

- The P1 ethics pack, 20 real consented documents, and quality-gate precision check are still open. No extraction accuracy is claimed.
- Extraction is line-based and rule-based, not a table model. Multi-column lab tables, labels after values, and unusual layouts will be missed or misread.
- Every extracted numeric field is `review`; there is no review endpoint or review UI, and the summary currently includes review points so data is visible. This is not clinical validation.
- No P3 normalisation, unit conversion, plausibility/arithmetic gates, or reference-range safety checks. `unit_norm` is always null from the worker.
- Handwritten documents produce no numeric observations by design. Handwriting detection is a conservative heuristic, not a trained classifier; a shadowed printed page can fall back to `handwritten`.
- The classifier is keyword-based. The existing 3-page discharge summary lands on `other` with confidence `0.386` and is treated as handwritten, so it yields no fields.
- PDF pages are not deduplicated; a perceptual hash cannot distinguish template pages that differ by one value.
- Page files are removed after the patient-delete transaction commits; a crash between commit and unlink can leave orphan files under `data/uploads`.
- The first registration only auto-claims a sole unowned v1 patient. Multiple legacy patients need a separate claim path that is not built.
- Accounts are local only; the cookie is not `Secure` over HTTP, there is no CSRF token (SameSite=Strict only), no password reset, no email, no admin role, and no share link.
- The worker is one thread and holds the engine while OCR runs. App shutdown waits at most five seconds for the worker; a long OCR job can outlive shutdown.
- The summary has no P4 directives yet, so `pending` is empty unless directives are inserted by another path. `problems` is always `[]`.
- The trend chart only renders with more than one point; a single point stays a table.
- Source paths show the normalised box; the dashboard does not yet link to live page images.

## Open contract decisions

- The summary response is frozen as a fixture and `GET /api/patients/{id}/summary` is now implemented. The current implementation includes `review` points; freeze whether review values belong in the charted payload before P3.
- Review response shape is not frozen; freeze it with the review loop.
- `problems` ships as `[]`; no diagnosis extraction is invented.
- Share revoke endpoint is described in `docs/API.md` but not implemented; add with dashboard sharing.
- Handwriting fields are contract-only; `handwriting.py` owns detection, assist owns ranking.
- Auth changed the v1 "one operator, no accounts" scope. The architecture, API, and data model now document local per-patient accounts and isolation. This is not clinic multi-tenancy or RBAC; no admin/operator role exists.

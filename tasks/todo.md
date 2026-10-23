# Task List

Ordered by dependency. One task per line, one owner, one test. Do not start a phase before the previous phase's gate is green.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · **GATE** blocks the next phase.

---

## Week 1 — Foundation

- [x] `pyproject.toml` / `requirements.txt`: core deps pinned (fastapi, uvicorn, pydantic, sqlalchemy, python-multipart, httpx, pytest)
- [x] NumPy / OpenCV / PyMuPDF / Pillow added for P1 intake
- [ ] PaddleOCR / PaddlePaddle / RapidFuzz added at P2 start
- [x] `smriti/config.py`: every key from plan §4, loaded once, recorded per run
- [x] `smriti/db.py`: SQLite WAL, `foreign_keys=ON`, schema v1 with 11 tables (SRS §3.4)
- [x] `smriti/models.py`: Pydantic v2 models for patient, document, observation, directive, medication, egress
- [x] `smriti/main.py`: app factory, static mount, profile switch
- [x] `tests/conftest.py`: temp DB, temp upload dir, loopback-only network guard
- [x] CI: pytest on push; fail on non-loopback network call
- [ ] Ethics pack submitted (OR-01)
- [~] Intended-use statement written once, used in UI, report, demo (OR-05); UI footer done, report and demo open
- [x] `docs/API.md` draft with the 15 endpoints; page-image endpoint added in P1 (16 total)
- [~] **GATE** ethics submitted; tests run (tests green; ethics pack open)

## Week 2 — Contract and probes

- [x] `web/src/fixtures/summary.json` frozen with 7 keys (FR-TIM-01) — pulled forward into P0
- [x] `tests/test_summary.py::test_contract` validates fixture against Pydantic (NFR-12) — pulled forward into P0
- [x] Vite + Tailwind + Recharts shell renders the fixture (patient mode; Recharts lazy-loads when a result has more than one point; 18 Vitest + axe tests)
- [x] Local intake form: create patient, upload JPEG/PNG/PDF with local-only consent, queued status and page preview (pulled forward from Week 6)
- [x] `POST /api/documents` + `GET /api/jobs/{id}` shapes agreed and implemented
- [ ] **Probe A** — `python -m smriti.candidates --probe`: PP-OCRv6 over 10 handwritten drug lines; record output and top-3
- [ ] **Probe B** — preprocessing A/B over 20 docs: baseline vs perspective+deskew+CLAHE+upscale
- [ ] Record both probe results in `docs/evaluation.md`
- [ ] **GATE** contract locked; probe A decides handwriting design; probe B decides pipeline steps

## Week 3 — Intake

- [x] `smriti/preprocess.py`: EXIF strip, perspective, deskew, CLAHE, upscale — pure functions
- [x] `smriti/quality.py`: short edge, Laplacian, aspect ratio, blank page, duplicate-page hash
- [x] `smriti/handwriting.py`: detector; sets `capture_type` server-side (FR-ING-02)
- [x] `smriti/ingest.py`: content hash, idempotent write, page split, job row
- [x] `POST /api/documents`, `POST /api/documents/{id}/consent`
- [x] `GET /api/documents/{id}/page/{n}`, `GET /api/documents/{id}`, `GET /api/jobs/{id}`
- [x] `tests/test_ingest.py`, `tests/test_quality.py`, `tests/test_preprocess.py`: 36 passed
- [ ] 20 real documents in hand, consent rows recorded
- [~] **GATE** five synthetic fixtures pass and EXIF/GPS is stripped; 20 real documents and the quality-gate precision check are still open

## Week 4 — OCR baseline

- [ ] `smriti/ocr.py`: PaddleOCR wrapper, words + normalised boxes, engine string
- [ ] `smriti/engines.py`: registry with versions
- [ ] `eval/run_eval.py` skeleton + `eval/metrics.py` (F1, CER) on a 5-doc fixture
- [ ] `tests/test_eval_smoke.py`: runs offline
- [ ] CER measured on 10 documents; per-template breakdown
- [ ] Annotation guide v1; 30-note double-annotated subset drawn **first** (FR-DIR-10)
- [ ] 40 documents confirmed on paper (A-03)
- [ ] **GATE** CER measured; 40 docs confirmed; kappa computation runnable

## Week 5 — Extraction

- [ ] `smriti/assembly.py`: table regions, rows, columns from OCR output
- [ ] `smriti/extract.py`: template rules → candidates
- [ ] `smriti/resolution.py`: synonym → range → unit, 2-of-3 agreement
- [ ] `data/analyte_map.csv`: 30 analytes, Indian synonyms, LOINC, specimen, timing
- [ ] `data/brand_lexicon.csv`: derived from the 40 prescriptions, not invented
- [ ] Directive grammar v1: `action_type × timing_type` patterns
- [ ] `tests/test_extract.py`, `tests/test_directives.py` span offsets
- [ ] **GATE** one printed document parsed end to end

## Week 6 — Review loop and first evaluation

- [ ] `POST /api/observations/{id}/review` + audit rows
- [ ] Review UI: field, crop, candidates, accept/correct/reject, keyboard path
- [~] Upload UI + 2 s job polling (FR-JOB-04); local create/upload/consent/page preview done, polling and review UI open
- [ ] `tests/test_review.py`
- [ ] **M1 evaluation** on 40 docs: field F1, end-to-end, material errors
- [ ] Medication F1 baseline; lexicon coverage reported (FR-MED-05)
- [ ] **GATE** printed end-to-end measured; if < 0.85, apply RISK-05 before week 8

## Week 7 — Safety

- [ ] `smriti/checks.py`: G1…G5 with tolerances (FR-SAF-01)
- [ ] `data/bounds.csv` with a citation per row; `data/swing.csv`
- [ ] `tests/test_checks.py`: each gate pass/fail/skipped; `skipped ≠ pass`
- [ ] Injected-corruption set: 200 cases, recall per gate
- [ ] Timeline + reference bands render only accepted values
- [ ] `tests/test_invariants.py::test_rejected_never_charted`
- [ ] **GATE** gate recall ≥ 0.80, false quarantine ≤ 0.10

## Week 8 — Normalisation and the three gates

- [ ] `smriti/normalize.py`: Decimal, unit map, glucose separation, mapping_rule
- [ ] `tests/test_normalize.py`: 30 synonyms, unit round-trip, no fuzzy on printed
- [ ] Source overlay: click value → page + box (FR-TIM-06)
- [ ] **Resolver experiment**: 40 docs with resolver off vs on, count review items
- [ ] **Handwriting decision**: green only if printed end-to-end ≥ 0.85 **and** probe A survived **and** a clinician labeller exists
- [ ] **GATE 1** normalisation ≥ 0.95
- [ ] **GATE 2** resolver shrinks queue ≥ 30 % or `egress` is deleted
- [ ] **GATE 3** handwriting go/no-go recorded in the report

## Week 9 — Handwriting assist (conditional)

- [ ] `smriti/candidates.py`: weighted ranking, phonetic normalisation, abstention margin
- [ ] `FieldReview.jsx`: crop with context line, 3 candidates, no default, search, add-box
- [ ] `handwriting_field` rows written for every action with `ms_to_verify`
- [ ] `tests/test_candidates.py`: ranking, abstain, no default
- [ ] `tests/test_invariants.py::test_handwritten_never_auto`
- [ ] **GATE** no handwritten field in any state but `review`

## Week 10 — Handwriting metrics and medications

- [ ] 25 handwritten pages annotated by the clinician
- [ ] Taps, seconds, top-3, accepted-unchanged measured
- [ ] **Vigilance test**: 10 % injected wrong top-1, study mode, false-accept recorded
- [ ] Failure taxonomy written (what the model misreads and why)
- [ ] Medication extraction: three states, source + timestamp, no merge
- [ ] **GATE** false-accept ≤ 5 %; otherwise the human gate is declared ineffective and the feature is cut

## Week 11 — Directives and clinician mode

- [ ] Directive evaluation: span F1, timing accuracy, date exact
- [ ] Reminders UI: anchor shown, unknown state shown, no past notifications
- [ ] Clinician mode: citation density, print view
- [ ] **GATE** span F1 ≥ 0.75, timing ≥ 0.80, date exact ≥ 0.70

## Week 12 — Numbers frozen

- [ ] Risk–coverage curve at 100/90/80 % (FR-EVL-05)
- [ ] Bootstrap CIs, 1000 resamples, seed recorded
- [ ] Local vs resolver table (FR-EVL-08)
- [ ] `eval/run_eval.py` full offline run; `report.json` + figures
- [ ] **GATE** every reported number regenerates offline

## Week 13 — Usability and bug pass

- [ ] 5–8 participant sessions: time-to-answer vs paper folder
- [~] Keyboard-only and contrast audit (NFR-09); automated axe pass done, manual session open
- [ ] Bug pass on the cut list
- [ ] **GATE** usability data in hand

## Week 14 — Demo

- [ ] Seeded demo DB; `SMRITI_PROFILE=demo` verified: no uploads, no egress, read-only
- [ ] 4-minute video recorded
- [ ] Rehearsal with a fallback plan (RISK-11)
- [ ] **GATE** demo runs offline from a cold start

## Week 15–16 — Report and viva

- [ ] Results chapter filled from `report.json`, never typed by hand
- [ ] Limitations section: lexicon coverage, 40-doc CI width, handwriting stratum, resolver that may not have shipped
- [ ] Viva answers prepared: why any egress at all, why not handwriting auto, why 40 documents
- [ ] **GATE** submission

---

## Standing rules

- Every merged change updates the FR traceability row it touches.
- A threshold change is an SRS change (§5.4), never a Python edit.
- No test calls the network.
- No image or free text leaves the device, ever.

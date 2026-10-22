# Smriti — Capability Map

Status: **frozen, pending review**
Phase: 0 of the spec-driven workflow (map → per-module specs → plan → tasks → implement)
Owner: requirements authority is `docs/SRS.md`; this file owns module boundaries only.

---

## 1. Authority rule

> `docs/SRS.md` §3 owns **requirements** — IDs, priorities, acceptance thresholds.
> `specs/SPEC-*.md` owns **how each module is built** — commands, structure, code style, tests, boundaries.
> On conflict, **the SRS wins and the spec is corrected.** Never the reverse.

Two documents that disagree are worse than one. Any change to a threshold starts in the SRS.

---

## 2. Frozen assumptions

Correct before the first module spec is written; changing one after that is a re-plan.

| ID | Assumption |
|---|---|
| A-01 | Printed documents are the core path. Handwriting is **assist-only**: every handwritten field requires an explicit human act, none is ever auto-accepted. |
| A-02 | No real document's **image** leaves the device. Cloud receives a typed projection of already-extracted values (§4, D-03). |
| A-03 | 40 real printed documents collected by week 6. 25 handwritten pages only if the handwriting track survives the week-8 gate. |
| A-04 | Three members, 12–15 h/week each, 16 weeks. |
| A-05 | Single process, CPU-first. Local dev: Ryzen 5 5600H, 8 GB RAM, GTX 1650 (4 GB VRAM). Deploy: free tier, CPU only. |
| A-06 | No ABDM/FHIR, no guideline engine, no RAG, no model fine-tuning. All future scope. |
| A-07 | SQLite, one background worker. No Postgres, no Redis, no Celery. |
| A-08 | 30 analytes, LOINC mapping, per-observation printed reference ranges, glucose series never merged. |
| A-09 | Four directive classes; anchor `collection_date` → `doc_date` → unknown, never today. |
| A-10 | Medications keep three never-merged states: `prescribed` / `reported_stopped` / `reported_ongoing`. |
| A-11 | Headline evaluation on 40 printed docs: end-to-end ≥ 0.85, field F1 ≥ 0.90, material errors ≤ 2%, risk–coverage +5 pts at 10% deferral. |
| A-12 | A pharmacist or final-year med student is available as the labelling oracle. **Unconfirmed.** |
| A-13 | The college mandates no document template. **Unconfirmed.** |

---

## 3. Decisions

| ID | Decision | Reversal cost |
|---|---|---|
| D-01 | Handwriting is a first-class module, **propose-verify** design: three candidates per field box, human taps one or types. Gated at week 8. | Low — fall back to crop + search by deleting the ranking step. |
| D-02 | Handwriting is the **first** capability cut if the printed path slips. (Corrects the SRS cut order, which protected it last.) | None. |
| D-03 | Cloud escalation sends a **typed projection**, never an image and never free text. Allowlist schema, not redaction. | Low — module deleted if it fails its gate. |
| D-04 | `egress` must shrink the human review queue by **≥ 30%** over 40 documents or be deleted. | None — deletion is the point. |
| D-05 | Two runtime profiles: `local-gpu` (full) and `demo-cpu` (synthetic corpus, cloud off, uploads disabled, read-only). | None. |
| D-06 | Image preprocessing is **measured, not assumed**. Only steps that improve field F1 on 20 in-house documents survive. | None. |

### Why projection and not redaction

Redaction is a denylist and cannot be proven complete — marginalia, stamps, barcodes, letterhead, filenames, document geometry. Under DPDP, anonymisation must be irreversible; a redaction box is pseudonymisation.

A typed projection is an **allowlist**. Every string is drawn from a closed vocabulary (30 analyte names, units, flags, table words); every number matches `^\d+(\.\d+)?$`. A person's name cannot be represented because the schema has no field for it. That is testable in CI rather than argued in a viva.

Outbound payload is one orphan table: no patient linkage, no dates, no free text.

---

## 4. Modules

| Module | Responsibility | Depends on | SRS |
|---|---|---|---|
| `intake` | Upload, consent capture, EXIF strip, rasterisation, quality gate, handwriting detection, perspective correction, deskew, duplicate-page detection, idempotent ingestion, job lifecycle | — | FR-ING, FR-JOB |
| `extraction` | OCR, layout reconstruction, field assembly, rules resolver, confidence from agreement, review queue, provenance boxes | `intake`, `egress` | FR-EXT, FR-ASM, FR-REV |
| `egress` | Typed-projection construction, vocabulary enforcement, consent gate, provider adapter, payload hashing, audit, kill switch | `extraction` | FR-EGR (new) |
| `normalisation` | 30 analytes, Indian synonyms, LOINC, unit conversion, printed ranges, glucose series separation | `extraction` | FR-NRM |
| `safety` | 5 arithmetic gates, plausibility bounds, swing rules, rejected values never charted | `extraction`, `normalisation` | FR-SAF |
| `medications` | Brand/dose/frequency extraction, drug lexicon, three-state model | `extraction` | FR-MED |
| `directives` | Four timing classes, anchoring, supersession, conditional triggers, PRN | `normalisation` | FR-DIR |
| `dashboard` | Aggregate summary, four zones, coverage strip, patient/clinician modes, share link + audit | `normalisation`, `safety`, `medications`, `directives` | FR-TIM, FR-SHR |
| `handwriting-assist` | Line/field segmentation, candidate ranking, per-field review UI, vigilance measurement | `extraction`, `medications`, `dashboard` | FR-HWR (new) |
| `evaluation` | Truth-set harness, metrics, bootstrap CIs, risk–coverage curve, offline reproduction | all (consumes artifacts) | FR-EVL |

**Not modules:** storage schema (architecture doc + ADR), deployment (ADR-09), the corpus itself (project activity, not a capability).

### Dependency graph

```
intake ──▶ extraction ──▶ normalisation ──▶ safety ──┐
              │    │            │                    │
              │    └──▶ egress  ├──▶ directives ─────┤
              │                 │                    ├──▶ dashboard ──┐
              └──▶ medications ─┴────────────────────┘                │
                                                                      ▼
                                                        handwriting-assist
evaluation: skeleton with extraction, full metrics at dashboard
```

No cycles. `directives` depends on `normalisation` for dates and analyte identity only, not on `safety` — which is why the two sit on separate branches.

### Build order

```
intake → extraction → normalisation → safety → medications → directives → dashboard → handwriting-assist
                ↘ egress (parallel after extraction, judged at week 8)
```

`evaluation` is the exception to strict ordering: harness skeleton with fixtures at `extraction`, one metric added per module, complete at `dashboard`. Otherwise the product is finished before anything can be measured.

---

## 5. Gates

| Week | Gate | Fail action |
|---|---|---|
| 2 | Handwriting probe: PP-OCRv6 over 10 handwritten drug lines; capitalisation survives and correct drug in top-3 ≈ half the time | D-01 downgrades to crop + search immediately |
| 2 | Preprocessing A/B over 20 in-house docs: baseline vs perspective+deskew+CLAHE+upscale | Drop any step that does not improve field F1 (D-06) |
| 4 | 40 documents physically in hand, confirmed on paper | Re-scope the evaluation, not the deadline |
| 6 | Printed end-to-end ≥ 0.85 on 40 docs | Cut per D-02 |
| 8 | `egress` review-queue shrink ≥ 30% | Delete `egress` (D-04) |
| 8 | Printed field F1 ≥ 0.90 and meds extracted | Cut handwriting regardless of probe results |
| 15 | Full evaluation reproduces offline from the frozen truth set | Report is not final |

---

## 6. Spec template

Each `specs/SPEC-<module>.md` contains, in order:

1. **Objective** — one paragraph, no restating the SRS
2. **Commands** — run and test this module in isolation
3. **Structure** — files and directories the module owns
4. **Code style** — naming, error handling, conventions
5. **Testing strategy** — unit / integration / fixture, and the threshold that proves it
6. **Boundaries** — what it must never do (most safety invariants live here)
7. **FR traceability** — one row per requirement: SRS ID → acceptance test
8. **Open questions** — time-boxed, with the fallback if unanswered

---

## 7. Standing risks

| Risk | Impact | Mitigation |
|---|---|---|
| A-12 — no clinician oracle for handwritten ground truth | `handwriting-assist` has no truth set; top-3 containment unmeasurable | Resolve by week 4. If unresolved, cut handwriting at week 8 regardless of probe results. |
| A-13 — college template unknown | Rewriting ~600 lines of SRS at week 12 | Confirm before SRS v1.1 is written. |
| Free-tier host too small | Deploy fails late | PaddleOCR peak is ~2.22 GB; rules out 512 MB tiers. Target HF Spaces CPU (16 GB). |
| Projection vocabulary invented rather than derived | `egress` resolves nothing useful | Vocabulary derived from the 40 real documents in week 5, not designed in advance. |
| Photographed multi-column reports | Adjacency destroyed before OCR; projection loses signal | Perspective correction in `intake`; if unresolved, those docs go straight to human review. |
| 8 GB local RAM | Docker + dev server + OCR exceeds it | Native venv for development; Docker only for deploy. One worker, never two. |

---

## 8. Next

Approve this map, then write `specs/SPEC-intake.md` through `specs/SPEC-evaluation.md` — ten specs, one page each. No code until specs are approved.

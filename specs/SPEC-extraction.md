# SPEC-extraction

| | |
|---|---|
| Module | `extraction` |
| Status | Draft for review |
| Depends on | `intake`, `egress` |
| SRS | FR-EXT-01…10, FR-ASM-01…05, FR-REV-01…05, FR-RED-01…08 (via `egress`) |
| Files | `smriti/ocr.py`, `smriti/extract.py`, `smriti/assembly.py`, `smriti/engines.py`, `api/routers/review.py` |

## 1. Objective

Page image → typed candidate fields with normalised boxes, an engine identity, a confidence, and a routing decision. Extraction decides *what the document says*; it does not decide what the value means, whether it is plausible, or whether it is safe to chart. Those are `normalisation` and `safety`.

The decisive design point: **rules resolve first, the network is the last resort.** Three independent signals (row label, printed range containment, unit set) resolve the large majority of rows deterministically and offline. Only the residual reaches `egress`.

## 2. Commands

```bash
pytest tests/test_extract.py tests/test_assembly.py -q
python -m smriti.extract --document <id> --dry-run      # parse, write nothing
python -m smriti.extract --document <id> --dump-fields  # print candidates + confidence
python -m smriti.ocr --page data/uploads/<hash>/page_1.webp --json
```

## 3. Structure

```
smriti/
  ocr.py        PaddleOCR wrapper; text + word boxes; no parsing
  assembly.py   layout: table regions, rows, columns, cell assignment
  extract.py    orchestrator: page → candidates → routing
  engines.py    engine registry (id, version, quantisation) recorded on every field
  resolution.py rule resolver: synonym → range → unit, 2-of-3 agreement
api/routers/review.py   list, accept, correct, reject; audit
```

Candidate lifecycle: `candidate → auto | review | rejected`. There is no other state, and `auto` is refused here if the source is handwritten.

## 4. Code style

- One field type, `FieldCandidate`, created in `extract.py` and passed down. No dicts between layers.
- Boxes are `[x0, y0, x1, y1]`, normalised 0–1, page-relative (CON-07). Pixel coordinates are never persisted.
- Numeric values are `Decimal`, parsed from the raw string and kept alongside it. Raw text is never discarded.
- Confidence is a **derived** number in `[0,1]`, computed from signal agreement — never passed through from a model's self-report.
- `engines.py` returns an engine string of the form `paddle:PP-OCRv6_small@1.0+cpu`; every observation stores it (FR-EXT-09).

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_resolver_two_of_three` — table of 20 ambiguous rows | rules resolve without network |
| Unit | `test_box_normalisation` — random pixel boxes round-trip | CON-07 |
| Unit | `test_confidence_is_derived` — confidence independent of engine claim | FR-ASM-01 |
| Fixture | 5-doc mini set: clean, skewed, shadowed, compressed, handwritten | no crash, correct routing |
| Truth set | 40 printed docs, full run | **field F1 ≥ 0.90, CER ≤ 0.05** |
| Invariant | `test_handwritten_never_auto` | SI-01 |
| Invariant | `test_no_numeric_from_handwritten` | SI-02 |

The headline numbers are produced by `evaluation`, not here. This module's job is to make them reproducible.

## 6. Boundaries

- **Never** open a network connection. The only path out is `egress.project_and_send()`; a direct `httpx`/`requests` import in this module fails CI.
- **Never** auto-accept a handwritten field (SI-01), and never emit a numeric lab candidate from a handwritten page at all (SI-02). Handwritten pages yield medication names, doses, frequencies, directives only (FR-EXT-10).
- **Never** write canonical units, LOINC codes, or interpreted flags — that is `normalisation`.
- **Never** discard the raw extracted string; corrections must retain the original (DR-03).
- **Never** mark a field `auto` without passing all gates (FR-ASM-02). The default is `review`.
- **Never** align a field to a box that does not correspond to a word or model box — route to `review` (FR-ASM-04).

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-EXT-01 | `test_ocr_emits_words_and_boxes` |
| FR-EXT-02 | `test_template_rows_assembled` |
| FR-EXT-03 | `test_analyte_mapping_includes_synonyms` |
| FR-EXT-04 | `test_residual_escalates_to_egress` |
| FR-EXT-05 | **Rewritten** — see `SPEC-egress`; escalation is text-only, not vision |
| FR-EXT-06 | `test_candidate_schema_validated` |
| FR-EXT-07 | `test_null_with_reason_routes_to_review` |
| FR-EXT-08 | `test_cache_hit_makes_no_call` |
| FR-EXT-09 | `test_engine_recorded_on_every_field` |
| FR-EXT-10 | `test_handwritten_yields_no_numerics` |
| FR-ASM-01 | `test_confidence_from_agreement` |
| FR-ASM-02 | `test_auto_requires_all_gates` |
| FR-ASM-03 | `test_handwritten_always_review` |
| FR-ASM-04 | `test_unalignable_box_routes_to_review` |
| FR-ASM-05 | `test_box_stored_normalised` |
| FR-REV-01…05 | `tests/test_review.py` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-EXT-01 | `PP-OCRv5 mobile` → `PP-OCRv6_small`, v5 mobile as fallback. |
| FR-EXT-04 | "cloud vision model" → "typed projection via `egress`". |
| FR-EXT-05 | Model escalation ladder still applies, but to text payloads, not images. |
| FR-EXT-06 | Output schema becomes the projection response schema, not `box_2d` from a vision model. |
| FR-EXT-08 | Cache key drops the image hash; use `projection_sha256`. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Is PP-OCRv6_small meaningfully better than v5 mobile on *Indian lab layouts*, not just the vendor bench? | Week 4 | Ship v5 mobile; record the comparison as a result |
| 2 | Does layout detection need a table model, or do whitespace projections suffice? | Week 5 | Whitespace only; merged-cell docs go to review |
| 3 | What agreement threshold makes `auto` precise? | Week 6, on 40 docs | Set conservatively; review rate is a reported metric, not a failure |

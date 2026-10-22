# SPEC-normalisation

| | |
|---|---|
| Module | `normalisation` |
| Status | Draft for review |
| Depends on | `extraction` |
| SRS | FR-NRM-01…04, DR-02 |
| Files | `smriti/normalize.py`, `data/analyte_map.csv`, `data/unit_map.csv` |

## 1. Objective

Turn a raw `(label, value, unit, range)` candidate into a canonical observation: one of 30 analyte ids, a decimal value, a canonical unit, and the laboratory's own reference range preserved untouched. This module is where "Hb", "Haemoglobin", "HEMOGLOBIN (HB)" become the same analyte — and where they must never become the same *observation* as a different specimen or timing.

The rule that governs every decision here: **never invent a number the document does not contain.** No derived reference ranges, no computed flags, no unit conversion when the unit is unknown.

## 2. Commands

```bash
pytest tests/test_normalize.py -q
python -m smriti.normalize --csv data/analyte_map.csv --validate
python -m smriti.normalize --document <id> --explain   # per-field decision trace
```

## 3. Structure

```
smriti/normalize.py
data/analyte_map.csv   label_synonym → analyte_id, loinc, specimen, timing, default_unit
data/unit_map.csv      from_unit → to_unit, factor, offset
tests/fixtures/normalise/  one CSV per analyte with real label variants
```

The 30 analytes are fixed and versioned. Adding a 31st is an SRS change, not a code change.

## 4. Code style

- Conversion arithmetic uses `Decimal` with an explicit quantum; `float` is banned in this module. A value that changes on round-trip is a bug.
- `normalize(candidate) -> Normalised | Unresolved` — no exceptions for data problems, only for programming errors. `Unresolved` carries a reason string that reaches the review queue.
- Lookup is exact-match on a normalised key: lowercase, collapse whitespace, strip trailing punctuation, expand known abbreviations. No fuzzy matching here — fuzzy matching belongs to handwritten candidate ranking, and it must never silently rename a printed label.
- Every mapping decision is recorded on the observation: `analyte_id`, `mapping_rule` (`exact` | `synonym` | `unresolved`).

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_synonyms_all_30` — every synonym in `analyte_map.csv` resolves to its analyte | coverage |
| Unit | `test_no_cross_analyte_collision` — no synonym maps to two analytes | safety |
| Unit | `test_unit_roundtrip` — convert and back, 10 000 random decimals, exact equality | Decimal correctness |
| Unit | `test_unknown_unit_is_unresolved` — never guesses | no silent conversion |
| Unit | `test_glucose_series_never_merge` | FR-NRM-04 |
| Truth set | correct analyte + canonical unit | **≥ 0.95** (SRS §4.1) |

## 6. Boundaries

- **Never** re-derive, interpolate, or overwrite the printed reference range (FR-NRM-03, DR-02). If the lab printed nothing, the observation has no range.
- **Never** merge fasting, postprandial, and random glucose. They are three analytes (FR-NRM-04).
- **Never** convert when the source unit is unknown or ambiguous — mark unresolved, route to review.
- **Never** fuzzy-match a printed label. A near-match is a different test.
- **Never** infer specimen or timing from position on the page; it comes from the label or the column header, or it stays unknown.
- **Never** apply a default unit because the analyte "usually" has one.

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-NRM-01 | `test_every_analyte_has_loinc` |
| FR-NRM-02 | `test_unit_pairs_cover_corpus` — every pair observed in the 40 docs is in `unit_map.csv` |
| FR-NRM-03 | `test_range_is_immutable` |
| FR-NRM-04 | `test_glucose_series_separate` |
| DR-02 | `test_range_survives_correction` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-NRM-02 | State that `unit_map.csv` is derived from the corpus, so the pair set is a measured artifact, not a guess. |
| new FR-NRM-05 | Record `mapping_rule` on every observation for auditability. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | How many Indian lab label variants exist for the same analyte? | Week 5, on 40 docs | Ship what the corpus contains; the rest stay unresolved, which is correct |
| 2 | Does any lab print ranges in a unit different from the result? | Week 6 | Store both units; never convert the printed range |

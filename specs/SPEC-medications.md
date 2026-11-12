# SPEC-medications

| | |
|---|---|
| Module | `medications` |
| Status | Draft for review |
| Depends on | `extraction` |
| SRS | FR-MED-01…03, SI-09 |
| Files | `smriti/medications.py`, `data/brand_lexicon.csv`, `api/routers/medications.py` |

## 1. Objective

Extract what was prescribed — brand, salt, dose, form, frequency, duration — and keep it permanently distinct from what the patient says they are actually taking. Three states, never merged, each with its own source and timestamp.

This is the module where a plausible-looking merge does the most harm: "prescribed amlodipine" and "patient reports stopped amlodipine" are both true statements about the same person at the same time, and collapsing them into one row produces a medication list that is wrong in a way no amount of confidence can fix.

## 2. Commands

```bash
pytest tests/test_medications.py -q
python -m smriti.medications --document <id> --dry-run
python -m smriti.medications --lexicon --validate     # duplicates, salt coverage, encoding
python -m smriti.medications --coverage --docs 40     # % of brand tokens found in lexicon
```

## 3. Structure

```
smriti/medications.py
data/brand_lexicon.csv   brand, salt, strength_options, form, source
api/routers/medications.py
```

Lexicon is **derived from the 40 collected prescriptions in week 5**, then supplemented by NLEM/Jan Aushadhi salt names. It is never invented in advance — an invented lexicon measures nothing.

Coverage is a first-class output: the fraction of brand tokens in the corpus that the lexicon contains. It is reported, because it caps every downstream number.

## 4. Code style

- `MedicationEvent` is append-only. A state change is a new row, never an `UPDATE`.
- `status ∈ {prescribed, reported_stopped, reported_ongoing}`. No other value, no default guessing.
- Patient-reported rows carry `reported_at` and `actor='patient'`; they are never rendered with the same visual weight as a prescription (FR-MED-03).
- Brand and salt are stored separately. If the lexicon knows the mapping, both are shown; if it doesn't, `salt` stays null rather than being guessed.
- Dose and frequency are stored as written plus a normalised form; the written form is what the UI shows.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_three_states_never_merge` — same drug in all three states yields three rows | SI-09 |
| Unit | `test_state_change_is_new_row` | append-only history |
| Unit | `test_unknown_brand_leaves_salt_null` | no silent mapping |
| Unit | `test_patient_report_attributed` | FR-MED-03 |
| Truth set | brand + dose + frequency extraction | **F1 ≥ 0.80** (new threshold) |
| Lexicon | `--coverage` over 40 real prescriptions | reported; expected 30–50 % |

## 6. Boundaries

- **Never** merge states (SI-09). Not for display, not for a count, not for "current medications".
- **Never** extract non-medication laboratory analytes (e.g. Triglycerides, Total Protein, Globulin, eGFR, Bilirubin) as brand medications (`NON_MED_WORDS` and `is_valid_medication_name()` guard this boundary).
- **Never** report older historical prescriptions as current ongoing therapy in longitudinal summaries; current medications are strictly bounded to the latest clinical report date.
- **Never** infer a stop. Only an explicit prescription or an explicit patient report changes state.
- **Never** map a brand to a salt silently — show both or show neither.
- **Never** invent a dose, frequency, or duration the document does not state.
- **Never** present a patient-reported status as verified.
- **Never** add guideline logic — no interactions, no contraindications, no dosing advice. Out of scope and out of competence.

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-MED-01 | `test_three_states` |
| FR-MED-02 | `test_no_merge_across_states`, `test_each_row_has_source_and_ts` |
| FR-MED-03 | `test_patient_report_timestamped_and_attributed` |
| SI-09 | `test_invariant_no_merged_state` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| new FR-MED-04 | Medication extraction F1 ≥ 0.80 on the 40 printed prescriptions. |
| new FR-MED-05 | Report lexicon coverage; it is a limitation, not a footnote. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | How many brand tokens does the corpus actually contain? | Week 5 | Coverage number is the result; state it plainly |
| 2 | Are frequencies ever written as `1-0-1` without a duration? | Week 5 | Yes, expected — duration stays null |
| 3 | Does a printed prescription ever carry two strengths of one brand? | Week 6 | Two rows; never sum |

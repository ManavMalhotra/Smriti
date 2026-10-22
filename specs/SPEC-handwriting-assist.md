# SPEC-handwriting-assist

| | |
|---|---|
| Module | `handwriting-assist` |
| Status | Draft, **gated at week 8** |
| Depends on | `extraction`, `medications`, `dashboard` |
| SRS | new FR-HWR-01…06, SI-01, SI-02, CON-05 |
| Files | `smriti/handwriting.py`, `smriti/candidates.py`, `web/src/components/FieldReview.jsx` |

## 1. Objective

Make an unreadable page cheap to transcribe **without ever letting the machine assert what it says.** The model proposes; the human disposes. Every handwritten field is created in `review` and leaves `review` only through an explicit human action on that field.

The product claim is not accuracy. It is **taps saved**: a prescription that takes 24 taps and 3 minutes by hand should take ≤ 9 taps and ≤ 50 seconds, with zero auto-accepted fields.

This module is deletable. If the week-2 probe shows the OCR output does not preserve capitalisation, or if the week-8 printed gate is missed, it is cut and the report says so.

## 2. Commands

```bash
pytest tests/test_candidates.py tests/test_handwriting.py -q
python -m smriti.candidates --probe samples/handwritten/     # one-afternoon feasibility probe
python -m smriti.candidates --document <id> --top 3
npm --prefix web run test -- FieldReview
```

The probe is a prerequisite, not a test: it prints OCR text for 10 handwritten drug lines and the top-3 candidates for each, so the decision to build is made on evidence.

## 3. Structure

```
smriti/
  handwriting.py   line/field segmentation from detector output; never recognises
  candidates.py    ranking: patient history × doctor letterhead × lexicon
data/brand_lexicon.csv          shared with medications
web/src/components/FieldReview.jsx   crop, candidates, caret, add-box
```

Ranking, in order of weight:

| Source | Weight | Why |
|---|---|---|
| This patient's medication history | 3 | after prescription 2, the candidate set is ~10, not 5 000 |
| This doctor's letterhead | 2 | one prescriber writes the same 8 drugs for years |
| Global lexicon | 1 | fallback for a first prescription |

Score = `fuzzy(ocr_text, brand) × phonetic(ocr_text, brand) × weight`, with a phonetic normalisation for Indian brand spellings (`ph→f`, doubled consonants collapsed). `rapidfuzz` only; no model, no training, no GPU.

## 4. Code style

- `CandidateList` always has 0–3 entries and never a `selected` index. There is no default.
- If `score[0] − score[1] < margin`, the list is empty and the UI shows a search box. Abstention is a valid output (`FR-HWR-04`).
- Every field carries `bbox` in the dashboard's normalised coordinate system, so `SourceOverlay` works unchanged.
- One audit row per human action: `{field_id, action ∈ accept|correct|reject|add, model_top1, human_value, ms_to_verify}`.
- No free-text transcription of a whole page. Field by field, or nothing.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_rank_prefers_patient_history` | weighting works |
| Unit | `test_abstains_on_close_scores` | no forced guess |
| Unit | `test_no_default_selection` — component snapshot | no preselect |
| Unit | `test_every_field_is_review` | SI-01 |
| Unit | `test_no_numeric_lab_candidates_from_handwriting` | SI-02 |
| Study | 25 handwritten prescriptions, 2 annotators | **top-3 ≥ 0.85** |
| Study | same session | **taps ≤ 9, time ≤ 50 s, accepted-unchanged ≥ 0.60** |
| Vigilance | 10 % of fields get a deliberately wrong top-1, study mode only | **false-accept ≤ 5 %** |
| Report | boxes the human had to add | missed-field rate, reported not gated |

The vigilance test is the reason this module is research rather than UI. It measures whether the human gate is real.

## 6. Boundaries

- **Never** create a handwritten field in any state other than `review` (SI-01).
- **Never** emit a numeric laboratory value from a handwritten page (SI-02). Drugs, doses, frequencies, directives only.
- **Never** preselect a candidate or offer a single-click "accept all".
- **Never** auto-advance past a field without a recorded action.
- **Never** inject wrong suggestions outside an explicit study session on consented documents.
- **Never** show the crop without its surrounding line — a drug name alone is ambiguous.
- **Never** silently drop a field the detector missed; the add-box path exists so misses are visible and counted.

## 7. FR traceability

| Requirement | Acceptance test |
|---|---|
| FR-HWR-01 fields proposed with boxes, one at a time | `test_field_sequence` |
| FR-HWR-02 top-3 from weighted ranking | `test_rank_prefers_patient_history` |
| FR-HWR-03 human action required per field | `test_every_field_is_review` |
| FR-HWR-04 abstain on close scores | `test_abstains_on_close_scores` |
| FR-HWR-05 add-box for missed fields | `test_add_box_flow` |
| FR-HWR-06 vigilance measurement | `test_false_accept_rate` |

These six requirements do not exist in SRS v1.0 and must be added in v1.1; SI-01 and SI-02 already permit this design without change.

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Does PP-OCRv6 preserve capitalisation at ~0.49 CER? | Week 2, one afternoon | Downgrade to crop + search; delete ranking |
| 2 | Is a clinician available to label 25 pages? | Week 4 | Cut the module at week 8 regardless of probe results |
| 3 | Does the ranking beat a plain search box enough to justify itself? | Week 9 | Report the comparison; ship the search box |

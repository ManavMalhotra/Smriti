# Annotation Guide

Version 1.0 · Applies to the 40-document truth set and the 150-note directive set.
Every annotator reads this before labelling a single field.

---

## 1. Purpose

The truth set is the reference against which every reported number is computed. A sloppy truth set does not produce a wrong result — it produces a *meaningless* one, because the error is invisible.

Three rules override everything else:

1. **Never guess.** If you cannot read it, mark it `ambiguous`. An abstention is data.
2. **Record what is printed, not what is correct.** If the lab printed a wrong unit, the truth set records that wrong unit.
3. **Annotate blind.** Do not look at the system's output while labelling. Agreement with the model is not the goal.

## 2. Roles and sequence

| Step | Who | When |
|---|---|---|
| Annotation guide v1 | All three | Week 4 |
| 30-note double annotation | Two annotators, independently | Week 4 |
| Kappa computed | Third member | Week 4 |
| Kappa ≥ 0.70 | — | else revise guide, re-draw subset |
| Remaining 120 notes | One annotator | Weeks 5–11 |
| Handwritten stratum (25 pages) | Clinician + one member | Week 9, only if the gate is green |

If kappa is below 0.70, **annotation stops**. Continuing produces labels that measure disagreement rather than extraction quality (`FR-DIR-10`).

## 3. Units of annotation

### 3.1 Observations (printed lab reports)

One row per printed result line. Not per analyte, not per panel — per line, exactly as printed.

### 3.2 Directives (printed notes and prescriptions)

One row per instruction the doctor wrote, with its exact span. If a sentence contains two instructions, that is two rows.

### 3.3 Medications (printed prescriptions)

One row per prescribed item: brand, dose, form, frequency, duration.

### 3.4 Handwriting (separate stratum)

One row per field: drug name, dose, frequency, duration, or directive. **Never** a numeric laboratory value — that annotation is forbidden by SI-02 and cannot exist in the truth set.

## 4. File formats

### 4.1 `eval/truth_set.csv`

```
doc_id, page, analyte_id, value_text, value_num, unit_raw, ref_low, ref_high,
flag_printed, bbox_x0, bbox_y0, bbox_x1, bbox_y1, status, note
```

| Column | Rule |
|---|---|
| `doc_id` | Stable id, never a filename containing a patient name |
| `page` | 1-based |
| `analyte_id` | From `data/analyte_map.csv`; if no match, use `UNMAPPED` and fill `note` |
| `value_text` | Exactly as printed, including `<`, `>`, `*` |
| `value_num` | Numeric part only; blank for non-numeric results |
| `unit_raw` | Exactly as printed; blank if none |
| `ref_low`, `ref_high` | As printed; blank if none. Never compute |
| `flag_printed` | Verbatim (`H`, `L`, `*`, blank) |
| `bbox_*` | Tight box around the value only, normalised 0–1 |
| `status` | `ok` \| `ambiguous` \| `not_a_result` |
| `note` | Required when `status != ok` |

Boxes are checked by eye against rendering. Tolerance ±0.01 on each coordinate.

### 4.2 `eval/annotations/directives.csv`

```
doc_id, span_text, span_start, span_end, action_type, timing_type,
time_value, time_unit, anchor_event, condition_text, target, note
```

`span_start` and `span_end` index into the document's plain text, and `text[span_start:span_end] == span_text` must hold. This is asserted by a test; a mismatch is a hard failure.

## 5. Decision rules — observations

1. **Multi-line results.** If a value and its unit are on separate lines, one row. If a value applies to a group header ("Differential Count"), it is not a result line on its own.
2. **Ranges printed as `13.0 - 17.0`.** `ref_low=13.0`, `ref_high=17.0`. A one-sided range (`< 200`) records `ref_high=200` and leaves `ref_low` blank.
3. **Qualitative results** (`Negative`, `Trace`, `Reactive`). `value_text` filled, `value_num` blank, `status=ok`.
4. **Two values on one line** (`Hb 13.2 / Hct 40.1`). Two rows.
5. **Duplicate analytes** (glucose appears twice with different timing). Two rows, with the timing recorded in `note` until the mapping supports it.
6. **Handwritten corrections on a printed report.** Ignore handwriting entirely; annotate the printed value. If the handwriting replaces the printed value, `status=ambiguous`.
7. **Strikethrough.** `status=ambiguous`, note the reason.
8. **Illegible.** `status=ambiguous`. Never infer from clinical plausibility — that is the system's job to get wrong, not the annotator's.

## 6. Decision rules — directives

### 6.1 What counts as a directive

An instruction to do something at a future time, or on a condition, or as needed. It must have an action.

| Text | Directive? | Why |
|---|---|---|
| "R/V after 2 weeks" | Yes | Action + relative time |
| "Review on 15/11/2026" | Yes | Action + absolute time |
| "Repeat KFT after stopping Atorvastatin" | Yes | Action + condition |
| "SOS for pain" | Yes | PRN |
| "Continue same treatment" | No | No timing, no new action |
| "Take rest" | No | Advice, not follow-up |
| "If fever, come immediately" | Yes | Conditional |
| "Reports attached" | No | Not an instruction |

When in doubt: if a reasonable doctor would expect the patient to do something later, it is a directive. If two annotators disagree, that is exactly what the kappa step is for.

### 6.2 Fields

| Field | Values | Note |
|---|---|---|
| `action_type` | `review` \| `test` \| `medication_change` \| `imaging` \| `admission` \| `other` | One per row |
| `timing_type` | `relative` \| `absolute` \| `conditional` \| `prn` | Four only |
| `time_value` | Integer | Blank for conditional and prn |
| `time_unit` | `day` \| `week` \| `month` \| `year` | Blank when no interval |
| `anchor_event` | `collection_date` \| `doc_date` \| `unknown` | Which date the interval counts from |
| `condition_text` | Exact words | Conditional only |
| `target` | What is to be done | `review`, `KFT`, `MRI lumbar spine`, etc. |

### 6.3 Anchoring

`anchor_event` is `collection_date` if the document prints one, else `doc_date`, else `unknown`.

**Never** use today's date. **Never** invent an anchor. If the document has no date at all, `anchor_event=unknown` and the directive has no due date.

### 6.4 Worked examples

| Source text | timing_type | time_value | time_unit | anchor_event | condition_text | target |
|---|---|---|---|---|---|---|
| "R/V after 2 weeks" | relative | 2 | week | collection_date | — | review |
| "Review on 15/11/2026" | absolute | — | — | — | — | review |
| "Repeat KFT after stopping Atorvastatin" | conditional | — | — | — | after stopping Atorvastatin | KFT |
| "SOS for pain" | prn | — | — | — | — | analgesia |
| "Come back if fever persists beyond 3 days" | conditional | 3 | day | — | fever persists | review |

## 7. Decision rules — medications

1. Record brand as written. Do not expand to a salt unless the prescription itself does.
2. Frequency as written (`1-0-1`, `BD`, `once daily`), plus the normalised form if unambiguous.
3. Duration as written (`× 5 days`, `30 days`). If absent, leave blank — do not assume.
4. Do not merge two strengths of the same brand into one row.
5. A patient-reported stop is **not** part of the printed annotation; it is recorded separately through the app.

## 8. Handwriting stratum

- Annotate drug name, dose, frequency, duration, and directives only.
- **No numeric laboratory values.** If a handwritten page contains a number next to an analyte, that page is excluded from the stratum and the reason is recorded.
- Mark illegible fields `ambiguous`. The whole point of the stratum is to measure what a human can and cannot read.
- Two annotators on all 25 pages. Report agreement per field type, not only overall.

## 9. Ambiguity protocol

`ambiguous` is a valid, expected, and useful label. It is not a failure.

Use it when:

- the text is unreadable at 200 % zoom;
- the printed value contradicts the printed unit in a way you cannot resolve by reading;
- two plausible readings exist and nothing on the page decides between them.

Do **not** use it when the value is merely unusual. Unusual is what the safety gates are for; the truth set records what is printed.

## 10. Kappa and adjudication

1. Both annotators label the same 30 notes independently.
2. Compute Cohen's kappa per field: `timing_type`, `time_value`, `action_type`, `target`.
3. If any field is below 0.70, revise this guide, re-draw 30 notes, recompute.
4. Disagreements on the adjudicated set are resolved by discussion, and the resolution rule is added to this guide.
5. The final kappa is reported per stratum (printed, handwritten), never pooled.

## 11. Quality checks before freeze

- [ ] `text[span_start:span_end] == span_text` for all directive rows
- [ ] Every `value_num` parses as a decimal
- [ ] Every `ref_low < ref_high` where both present
- [ ] Every `bbox` within 0–1 and non-degenerate
- [ ] No `doc_id` contains a patient name
- [ ] Row count matches the document count in the manifest
- [ ] Truth set hashed and versioned; hash recorded in the report
- [ ] Random 20-row audit by the third member, errors corrected

## 12. Common mistakes

| Mistake | Consequence |
|---|---|
| Copying the reference range from a different row | Field F1 looks better than reality |
| Normalising a unit while annotating | The system is graded against a value no lab printed |
| Skipping ambiguous rows | Accuracy is computed only on easy cases |
| Annotating after seeing model output | Confirmation bias, unmeasurable |
| Using today's date as an anchor | Directly violates SI-10, corrupts every timing metric |
| Pooling printed and handwritten strata | Hides the one result the handwriting work exists to produce |

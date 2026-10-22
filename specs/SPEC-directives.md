# SPEC-directives

| | |
|---|---|
| Module | `directives` |
| Status | Draft for review |
| Depends on | `normalisation` |
| SRS | FR-DIR-01…11, SI-06, SI-08, SI-10, OR-05 |
| Files | `smriti/directives.py`, `api/routers/patients.py` (directive endpoints) |

## 1. Objective

Extract what the doctor told the patient to do next, with the exact sentence it came from, and compute a due date only where the document supports one.

This is the project's headline contribution, and the failure it must not commit is subtle: producing a reminder the doctor never wrote. Every rule below exists to make a fabricated date structurally impossible rather than unlikely.

## 2. Commands

```bash
pytest tests/test_directives.py -q
python -m smriti.directives --document <id> --explain
python -m smriti.directives --eval --truth eval/truth_set.csv   # span F1, timing, date exact
python -m smriti.directives --kappa --annotations data/ann/      # blocks if < 0.70
```

## 3. Structure

```
smriti/directives.py
tests/fixtures/directives/  200 span cases, each with anchor, class, expected due date
```

Extraction is rules-first — a small grammar over `action_type × timing_type` — with the cloud path used only for spans the grammar cannot parse, and only through `egress`. Rules keep the span exact; a model that paraphrases destroys the citation (SI-07).

## 4. Code style

- `Directive` is a frozen dataclass with all fields from FR-DIR-01, including the exact `span_text` and its offsets into the source text.
- `timing_type ∈ {relative, absolute, conditional, prn}` only.
- `anchor_event ∈ {collection_date, doc_date, unknown}`. There is no `today` member — the enum cannot express it (SI-10).
- Date arithmetic uses `datetime.date` and integer `time_value`; a relative directive is `anchor + timedelta`. No date library, no NLP date parser.
- An unresolvable anchor yields `state='unknown_date'` and a `due_date` of `None`. Never a sentinel, never an estimate.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_anchor_priority` — collection present, absent, both absent | FR-DIR-03 |
| Unit | `test_enum_has_no_today` | SI-10 structurally |
| Unit | `test_past_absolute_rejected` — clock frozen | FR-DIR-04 |
| Unit | `test_past_relative_not_notified` | FR-DIR-08, SI-08 |
| Unit | `test_conditional_no_due_date` | FR-DIR-05 |
| Unit | `test_prn_no_date` | FR-DIR-06 |
| Unit | `test_supersession_newest_per_action` | FR-DIR-07 |
| Unit | `test_span_offsets_roundtrip` — `text[start:end] == span_text` | SI-07 |
| Truth set | 150 printed notes | **span F1 ≥ 0.75, timing ≥ 0.80, date exact ≥ 0.70** |
| Annotation | 30 double-annotated notes, before remainder | **kappa ≥ 0.70**, blocks further annotation |

Kappa is run first and gates the rest of the work (FR-DIR-10). If two annotators cannot agree on what counts as a directive, the metric downstream measures disagreement, not extraction quality.

## 6. Boundaries

- **Never** anchor on today, under any code path (SI-10).
- **Never** compute a date for a conditional or PRN directive (FR-DIR-05, FR-DIR-06).
- **Never** schedule a reminder for a date already past at extraction time (SI-08, FR-DIR-08).
- **Never** paraphrase a directive. The rendered sentence is the source sentence — a rewrite is a new clinical claim and the system is not entitled to make one.
- **Never** compute guideline intervals ("next screening in 1 year"). Out of scope; SI-06 exists because this module is the one most likely to drift into it.
- **Never** let one directive supersede another of a different `action_type` (FR-DIR-07).
- **Never** display a directive without its document (FR-DIR-09).

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-DIR-01 | `test_all_fields_populated` |
| FR-DIR-02 | `test_due_date_only_for_absolute_and_relative` |
| FR-DIR-03 | `test_anchor_priority` |
| FR-DIR-04 | `test_past_absolute_rejected` |
| FR-DIR-05 | `test_conditional_open_trigger` |
| FR-DIR-06 | `test_prn_no_date` |
| FR-DIR-07 | `test_supersession` |
| FR-DIR-08 | `test_no_past_notification` |
| FR-DIR-09 | `test_source_sentence_rendered` |
| FR-DIR-10 | `test_kappa_blocks_annotation` |
| FR-DIR-11 | `test_metrics_split_by_capture_type` |
| SI-06 | `test_no_computed_guideline_dates` |
| SI-07 | `test_span_offsets_roundtrip` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-DIR-02 | Add: a relative directive whose computed due date is in the past is stored as `unknown_date`, not scheduled. |
| FR-DIR-10 | Specify that the 30-note kappa subset is drawn before the remaining 120, not after. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Does the grammar cover Indian prescription phrasing ("review after 2 wks", "R/V 15 days", "f/u in 1 mth")? | Week 5, on 50 notes | Add patterns from the corpus; report per-pattern accuracy |
| 2 | Inter-annotator kappa on directives — will it reach 0.70? | Week 4 | If below, narrow the definition of directive and re-draw the subset; report the narrowed definition |
| 3 | Handwritten directives: are they in the 25 handwritten pages? | Week 9, only if the track survives | Report printed-stratum metrics only (already permitted by FR-DIR-11) |

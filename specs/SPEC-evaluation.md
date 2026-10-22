# SPEC-evaluation

| | |
|---|---|
| Module | `evaluation` |
| Status | Draft for review |
| Depends on | all (consumes artifacts) |
| SRS | FR-EVL-01…08, §4.1 thresholds, FR-SAF-05, FR-DIR-10 |
| Files | `eval/run_eval.py`, `eval/metrics.py`, `eval/truth_set.csv`, `eval/annotations/`, `tests/test_eval_smoke.py` |

## 1. Objective

Turn a folder of documents into the numbers in the report — reproducibly, offline, from frozen inputs.

The rule that makes the results honest: **thresholds are written before the run and are not edited afterwards.** §4.1 of the SRS is the pre-registration. If a number misses, the report says it missed. Editing a threshold after seeing the result converts a measurement into marketing.

## 2. Commands

```bash
python eval/run_eval.py                       # full run, cached, offline
python eval/run_eval.py --stratum handwritten
python eval/run_eval.py --coverage 100 90 80  # risk–coverage curve
python eval/run_eval.py --verify-determinism  # run twice, compare output hash
pytest tests/test_eval_smoke.py -q
```

CI runs the smoke test only. The full harness runs offline, never on a pull request.

## 3. Structure

```
eval/
  run_eval.py       orchestration, one function per reported table
  metrics.py        F1, CER, exact match, bootstrap CI, risk–coverage
  truth_set.csv     document_id, analyte, value, unit, ref_low, ref_high, flag, page, bbox
  annotations/      directive spans, 150 notes, double-annotated subset of 30
  cache/            every cloud response, keyed by payload hash
  out/report.json   machine-readable results
  out/*.png         figures used in the report
```

Truth set is immutable once frozen. Any correction is a new version with a changelog line and a hash; silent edits are forbidden.

## 4. Code style

- One function per reported table, named after the table in the report. No shared "evaluate everything" monolith.
- Every metric returns `{value, ci_low, ci_high, n}`. A number without a sample size is not a result.
- Bootstrap: 1000 resamples, fixed seed from config, CIs reported at 95 %. A different seed must not change a conclusion by more than the CI width.
- No network. If a cache entry is missing the run fails loudly rather than re-calling a model (FR-EVL-06).
- Output is `report.json` plus figures; the prose in the report is filled from these, never typed by hand.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | `test_f1_known_answer` on a hand-computed confusion matrix | metric implementation |
| Unit | `test_bootstrap_deterministic` — same seed, same CI | FR-EVL-03 |
| Unit | `test_split_by_template_not_sample` | FR-EVL-04 |
| Smoke | `test_eval_runs_on_5_doc_fixture` offline | harness integrity |
| Determinism | run twice, byte-identical `report.json` | FR-EVL-01 |
| Invariant | `test_no_handwritten_auto_in_results` | SI-01, FR-EVL-07 |
| Guard | `test_thresholds_match_srs` — reads §4.1 from the SRS source | thresholds cannot drift |

That last guard is the important one: it makes editing a threshold an SRS change, visible in review, not a quiet edit in a Python file.

## 6. Reported metrics

| Metric | Stratum | Threshold |
|---|---|---|
| Field F1 | printed | ≥ 0.90 |
| CER | printed | ≤ 0.05 |
| End-to-end (value + field + unit) | printed | ≥ 0.85 |
| Material errors | printed | ≤ 2 % |
| Risk–coverage gain at 10 % deferral | printed | ≥ 5 points |
| Normalisation accuracy | printed | ≥ 0.95 |
| Gate recall / false quarantine | injected | ≥ 0.80 / ≤ 0.10 |
| Directive span F1 | printed | ≥ 0.75 |
| Timing accuracy | printed | ≥ 0.80 |
| Date exact match | printed | ≥ 0.70 |
| Cohen's kappa | 30 notes | ≥ 0.70 |
| Handwritten: CER, span F1, abstention, accepted unchanged, s/note | handwritten | report only, 100 % human-confirmed |
| Review-queue shrink with `egress` | printed | ≥ 30 % or module deleted |

## 7. Boundaries

- **Never** train on, tune against, or select a threshold using the truth set.
- **Never** report a mean without its CI and `n`.
- **Never** merge strata — printed and handwritten are always separate rows.
- **Never** split synthetic data by sample; split by template (FR-EVL-04).
- **Never** edit `truth_set.csv` after freeze without a version bump and a changelog entry.
- **Never** call the network during a run (FR-EVL-06).
- **Never** put a patient identifier in any artifact under `eval/out/` (OR-04).

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Are 40 documents enough for a ±5 point CI? | Week 6 | Report the CI width as a limitation rather than hiding it |
| 2 | Does the synthetic–real gap need its own table? | Week 12 | One paragraph plus a per-template split |
| 3 | Do the 25 handwritten pages have a second annotator? | Week 9 | Single annotator; report inter-rater as unavailable, not as agreement |

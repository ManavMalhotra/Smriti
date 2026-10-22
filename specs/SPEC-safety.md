# SPEC-safety

| | |
|---|---|
| Module | `safety` |
| Status | Draft for review |
| Depends on | `extraction`, `normalisation` |
| SRS | FR-SAF-01…05, SI-03, DR-04 |
| Files | `smriti/checks.py`, `data/bounds.csv`, `data/swing.csv` |

## 1. Objective

Reject impossible values before they can reach a chart. This is the only module whose job is to say *no* — and its failure mode is asymmetric: a false accept puts a wrong number in front of a patient, a false reject costs one review tap. Every design choice here favours rejection.

Two layers, deliberately separate:

1. **Arithmetic gates** — the value must be internally consistent with other values on the same report (FR-SAF-01).
2. **Plausibility bounds** — the value must be biologically possible for a human (FR-SAF-02).
3. **Swing rules** — a value that jumps far from the last accepted value is suspicious, not necessarily wrong (FR-SAF-03), so it routes to review rather than rejection.

## 2. Commands

```bash
pytest tests/test_checks.py -q
python -m smriti.checks --document <id>            # run gates, print verdicts
python -m smriti.checks --explain <observation_id> # which gate fired, inputs, tolerance
python -m smriti.checks --bounds --validate        # bounds table sanity: low < high
```

## 3. Structure

```
smriti/checks.py
data/bounds.csv    analyte_id, hard_low, hard_high, source_citation
data/swing.csv     analyte_id, max_relative_change, max_absolute_change
```

Every bound carries a citation. An uncited bound is not allowed into the file — a plausibility limit that cannot be traced is a guess with authority.

The five arithmetic gates are fixed by FR-SAF-01:

| Gate | Check | Tolerance |
|---|---|---|
| G1 | DLC sum | 100 ± 2 % |
| G2 | Friedewald LDL = TC − HDL − TG/5 | only when TG ≤ 400 mg/dL |
| G3 | Total bilirubin = direct + indirect | ± 0.2 mg/dL |
| G4 | MCV = Hct / RBC × 10 | ± 1 fL |
| G5 | ANC = WBC × neutrophil % / 100 | ± 0.1 ×10³/µL |

A gate that cannot run because an input is missing has outcome `skipped`, never `pass`.

## 4. Code style

- Gates are pure functions with signature `(Observation, Context) -> Verdict`. `Verdict` is `pass | review | reject`, plus `gate_id`, `inputs`, `tolerance` (FR-SAF-04).
- Gate order is fixed and short-circuits on `reject`; `review` does not stop later gates.
- No gate raises. A malformed input is `skipped` with a reason.
- Bounds and thresholds are loaded from CSV at startup, validated once, and are never hard-coded.
- `Context` contains only observations from the *same document* plus the last accepted value per analyte. No population statistics, no guideline logic.

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Unit | one test per gate, with passing, failing, and missing-input cases | FR-SAF-01 |
| Unit | `test_bounds_table_monotonic` — every `hard_low < hard_high` | table integrity |
| Unit | `test_skip_is_not_pass` | cautious default |
| Injected | 200 corruptions across 30 analytes (10× , 100×, unit swap, digit drop, digit add) | **recall ≥ 0.80** |
| Truth set | clean values through the same pipeline | **false quarantine ≤ 0.10** |
| Invariant | `test_rejected_never_charted` | SI-03 |
| Invariant | `test_rejected_retained_for_eval` | DR-04 |

The SRS threshold is 0.80 recall / 0.10 false quarantine. Both are reported per gate, not only in aggregate — a gate that never fires is either unnecessary or broken, and the report must show which.

## 6. Boundaries

- **Never** chart, average, or summarise a `rejected` observation (SI-03). It stays in the database, visible only to the review UI and the evaluation harness.
- **Never** silently drop a rejection — the dashboard must show that something was excluded, with the reason.
- **Never** run a gate without an analyte-specific bound; a generic "between 0 and 1000" check is not a gate.
- **Never** treat a missing input as a pass.
- **Never** use population reference ranges as plausibility bounds. The printed range is the lab's; the bounds are biology's. They are different tables and must not be confused.
- **Never** reject on a swing rule — swing routes to `review`, because a real change and an OCR error look identical at this stage.

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-SAF-01 | `test_g1_dlc_sum` … `test_g5_anc` |
| FR-SAF-02 | `test_hard_bounds_reject`, `test_bounds_are_cited` |
| FR-SAF-03 | `test_swing_routes_to_review` |
| FR-SAF-04 | `test_verdict_records_gate_and_inputs` |
| FR-SAF-05 | `test_injected_corruption_recall` (harness) |
| SI-03 | `test_rejected_never_charted` |
| DR-04 | `test_rejected_retained` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-SAF-01 | Add the explicit tolerance column above; the v1.0 text names the checks but not the tolerances. |
| FR-SAF-02 | Require a citation on every bound. |
| new FR-SAF-06 | Missing gate input shall be `skipped`, never `pass`. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Where do the biological bounds come from? | Week 4 | Standard adult reference texts, cited per row; paediatrics out of scope and stated |
| 2 | Do swing thresholds differ enough per analyte to justify a table? | Week 7 | One global relative threshold plus two exceptions, documented |
| 3 | Can G2 run if TG > 400? | Already answered: no | Skip with reason; never estimate LDL from a non-valid Friedewald |

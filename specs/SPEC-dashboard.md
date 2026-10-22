# SPEC-dashboard

| | |
|---|---|
| Module | `dashboard` |
| Status | Draft for review |
| Depends on | `normalisation`, `safety`, `medications`, `directives` |
| SRS | FR-TIM-01…08, FR-SHR-01…05, FR-REV-01…05, CON-08, NFR-03, NFR-09, NFR-10, NFR-12, SI-07 |
| Files | `smriti/summary.py`, `smriti/share.py`, `api/routers/patients.py`, `api/routers/share.py`, `web/src/` |

## 1. Objective

One page that answers "what changed since last visit" in under a minute, where every rendered value can be traced to a box on a page by clicking it.

Two audiences, one payload: the patient needs orientation, the clinician needs evidence density. Both get the same four zones in the same order, differing only in what is expanded by default.

## 2. Commands

```bash
npm --prefix web run dev            # Vite dev server, proxies /api
npm --prefix web run build          # output mounted by FastAPI at /
npm --prefix web run test           # component + a11y tests
pytest tests/test_summary.py tests/test_share.py -q
python -m smriti.summary --patient <id> --out .cache/summary.json
```

## 3. Structure

```
smriti/
  summary.py      the aggregate payload builder
  share.py        token, PIN, expiry, lockout, audit
api/routers/
  patients.py     /summary, /observations, /directives
  share.py        create, resolve, revoke
web/src/
  App.jsx
  api/client.js
  components/Header.jsx, Problems.jsx, Medications.jsx, Results.jsx,
             Pending.jsx, Documents.jsx, CoverageStrip.jsx, SourceOverlay.jsx
  pages/Dashboard.jsx, SharedView.jsx
```

`SourceOverlay` is shared with `handwriting-assist`. It consumes the same normalised box, so there is one coordinate system and one review surface, not two (CON-07).

## 4. Code style

- **JavaScript, not TypeScript** (CON-06). No state library, no UI kit, no CSS-in-JS.
- The payload shape is defined once, in Pydantic, and frozen as `web/src/fixtures/summary.json` in week 2. The UI is built against the fixture before the backend exists (NFR-12).
- No component fetches more than the summary; deep data is lazy-loaded per analyte on click (CON-08).
- Every numeric render goes through one `<Value>` component — the only place that formats a value, a unit, and a flag. Provenance cannot be forgotten if there is one door.
- Charts are Recharts with an accessible table rendered alongside (NFR-10).

## 5. Testing strategy

| Level | Test | Proves |
|---|---|---|
| Contract | `test_summary_matches_fixture` — Pydantic-validated against `summary.json` | NFR-12 |
| Unit | `test_four_zones_fixed_order` | FR-TIM-03 |
| Unit | `test_coverage_one_cell_per_quarter`, zero-document quarters distinguished | FR-TIM-04 |
| Unit | `test_gap_over_six_months_is_dotted` — computes segment style from dates | FR-TIM-05 |
| Unit | `test_printed_flag_verbatim` — no computed abnormal judgement | FR-TIM-07 |
| E2E | click value → overlay opens at the right box, page and document id match | FR-TIM-06 |
| E2E | keyboard-only traversal of the review queue | FR-REV-04, NFR-09 |
| Perf | 40 documents, cold cache | **payload ≤ 2 s** (NFR-03) |
| Security | 6 PIN guesses → locked; expired token → 401; revoked → 401; audit rows present | FR-SHR-01…05 |
| Invariant | every rendered value has a source path | SI-07 |

## 6. Boundaries

- **Never** render a value without a path to its document, page, and box (SI-07). There is no "summary-only" number.
- **Never** chart a `rejected` observation (SI-03). Show an exclusion notice instead.
- **Never** merge medication states (SI-09). Three groups, visibly labelled.
- **Never** compute an abnormal flag; display the laboratory's printed flag verbatim (FR-TIM-07).
- **Never** interpret a gap — state its length, not its meaning (FR-TIM-08).
- **Never** show raw OCR text to the patient. Clinician mode may show it with the source.
- **Never** make the shared view writable, and never omit the intended-use statement from it (FR-SHR-05).
- **Never** log a share PIN or token (NFR-07).

## 7. FR traceability

| SRS | Acceptance test |
|---|---|
| FR-TIM-01 | `test_summary_payload_complete` |
| FR-TIM-02 | `test_abnormal_first_then_recent`, `test_max_five_points` |
| FR-TIM-03 | `test_zone_order` |
| FR-TIM-04 | `test_coverage_strip` |
| FR-TIM-05 | `test_dotted_gap` |
| FR-TIM-06 | `test_overlay_click` |
| FR-TIM-07 | `test_flag_verbatim` |
| FR-TIM-08 | `test_gap_language` |
| FR-SHR-01 | `test_token_pin_expiry` |
| FR-SHR-02 | `test_revoke_and_reject` |
| FR-SHR-03 | `test_lockout_after_five` |
| FR-SHR-04 | `test_share_audit_rows` |
| FR-SHR-05 | `test_shared_view_readonly_with_disclaimer` |
| FR-REV-01…05 | `tests/test_review.py` |

### SRS v1.1 deltas

| ID | Change |
|---|---|
| FR-TIM-01 | Name the seven payload keys explicitly and freeze them in week 2. |
| new FR-TIM-09 | Rejected observations shall be surfaced as an exclusion notice, not hidden. |
| FR-SHR-01 | Add: the PIN is stored hashed, never in plaintext. |

## 8. Open questions

| # | Question | Time-box | Fallback |
|---|---|---|---|
| 1 | Five points per analyte — enough for a clinician? | Week 8, on 10 real timelines | Keep five in summary, full series behind the click |
| 2 | Does the four-zone order survive at 1366×768? | Week 8 | Collapse zones to accordions below 1100 px |
| 3 | Clinician mode: what expands by default? | Week 12 usability | Ship patient mode only if time is short; this is a cut-list item |

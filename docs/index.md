# Documentation Index

Reading order and authority. If two documents disagree, the one higher in this table wins.

| # | Document | Owns | Status |
|---|---|---|---|
| 1 | `docs/SRS.md` v1.1 | All requirements: FR, NFR, SI, OR, CON, DR. Thresholds. | **Frozen** |
| 2 | `specs/CAPABILITY-MAP.md` | Module boundaries, dependencies, gates | **Frozen** |
| 3 | `specs/SPEC-*.md` (10 files) | How each module is built and tested | **Frozen** |
| 4 | `tasks/plan.md` | Technical approach, configuration, deployment | Draft |
| 5 | `tasks/todo.md` | Ordered work, week by week, with gates | Draft |
| 6 | `docs/architecture.md` | Runtime structure, trust boundaries | **Done** |
| 7 | `docs/data-model.md` | Schema, state machines, indexes | **Done** |
| 8 | `docs/API.md` | The 15 endpoints and the frozen summary payload | **Done** |
| 9 | `docs/evaluation.md` | Truth set, metrics, pre-registered thresholds | Pending |
| 10 | `docs/test-plan.md` | Verification matrix, CI gates | Pending |
| 11 | `docs/annotation-guide.md` | How to label documents, kappa protocol | **Done** |
| 12 | `docs/ethics-consent.md` | Ethics submission, consent, data handling | **Done** |
| 13 | `docs/synopsis.md` | One-page project synopsis | **Done** |
| 14 | `docs/project-plan.md` | Timeline, roles, risks | Pending |
| 15 | `docs/adr.md` | Architecture decision records | Pending |
| 16 | `docs/demo-viva.md` | Demo script, likely questions, answers | Pending |
| 17 | `docs/report-outline.md` | Results chapter structure, figure list | Pending |

## Authority rule

> The SRS owns **what** and **how much**. Specs own **how**. Tasks own **when**.
> On conflict, the SRS wins and the lower document is corrected.

A threshold lives in exactly one place: SRS §4.1. A copy of it anywhere else is a bug waiting to happen, which is why `eval/run_eval.py` reads thresholds from the SRS source and fails if they drift.

## Change control

- Requirements change: SRS version bump, agreed by all three members.
- Module boundary change: capability map revision, then the affected spec.
- Threshold change after a result is known: not permitted. See SRS §5.4.5.

## For the examiner

The shortest path to understanding the project:

1. `docs/synopsis.md` — what and why, one page
2. `docs/SRS.md` §1.2–1.3 and §4.1 — scope, limits, and the numbers being claimed
3. `docs/evaluation.md` — how those numbers are produced
4. `docs/adr.md` — why the unusual choices were made

The shortest path to judging the engineering:

1. `specs/CAPABILITY-MAP.md` — the system in one table
2. `specs/SPEC-egress.md` — the trust boundary
3. `specs/SPEC-safety.md` — what the system refuses to do

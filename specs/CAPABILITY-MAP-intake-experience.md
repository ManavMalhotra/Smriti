# Capability Map: Intake experience

Status: scope, specs, migration, plan, and checklist approved by the user on 2026-11-04. Implemented and locally verified on 2026-11-05; results and remaining production-verification obligations are in `tasks/todo.md`.
Requirements authority: `docs/SRS.md`; extends existing intake and account capabilities.

| Module id | Responsibility | Depends on | Spec |
|---|---|---|---|
| `registration` | Existing registration validation, useful errors, successful session | Existing account API | [SPEC-registration.md](SPEC-registration.md) |
| `processing` | Truthful job telemetry, concise activity, expandable colorful logs | Existing intake and worker | [SPEC-processing.md](SPEC-processing.md) |
| `bulk-upload` | Sequential uploads, independent file states and review links | `processing`, existing authenticated upload API | [SPEC-bulk-upload.md](SPEC-bulk-upload.md) |

Build order: registration → processing → bulk-upload. This is an order, not a new dependency between accounts and processing.

## Shared assumptions and boundaries

- Existing React/JavaScript, CSS tokens, FastAPI, SQLite, and one worker stay in place. Libraries are permitted by the user, but none is needed for status colors and expandable event lists.
- Existing account data, medical records, review decisions, and uncommitted work are preserved. No reset, automatic reprocessing, or live database migration in this specification phase.
- Events describe the engine actually used. RapidOCR, a PDF text layer, or cached OCR must never be relabeled PaddleOCR-VL.
- Real Qwen + PaddleOCR-VL verification remains a separate unfinished obligation; this UI change does not establish model correctness.
- No WebSocket service, general-purpose log platform, remote telemetry, resumable upload infrastructure, or new medical interpretation.

## Evidence before implementation

- An isolated synthetic registration succeeds with HTTP 201 and a working session. Short usernames, usernames with spaces, and short passwords produce HTTP 400 with a field but only “Malformed request.” The frontend uses `noValidate` and checks only nonempty credentials.
- Five existing backend account/validation tests and twelve Auth/Intake frontend tests passed on 2026-11-04. These tests do not cover the proposed new behavior.
- The worker records coarse stages, but `GET /api/jobs/{id}` returns only state, page, total, and error. Its page count is OCR progress, not overall processing progress.

# Smriti — Project Understanding Report

**Reviewed:** 12 November 2026. **Snapshot:** current working tree, based on commit `ffcd15c`, including existing modified and untracked files.

**Method:** static source inspection, caller tracing, schema/configuration inspection, and test/specification inventory. This is a project-understanding report, not a completed security audit or clinical validation.

> Smriti turns disconnected medical documents into a longitudinal patient record. Its contribution is source traceability and human review, not simply OCR.

**Navigation:** [Purpose](#1-purpose-and-actual-scope) · [Technology](#2-technology-and-dependencies) · [Architecture](#3-architecture) · [Program flows](#4-frontend-to-backend-program-flows) · [Models](#5-models-and-extraction-pipeline) · [Data](#6-data-model-and-persistence) · [Principles](#7-requirements-philosophy-and-principles) · [Design](#8-interface-design-ux-dx-and-ax) · [Tests](#9-testing-and-evaluation) · [Every file](#10-file-by-file-reference) · [Gaps](#11-important-gaps-and-contradictions) · [Reading guide](#12-reading-guide-and-inspection-limits)

## 1. Purpose and actual scope

The intended audience is an Indian patient organizing existing laboratory reports, prescriptions, pharmacy slips, and medical history. The original research plan is a 16-week, three-member project measuring correctness on 40 printed documents and 150 annotated directive notes.

The working application has local patient accounts, uploads, background processing, document review, laboratory trends, logical reports, a document library, processing history, and optional consented cloud extraction. Imaging/discharge prose is supported beyond the original printed-lab scope.

**Research prototype: not a medical device, not for clinical use, and not a diagnosis or treatment recommendation system.** Implemented functionality does not establish accuracy or hardware suitability.

This report describes the code actually present. Requirements and older status documents sometimes describe a different system; those conflicts are identified below.

## 2. Technology and dependencies

| Area | Technology | Role |
|---|---|---|
| Browser | React 19, JavaScript/JSX | Components and local hook state; no TypeScript, Redux, or router package. |
| Frontend tooling | Vite 8, Tailwind 4 | Development proxy, production bundling, CSS integration. Most styling is custom CSS. |
| Charts | Recharts 3 | Laboratory trends; lazy-loaded when multiple readings exist. |
| HTTP | FastAPI, Uvicorn, Starlette | Same-origin API and built frontend, served on localhost. |
| Validation | Pydantic v2 | Strict request/response models and cloud-output validation. |
| Persistence | SQLAlchemy Core, SQLite | Parameterized SQL, explicit transactions, WAL, migrations. Not an ORM entity layer. |
| Images/PDF | Pillow, OpenCV, NumPy, PyMuPDF | Decoding, rendering, quality measurement, normalization, masks, text-layer inspection. |
| CPU OCR | RapidOCR ONNX + PP-OCRv5 mobile weights | Local detection/recognition; optional PaddleOCR/PaddlePaddle fallback. |
| Local vision | llama.cpp `llama-server.exe`, GLM-OCR GGUF | CUDA-backed independent extraction in a disposable process. |
| Optional cloud | Google GenAI SDK, Gemini | Structured extraction from owner-approved masked JPEGs. |
| Supervision | Python multiprocessing/threading, ctypes, psutil | Exclusive coordinator, Windows Job Objects, resource guards and sampling. |
| Testing | pytest, Vitest, Testing Library, jsdom, jest-axe | Backend boundaries, frontend behavior, synthetic journeys, accessibility checks. |

`requirements.txt` pins FastAPI 0.161.0, Uvicorn 0.54.0, Pydantic 2.14.1, SQLAlchemy 2.1.6, python-multipart 0.0.32, HTTPX 0.28.1, pytest 8.4.2, psutil 7.2.2, NumPy 2.3.5, OpenCV-contrib 4.10.0.84, Pillow 13.0.0, PyMuPDF 2.0, PaddleOCR 3.7.0, PaddlePaddle 3.3.1, google-genai 3.0.0, and python-dotenv 1.2.4. Frontend versions use ranges; `web/package-lock.json` records resolved packages.

**Dependency caveats:** RapidOCR, ONNX Runtime, Hugging Face Hub and Requests are used directly but not explicitly listed in the main requirements. Their availability may depend on the existing environment or transitive packages. Weights, the English recognition dictionary, CUDA/driver support and llama.cpp binaries are external runtime prerequisites. `requirements-cloud.txt` also lists google-genai and RapidFuzz, despite google-genai already being in the main requirements. `uv.lock` contains only metadata, not a resolved dependency graph. Fresh installation was not verified.

The documented environment is Python 3.11, native Windows, and Node 20.19+ or 22.12+. Linux CI is not proof that the Windows-specific supervised runtime works on Linux.

## 3. Architecture

This is a **modular local application**, not microservices. One FastAPI service serves React and the API. One exclusive coordinator schedules work; expensive operations execute in owned child processes. There is no Celery, Redis, message broker, vector database, external authentication, or distributed scheduler.

```text
React: account / upload / queue / library / review / summary
                 │ fetch + same-origin cookie
FastAPI routers ─┼──────────────── SQLite account/clinical records
                 │                              ▲
       bounded multipart spool                  │ atomic clinical save
                 │                              │
Service → exclusive Coordinator → supervised stage processes
                                  ├─ inspect / prepare / validate
                                  ├─ PDF text layer or CPU OCR
                                  ├─ rules / prose / dates / reports
                                  ├─ local GLM-OCR independent read
                                  ├─ optional masked-image Gemini
                                  └─ cross-check / publish

Private sources + artifacts/candidate SQLite + durable checkpoints
Diagnostics → bounded private rotating JSONL and terminal sinks
```

Three storage categories matter: durable clinical records/sources; operational submissions/batches/progress/cleanup receipts; and intermediate medical data such as OCR artifacts, candidate SQLite and mask-review JPEGs. Intermediate medical data is not safe diagnostic logging.

The central safeguard separates **HTTP acceptance**, **complete source preparation**, and **clinical publication**. Receiving a file does not create fake document metadata; reading some pages does not publish a half-complete medical record.

Current configuration defaults include a 25 MiB file limit, 50 million pixels/page, two simultaneous spoolers, twenty raw-file slots, ten frozen submissions, twenty pages/window, 2 GiB active output accounting, a 1 GiB free-disk floor, 6 GiB owned-tree native-memory ceiling and 2 GiB available-RAM floor before local vision launch. Inspection/preparation/helper budgets default to 300 seconds; local vision requests to 240 seconds/page. These are provisional guards, not measured proof that the application fits an 8 GB laptop.

Diagnostics default to 10 MiB files, five backups, seven-day retention, 512 events per independent sink and a two-second shutdown budget. Process/device samples are observations, not absolute memory peaks or model-attributed VRAM guarantees.

## 4. Frontend-to-backend program flows

### Startup and accounts

`start.bat` delegates to `start.ps1`. The PowerShell launcher creates/reuses the Python environment, conditionally installs dependencies, builds React when needed, and starts `smriti.server`. That sanitized launcher runs Uvicorn against `smriti.main:app`; `main.py` calls `create_app()`.

`create_app()` validates storage placement, initializes/migrates SQLite, registers routers, and mounts `web/dist`. Its lifespan starts diagnostics and the processing service. Shutdown pauses admission and confirms coordinator/stage cleanup before disposing the database engine.

React `main.jsx` mounts `App.jsx`. App checks `/api/auth/me`; unauthenticated users see `Auth.jsx`. Register/login POSTs validate inputs, hash passwords with scrypt, create a hashed random session token, and issue an HttpOnly, SameSite=Strict cookie. Requests resolve that session and check patient/document ownership. There is no clinician/admin role implementation.

### Upload through publication

1. `Intake.jsx` selects multiple files, freezes shared metadata/consent options, and uploads **one file at a time** using `FormData` and `/api/documents`.
2. `documents.py` checks authentication, demo restrictions and service admission, then calls `http_intake.receive_upload()`.
3. `http_intake.py` parses a bounded multipart stream. `spool.py` reserves private capacity, writes bounded chunks, checks signatures/metadata, fsyncs, and hashes `patient_id + separator + file bytes` for same-owner deduplication.
4. Acceptance persists a `submissions` row and returns HTTP 202 with a stable job ID, null document ID and unknown pages. Duplicates return 409 with the existing identity. HTTP does not render or run OCR.
5. `Service` drives `Coordinator.process_batch()`. The coordinator freezes up to ten FIFO submissions; later arrivals cannot refill that batch.
6. `preparation.py` inspects the source and prepares/validates consecutive windows of at most twenty pages. Every page passes quality/pixel guards and is normalized into WebP with identity/hash metadata.
7. Complete preparation atomically creates document, consent and same-ID job rows, then deletes the ephemeral raw spool. Failure before promotion creates no clinical document/facts.
8. `model_stages.ocr_target()` reuses valid artifacts/text-layer words or lazily loads CPU RapidOCR. Explicitly enabled Paddle fallback runs in another child after primary initialization failure and confirmed cleanup.
9. `processing_helpers.rules_target()` classifies the whole document, extracts metadata/fields/medications/prose/reports/directives, and stores private candidates, not clinical rows.
10. Eligible local vision windows use GLM-OCR; optional requested cloud review pauses for finalized masks. `verification_target()` compares readings and associates candidates with logical reports.
11. `publication_target()` rechecks consent, state, capacity and absence of prior clinical rows; inserts all records and completion state in **one document transaction**. Observations are initially `review`, including dual-read matches.
12. Scratch cleanup follows confirmed stage shutdown. Failed later processing retains complete normalized sources but does not publish partial clinical rows.

A 45-page PDF uses 1–20, 21–40 and 41–45 internal ranges while retaining one document/job, global page numbers, document-wide interpretation and one final clinical save. No page-count admission cap does **not** mean unlimited bytes, RAM, storage, execution time, or guaranteed completion.

### Queue, review, and dashboard

`#/queue` loads compact owner-scoped Active/Recent job lists; selected detail loads bounded history. Active polling waits for requests to finish before scheduling another check. Accepted jobs survive navigation/reload; unsent browser files do not. Current Queue also offers retry and failed-job deletion, contrary to older documentation claiming otherwise.

`DocumentDetail.jsx` requests `/api/documents/{id}?page=N&offset=M` and the owner-protected normalized page image. `PageOverlay` renders normalized boxes as percentage-positioned highlights. Review POSTs accept/correct/reject to `/api/observations/{id}/review`; the router checks ownership/current status, records changes in append-only audit, and returns the updated observation and rebuilt summary. Corrections preserve old values through audit, not an immutable original-value column.

Report dates/category/title/facility can be edited separately through `/api/reports/{id}`. Document display labels and verified dates use PATCH `/api/documents/{id}`. Handwritten/low-confidence pages have a manual medication quick-entry path; this is not the full planned ranked handwriting-assist workflow.

App fetches `/api/patients/{id}/summary`, `/timeline`, account features and active-job snapshots. `summary.build_summary()` assembles coverage, results, medications, pending directives, documents and additional clinical groupings. React renders recent reports, health history, prescriptions, results/filters and uncharted findings. Source actions open a drawer or the appropriate review page. The dashboard therefore uses more than the originally proposed single aggregate request.

### Optional cloud and erasure

With a server-side key and per-upload cloud request, local OCR produces editable mask proposals and private source JPEG previews. `RedactionConsent.jsx` requires pages to load and a review acknowledgment; masks can be drawn, removed or entered numerically. Approval records the finalized page-mask map; the backend burns those masks into new metadata-free JPEGs before Gemini receives them. Original PDFs, raw OCR text and patient-context strings are not sent by this document path. Egress rows record payload hashes and outcomes. Heuristic redaction and a checkbox are **not** proof of complete de-identification.

The patient-level cloud-summary function currently returns the local digest with a warning; it does not send raw OCR to Gemini.

Owner erasure revokes consent, pauses the service, confirms owned work has stopped, validates/cleans sources and scratch, then deletes rows. Unconfirmed cleanup returns 503 and keeps recovery metadata. Existing audit rows remain. The separate reset script bypasses this controlled path and must not be treated as routine cleanup.

## 5. Models and extraction pipeline

**“Model” has three meanings here:** OCR/vision neural models, Pydantic API/data contracts, and the SQLite relational model. There is no training/fine-tuning pipeline, embedding index, RAG retrieval, or chatbot.

| Component | Actual current behavior |
|---|---|
| Digital PDF inspection | PyMuPDF words are accepted only after word-count, glyph/garbage, geometry, overlap and raster-coverage checks. Production preparation calls `inspect()` directly; the separate raster-crosscheck helper is not wired into that preparation path. |
| RapidOCR | PP-OCRv5 mobile detection plus English recognition ONNX weights, explicitly CPU providers. Current constructor defaults to six intra-op threads, not the four repeatedly described in docs. Production calls full-page `read(debug=True)`. |
| PaddleOCR | CPU adapter; coordinator fallback is opt-in and only after Rapid initialization failure, not arbitrary low confidence. |
| Classification/layout | Keyword/structural scoring for ten document types; whitespace groups words into rows, cells and table regions. Column templates carry across pages. |
| Resolution | Configured label/synonym, printed unit agreement and value-within-printed-range signals. Two signals support a resolved mapping; confidence is a heuristic score, not calibrated clinical probability. |
| Rules/prose/dates | Deterministic printed-row/medication parsing, source-grounded section slicing, labeled date/identifier extraction and relative/absolute/conditional/PRN directives. |
| Local vision | **GLM-OCR 0.9B Q8_0**, with GGUF/mmproj and CUDA llama-server. Historical stage/event/error identifiers still say `qwen`; those names do not identify the actual model. |
| Cloud | Configurable Gemini ID; default `gemini-3.8-flash`, with high thinking. Some engine/event metadata hardcodes `gemini-3.8-flash-high`, so configured request identity and recorded labels can disagree. |
| Standardized summary | Local digest of up to 100 persisted non-rejected reports. Current UI labels it “Recent reports”; it is not the full hypertension/treatment synthesis described in some docs. |

Local GLM requests resize to a 1024px long edge without changing canonical sources, use a 4096 context and up to 2048 output tokens. The adapter requests structured lab JSON with a Chinese prompt. It assigns a placeholder box; cross-check may relocate VLM-only values using OCR. Accurate field-level source localization is therefore not guaranteed for every model-only result.

Operational vision failures can leave explicit unavailable outcomes and OCR-only review after confirmed cleanup. Corruption, revoked consent, capacity failure or unconfirmed shutdown still block publication. Human review remains distinct from model agreement.

## 6. Data model and persistence

`smriti/db.py` and the schema's `PRAGMA user_version` identify **v14**, despite a v11 schema comment and older docs mentioning v8/v11. Numbered SQL migrations run sequentially on initialization. Starting the app can therefore modify a pre-existing database.

```text
patient ─┬─ auth_session
         ├─ document ─┬─ consent / cloud_consent
         │            ├─ report ─ observation
         │            ├─ observation / page_text / directive
         │            ├─ jobs / handwriting_field / egress
         ├─ medication (also links to source document)
         ├─ share_token (schema exists; sharing routes do not)
         └─ submissions ─ stage_batches

audit: append-only change records
stage_artifact: cached JSON, keyed by identity/page/stage/version
```

| Entity | Meaning |
|---|---|
| patient/auth_session | Alias, optional demographics, username/password hash; hashed expiring session tokens. |
| document | One complete prepared upload, source directory, page count, classification, dates, quality and status. |
| report | A logical dated/facility-associated page range inside a document; one PDF can contain multiple reports. |
| observation | Numeric or prose fact, label/analyte, raw/canonical units, printed interval/flag, box/page, engine, status/reason, evidence and optional clinical JSON. |
| medication/directive | Prescribed/reported medication states and source-linked timing instructions; conditional/PRN directives cannot have fabricated due dates. |
| submissions/stage_batches | Pre-document acceptance, owner/consent snapshot, raw source, preparation manifests, immutable FIFO membership, checkpoints and cleanup accounting. |
| page_text/stage_artifact | Persisted page readings and JSON caches; not an event-sourced clinical database. |
| audit/egress/cloud_consent | Change history, outbound payload-hash outcomes and per-document mask-approval state. |
| handwriting_field/share_token | Schema support for broader planned features, not evidence those user journeys are implemented. |

Most lab numbers are stored as text to retain extraction representation; charts convert finite values to floats. Laboratory series are separated by analyte **and unit**, without a completed unit-conversion/LOINC layer.

Clinical boxes use `[x0,y0,x1,y1]` in 0–1. Cloud clinical boxes use `[y0,x0,y1,x1]` in 0–1000; consent masks use `[x,y,width,height,label,id]` in 0–1000. Explicit conversion is required; “normalized box” alone is not a sufficient contract.

SQL constraints/triggers enforce owner-linked promotion, positive prepared counts, frozen batches, append-only audit and prohibition of handwritten numeric/auto observations. Filesystem privacy includes link/reparse-point rejection and Windows ACLs. Plain SQLite/source files are **not encrypted at rest** by this implementation.

## 7. Requirements, philosophy, and principles

The declared workflow is **requirements → capability map → focused specs → implementation plan → task checklist → tests/implementation**. `docs/index.md` gives the SRS authority over requirements/thresholds, specs authority over implementation boundaries, and tasks authority over sequence. This is specification-driven engineering, although documentation drift currently weakens that traceability.

| Principle | Evidence and interpretation |
|---|---|
| Trust and measurement over capture | Source page/box links, review transitions, a truth-set protocol and evaluation harness. Extraction alone is not the intended success criterion. |
| Human-in-the-loop | Every newly published observation starts in review; accepting requires a separate action. `auto` currently also means human-accepted, conflicting with the SRS glossary. |
| Local-first | CPU OCR/rules and local vision; optional explicit masked-image cloud processing is an exception, not a cloud-free guarantee. |
| Rules before models | Synonym/unit/range resolution and grounded section slicing keep common cases deterministic. No model training needed. |
| Fail closed on ownership/integrity | Consent/state/hash/artifact validation, no unowned-port reuse, and cleanup fences before another stage. |
| Atomic clinical publication | Intermediate candidates remain private; one final document transaction prevents partial charted records. |
| Bounded resources | Lazy page windows, finite bytes/pixels/output/deadlines, independent bounded log queues and verified child cleanup. |
| Honest uncertainty | Unknown counts remain null; unavailable verification is distinct from success; missing telemetry is not zero or proof of fit. |
| Minimal deployment | One local app/database/coordinator, platform primitives instead of a distributed queue stack. |
| Reproducible research | Synthetic offline harness and fixed-seed bootstrap; real-corpus gates are separate from implementation tests. |

Key intended safety requirements: no auto/numeric lab facts from handwriting; never anchor relative instructions on today; retain printed reference ranges and correction history; exclude hard-bound failures; no unconsented egress; source citations for clinical statements.

**Important distinction:** handwriting constraints are backed by SQL triggers; the full hard-bound rejection/arithmetic/swing pipeline is not. Bounds currently annotate review reasons, while summary includes review values. Original typed-projection/no-image-egress requirements also conflict with the implemented masked-image cloud path.

Research targets include field F1 ≥0.90, CER ≤0.05, end-to-end correctness ≥0.85 on 40 printed documents, medication F1 ≥0.80, and directive metrics on 150 notes. These are acceptance targets, not established results.

## 8. Interface design: UX, DX, and AX

`Agents.md` explicitly asks every screen to serve users, developers and the next editing agent, and rejects labels whose only purpose is explaining layout.

**UX:** document-centric actions, restrained system typography, neutral surfaces, blue actions and semantic warning/error colors. Source review places the image beside editable fields. Progressive disclosure keeps processing history and earlier prescriptions expandable. Native forms, dialogs, browser hash navigation and table alternatives reduce custom machinery. Focus handling, Escape/Tab behavior, accessible labels, reduced-motion CSS and axe tests show deliberate accessibility work; they do not establish complete WCAG compliance.

**DX:** Python modules have focused boundaries, API uses explicit SQL/transactions and shared contracts, settings are concentrated in one dataclass, and scripts provide one-command setup/verification. Tests isolate database/storage and fake expensive inference. There is no unnecessary state library or service stack.

**AX:** source files, specifications, requirement IDs, test names, operational stage identities and `shortcut:` comments explain ownership and known ceilings. Historical Qwen names behind GLM, duplicated old/live extraction helpers, and stale docs make editing harder than the intended philosophy.

Current views are sign-in/register, summary, upload, queue, document library and document review. There is no currently wired patient-versus-doctor toggle, share view, admin dashboard or full handwriting candidate-ranking interface. Cosmetic `.doctor-mode` CSS and contract fields do not implement those flows.

## 9. Testing and evaluation

The inspected inventory contains **245 project-owned files**, excluding ignored runtime/vendor files and this new report; **122 Python files**, **446 named backend test functions** before parametrization, and **18 frontend test files**. Function count is not the executed-test count.

`tests/conftest.py` requires unit/integration/system markers, uses temporary storage with worker/VLM disabled by default, and blocks non-loopback socket connections in the test process. Runtime tests explicitly exercise real spawned synthetic targets; clinical tests use fake engines and pages. Frontend tests use jsdom/fetch mocks, Testing Library and axe. These are not full browser-to-live-model tests.

CI installs dependencies, runs backend pytest and deterministic evaluation, then frontend layers and production build on Ubuntu. Windows runtime compatibility and package availability still require separate verification.

`eval/run_eval.py` measures deterministic rule extraction over synthetic pre-supplied OCR words: field F1, assembled-field CER, exact document match, bootstrap intervals and handwriting counts. It does **not** measure the full image→OCR→vision→review runtime or read SRS thresholds, despite a documentation claim that it does. Step-0d uses external B1 numeric truth/B2 crops. Parser bake-off measures adapters; OvisOCR and TeleOCR remain unavailable placeholders, and some “peak” measurements are only before/after snapshots.

`tasks/todo.md` records historical runs, including 709 passed/1 skipped and frontend/build passes. They belong to dated earlier slices, not this report's snapshot. **No test suite, build, benchmark, model call or live app was run for this report.** Static AST inspection parsed the project Python sources without importing the application.

## 10. File-by-file reference

This lists every tracked/non-ignored project file found during inspection. Generated dependencies, caches, private data and binaries are grouped separately; their individual contents are not application architecture.

### Root, launch, and API

| File | Responsibility |
|---|---|
| `README.md` | Project introduction, setup, status and usage; contains mixed historical/current claims. |
| `Agents.md` | UX/DX/AX and layout-label design instructions. |
| `.gitignore` | Excludes environments, data, secrets, builds and caches; selectively allows vocabulary/bounds/dictionary. |
| `.env.example` | Server-only configuration template for profiles, cloud key/model and OCR fallback. |
| `pyproject.toml` | pytest paths, quiet defaults and test-layer markers; not a complete package manifest. |
| `requirements.txt` | Pinned main Python dependencies. |
| `requirements-cloud.txt` | Additional cloud-related install list. |
| `uv.lock` | Python-version/lock metadata only; no package resolutions. |
| `start.bat` | Windows double-click entry to PowerShell startup. |
| `start.ps1` | Environment/dependency/build freshness checks and sanitized localhost launch. |
| `.github/workflows/ci.yml` | Separate backend and frontend CI verification jobs. |
| `api/__init__.py` | API package marker. |
| `api/errors.py` | Shared HTTP error envelope/helper. |
| `api/routers/__init__.py` | Router package marker. |
| `api/routers/auth.py` | Registration, login throttling, cookie sessions, logout, current account and feature availability. |
| `api/routers/documents.py` | Bounded upload, metadata PATCH, human quick-entry, consent/previews, bounded document reads and protected pages. |
| `api/routers/jobs.py` | Owner-scoped list/detail, retry and failed-job deletion. |
| `api/routers/patients.py` | Summary/timeline, clinical-digest refresh, patient cloud-consent audit and owner erasure. |
| `api/routers/reports.py` | Audited correction of logical report metadata. |
| `api/routers/review.py` | Observation accept/correct/reject, numeric validation, change audit and rebuilt summary. |

### Application lifecycle, intake, and supervision

| File | Responsibility |
|---|---|
| `smriti/__init__.py` | Application package marker. |
| `smriti/main.py` | ASGI app instance created by the factory; importing can initialize/migrate data. |
| `smriti/server.py` | Sanitized Uvicorn launcher on localhost. |
| `smriti/app.py` | Factory, lifecycle, middleware/errors, routers, health/status routes and static mount. |
| `smriti/config.py` | Immutable settings, environment loading and runtime resource validation. |
| `smriti/db.py` | SQLite setup, schema version, numbered migrations and connection pragmas. |
| `smriti/auth.py` | scrypt/session hashing, current-patient/ownership helpers and audit inserts. |
| `smriti/service.py` | Coordinator thread lifetime, admission, bounded retry/recovery and pause. |
| `smriti/coordinator.py` | Exclusive frozen FIFO orchestration, durable checkpoint recovery, degradation and publication/cleanup fences. |
| `smriti/runtime.py` | Windows Job Objects, exclusive locks, spawned stage protocol, deadlines, memory limits and confirmed process-tree cleanup. |
| `smriti/http_intake.py` | Bounded multipart streaming without framework-managed decoded uploads. |
| `smriti/spool.py` | Raw reservations, owner-scoped hash/deduplication, durable submissions, confirmed deletion and crash recovery. |
| `smriti/ingest.py` | Consent changes, RGB transparency flattening, cloud preview retrieval and finalized mask approval. |
| `smriti/preparation.py` | Source inspection, page rendering/normalization, hash validation, promotion and failed-preparation cleanup. |
| `smriti/private_paths.py` | Private path/link checks and Windows user/system ACL setup. |
| `smriti/output_quota.py` | Durable output reservation/reconciliation, bounded reads and charged file writes. |
| `smriti/processing_store.py` | Identity-bound page artifacts, complete-source validation, streaming page reads and scratch cleanup. |
| `smriti/candidates.py` | Quota-accounted private candidate SQLite, dedup/report association, mask records and cloud-item conversion. |
| `smriti/publication.py` | Fenced one-transaction insertion of all clinical records and completion state. |
| `smriti/erasure.py` | Stop/revoke/clean/delete lifecycle for one authenticated owner. |
| `smriti/stage.py` | Lazy ≤20-page execution windows and legacy/database artifact cache helpers. |
| `smriti/job_progress.py` | Allowlisted bounded progress history, verification/failure state and post-commit event forwarding. |
| `smriti/observability.py` | Safe event projection, sanitized logging, rotating JSONL and independent bounded sink processes. |
| `smriti/runtime_telemetry.py` | Observed process/tree RAM and bounded NVIDIA device-memory sampling. |

### Extraction and domain modules

| File | Responsibility |
|---|---|
| `smriti/models.py` | Strict Pydantic requests, summary/timeline contracts and domain enums; not neural models. |
| `smriti/quality.py` | Blur/resolution/aspect/ink metrics, page rejection and perceptual duplicate helpers. |
| `smriti/preprocess.py` | Perspective, deskew, contrast/resize normalization; PII proposals, burned masks and JPEG encoding. |
| `smriti/handwriting.py` | Image-component capture heuristic and OCR/page-review safety heuristic. |
| `smriti/text_layer.py` | PDF word/glyph/layout validation, rotation, optional suspicious-raster helper and word serialization. |
| `smriti/ocr.py` | OCR word/protocol definitions, Rapid/Paddle CPU adapters, recognition-only APIs and legacy singleton helpers. |
| `smriti/engines.py` | Engine/version metadata and identifiers for rule/model provenance. |
| `smriti/model_stages.py` | Disposable OCR/local-vision targets, preparation of mask-review pages and approved Gemini extraction. |
| `smriti/assembly.py` | Whitespace rows/cells/regions, header recognition and column-template alignment/carry. |
| `smriti/classify.py` | Document keyword/structural scoring and boilerplate recognition, including streamed classification. |
| `smriti/analytes.py` | Cached CSV vocabulary, synonym matching and display/unit lookup. |
| `smriti/resolution.py` | Deterministic label/unit/reference-range agreement and heuristic confidence. |
| `smriti/extract.py` | Printed lab/medication parsing, source boxes, candidate types, legacy whole-list and streaming extraction. |
| `smriti/checks.py` | Bounds/numeric validation plus arithmetic/date/identity/orphan helpers; many helpers are not production-wired. |
| `smriti/metadata.py` | Labeled clinical dates, UHID/doctor/facility identifiers and streamed metadata extraction. |
| `smriti/bounded_text.py` | Document-wide line iteration with exact offsets and maximum logical-line bytes. |
| `smriti/prose.py` | Section slicing and grounding verification against source OCR text. |
| `smriti/reports.py` | Logical report segmentation by date/facility, preferred section summaries and fact/label classification. |
| `smriti/directives.py` | Relative/absolute/conditional/PRN instruction parsing and source-date anchoring. |
| `smriti/vlm.py` | Actual GLM-OCR llama-server adapter, lifecycle, bounded requests/response parsing and optional Gemini schema extraction. |
| `smriti/worker.py` | OCR–VLM numeric cross-check and handwritten-page helper; scheduling now lives elsewhere. |
| `smriti/processing_helpers.py` | Supervised document-wide classification/rules/prose/directives and final verification/report association. |
| `smriti/summary.py` | Coverage, unit-separated result series, medication groups, clinical snapshot/master timeline and dashboard assembly. |
| `smriti/clinical_summary.py` | Local recent-report digest, medication-name filtering, cached retrieval and disabled raw-text cloud summary. |

### Schema, migrations, and vocabulary

| File | Responsibility |
|---|---|
| `smriti/schema.sql` | Complete fresh v14 tables, checks, indexes and integrity/safety triggers. |
| `smriti/migrations/002_auth_ocr.sql` | Accounts/sessions and OCR-related schema extension. |
| `smriti/migrations/003_doc_types_provenance.sql` | Expanded document categories and source/model provenance. |
| `smriti/migrations/004_identity_dates.sql` | Discrete identity and clinical date fields. |
| `smriti/migrations/005_stage_queue.sql` | Job stages and artifact caching. |
| `smriti/migrations/006_prose_review_and_audit_index.sql` | Prose-compatible review constraints and audit lookup index. |
| `smriti/migrations/007_identity_mrd_hospital.sql` | MRD/hospital identity metadata. |
| `smriti/migrations/008_reports.sql` | Logical reports, observation linkage/fact metadata and historical backfill. |
| `smriti/migrations/009_job_progress.sql` | Durable structured job progress. |
| `smriti/migrations/010_runtime_stages.sql` | Submissions/batches and operational integrity guards. |
| `smriti/migrations/011_long_pdf_windows.sql` | Removes operational upload page-count restrictions while retaining bounded windows. |
| `smriti/migrations/012_retry_completed_batches.sql` | Permits reassigning submissions from completed batches for retry. |
| `smriti/migrations/013_cloud_clinical.sql` | Clinical JSON, medication provenance and document cloud-consent table. |
| `smriti/migrations/014_document_labels.sql` | Human display name and verified date. |
| `data/analyte_map.csv` | Thirty analyte IDs, display names, units and synonyms; no LOINC codes. |
| `data/bounds.csv` | Thirty broad biological bounds with citation text; citations not independently verified here. |

### Frontend foundation and pages

| File | Responsibility |
|---|---|
| `web/package.json` | React/chart dependencies, development/test/build commands. |
| `web/package-lock.json` | Resolved npm dependency tree. |
| `web/vite.config.js` | React/Tailwind plugins, localhost API proxy, jsdom setup and test timeout. |
| `web/index.html` | Browser document/root mount. |
| `web/public/favicon.svg` | Application icon. |
| `web/src/main.jsx` | React entry point and CSS import. |
| `web/src/App.jsx` | Account gate, hash views, shared summary/timeline requests, active polling and navigation callbacks. |
| `web/src/index.css` | Shared visual tokens, responsive layouts, controls, review/drawer/chart/redaction styles and motion rules. |
| `web/src/lib/api.js` | Same-origin fetch/JSON handling and structured `ApiError`; caller supplies request headers. |
| `web/src/lib/navigation.js` | Parses/generates summary/library/intake/queue/document-page hash routes. |
| `web/src/lib/format.js` | Shared date/unit-range/status/category/identity display formatting. |
| `web/src/fixtures/summary.json` | Synthetic shared summary contract fixture, not production patient records. |
| `web/src/pages/Auth.jsx` | Sign-in/register forms, client validation and field-linked errors. |
| `web/src/pages/Dashboard.jsx` | Composes current summary/history/prescriptions/results/pending and source drawer. |
| `web/src/pages/Intake.jsx` | Multi-file selection, sequential uploads, per-file outcomes/progress and unsent-file navigation guard. |
| `web/src/pages/Queue.jsx` | Active/Recent pagination, polling, selected detail, cloud approval, retry and failed-job deletion. |
| `web/src/pages/DocumentsLibrary.jsx` | Type/review filtering, month grouping, document links and metadata editing. |
| `web/src/pages/DocumentDetail.jsx` | Bounded page/result review workbench, zoom/highlights, fact/report correction, manual handwriting entry and egress history. |

### Frontend components

| File | Responsibility |
|---|---|
| `web/src/components/Header.jsx` | Patient identity/date range, navigation, first gap and coverage. |
| `web/src/components/Footer.jsx` | Research disclaimer and optional-cloud privacy disclosure. |
| `web/src/components/Panel.jsx` | Shared accessible titled section. |
| `web/src/components/Value.jsx` | Number/unit/printed-flag rendering with missing-value handling. |
| `web/src/components/CoverageStrip.jsx` | Quarterly document counts, empty quarters, undated/future counts. |
| `web/src/components/History.jsx` | Chronological reports/document fallbacks or supplied clinical events with sources. |
| `web/src/components/StandardizedSummary.jsx` | Recent source-linked report digest with expand/show-all. |
| `web/src/components/Problems.jsx` | Diagnosis/allergy/procedure snapshot or legacy problem list. |
| `web/src/components/Medications.jsx` | Daily/as-needed/earlier prescription grouping and source links; no current-use guarantee. |
| `web/src/components/Results.jsx` | Organ/reference-range filters, lazy trends, all-reading tables, review/exclusion notices and sources. |
| `web/src/components/TrendChart.jsx` | Reference bands/lines, tooltips and circle/triangle dots; table is the accessible alternative. |
| `web/src/components/Pending.jsx` | Open/unknown-date instructions and due/anchor information. |
| `web/src/components/Processing.jsx` | Compact active-job dashboard panel linking to Queue. |
| `web/src/components/JobProgress.jsx` | Activity, stage progress, verification states, elapsed time, bounded events and support ID. |
| `web/src/components/PageOverlay.jsx` | Source image with normalized percentage-positioned boxes. |
| `web/src/components/SourceOverlay.jsx` | Source modal/drawer with keyboard focus trap, Escape and focus restoration. |
| `web/src/components/SourcePills.jsx` | Clinical box conversion and one source action per stored anchor. |
| `web/src/components/UnassignedFindings.jsx` | Non-charted prose/unmapped/excluded findings and source-document actions. |
| `web/src/components/RedactionConsent.jsx` | Native dialog, paged local previews, mask proposal editing/drawing/keyboard coordinates, approval or offline decline. |

### Backend test infrastructure and application tests

The descriptions below identify test intent from inspected definitions and selected fixtures; they are not claims that the current tests pass.

| File | Checks/support |
|---|---|
| `tests/__init__.py` | Test package marker. |
| `tests/conftest.py` | Layer enforcement, temporary apps/storage and non-loopback network blocking. |
| `tests/factory.py` | Shared synthetic test data/record construction. |
| `tests/staged_runtime.py` | Synthetic staged-pipeline fixtures and fake supervision. |
| `tests/runtime_targets.py` | Importable synthetic spawned targets for success/failure/hang/process-tree cases. |
| `tests/observability_targets.py` | Spawn targets for log-writer pressure/failure/privacy tests. |
| `tests/fixtures/schema_v9.sql` | Historical schema fixture for migration compatibility. |
| `tests/test_app.py` | Health and unsafe upload/static-root placement. |
| `tests/test_app_diagnostics.py` | Private exception handling, sanitized launcher, poll suppression and lifecycle/log cleanup. |
| `tests/test_patients.py` | Account validation, legacy claim, sessions, ownership, demo and erasure. |
| `tests/test_db.py` | Schema, constraints, migrations, ownership, frozen batches and handwriting/audit triggers. |
| `tests/test_ingest.py` | Upload promotion/dedup, EXIF/PDF/quality, consent, pages/jobs and deletion. |
| `tests/test_http_intake.py` | Multipart ordering, truncation, metadata and file/request limits. |
| `tests/test_upload_api.py` | HTTP only spools, pending duplicates, closed admission and owner checks. |
| `tests/test_spool.py` | Bounded raw capacity, durability, duplicate convergence, cleanup/recovery and live writers. |
| `tests/test_preparation.py` | Long PDFs, complete promotion, identity/recovery, later failures and confirmed cleanup. |
| `tests/test_output_quota.py` | Durable global quota/reservations and accounted writes/release. |
| `tests/test_quality.py` | Resolution/blur/blank/aspect gates and perceptual duplicates. |
| `tests/test_preprocess.py` | Processing order, deskew and minimum upscale. |
| `tests/test_ocr.py` | OCR protocol, result boxes, mocked adapters, recognition APIs and explicit CPU validation. |
| `tests/test_text_layer.py` | PDF glyph/geometry/rotation/raster policy and word round trips. |
| `tests/test_assembly.py` | Rows/cells/regions and cross-page header carry. |
| `tests/test_extract.py` | Document types, numeric/medication extraction, provenance, unresolved labels and handwriting exclusion. |
| `tests/test_resolution.py` | Two-of-three signals, unit and range matching. |
| `tests/test_checks.py` | Bounds, numeric checks, arithmetic gates, dates, identities and orphan helpers. |
| `tests/test_metadata.py` | Labeled date/identifier/facility extraction and DOB exclusion. |
| `tests/test_directives.py` | Four timing classes, anchor precedence, past-date behavior, exact spans and persistence. |
| `tests/test_prose.py` | Source grounding, hallucination rejection and deterministic clinical sections. |
| `tests/test_reports.py` | Date/facility segmentation, continuations, summaries and fact labels. |
| `tests/test_bounded_text.py` | Exact streamed Unicode offsets, line limits and classification/metadata equivalence. |
| `tests/test_bounded_helpers.py` | Complete-document semantics across page twenty and no whole-document prefetch. |
| `tests/test_candidates.py` | Private deduplication, report association, quotas and candidate-database identity. |
| `tests/test_execution_windows.py` | Lazy ordered/global windows, short packing, long isolation and invalid cursors. |
| `tests/test_model_stages.py` | Lazy OCR, separate fallback, cached/source identities, unavailable vision and safe failure metadata. |
| `tests/test_processing_helpers.py` | Empty/degraded/disabled vision, missing artifacts and cross-check equivalence. |
| `tests/test_worker.py` | Cross-check behavior, synthetic extraction, ownership, source retention and atomic failure. |
| `tests/test_vlm.py` | Owned endpoint/lifecycle, requests, strict JSON, bounds and sanitized transport failures. |
| `tests/test_coordinator.py` | Frozen FIFO, exclusivity, interruption/recovery, long-document atomicity and degradation fences. |
| `tests/test_runtime_stages.py` | Real synthetic spawned trees, deadlines/memory, safe IPC, locks and confirmed cleanup. |
| `tests/test_runtime_telemetry.py` | Numeric driver output, sampled RAM/VRAM, unavailable values and sampler cleanup. |
| `tests/test_service.py` | Service pause, bounded retry, recovery validation and permanently closed admission on fences. |
| `tests/test_job_progress.py` | Committed bounded history, latest failure, truthful counters and no deleted-job resurrection. |
| `tests/test_jobs.py` | Owned compact list/detail, pending/legacy counts, pagination, retry and failed-job deletion. |
| `tests/test_observability.py` | Privacy registry, ACLs, sink exclusivity, rotation, blocked/dead writers and shutdown. |
| `tests/test_publication.py` | One final clinical save, rollback and no revoked/populated replacement writes. |
| `tests/test_erasure.py` | Owner-only file cleanup, paused work, locked files and retained recovery metadata. |
| `tests/test_review.py` | Accept/correct/reject, original-value audit, numeric validation, prose and ownership. |
| `tests/test_document_ranges.py` | Bounded long-document reads, response-capacity checks and owner scope. |
| `tests/test_summary.py` | Shared contract, gaps, mixed-unit separation and date fallback. |
| `tests/test_clinical_summary.py` | Medication noise filtering and source-linked local report digest/API. |
| `tests/test_timeline.py` | Chronological logical reports, category/date filters, ownership and audited correction. |
| `tests/test_dynamic_redaction.py` | PII masks, handwritten demographic strip, QR detection and invalid-mask failure. |
| `tests/test_gemini_fallback.py` | Mocked cloud schema/dates/regimens/anchors and consented masked-image publication. |
| `tests/test_system.py` | Synthetic upload→review→summary journey and no handwritten numeric/directive publication. |
| `tests/test_eval_smoke.py` | Known-answer metrics, kappa CLI and deterministic offline fixture evaluation. |
| `tests/test_bakeoff.py` | Synthetic manifest, mock parser/resources and adapter selection. |
| `tests/test_step0d_benchmark.py` | External ground-truth gate; no fabricated benchmark inputs. |

### Frontend tests

| File | Checks/support |
|---|---|
| `web/src/test/setup.js` | DOM assertions, cleanup and browser/test environment setup. |
| `web/src/test/App.system.test.jsx` | Mocked account/upload/review/summary and hash-navigation journeys. |
| `web/src/test/Auth.integration.test.jsx` | Account forms, validation and API-error behavior. |
| `web/src/test/ClinicalDashboard.integration.test.jsx` | Clinical groups, sources and dashboard presentation. |
| `web/src/test/DocumentDetail.integration.test.jsx` | Source loading, observation/report corrections and bounded navigation. |
| `web/src/test/Intake.integration.test.jsx` | Upload/dedup/progress, multi-file independence and consent. |
| `web/src/test/Queue.integration.test.jsx` | Active/Recent lists, polling, selected detail and navigation/session behavior. |
| `web/src/test/RedactionConsent.integration.test.jsx` | Mask review, approve/decline and keyboard-accessible dialog behavior. |
| `web/src/test/a11y.integration.test.jsx` | Automated axe checks and keyboard/source-dialog behavior. |
| `web/src/test/CoverageStrip.unit.test.jsx` | Quarterly document/gap rendering. |
| `web/src/test/History.unit.test.jsx` | Chronological entries and source actions. |
| `web/src/test/JobProgress.unit.test.jsx` | Activity, stages, elapsed time and verification disclosure. |
| `web/src/test/Medications.unit.test.jsx` | Medication grouping/state/provenance presentation. |
| `web/src/test/Processing.unit.test.jsx` | Compact active-job panel behavior. |
| `web/src/test/Results.unit.test.jsx` | Result tables, review/exclusions and source links. |
| `web/src/test/StandardizedSummary.unit.test.jsx` | Source-linked recent-report digest presentation. |
| `web/src/test/TrendChart.unit.test.jsx` | Per-reading intervals and chart-point presentation. |
| `web/src/test/format.unit.test.jsx` | Date/status/category/range formatting. |
| `web/src/test/navigation.unit.test.js` | Hash route parsing and generation. |

### Evaluation and operational scripts

| File | Responsibility |
|---|---|
| `eval/__init__.py` | Evaluation package marker. |
| `eval/README.md` | Offline harness usage and synthetic/real distinction. |
| `eval/fixtures/smoke_docs.json` | Synthetic OCR words and extraction truth for smoke evaluation. |
| `eval/metrics.py` | F1, CER/edit distance, exact match, bootstrap intervals and Cohen's kappa. |
| `eval/run_eval.py` | Rule-extraction fixture metrics and deterministic report generation. |
| `eval/kappa.py` | Two-annotator CSV agreement CLI. |
| `eval/manifest.py` | PDF page-cache rendering and benchmark manifest construction. |
| `eval/bakeoff.py` | Parser adapter registry/results and resource measurements; two candidate adapters are placeholders. |
| `eval/run_bakeoff.py` | Runs selected parsers and emits benchmark summaries/artifacts. |
| `eval/eval_0d.py` | CPU OCR truth/crop benchmark, token-fusion/line-order analysis and error histogram. |
| `scripts/verify.bat` | Windows wrapper for verification. |
| `scripts/verify.ps1` | Backend/frontend layers, full frontend suite/build and evaluation smoke. |
| `scripts/reset_user_data.py` | Destructive global medical-data reset preserving accounts; removes audit protection temporarily and bypasses supervised erasure. Not executed. |

### Documentation, specifications, and project management

| File | Owns/describes |
|---|---|
| `docs/index.md` | Reading order, authority and change-control rules. |
| `docs/SRS.md` | Functional/nonfunctional requirements, safety invariants, acceptance targets and amendments. |
| `docs/architecture.md` | Runtime boundaries, trust, flows, deployment and failure handling; includes stale claims. |
| `docs/data-model.md` | Entities, states, indexes, migrations and erasure. |
| `docs/API.md` | API conventions and implemented versus contract-only endpoints. |
| `docs/test-plan.md` | Test pyramid, commands, fixtures, traceability and known gaps. |
| `docs/annotation-guide.md` | Ground-truth labeling, ambiguity rules and annotation agreement protocol. |
| `docs/ethics-consent.md` | Intended research consent, privacy, retention/release and incident handling. |
| `docs/synopsis.md` | Academic problem statement, objectives, methodology and expected outcomes; historical scope. |
| `docs/ARCH_STATUS.md` | Dated stage/measurement/licensing board; not authoritative proof of current integration. |
| `docs/LICENSES.md` | Model/dataset license register and unresolved drug-data decision. |
| `docs/qwen-hardware.md` | Historical Qwen configuration/hardware references and incident/fit limitations. |
| `docs/redacted-cloud.md` | Optional finalized-mask cloud workflow and its limitations; some summary details are stale. |
| `specs/CAPABILITY-MAP.md` | Original module responsibilities/dependencies/build gates and later extensions. |
| `specs/CAPABILITY-MAP-intake-experience.md` | Registration, processing visibility and bulk-upload boundaries. |
| `specs/SPEC-intake.md` | Input, preparation, quality, consent, deduplication and source lifecycle. |
| `specs/SPEC-extraction.md` | OCR/layout/field assembly, resolution, review and provenance. |
| `specs/SPEC-egress.md` | Original vocabulary-only projection/consent/egress boundary, not the current image flow. |
| `specs/SPEC-normalisation.md` | Planned analyte/LOINC/unit normalization and printed ranges. |
| `specs/SPEC-safety.md` | Planned arithmetic/plausibility/swing gates and exclusions. |
| `specs/SPEC-medications.md` | Drug extraction/lexicon and prescribed-versus-reported states. |
| `specs/SPEC-directives.md` | Four timing classes, anchoring, supersession and annotation evaluation. |
| `specs/SPEC-dashboard.md` | Aggregate contract, layout, source overlays and planned sharing/modes. |
| `specs/SPEC-handwriting-assist.md` | Planned candidate-ranking and mandatory human confirmation/study metrics. |
| `specs/SPEC-evaluation.md` | Intended truth set, full research metrics and offline reproduction. |
| `specs/SPEC-registration.md` | Actionable normalized account validation and privacy-preserving errors. |
| `specs/SPEC-processing.md` | Truthful processing activity/progress/event disclosure. |
| `specs/SPEC-bulk-upload.md` | Sequential client uploads and independent per-file outcomes. |
| `specs/SPEC-runtime-stages.md` | Bounded intake/stages, process ownership, long PDFs, degradation and recovery. |
| `specs/SPEC-observability.md` | Safe event schema, independent bounded sinks and existing job-view monitoring. |
| `tasks/plan.md` | Implementation sequencing, design decisions, amendments and rollout gates. |
| `tasks/todo.md` | Ordered checklist and dated verification/remaining-gate ledger. |
| `tasks/status.md` | Historical module board and PR/commit log. |

### Local documents and excluded/generated material

| Path | Role and inspection boundary |
|---|---|
| `sample/HM CT SCAN 2021,22,24,25.pdf` | Untracked local example medical PDF; contents and consent/de-identification were not inspected. |
| `test-doc/HM-CT-SCAN-2021-22-24-25_260914_212904.pdf` | Untracked local test/example PDF; not treated as synthetic or safe to publish. |
| `.env` | Ignored server secrets/configuration. Contents intentionally not inspected. |
| `data/smriti.db`, uploads, spool, logs, models, binaries, evaluation caches | Private runtime storage/assets; not inspected or executed. |
| `data/models/en_dict.txt` | OCR recognition dictionary expected/provisioned locally; ignore exception allows it, but it is not in the inspected tracked/non-ignored file inventory. |
| `web/node_modules/`, `.venv/` | Installed third-party packages/environment, not project source. |
| `web/dist/`, `__pycache__/`, `.pytest_cache/`, `eval/out/` | Generated builds/cache/evaluation outputs; not a substitute for a fresh verification run. |
| `tmp*/`, `pytest-of-*/`, `ffcache*` | Local temporary/test/parser artifacts; retained untouched. |
| `.git/` | Version-control internals, not application logic. |
| `.opencode/commands/`, `.opencode/skills/` | Empty local tooling directories at inspection. |
| `.omc/config.json` | Ignored local agent/tool configuration; not application runtime and not inspected. |
| `docs/PROJECT-REPORT.md` | This new static architecture/flow/file-reference report. |

The two PDF directories are not covered by the data-directory ignore rule. Their untracked presence contradicts any blanket claim that all local medical examples are automatically excluded from a future commit; review them before staging or publishing.

## 11. Important gaps and contradictions

These are observations needed to understand the project, not changes made or an exhaustive defect audit.

1. **Privacy contract drift:** original SRS invariants/capability map prohibit image egress and rely on a vocabulary-only projection. Current optional cloud processing sends finalized-mask JPEGs. Consent does not make that equivalent to the original invariant. README/Auth also retain “no cloud” statements. A single reviewed privacy contract is needed before deployment.
2. **Local model identity drift:** actual GLM-OCR weights, CUDA flags and 1024px requests differ from Qwen references/tuning in docs. Historical identifiers intentionally persist for checkpoints, but event prose still claims Qwen reading and exact verification. Use actual engine identity, not stage name, when interpreting logs.
3. **Safety helpers are not the safety pipeline:** five arithmetic checks, date-window/identity/orphan helpers exist and have tests, but caller search found no production invocation of those checks. Bounds return review reasons, not hard rejection. Review observations are charted, and ordinary acceptance does not reapply analyte biological bounds. The promised “failing hard bounds never charted” rule is not established.
4. **Incomplete normalization:** vocabulary has thirty entries but no LOINC codes or unit conversion map. Postprandial glucose does not have its own configured ID. Some organ-group IDs differ from the CSV (`fasting_glucose`/`total_cholesterol` versus alternatives in `ORGAN_ANALYTES`). Keeping units apart is useful but not complete clinical normalization.
5. **Source localization limits:** GLM fields initially receive a fixed placeholder box; OCR relocation is value-based. A valid in-range box is not proof of a correct field box. Raw OCR grounding also proves text was copied, not that the OCR text is clinically correct.
6. **Summary/data-contract drift:** original “exactly seven keys,” one-request dashboard, five-point summary limit and dotted >six-month chart gaps are not the current behavior. Summary has additive clinical fields, results retain all points, and the chart uses one solid line. Current UI has no mode toggle. The local standardized digest is cached by patient/stage; no connected automatic invalidation on new documents/report edits was found.
7. **Out-of-scope features remain schema/specs:** sharing/PIN, medication-report updates, full handwriting ranking and notification/supersession journeys are not complete implemented endpoints. Report-level `auto` can be assigned by segmentation without human review, unlike observation publication. Do not interpret every `auto` identically.
8. **Deployment/security limits:** localhost cookie is not Secure; at-rest encryption is absent. `/api/system/gemini-status` has no account dependency and can perform a real outbound ping when configured. Normalized page responses permit private browser caching. These boundaries need deliberate review before remote exposure or real sensitive-data acceptance.
9. **Operational exception paths need review:** retry lacks the explicit demo check used by other writes; Queue offers retry for queued and failed jobs even where no prepared document exists. Reset bypasses owner/runtime/audit safeguards and can conflict with restrictive submission foreign keys. These are not production-safe recovery procedures by implication.
10. **Evidence does not travel automatically across changes:** historical schema/test/model/benchmark claims differ from this checkout. In bake-off, unavailable GPU data becomes zero and before/after memory samples are labeled peaks; step-0d records a four-thread label although the current constructor defaults to six. Those outputs should not be compared as validated current hardware evidence.

**Expert assessment:** the strongest engineering is the separation of intake, preparation, private candidates and atomic publication, with explicit owner/process/cleanup boundaries. The largest risk is treating that operational robustness as proof of clinical correctness, source accuracy, privacy compliance or completion of the original requirements.

## 12. Reading guide and inspection limits

For a new developer, read these in order:

1. `smriti/models.py` and `smriti/schema.sql`: what the application stores and exposes.
2. `web/src/App.jsx`, `web/src/lib/api.js`, `api/routers/documents.py`: browser/API entry boundaries.
3. `smriti/http_intake.py`, `smriti/spool.py`, `smriti/preparation.py`: accepted input becomes a complete source.
4. `smriti/service.py`, `smriti/coordinator.py`, `smriti/runtime.py`: ownership, execution and recovery.
5. `smriti/model_stages.py`, `smriti/processing_helpers.py`, `smriti/candidates.py`, `smriti/publication.py`: processing becomes atomic clinical data.
6. `smriti/extract.py`, `smriti/resolution.py`, `smriti/prose.py`, `smriti/vlm.py`: extraction policy and model limits.
7. `smriti/summary.py`, `smriti/clinical_summary.py` and the dashboard/review pages: clinical data becomes a user-visible record.
8. Connected tests, then SRS/specs/task history: separate intended policy, implemented behavior and measured evidence.

This inspection deliberately did not start the application, initialize/migrate any live database, inspect `.env` or private patient/document contents, download/install packages, call local/cloud models, run destructive scripts, modify existing source/specifications, commit or push. Only this report was added.

No fresh runtime accuracy, performance, GPU fit, browser rendering, dependency compatibility or clinical/security compliance is claimed. File descriptions are an orientation map; they are not line-by-line verification of every test/vendor artifact. This working-tree report will age as uncommitted code changes.

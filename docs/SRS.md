# Software Requirements Specification — Smriti

**Document ID:** SRS-SMR-001
**Version:** 1.4
**Date:** 7 November 2026
**Status:** Baseline with user-approved intake/runtime, long-PDF, private observability and owner-only Queue/hash navigation. Connected implementation and synthetic result ledger in `tasks/todo.md`; live rollout, hardware/clinical acceptance and expanded clinical policies remain separately gated. Changes via §5.4 only.
**Project:** Smriti — Longitudinal Patient Record Intelligence (major project, 16 weeks, 3 members)

### Approved runtime amendment — 7 November 2026

This amendment supersedes earlier mandatory-Qwen failure wording for the approved slice in `tasks/plan.md` §13.9; clinical human review remains mandatory.

- **FR-RUN-19:** Keep the 6 GiB owned-tree ceiling and ≤20-page/≤10-submission FIFO bounds. Serve Qwen with one slot, 4096 context, Q8 K/V caches, CPU mmproj, six CPU threads and no warmup. Request-only images have a 1280px long edge (no upscaling), ≤2048 output tokens and a 240s per-page budget; canonical source images remain unchanged.
- **FR-RUN-20:** After confirmed Qwen shutdown, operational failure records identity-bound unavailable outcomes for missing printed pages. Keep valid readings and complete OCR, annotate unmatched OCR fields for review without confidence increases, and publish once. Empty valid readings permit OCR-only review. Missing unexplained/corrupt artifacts, revoked consent, capacity failure and unconfirmed shutdown do not permit degraded publication.
- **FR-RUN-21:** Unexpected coordinator interruption closes admission, reloads and validates durable ownership/checkpoints/artifacts before resuming, and retries with 1–30s interruptible exponential backoff. Stop after ten consecutive failed attempts; cleanup/ownership/corruption fences stop immediately. Announce recovery only after validation succeeds; pause never reopens admission.
- **FR-JOB-10:** Owner-only Queue/API distinguish partial versus unavailable independent verification and recovering activity. Bounded allowlisted diagnostics record retries/failure codes, never source/model output. Suppress successful job list/detail polls, retain failed request diagnostics.

Acceptance: isolated adapter, corruption, degradation/resume, worker retry/pause, API/privacy and UI regressions, then full backend/frontend suites/build. Real-model/GPU fit, latency/accuracy and live stored-job recovery remain separate gates. References: `docs/qwen-hardware.md`.

---

## 1. Introduction

### 1.1 Purpose

This document specifies the functional, non-functional, data, interface, and safety requirements for Smriti v1.4. It is the contract between the three project members and the basis for verification in §4. Every requirement is uniquely identified and testable. A feature that cannot be traced to a requirement and an acceptance check in §4 is not built. Local-runtime and 2026-11-07 Queue/fix requirements record the user's approvals, not hardware or clinical verification.

### 1.2 Scope

Smriti converts a folder of printed medical documents that the user already owns into a longitudinal, source-linked patient record.

In scope:

- Printed laboratory reports, printed prescriptions, and pharmacy printouts.
- 30 analytes across CBC, LFT, KFT, lipid profile, HbA1c, and TSH.
- Bounding-box provenance for every charted value.
- Directive extraction across four timing classes (relative, absolute, conditional, PRN).
- One-page dashboard with patient mode and clinician mode.
- Static, cited guideline cards.
- Handwritten prescriptions as an **assisted transcription** path: the system proposes candidates, a human confirms every field. No handwritten value is ever auto-charted.
- A share link with PIN, expiry, revocation, and audit.
- A reproducible evaluation harness over 40 real documents and 150 annotated notes.

Out of scope: see §5.3.

### 1.3 Intended use

Smriti is a **research prototype**. It organizes medical documents the user already owns. It does not diagnose, does not recommend treatment, and does not replace a doctor. Reminders transcribe what the treating doctor wrote. It is not a medical device and is not for clinical use. This statement appears on the first screen, in the report, and in the demo.

The system is designed to run without any cloud dependency for its headline result. When a remote resolver is enabled, it receives only a **typed projection** — vocabulary tokens and numbers, with no image, no free text, no dates, and no patient linkage (§3.6, FR-EGR). The document itself never leaves the device.

### 1.4 Definitions

| Term | Meaning |
|---|---|
| Observation | One analyte value read from one document, with unit, reference range, flag, box, engine, confidence, status |
| Directive | A follow-up instruction written by a doctor, extracted with its span and timing class |
| Relative timing | Timing expressed from an anchor, e.g. "after 2 weeks" |
| Absolute timing | A calendar date written in the document |
| Conditional timing | An action gated on an event, e.g. "repeat KFT after stopping drug" |
| PRN | As needed; no date exists |
| Anchor date | `collection_date` if present, else `doc_date`, else unknown. Never today |
| Auto | A field accepted without human confirmation |
| Review | A field awaiting human accept/correct |
| Rejected | A field that failed a hard gate and is never charted |
| Projection | A schema-bounded, de-identified representation of extracted table values: vocabulary tokens and numbers only. Carries no free text, dates, identifiers, or patient linkage |
| Egress | Any transmission of document-derived data to a non-local service |
| Capture type | `printed` or `handwritten`; derived server-side |
| Truth set | The 40-document annotated corpus used for the headline number |
| Material error | A value wrong by more than 10 percent, or a wrong unit, that reached `auto` |
| Tap | One human action on one field in the assisted review surface |

### 1.5 References

1. IEEE 830 / ISO/IEC/IEEE 29148 requirement conventions.
2. Smriti Final Project Plan, v1.0, 22 October 2026.
3. Gemini API terms, pricing, models, and rate limits (accessed 22 October 2026).
4. PaddleOCR PP-OCRv5 and PP-OCRv6 documentation and benchmark tables (accessed 23 October 2026).
5. DPDP Act 2023 (India) — consent and purpose limitation.
6. Institutional ethics committee submission pack.

---

## 2. Overall description

### 2.1 Product perspective

FastAPI serves the API and the built React bundle at one URL. SQLite holds the record. A local OCR pipeline produces text and boxes; rules resolve most rows; an optional text-only resolver handles the residual. Every charted value and every reminder is traceable to a stored source. The approved Phase 1 local-runtime extension replaces same-process expensive processing with one coordinator, disposable preparation/CPU OCR children, and a coordinator-owned local Qwen `llama-server` lifecycle. HTTP intake only validates basic ownership/consent/input limits and spools bounded chunks. No queue service or remote vision runtime is introduced. This extension is specified in `specs/SPEC-runtime-stages.md`; implementation and deployment remain gated by `tasks/plan.md` §12.

### 2.2 User classes

| Actor | Goal | Rights |
|---|---|---|
| Record owner (patient) | Understand what changed over time | Own record, upload, review, share, revoke |
| Clinician (viewer) | Answer "what changed since last visit" quickly | Read-only, all citations visible, print |
| Operator / annotator | Correct extraction, run evaluation | Review queue, truth set, eval harness |
| Researcher | Reproduce reported numbers | Read-only eval artifacts, no patient identity |

### 2.3 Operating environment

| Item | Baseline |
|---|---|
| Development and demo machine | Windows 11, 8 GB RAM, NVIDIA GTX 1650 4 GB; approved local verification uses the existing GPU-backed Qwen runtime; actual RAM/VRAM and deadlines remain unverified |
| Runtime | Python 3.11, Node 20+, SQLite 3 |
| Browser | Current Chrome, Edge, or Firefox, 1366×768 minimum |
| Deployment | One Docker image, one URL; local Phase 1 permits supervised stage children, not multiple coordinators. Public demo remains read-only; no new remote/deployment architecture approved |
| Network | Local pipeline works offline; the resolver path requires outbound HTTPS |

### 2.4 Design and implementation constraints

| ID | Constraint |
|---|---|
| CON-01 | No paid services. Remote use is limited to free-tier models or self-hosted open weights with a documented fallback. |
| CON-02 | Phase 1 local exception: preserve renderer, normalization, configured RapidOCR/Paddle CPU engines, models, prompts and rules. Eligible printed pages receive Qwen reading or explicit unavailable outcomes under FR-RUN-19/20. New model integrations and remote vision remain outside this exception. |
| CON-03 | API, review, and read-only demo remain usable without CUDA; OCR children must be explicitly CPU-only. Local Qwen may use the GTX 1650. Missing/failed operational verification is visible as degraded review under FR-RUN-20; never claim independent or human verification succeeded. Corruption/consent/cleanup fences remain blocking. |
| CON-04 | Handwritten content is never auto-charted. |
| CON-05 | No handwriting fine-tuning, no QLoRA, no local-model comparison as a deliverable. |
| CON-06 | Backend: FastAPI, Pydantic v2, SQLAlchemy, SQLite. Frontend: Vite, React (JS), Tailwind, Recharts. No TypeScript, no state library, no UI kit. |
| CON-07 | Bounding boxes are stored normalised to 0–1, at every layer. |
| CON-08 | The dashboard is one aggregate payload, not eight calls. |
| CON-09 | One Dockerfile. FastAPI mounts `web/dist`. |
| CON-10 | The application must remain usable with 40 documents and 150 annotations on the baseline machine. |

### 2.5 Assumptions and dependencies

| ID | Assumption | If false |
|---|---|---|
| ASM-01 | Ethics approval is granted before any real document is collected | Project re-planned around synthetic data; see RISK-01 |
| ASM-02 | Consent covers third-party processing of a typed projection derived from the document | Resolver path disabled; local rules only (Annex B, fallback) |
| ASM-03 | At least 20 real printed documents are available by Week 4 | Synthetic plus 10 real; synthetic–real gap reported as a result |
| ASM-04 | Free-tier model IDs remain available during the project | Pinned ID plus cache; local-only path remains valid |
| ASM-05 | Documents are scanned or photographed at the quality gate threshold | Re-shoot prompt; document rejected, not degraded |
| ASM-06 | Three members work 12–15 hours per week each | Cut order in §5.1 applies |

---

## 3. System requirements

Priority: **M** mandatory, **S** should, **C** could.
Verification: **T** test, **D** demonstration, **A** analysis, **I** inspection.

### 3.1 Functional requirements

#### 3.1.1 Ingestion and quality

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-ING-01 | The system shall accept a multipart upload of JPEG, PNG, or PDF after ownership, consent, supported-type, and basic input-limit checks; spool bounded chunks to private disk and return a durable pending submission/job identity. HTTP intake shall not decode, render, normalize, or OCR. Create the `document` row with status `queued` only after durable successful background preparation verifies positive page count and normalized paths. Bound multipart buffers, concurrent spoolers, and total spool capacity. | M | T |
| FR-ING-02 | The system shall determine `capture_type` server-side from handwriting detection and shall not accept it from the client. | M | T |
| FR-ING-03 | The system shall reject an image whose short edge is below 1000 px, whose Laplacian variance is below the configured threshold, or whose aspect ratio is implausible, with a re-shoot message and status `rejected_quality`. | M | T |
| FR-ING-04 | The system shall strip EXIF, correct perspective when a page quad is detected, deskew, apply contrast normalisation, upscale pages below 1500 px on the long edge, and split multi-page PDFs into page images before OCR. | M | T |
| FR-ING-05 | The system shall compute a content hash and make ingestion idempotent: re-uploading the same file shall not create a duplicate document. | M | T |
| FR-ING-06 | The system shall record `quality_score`, page count, and the applied preprocessing steps. | S | T |
| FR-ING-07 | The system shall accept `collection_date` and `doc_date` separately; `collection_date` may be null. | M | T |
| FR-ING-08 | The system shall return `202` with a `job_id` and process the document asynchronously. | M | T |
| FR-ING-09 | Before preparation, the submission shall durably record owner and consent scope, version, grant time, and revocation state. Successful preparation shall atomically create/link document, per-document `consent`, and job, preserving the original grant and rechecking consent validity. No preparation without submission consent; no document processing or egress without its consent row. | M | T |
| FR-ING-10 | The UI shall accept multiple files, send one upload at a time through the existing endpoint, and show independent uploaded, processing, duplicate, rejected, and failed outcomes with source-document links. One file's rejection shall not discard the remaining files. | M | T |
| FR-ING-11 | Raw upload bytes shall be strictly ephemeral in restricted `data/spool/`, excluded from static serving, exports, backups, and git. After committed successful preparation or deterministic rejection (including byte/page/pixel limits, password, invalid/corrupt format, hard quality failure), close handles and immediately unlink; set `spool_deleted_at` only after confirmed removal. Persist/recover pending or failed cleanup separately. Only unexpected parser/renderer crashes with explicit `DEBUG_RETAIN_FAILED_SPOOL=1` may retain raw spools; retained files stay quota-accounted and erasable. Permanent archival/download is rejected for Phase 1. Apply equivalent cleanup to multipart/partial files. | M | T, I |

#### 3.1.2 Projection and egress control

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-EGR-01 | The system shall represent outbound table data as a typed projection whose every string is a member of a configured vocabulary and whose every numeric value matches `^-?\d+(\.\d+)?$`. Construction shall be the only path to a payload. | M | T |
| FR-EGR-02 | A projection shall contain no name, date, identifier, facility, free text, image, base64 data, or cross-document linkage. | M | T |
| FR-EGR-03 | The system shall require a per-document `consent` row before any egress; absent consent, the document shall be processed locally and no call made. | M | T |
| FR-EGR-04 | The system shall write one `egress` row per attempt, including refusals, recording `payload_sha256`, model ID, prompt version, schema version, outcome, reason, and timestamp. | M | T |
| FR-EGR-05 | The resolver shall be disabled by default; enabling it shall be per document, and the `demo` deployment profile shall never egress regardless of flags. | M | D |
| FR-EGR-06 | The system shall validate a resolver response against the request's `roi_id` set and the analyte vocabulary, and shall discard the response on any mismatch. | M | T |
| FR-EGR-07 | The system shall cache every response keyed by `payload_sha256`, prompt version, schema version, and model ID; a cache hit shall produce no outbound call. | M | T |
| FR-EGR-08 | The system shall never transmit image bytes, base64 image data, or a URL resolving to a stored document. | M | I |

#### 3.1.3 Extraction

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-EXT-01 | The system shall store OCR word text with normalized boxes. Historical baseline selected PaddleOCR PP-OCRv6_small with v5 mobile fallback; the approved Phase 1 local exception instead preserves the current configured RapidOCR primary/Paddle initialization-failure fallback and validated PDF text-layer reuse, with explicit CPU-only disposable execution. This is not approval for a model upgrade or a new low-confidence fallback trigger. | M | T |
| FR-EXT-02 | The system shall assemble OCR words into rows and fields using template rules for printed laboratory reports. | M | T |
| FR-EXT-03 | The system shall map each extracted value to one of the 30 configured analytes using `analyte_map.csv`, including Indian synonyms and specimen and timing columns. | M | T |
| FR-EXT-04 | The system shall resolve values that template rules cannot, by constructing a typed projection and consulting the resolver only where FR-EGR passes. | S | T |
| FR-EXT-05 | The resolver and document understanding engine shall use `gemini-3.8-flash-high` with `thinking_level="high"` (with local rules offline fallback). Retries are capped at one. | S | T |
| FR-EXT-06 | The resolver response shall be a schema-validated mapping from `roi_id` to analyte id, and shall be validated with Pydantic. | M | T |
| FR-EXT-07 | The system shall treat a model-declared null with a reason as a valid abstention and shall route it to review rather than guessing. | M | T |
| FR-EXT-08 | The system shall cache every resolver response on disk keyed by projection hash, prompt version, schema version, and model ID; a cache hit shall not produce an outbound call. | M | T |
| FR-EXT-09 | The system shall record on every observation the engine identifier, including model ID and quantisation or version. | M | T |
| FR-EXT-10 | For `capture_type = handwritten`, the system shall extract only medication names, doses, frequencies, and directives; it shall not extract numeric laboratory values. | M | T |

#### 3.1.4 Field assembly and confidence

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-ASM-01 | For printed documents, the system shall compare the local OCR result with the resolver result when both exist and shall set confidence from their agreement plus gate outcomes. | S | T |
| FR-ASM-02 | A field shall be set to `auto` only if it agrees, passes all gates, and is not from a handwritten document. | M | T |
| FR-ASM-03 | All handwritten fields shall be created with status `review`, regardless of model confidence. | M | T |
| FR-ASM-04 | A field whose box cannot be aligned to a word or model box shall be set to `review`. | M | T |
| FR-ASM-05 | The system shall store the normalised box for every field at 0–1 coordinates. | M | T |

#### 3.1.5 Normalisation

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-NRM-01 | The system shall assign a LOINC code to each of the 30 analytes. | M | T |
| FR-NRM-02 | The system shall convert units using `unit_map.csv` with explicit factors and offsets, covering only the pairs present in the corpus. | M | T |
| FR-NRM-03 | The system shall preserve the laboratory's printed reference range per observation and shall never re-derive or overwrite it. | M | T |
| FR-NRM-04 | The system shall keep fasting, postprandial, and random glucose as distinct series and never merge them. | M | T |
| FR-NRM-05 | The system shall record on every observation whether the analyte mapping was exact, synonym-based, or unresolved. | S | T |

#### 3.1.6 Safety gates

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-SAF-01 | The system shall apply the five arithmetic checks with explicit tolerances: DLC sum 100 ± 2; Friedewald LDL when TG ≤ 400 mg/dL; total bilirubin equals direct plus indirect ± 0.2 mg/dL; MCV equals Hct divided by RBC times 10 ± 1 fL; ANC equals WBC times neutrophil percent divided by 100 ± 0.1 ×10³/µL. | M | T |
| FR-SAF-02 | The system shall apply hard plausibility bounds per analyte, each carrying a citation, and set failures to `rejected`; rejected values shall never be charted. | M | T |
| FR-SAF-03 | The system shall set a value to `review` when it changes from the last accepted value by more than the configured swing threshold for that analyte. | M | T |
| FR-SAF-04 | The system shall record which gate fired, its inputs, and its tolerance. | M | T |
| FR-SAF-05 | The evaluation harness shall measure gate recall and false-quarantine rate against injected corruptions. | M | T |
| FR-SAF-06 | A gate that cannot run because an input is missing shall record `skipped`; it shall never record `pass`. | M | T |

#### 3.1.7 Review queue

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-REV-01 | The system shall list every `review` field with value, unit, reference range, source thumbnail, highlighted box, engine, and reason. | M | T |
| FR-REV-02 | The system shall allow accept, correct, and reject, and shall write an audit row for each action. | M | T |
| FR-REV-03 | A corrected value shall retain its original extracted value and box. | M | T |
| FR-REV-04 | The review queue shall be keyboard-navigable and shall show the source image beside the editable field. | S | T |
| FR-REV-05 | Accepting a field shall recompute downstream timeline and chart state in the same request. | M | T |

#### 3.1.8 Timeline and dashboard

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-TIM-01 | The system shall expose one aggregate payload at `GET /api/patients/{id}/summary` with exactly these keys: `patient`, `coverage`, `problems`, `medications`, `results`, `pending`, `documents`. | M | T |
| FR-TIM-02 | Results shall be ordered abnormal first, then most recent, with at most five points per analyte in the summary view. | M | T |
| FR-TIM-03 | The dashboard shall render four zones in fixed order: header with gap banner; problems and current medications side by side; results; pending and documents. | M | T |
| FR-TIM-04 | The coverage strip shall render one cell per quarter and visibly distinguish quarters with zero documents. | M | T |
| FR-TIM-05 | Any chart segment spanning more than six months shall be rendered dotted, never solid. | M | T |
| FR-TIM-06 | Clicking a charted value shall open the source page with the field's box highlighted. | M | T |
| FR-TIM-07 | The dashboard shall display the laboratory's printed flag verbatim and shall not display a computed abnormality judgement. | M | T |
| FR-TIM-08 | The dashboard shall state the gap in plain language, e.g. "No data for 14 months", without interpretation. | M | T |
| FR-TIM-09 | The dashboard shall surface rejected observations as an exclusion notice with a reason, and shall never silently omit them. | M | T |

#### 3.1.9 Directives and reminders

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-DIR-01 | The system shall extract, for each directive, `action_type`, `timing_type`, `time_value`, `time_unit`, `anchor_event`, `condition_text`, `target`, and the exact `span_text`. | M | T |
| FR-DIR-02 | The system shall compute a due date only for absolute and relative directives. A relative directive whose computed date is already past shall be stored with state `unknown_date`, not scheduled. | M | T |
| FR-DIR-03 | Relative directives shall anchor on `collection_date`, else `doc_date`, else remain unknown; the system shall never use the current date as an anchor. | M | T |
| FR-DIR-04 | Absolute directives that resolve to a past date at extraction time shall be rejected, not scheduled. | M | T |
| FR-DIR-05 | Conditional directives shall create an open trigger with a checklist and shall not receive a fabricated date. | M | T |
| FR-DIR-06 | PRN directives shall be displayed as "as needed" with no date. | M | T |
| FR-DIR-07 | The system shall apply supersession: the newest directive per action type within a document type wins, and superseded directives shall not notify. | M | T |
| FR-DIR-08 | The system shall not notify for any date already past at extraction time. | M | T |
| FR-DIR-09 | Every rendered directive shall display its source sentence and document. | M | T |
| FR-DIR-10 | The system shall compute Cohen's kappa on a 30-note double-annotated subset drawn before the remainder, and shall block further annotation if kappa is below 0.70. | M | T |
| FR-DIR-11 | Kappa and directive metrics shall be reported separately for printed and handwritten strata. | S | T |

#### 3.1.10 Medications

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-MED-01 | The system shall represent three distinct states: prescribed, patient-reported stopped, and patient-reported ongoing. | M | T |
| FR-MED-02 | The system shall never merge states; each row shall display the state with its source and timestamp. | M | T |
| FR-MED-03 | Patient-reported status shall be timestamped and attributed to the patient, never presented as verified. | M | T |
| FR-MED-04 | The system shall extract brand, dose, and frequency from printed prescriptions with F1 ≥ 0.80 on the 40-document corpus. | M | T |
| FR-MED-05 | The system shall report lexicon coverage as the fraction of corpus brand tokens present in `brand_lexicon.csv`, and shall present it as a stated limitation. | M | T |

#### 3.1.11 Share and audit

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-SHR-01 | The system shall create a share token bound to one patient with a six-digit PIN, stored hashed, and a 30-minute expiry. | M | T |
| FR-SHR-02 | The system shall revoke a token on demand and reject expired or revoked tokens. | M | T |
| FR-SHR-03 | The system shall lock a token after five failed PIN attempts and record the lockout. | M | T |
| FR-SHR-04 | Every share creation, access, failed attempt, and revocation shall write an audit row. | M | T |
| FR-SHR-05 | The shared view shall be read-only and shall display the intended-use statement. | M | T |

#### 3.1.12 Jobs

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-JOB-01 | The system shall expose ownership-checked job state, page progress, total pages, stage, document identity, and safe error text at `GET /api/jobs/{id}`, including submissions that do not yet have a document. Preserve historical fields and job identities; unavailable history shall not be fabricated. | M | T |
| FR-JOB-02 | A failed job shall be retryable without duplicating observations. | M | T |
| FR-JOB-03 | A job shall not leave a document in a partially charted state; writes shall be transactional per document. | M | T |
| FR-JOB-04 | The UI shall poll every two seconds while a job is active and stop on a terminal state. | S | T |
| FR-JOB-05 | Job progress shall expose actual stage, active model, current page, stage-specific completed pages, timestamps, and ordered processing events. Unknown progress shall remain indeterminate; OCR completion shall not imply document completion. | M | T |
| FR-JOB-06 | The UI shall show concise current activity and expandable timestamped technical events with text and semantic color, keyboard access, and reduced-motion support. Model skips, cache reuse, failures, and interrupted processing shall remain distinguishable from successful inference. | M | T |
| FR-JOB-07 | Processing events shall be ownership-checked, bounded operational metadata only, retained with the job and removed with its deletion. Logs shall not contain credentials, document text, extracted medical values, patient metadata, images, prompts, or raw model responses. | M | T |
| FR-JOB-08 | Pending/preparing responses shall expose `document_id: null`, `total_pages: null`, and `stage: "pending_intake" \| "preparing"`; legacy `total` is also null while unknown. At successful promotion keep the same public job ID and populate verified counts/document links. Deferred rejection shall remain terminal and pollable without creating a clinical row. Update API/UI/fixtures together; positive existing document/job-count invariants remain intact. | M | T |
| FR-JOB-09 | Accepted jobs shall remain discoverable after leaving Upload/reloading through owner-only `GET /api/jobs` and `#/queue`. Independently paginate compact Active (queued/running) and Recent (done/failed) lists, maximum 50 rows; only one selected job loads bounded history. Distinct Summary/Intake/document source-page hash routes shall honor navigation/reload and guard unsent files. Polling shall not overlap, shall stop terminal detail/expired sessions, and shall retain last progress on transient failures. Listing shall never recover/requeue legacy jobs. | M | T |

#### 3.1.13 Handwriting assist

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-HWR-01 | The system shall propose handwritten fields one at a time, each with its page, normalised box, and the surrounding line. | S | T |
| FR-HWR-02 | The system shall rank at most three candidates per field, weighted by the patient's medication history, the prescriber's prior documents, and the global lexicon. | S | T |
| FR-HWR-03 | Every handwritten field shall require an explicit human action — accept, correct, reject, or add — before leaving `review`. | M | T |
| FR-HWR-04 | Where the top two candidate scores are within the configured margin, the system shall present a search field rather than a ranked guess. | S | T |
| FR-HWR-05 | The system shall allow the operator to draw a box for a field the detector missed, and shall count such fields. | S | T |
| FR-HWR-06 | In a study session only, the system shall inject a deliberately wrong top-1 candidate on a configured fraction of fields and record whether it was accepted. | S | T |

#### 3.1.14 Evaluation

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-EVL-01 | `eval/run_eval.py` shall regenerate every number reported in the results chapter from `truth_set.csv` and cached artifacts. | M | T |
| FR-EVL-02 | The harness shall report field F1, CER, end-to-end correctness, material-error rate, gate recall, gate false-quarantine, directive span F1, timing accuracy, and date exact match. | M | T |
| FR-EVL-03 | The harness shall compute 95 percent confidence intervals with 1000 bootstrap resamples and a recorded seed. | M | T |
| FR-EVL-04 | The harness shall report per-template results and shall split synthetic data by template, never by sample. | M | T |
| FR-EVL-05 | The harness shall produce the risk–coverage curve at 100, 90, and 80 percent coverage. | M | T |
| FR-EVL-06 | The harness shall run with no network access when all responses are cached. | M | T |
| FR-EVL-07 | The harness shall report handwritten metrics separately and shall verify that no handwritten field has status `auto`. | M | T |
| FR-EVL-08 | The harness shall report the local-versus-resolver field F1 difference on the consented subset. | C | T |

#### 3.1.15 Account registration

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-AUTH-01 | Registration shall enforce the existing username, password, and alias constraints on the client and server, show actionable field-linked errors without echoing submitted values, and create a working session for valid inputs. | M | T |
| FR-AUTH-02 | Duplicate usernames, server unavailability, and demo read-only responses shall remain actionable without clearing valid form fields. Existing accounts, session security, and legacy-record ownership behavior shall be preserved. | M | T |

#### 3.1.16 Hardware-safe local runtime — approved 2026-11-05

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| FR-RUN-01 | Atomically freeze up to `MAX_BATCH_SUBMISSIONS = 10` pending submissions and prepare sequentially without a document page-count rejection. `MAX_WORKSET_PAGES = 20` caps internal execution windows, not uploads. Short documents retain whole-document packing; a longer document runs alone in consecutive bounded ranges, preserving one document/job, original page numbering, document-wide interpretation and final atomic publication. New arrivals cannot join/extend the frozen batch. Retain byte/pixel/quality/ownership/consent checks and finite disk accounting. | M | T |
| FR-RUN-02 | Admit at most one expensive stage tree at a time. Use disposable spawned preparation/OCR children and hard monotonic deadlines; terminate then wait ≤5s, kill then wait ≤5s, and verify owned-tree exit. Windows supervision shall use a kill-on-close Job Object or recursive child-first `psutil` cleanup with bounded waits/identity checks; the plan selects Job Objects as the primary guard before descendant creation. Advance only after validated artifacts, successful child outcome, and confirmed cleanup. Unconfirmed exit stops admission. Keep short per-page artifact transactions and transactional final medical writes per document. | M | T |
| FR-RUN-03 | The coordinator shall not retain/load OCR model runtimes. OCR children shall set `CUDA_VISIBLE_DEVICES=""` before lazy ONNX/Paddle imports, explicitly select CPU providers/device and existing thread limits, and report actual engine/provider identity. Existing fallback runs in a separate child after primary-tree exit, not as an overlapping stack. | M | T |
| FR-RUN-04 | The local coordinator shall own `llama-server`, spawn it for eligible printed verification and confirm tree shutdown at workset exit, including errors/cancellation. An occupied unowned local port is never reused/terminated. Every inference request uses its active `VlmSession`/resolved URL, shared with readiness; no global endpoint fallback. Retain handwritten exclusions/skips and prompts, ≥30s startup and the FR-RUN-19 default 240s request budget; FR-RUN-20 defines visible operational degradation. | M | T |

**Approved long-PDF amendment — 2026-11-05:** the user approved [SPEC-runtime-stages.md §8](../specs/SPEC-runtime-stages.md#8-approved-long-pdf-requirements-amendment--2026-11-05) (“okay proceed”). No page-count rejection; the 25 MiB default byte limit, 50,000,000-pixel per-page limit and quality/privacy checks remain. FR-RUN-02 preparation budgets now apply to bounded ≤20-page ranges (initial 300s each), with a separate finite 300s manifest-inspection budget; heartbeats cannot extend a stalled range. OCR/VLM startup/request budgets and verified cleanup remain unchanged per internal window. Normalized output/artifacts require finite disk accounting, bounded bookkeeping and unchanged document-wide semantics. These requirements supersede the earlier whole-document/page-count admission policy, not its historical approval record. The revised implementation plan in `tasks/plan.md` §13 still awaits review; no live migration/restart/processing is authorized.

**Observability scope selected — 2026-11-05:** the user requested production-oriented logging/monitoring, selected the existing job view plus local files, and explicitly added CMD/terminal panels. Detailed requirements are drafted separately in [SPEC-observability.md](../specs/SPEC-observability.md); they await review. No operator dashboard, public global log endpoint, external logging service or horizontal-scaling claim is authorized. NFR-05/07 privacy and FR-JOB owner boundaries apply to all sinks, including terminals.

### 3.2 Non-functional requirements

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| NFR-01 | A single printed page shall complete local OCR in ≤ 5 s on the baseline machine. | M | T |
| NFR-02 | Retain the <3.5 GB resident-memory target for the pipeline coordinator plus active owned stage tree during a batch. Report observed per-process and tree RSS peaks, sample interval/coverage, and system available RAM; summed RSS may double-count shared mappings and sampled peaks do not prove unsampled maxima. This target has not been established for the current Qwen path; do not claim success without measured evidence or relax the threshold based on a failed result. | M | T |
| NFR-03 | The aggregate dashboard payload shall be served in ≤ 2 s for 40 documents. | M | T |
| NFR-04 | The API/read-only demo shall start from cold in ≤60s without a GPU; this excludes model-stage startup. The approved local Qwen path follows CON-03 and FR-RUN-04, not a claim of GPU-free mandatory verification. | M | T |
| NFR-05 | No secret shall appear in client code, the built bundle, logs, or error messages. | M | I |
| NFR-06 | Uploads shall be stored outside the served static root and shall be addressed by opaque IDs; path traversal shall be rejected. | M | T |
| NFR-07 | Logs shall never contain a patient name, UHID, phone number, Aadhaar number, share PIN, or payload content. | M | I |
| NFR-08 | Audit rows shall be append-only through the application; updates and deletes shall be rejected. | M | T |
| NFR-09 | The system shall be usable with keyboard only and shall meet WCAG 2.1 AA contrast. | M | T |
| NFR-10 | Every chart shall have a text or table alternative exposing the same values. | M | T |
| NFR-11 | Every resolver call shall have a timeout, one retry, and a defined fallback state. | M | T |
| NFR-12 | The Pydantic summary contract shall be validated in CI against `summary.json`. | M | T |
| NFR-13 | All model IDs, prompt versions, schema versions, and thresholds shall be recorded in config and stored with results. | M | T |
| NFR-14 | The build shall produce one Docker image that serves the API and the built frontend. | M | D |
| NFR-15 | The UI shall remain functional at 1366×768 and at 100 percent and 125 percent browser zoom. | S | D |
| NFR-16 | The system shall degrade to local-only operation with a visible banner when the resolver is unavailable. | M | D |
| NFR-17 | The projection schema shall be validated in CI; any outbound string outside the vocabulary shall fail the build. | M | T |
| NFR-18 | Use pinned `psutil` (no `pynvml`) for 1–2s coordinator RSS, Windows private committed bytes when available, child observed peak RSS, descendant RAM, and system available RAM. Use installed `nvidia-smi` before/during/after stages through one streamed `-l 2` process or nonoverlapping ≥2s queries, each query/initial readiness/stall bounded at 3s. Failed/unavailable GPU readings are null with `reason: "nvidia_smi_unavailable_or_timeout"`. Record stage/attempt, actual engines/pages, timings, operation/cleanup outcomes and sample coverage; bound storage and stop/reap samplers at stage exit. Device-wide dedicated VRAM is not child attribution or shared WDDM RAM. Follow FR-JOB-07/NFR-07 privacy rules. | M | T, D |

### 3.3 Safety invariants

These are absolute. A build that violates any of them is rejected regardless of accuracy.

| ID | Invariant |
|---|---|
| SI-01 | No handwritten observation shall ever reach status `auto`. |
| SI-02 | No numeric laboratory value shall be extracted from a handwritten document. |
| SI-03 | No value that failed a hard plausibility bound shall be charted. |
| SI-04 | No image of a document shall be transmitted off the device. |
| SI-05 | No egress shall occur without a valid projection and a per-document consent row. |
| SI-06 | No guideline card shall contain a computed date; directive dates derive only from the doctor's written interval and a stored anchor. |
| SI-07 | No rendered sentence on the clinician view shall lack a stored citation. |
| SI-08 | No reminder shall be created from a date already past at extraction time. |
| SI-09 | No medication state shall be merged or inferred; only extracted or patient-reported states are displayed. |
| SI-10 | The current date shall never be used as an anchor for a relative directive. |

### 3.4 Data requirements

All boxes are normalised 0–1. All timestamps are ISO 8601 UTC.

| Table | Fields | Notes |
|---|---|---|
| `patient` | `id`, `alias`, `dob`, `sex`, `created_at` | `alias` is the only display identifier |
| `document` | `id`, `patient_id`, `doc_type`, `capture_type`, `doc_date`, `collection_date`, `lab_name`, `image_path`, `page`, `quality_score`, `content_hash`, `status`, `created_at` | `capture_type` is derived server-side; `content_hash` makes ingestion idempotent |
| `consent` | `id`, `document_id`, `scope`, `version`, `granted_at`, `revoked_at` | One row per document; absence blocks processing and egress |
| `observation` | `id`, `document_id`, `analyte_id`, `value_num`, `value_text`, `unit_raw`, `unit_norm`, `ref_low`, `ref_high`, `flag_printed`, `bbox_json`, `page`, `engine`, `confidence`, `status`, `reason`, `mapping_rule`, `created_at` | `status` ∈ auto, review, rejected |
| `directive` | `id`, `document_id`, `span_text`, `span_start`, `span_end`, `action_type`, `timing_type`, `time_value`, `time_unit`, `anchor_event`, `condition_text`, `target`, `anchor_date`, `due_date`, `state` | `state` ∈ open, done, superseded, unknown_date |
| `medication` | `id`, `patient_id`, `brand_raw`, `salt`, `dose`, `freq`, `start_date`, `status`, `reported_at`, `source_doc_id` | `status` ∈ prescribed, reported_stopped, reported_ongoing |
| `handwriting_field` | `id`, `document_id`, `page`, `bbox_json`, `field_type`, `model_top1`, `candidates_json`, `human_value`, `action`, `ms_to_verify`, `status` | `action` ∈ accept, correct, reject, add; `status` ∈ review, resolved |
| `egress` | `id`, `document_id`, `payload_sha256`, `model_id`, `prompt_version`, `schema_version`, `outcome`, `reason`, `ts` | One row per attempt, including refusals |
| `audit` | `id`, `entity`, `entity_id`, `field`, `old`, `new`, `actor`, `ts` | Append-only |
| `jobs` | `id`, `document_id`, `state`, `page`, `total`, `error`, `ts` | `state` ∈ queued, running, done, failed |
| `submissions` (approved operational addition) | Public job identity, patient owner, patient-scoped hash, private spool identity/bytes, consent snapshot, requested overrides, pending/preparing/terminal outcome, nullable prepared document link/count, batch position, preparation manifest/progress, cleanup intent/state, `spool_deleted_at` | Exists before clinical document; promotion links to same-ID job; no extracted clinical facts in queue/telemetry. Exact layout is planned in `tasks/plan.md` §12 |
| `stage_batches` (approved operational addition) | Frozen submission membership/order, coordinator ownership/attempt, workset document membership/page counts, durable checkpoints, bounded stage measurement summaries | Operational only; no rewrite of accounts, clinical rows, human reviews, or existing jobs |

Data rules:

- DR-01: `collection_date` and `doc_date` are separate and may differ.
- DR-02: The printed reference range is stored per observation and is immutable after ingestion.
- DR-03: Original extracted values survive every correction.
- DR-04: Rejected observations are retained for evaluation but excluded from all charts and summaries.
- DR-05: Uploads are gitignored and never committed.
- DR-06: A projection contains no free text, date, identifier, or patient linkage; this is a property of the schema, not of a filter.
- DR-07: Preserve existing `document.page_count >= 1` and positive prepared `jobs.total`/non-null document references. Pending submissions are not fake documents. Raw spool cleanup records confirmed absence, not intended deletion; operational rows/artifacts follow owner erasure and do not resurrect deleted jobs/patients. Stage artifacts containing OCR/model data remain private medical data, never operational logs.

### 3.5 External interface requirements

#### 3.5.1 HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/patients` | Create patient alias |
| DELETE | `/api/patients/{id}` | Erase all rows and files for one patient; writes one audit row |
| POST | `/api/documents` | Multipart upload plus `doc_date`, `collection_date`; returns 202 with `job_id` |
| POST | `/api/documents/{id}/consent` | Record consent scope or cloud redaction approval |
| GET | `/api/documents/{id}/redaction-preview` | PII-redacted JPEG previews awaiting cloud approval |
| GET | `/api/jobs/{id}` | Job state and progress |
| GET | `/api/patients/{id}/summary` | Whole dashboard payload with longitudinal summary |
| GET | `/api/patients/{id}/clinical-summary` | Standardized longitudinal clinical summary |
| POST | `/api/patients/{id}/clinical-summary/refresh` | Refresh standardized clinical summary (optional use_cloud) |
| POST | `/api/patients/{id}/cloud-consent` | Record patient-level cloud consent in audit |
| GET | `/api/patients/{id}/observations?analyte=` | Deep view |
| GET | `/api/documents/{id}` | Metadata, boxes, image URL, consent and egress state |
| POST | `/api/observations/{id}/review` | Accept, correct, or reject; writes audit |
| POST | `/api/medications/{id}/report` | Patient-reported stopped or ongoing |
| GET | `/api/patients/{id}/directives` | Directives with timing and source |
| GET | `/api/documents/{id}/handwriting-fields` | Field boxes and candidates |
| POST | `/api/handwriting-fields/{id}/review` | Accept, correct, reject, or add |
| POST | `/api/share` | Create a PIN-protected share |
| GET | `/api/share/{token}` | Resolve a share token |

Contract rules: OpenAPI is the source of truth; the summary payload is frozen in Week 2; no observation-bearing endpoint returns a value without its box and document ID. Additions are permitted after Week 2; breaking changes are not.

Approved Phase 1 pre-intake extension: `POST /api/documents` returns 202 with a stable `job_id`, null `document_id`/`pages`/`total_pages`, and pending-intake stage. `GET /api/jobs/{id}` resolves owned submissions as well as historical jobs; unknown legacy `total` is null only for the new states (FR-JOB-08). Existing prepared duplicate-document responses are preserved; active submission duplicates resolve to the existing pending job without creating a second spool or processing run. Coordinated clients must tolerate null counts/no document until promotion; compatibility tests are required before shipping. No raw-download endpoint is added.

#### 3.5.2 Resolver interface (text only)

| Item | Requirement |
|---|---|
| Input | A projection object: vocabulary tokens, numbers, `roi_id`s, schema version. No image, no free text |
| Output | JSON validated by Pydantic: `{ "assignment": { "<roi_id>": "<analyte_id>" }, "abstain_reason": string \| null }` |
| Providers | `local_rules` (default, no network), `self_hosted` (open weights), `sarvam`, `gemini` (synthetic corpus only) |
| Fast model | `gemini-3.8-flash` |
| Escalation model | `gemini-3.8-flash-high` (`thinking_level="high"`) |
| Retries | At most one, on null, validation failure, or low confidence |
| Cache key | SHA-256 of canonical projection JSON + prompt version + schema version + model ID |
| Timeout | 30 s per call |
| Fallback | Review queue with reason `resolver_unavailable`; never a guessed value |
| Logging | One `egress` row per attempt; payload content never logged |

Illustrative response contract:

```json
{
  "assignment": { "r1c2": "hemoglobin", "r2c2": "platelet_count" },
  "abstain_reason": null
}
```

#### 3.5.3 Local interfaces

| Interface | Requirement |
|---|---|
| Filesystem | Uploads, cached responses, and exports under configured paths; uploads outside the static root |
| SQLite | Single file; foreign keys enabled; WAL mode; one writer |
| OCR | Historical Paddle baseline retained as decision history; Phase 1 preserves current configured RapidOCR/Paddle and text-layer path in explicit CPU children (FR-EXT-01, FR-RUN-03) |
| Local Qwen | Coordinator-owned `llama-server` only for the existing verification path; active session endpoint, finite workset lifetime, no unowned-port reuse |
| Spool | Restricted `data/spool/`, excluded from static roots/backups; ephemeral lifecycle and confirmed deletion per FR-ING-11 |
| Build | `npm run build` output mounted by FastAPI at `/` |
| Profiles | `local-gpu` (full) and `demo` (synthetic corpus, uploads disabled, egress disabled, read-only) |

### 3.6 Organizational requirements

| ID | Requirement | Pri | Ver |
|---|---|---|---|
| OR-01 | Ethics approval shall be filed before any real document is collected. | M | I |
| OR-02 | The consent form shall disclose that a typed projection derived from the document may be processed by a third-party service, and shall name the categories of data excluded. | M | I |
| OR-03 | Corpus release and demo artifacts shall be manually de-identified; no automated redaction shall be relied upon. | M | I |
| OR-04 | Annotations and released data shall be de-identified and shall not permit re-identification. | M | I |
| OR-05 | The intended-use statement shall appear on screen 1, in the report, and in the demo. | M | I |

---

## 4. Verification and acceptance

### 4.1 Acceptance thresholds

| What | Set | Metric | Threshold |
|---|---|---|---|
| Field extraction | 40 printed docs | Field F1, CER, per template | F1 ≥ 0.90, CER ≤ 0.05 |
| End-to-end | 40 printed docs | Correct value + field + unit | ≥ 0.85 |
| Material errors | 40 printed docs | >10 percent off or wrong unit reaching `auto` | ≤ 2 percent |
| Risk–coverage | 40 printed docs | Accuracy at 100, 90, 80 percent coverage | Deferring 10 percent gains ≥ 5 points |
| Gate detection | Injected corruptions | Recall, false quarantine | ≥ 0.80, ≤ 0.10 |
| Normalisation | Truth set | Correct analyte and canonical unit | ≥ 0.95 |
| Medications | 40 printed docs | Brand + dose + frequency F1 | ≥ 0.80 |
| Directives (printed) | 150 notes | Span F1, timing accuracy, date exact | ≥ 0.75, ≥ 0.80, ≥ 0.70 |
| Annotation | 30 notes | Cohen's kappa | ≥ 0.70 |
| Handwriting assist | 25 notes | Top-3 containment, taps/note, s/note, false-accept | ≥ 0.85, ≤ 9, ≤ 50, ≤ 5 percent |
| Handwriting safety | 25 notes | Auto-accepted handwritten fields | **0**, by construction |
| Resolver value | 40 printed docs | Review items per document, disabled vs enabled | Shrink ≥ 30 percent or module removed |
| Clinician view | 5 users | Time to "what changed since last visit" | < 60 s |
| Unsupported claims | Rendered UI | Citation coverage | 100 percent |
| Usability | 5–8 users | Time-to-answer versus paper folder | Beats folder |
| Reproducibility | Full harness | Numbers regenerated offline from cache | 100 percent |

### 4.2 Traceability matrix

| Requirement group | Module | Primary test | Reported metric |
|---|---|---|---|
| FR-ING, FR-JOB | `smriti/ingest.py`, `api/routers/jobs.py` | `tests/test_ingest.py` | Quality-gate rejection rate |
| FR-JOB-09 | `api/routers/jobs.py`, `Queue.jsx`, `App.jsx`, `navigation.js` | `tests/test_jobs.py`, `Queue.integration.test.jsx`, `App.system.test.jsx`, `navigation.unit.test.js` | Owner isolation, bounded lists/history, navigation/reload/source-page routes, polling/session/terminal behavior |
| FR-ING-11, FR-JOB-08, FR-RUN, NFR-18, DR-07 | `runtime-stages`: intake, stage coordinator, OCR/VLM, job API/UI | Planned `tests/test_runtime_stages.py`, `tests/test_runtime_telemetry.py`, intake/jobs/DB/UI regressions (`tasks/plan.md` §§12–13) | Confirmed spool/tree cleanup, bounded internal windows with no upload page cap, complete-document semantics/publication, actual timing/RAM/VRAM, explicit unavailable readings; no clinical accuracy claim |
| FR-EGR | `smriti/egress.py`, `smriti/projection.py` | `tests/test_egress.py` | Zero image egress; review-queue shrink |
| FR-EXT | `smriti/ocr.py`, `smriti/extract.py`, `smriti/engines.py` | `tests/test_extract.py` | Field F1, CER, cache-hit rate |
| FR-ASM | `smriti/extract.py` | `tests/test_assembly.py` | Auto-accept precision |
| FR-NRM | `smriti/normalize.py` | `tests/test_normalize.py` | Analyte and unit accuracy |
| FR-SAF | `smriti/checks.py` | `tests/test_checks.py` | Gate recall, false quarantine |
| FR-REV | `api/routers/review.py`, review UI | `tests/test_review.py` | Correction rate, audit completeness |
| FR-TIM | `api/routers/patients.py`, dashboard | `tests/test_summary.py` | Payload time, citation coverage |
| FR-DIR | `smriti/directives.py` | `tests/test_directives.py` | Span F1, timing, date exact, kappa |
| FR-MED | `smriti/medications.py`, medication UI | `tests/test_medications.py` | State separation violations = 0, med F1 |
| FR-HWR | `smriti/candidates.py`, `FieldReview.jsx` | `tests/test_candidates.py` | Taps, top-3, false-accept |
| FR-SHR | `api/routers/share.py` | `tests/test_share.py` | Lockout, expiry, audit rows |
| FR-EVL | `eval/run_eval.py` | `tests/test_eval_smoke.py` | Offline reproducibility |
| SI-01 to SI-10 | All | `tests/test_invariants.py` | Violations = 0 |

### 4.3 Test strategy

1. **Unit tests** for pure functions: normalisation, gates, date arithmetic, projection schema, schema validation.
2. **Invariant tests** for SI-01 to SI-10, run in CI on every commit.
3. **Fixture tests** on a frozen 5-document mini set covering clean, skewed, shadowed, compressed, and handwritten.
4. **Contract test** validating `summary.json` against the Pydantic schema.
5. **Evaluation run** only on the full truth set, offline, from cache.
6. **Usability sessions** in Week 13 on both modes.
7. No test shall call the network. A network call in CI is a failure.

---

## 5. Project constraints

### 5.1 Milestones

| Week | Deliverable | Gate |
|---|---|---|
| 1 | Synopsis, intended-use statement, ethics filed, consent with OR-02 | Ethics submitted |
| 2 | Frozen contract; `summary.json`; response cache; handwriting OCR probe; preprocessing A/B | Contract locked, probe decided |
| 3 | Quality gate, perspective, deskew, page split; Vite shell on fixtures | 20 documents available |
| 4 | PP-OCRv6 baseline and CER; eval harness skeleton; annotation guide v1; 40 docs confirmed | CER measured on 10 docs |
| 5 | Local field assembly and review backend; upload and job UI; directive grammar v1 | One printed document end to end |
| 6 | M1 eval; review queue UI; medication lexicon from corpus | Printed end-to-end measured |
| 7 | Arithmetic, plausibility, swing gates; timeline and reference bands | Gates measured |
| 8 | Normalisation; source overlay; resolver value experiment; handwriting go/no-go | ≥ 0.85 end-to-end, resolver ≥ 30 percent or cut, handwriting cut if either fails |
| 9 | Handwriting assist (if green): segmentation, ranking, field review UI | No handwritten `auto` |
| 10 | Handwriting metrics and failure taxonomy; medication extraction | Taps, top-3, false-accept reported |
| 11 | Directive evaluation; reminders and clinician mode | Span F1 ≥ 0.75 |
| 12 | Risk–coverage, material-error rate, resolver table; numbers frozen | All numbers reproducible |
| 13 | Bug pass; usability sessions | Usability data in hand |
| 14 | Seeded demo DB; 4-minute video; rehearsal | Video recorded |
| 15 | Report writing | Draft to guide |
| 16 | Polish, viva prep, submission | Submitted |

If the schedule slips, cut in this order: handwriting assist, clinician-view usability study, share link, medication extraction depth. Never cut the end-to-end number or any safety invariant.

### 5.2 Risk register

| ID | Risk | Trigger | Mitigation | Fallback |
|---|---|---|---|---|
| RISK-01 | Ethics approval delayed | Week 2 | File in Week 1; prepare synthetic corpus in parallel | Synthetic plus 10 real; report the gap |
| RISK-02 | Third-party terms still block derived-data egress | Any time | Local-only default; projection, not document; OR-02 consent | Local rules only; resolver on synthetic |
| RISK-03 | Free-tier model retired or quota changed | Any time | Pin IDs; cache; record versions | Local-only mode; cache replay |
| RISK-04 | Wrong anchor date yields a wrong reminder | `collection_date` null > 30 percent | Two-date UI; unknown state | Display "date unknown"; never guess |
| RISK-05 | Field F1 below 0.80 | Week 6 | Template parsers for the top three labs; rules resolver | Report per-template split as a finding |
| RISK-06 | Directive F1 below 0.60 | Week 11 | Rules-first extraction; relative-only scope | Conditional and PRN to future scope |
| RISK-07 | Fewer than 20 real documents | Week 4 | Start collection Week 1; friends and family consent | Synthetic plus 10 real |
| RISK-08 | Handwriting scope creep | Any time | Week-2 probe, week-8 gate, separate truth set, SI-01 and SI-02 | Delete the module; report the probe |
| RISK-09 | 8 GB machine out of memory | Any time | CPU-only; one model at a time; native venv, no Docker in dev | Precompute demo artifacts |
| RISK-10 | Contract drift breaks the UI | Any time | Pydantic validation of `summary.json` in CI | Freeze payload; regenerate fixtures |
| RISK-11 | Demo fails live | Week 14 | Seeded DB, recorded video, offline mode | Play the video |
| RISK-12 | Perceived as a medical device | Viva | Intended-use statement; static cards; no computed guideline dates | Point to SI-06 and SI-07 |
| RISK-13 | No clinician available to label handwritten pages | Week 4 | Recruit early; pay in thanks, not money | Cut handwriting at week 8 |

### 5.3 Out of scope

Handwriting as an auto-charted source; handwritten numeric values; cloud image processing of real documents; full LOINC; cultures, serology, imaging; handwriting fine-tuning; QLoRA; new local VLM deployment beyond the approved existing Qwen lifecycle; local model comparison as a deliverable; drift, RCV, or CUSUM; guideline-driven scheduling; conflict resolution; encounter clustering; ABDM or FHIR export; RBAC or multi-tenancy; RAG question answering; chatbots; NLI explanations; Indic TTS; clinic mode; prescription dispensing. Phase 1 permits resource measurements of the existing pipeline only, after separate real-record authorization; segmentation, inherited-context migrations, clinical revisions, and broader history redesign remain deferred.

### 5.4 Change control

1. Any change to §3, §4.1, or SI-01 to SI-10 requires agreement from all three members and a version bump.
2. A change that cannot be scored in §4.1 is rejected by default.
3. Requirement deletions are recorded with a reason; they are not silently removed.
4. The contract in §3.5.1 is frozen after Week 2; additions are allowed, breaking changes are not.
5. Thresholds in §4.1 are pre-registered: they are never edited after a result is known.

---

## Annex A — Requirement count

The table records baseline v1.1 counts, not a recount of later intake/account additions. Runtime v1.2 adds FR-ING-11, FR-JOB-08, FR-RUN-01…04 (six functional requirements), NFR-18, and DR-07. v1.4 adds the user-approved persistent owner-only Queue/navigation requirement FR-JOB-09; no safety invariant or acceptance threshold is deleted or relaxed. Smart page selection, a dedicated human-review queue/provenance policy, visit-date improvements and medication reconciliation remain specification work after the user selected “Finish fixes first.”

| Group | Count |
|---|---|
| Functional | 96 |
| Non-functional | 17 |
| Safety invariants | 10 |
| Organizational | 5 |
| Constraints | 10 |
| Data rules | 6 |

---

## Annex B — Engine decision record

| Decision | Choice | Why | Rejected alternatives |
|---|---|---|---|
| Printed OCR | PaddleOCR PP-OCRv6_small, CPU; v5 mobile fallback | Print-EN accuracy 0.933 against 0.860 for v5 mobile; 1.75 s/page and ~2.2 GB peak measured for the v5 mobile class; gives boxes; no GPU; no quota | v5 mobile as primary (lower accuracy); EasyOCR (weaker boxes), Tesseract (weaker on Indian lab layouts) |
| Printed extraction | Rules and template parsers first | Deterministic, free, reproducible, no egress; keeps the headline independent of quota | Cloud-first extraction (couples the headline to a free tier) |
| Egress | Typed projection of extracted values | Provably free of identifiers by construction; an allowlist can be tested, a redaction cannot | Redacted page images (irreversibility unprovable; DPDP risk) |
| Remote resolver | Gemini 3.5 Flash-Lite, escalate to 3.8 Flash; self-hosted and Sarvam behind the same interface | Document-parsing positioning, structured output, free tier, India availability, stable IDs | Vision-model page transcription (requires image egress); Groq (terms unverified) |
| Handwriting | Constrained assist: PP-OCRv6 text, fuzzy plus phonetic ranking against a weighted candidate set, mandatory human gate | Turns an open-vocabulary transcription problem into a small ranking problem; requires no new model; fails safely to a search box | Cloud VLM page transcription (image egress); handwriting fine-tune (needs GPU and thousands of lines); local 2B VLM (CON-02, 8 GB machine); PP-OCRv5 mobile handwritten English recognition measured at 0.4944, insufficient alone |
| Directive extraction | Rules-first, remote resolver for the ambiguous minority | Minimises egress; keeps spans exact | Cloud-only extraction (more exposure, worse offsets) |
| PDF and boxes | Local normalised coordinates | Survives resize; single convention | Pixel coordinates |
| Storage | SQLite, WAL, one writer | Fits 8 GB and every free tier; 40 documents is not a scale problem | Postgres (no free tier fits the measured 2.2 GB pipeline peak) |

---

## Annex C — Glossary

| Term | Definition |
|---|---|
| Anchor date | The date a relative directive counts from; `collection_date`, else `doc_date`, else unknown |
| CER | Character error rate |
| Egress | Any transmission of document-derived data to a non-local service |
| Material error | A value more than 10 percent wrong, or a wrong unit, that reached `auto` |
| Projection | A schema-bounded, de-identified representation of extracted values: vocabulary tokens and numbers only |
| Provenance | The stored document, page, and box that a value came from |
| Span | The exact source text of a directive |
| Tap | One human action on one field in the assisted review surface |
| Truth set | The 40-document annotated reference corpus |

---

**Document control**

| Version | Date | Change |
|---|---|---|
| 1.0 | 22 Oct 2026 | Baseline: printed-first, local OCR, cloud on redacted pages only, handwriting as a human-gated measured track |
| 1.1 | 23 Oct 2026 | Egress replaced by typed projection (FR-RED deleted, FR-EGR added); `capture_type` derived server-side; consent table and FR-ING-09; PP-OCRv6_small; handwriting assist with FR-HWR; medication F1 and lexicon coverage; gate tolerances and FR-SAF-06; FR-TIM-09; hashed share PIN; resolver interface rewritten; cut order revised |
| 1.2 | 5 Nov 2026 | User-approved Phase 1 gates: ephemeral raw spool with confirmed success/rejection deletion and crash-only debug retention; additive operational submissions/batches and deferred document/consent/job promotion with null pending totals; pinned psutil/no pynvml and low-overhead nvidia-smi/null telemetry; frozen ≤10 submissions and ≤20-page whole-document worksets. Scoped same-process/no-local-VLM/CPU-only deployment exceptions, Windows tree cleanup, and unified VLM endpoint. Requirements and implementation plan approved; checklist approval/runtime implementation, live migration/restart, real-record processing, and hardware acceptance remain outstanding. |
| 1.3 | 5 Nov 2026 | User approved long-PDF requirements: no document page-count rejection; ≤20 internal windows, bounded per-range preparation deadlines and disk/bookkeeping, one document/job and unchanged complete-document semantics/atomic publication. Revised plan/checklist still require review. Logging scope selected: existing job view, CMD/terminal and local files; observability spec is a draft. Original RT-01–03 evidence remains historical; no live deployment or hardware success claimed. |

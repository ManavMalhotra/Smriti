# SPEC-runtime-stages

## VLM naming cleanup — scope selected, specification awaiting approval

- Objective: the configured model is GLM-OCR; current UI, comments, and documentation must say GLM-OCR or local VLM. Runtime identifiers use model-neutral `vlm` names.
- Reach: coordinator targets/checkpoints, artifact paths and manifests, runtime failure codes, progress/diagnostic allowlists, API responses, React labels, tests/fixtures, and linked documentation.
- Compatibility: accept legacy stage/event/error/manifest names and artifact filenames at read boundaries; emit new names for new work. Preserve checkpoint validation, ownership, source hashes, model identity checks, and cleanup fences.
- Historical data: do not rewrite live SQLite rows, clinical provenance, stored files, or audit history. Display a former engine as a legacy VLM, never claim its readings or benchmark results came from GLM-OCR. Legacy literals may remain only where compatibility requires them and in its regression fixtures.
- Documentation: rename the hardware document to `docs/vlm-hardware.md`, repair links, and retire obsolete model-specific instructions without inventing GLM-OCR measurements. The existing GLM model paths, prompt, quantization, 1024px cap, budgets, and launch flags stay unchanged.
- Style: use existing helpers and plain Python/JavaScript names, for example `vlm_target`, `vlm_loading`, and `vlm_http_error`; no new dependency, service, or schema migration.
- Verify: synthetic regressions must cover legacy progress/failure metadata, interrupted checkpoint recovery, old artifact discovery/cleanup, new-name publication, and frontend labels. Search remaining former-model references and justify every compatibility occurrence.
- Commands: `.venv\Scripts\python.exe -m pytest -q`; `npm --prefix web run test`; `npm --prefix web run build`; `git diff --check`. Use isolated synthetic databases and temporary roots only.
- Boundaries: always preserve validation, cleanup, review, and historical identity; ask before any persisted-data migration or model-setting change; never restart live processing, download models, delete user data, or relabel old clinical readings.
- Open questions: none about selected scope; implementation begins after approval of this compatibility contract.

## Approved §13.9 amendment (2026-11-07)

SRS FR-RUN-19…21 supersede older mandatory printed-Qwen failure policy below. Qwen operational failures with confirmed owned shutdown leave durable per-page `outcome: unavailable`, allowlisted `error_code`, empty fields and the existing source/model identity. Legacy valid artifacts without `outcome` mean `read`. Any unexplained missing page or corrupt outcome still fails validation. Freeze all missing printed pages of affected documents, keep valid readings and OCR, and cross-check even when no model fields exist so unmatched OCR gets review provenance without confidence inflation. Disabled Qwen also annotates printed OCR-only fields. One final clinical save stays review-required.

Qwen requests alone resize to long edge 1280, never overwrite/upscale canonical images; 4096 context/2048 tokens/240s, Q8 KV, CPU mmproj, six threads, no warmup and one slot. No automatic model/flag fallback or download. Unexpected supervisor interruptions retain named ownership for validated recovery; true cleanup/checkpoint/source corruption fences stop admission. Worker retries are interruptible, exponential 1–30s, at most ten consecutive failures; reset only after a successful processing/idle cycle. Recovery revalidates source/page artifacts and candidate identity before announcing resumption.

After all missing outcomes are durably frozen and existing artifacts validated, exclude that document from further Qwen windows. A child that consistently fails even before inference must not create an unbounded loop over already degraded work; unaffected frozen members still run.

Implementation reaches config/VLM, page store/model/helper/coordinator/service, diagnostics/progress/API/Queue, tests and docs. Verification is synthetic only; references and limits are in `docs/qwen-hardware.md`.

| | |
|---|---|
| Module | `runtime-stages` |
| Status | Post-critique MVP implementation directed under `tasks/plan.md` §13.7; staged runtime connected, synthetic result ledger in `tasks/todo.md`; hardware/clinical/live-rollout acceptance remains open |
| Scope | Hardware-safe intake, OCR, rules and printed-page Qwen with explicit degraded review under §13.9 |
| Depends on | Existing account/consent boundary, intake helpers, OCR adapters, VLM adapter, SQLite artifacts, processing UI |
| Requirements authority | `docs/SRS.md` v1.3; original plan in `tasks/plan.md` §12, subsequently authorized long-PDF/MVP resolutions in §13.7 |

Approved scope change: PDFs have no page-count admission rejection; §8 replaces the earlier upload/whole-document cap with bounded internal windows. The user subsequently directed implementation under §13.7 without another approval loop. Earlier pending-review statements/four-gate records remain historical evidence, not current blockers. User-visible activity and operator file/terminal diagnostics are scoped in `SPEC-observability.md`. The implemented v1 checkpoint resumes validated missing work; unknown historical v10 shapes remain fenced for separately authorized recovery.

## 1. Objective and assumptions

Stop concurrent rendering and resident OCR runtimes from competing with Qwen on the local Windows 11 / Ryzen 5 5600H / 8 GB RAM / GTX 1650 4 GB machine. Preserve existing extraction semantics while replacing resource-lifetime assumptions with supervised process boundaries and measured telemetry.

The user's first-phase contract selects bounded intake, finite batches, disposable stages, and hardware measurements. This spec does not approve the broader medical-history redesign.

- Keep FastAPI, React/JavaScript, SQLite, one coordinator, PyMuPDF, existing OCR weights, and the existing local `llama-server`/Qwen model.
- Keep current upload byte/pixel limits, 300-DPI rendering, normalization parameters, hard quality gates, and PDF text-layer validation. Remove document page-count rejection under §8; ≤20 is an internal execution ceiling only. Resolution or threshold tuning follows measured evidence and separate approval.
- Keep Qwen reading or explicit durable unavailable outcomes for eligible printed pages, handwritten numeric exclusion, and handwritten-page skipping. A failed or skipped verification is not a successful independent reading.
- Freeze upload identities before rendering; page totals are unknown until the background inspection establishes them.
- New uploads may spool while inference runs, but may not start image decoding, rendering, normalization, or an OCR runtime.
- Stage checkpoints contain processing artifacts, not partially published clinical facts. Preserve transactional final writes per document. No new clinical schema, revision model, split/merge, or publication policy in this phase.

## 2. Submission and bounded intake contract

### HTTP boundary

`POST /api/documents` retains authentication, same-patient ownership, consent validation, supported-type checks, and byte-limit enforcement. Stream bounded chunks from `UploadFile` to an application-owned private staging file; do not read the entire upload into a bytes object or decode images in the request handler. Multipart parser limits and concurrent spoolers must also be bounded; moving only rendering does not bound HTTP memory or disk consumption.

Compute the existing patient-scoped content hash incrementally. Do not use the filename as a path or change duplicate identity. A duplicate active submission resolves to its existing identity; a duplicate prepared document preserves existing duplicate behavior. Finalize the staging file and durable submission record before returning 202. A disconnect, disk-full error, or duplicate race must not leave an accepted job pointing to a missing file.

Accepted means stored for background inspection, not validated as a readable PDF or processed. A PDF decode, password, dimension, quality or operational capacity failure discovered later becomes a specific terminal intake outcome in the job API/UI, not a retroactive HTTP rejection. New intake must not reject solely for page count; old page-limit outcomes remain readable.

Use additive `submissions` and `stage_batches` operational storage. Keep the existing `document.page_count >= 1`, non-null `jobs.document_id`, and positive `jobs.total` invariants. Create the clinical `document`, its consent, and the existing `jobs` row only after successful preparation, in one short transaction that links the submission to them. Submission ownership and consent scope/version/grant time must be durable before preparation; transfer consent without inventing a later grant time and recheck that it is still valid at promotion.

Before promotion, the durable public `job_id` identifies the submission. `GET /api/jobs/{job_id}` returns `document_id: null`, `total_pages: null`, and `stage: "pending_intake" | "preparing"`. The legacy response fields `id`, `state`, `page`, `total`, `error`, and progress remain present: unknown `total` is null, never 1 or 0. Keep `pages: null` on the upload response and do not expose source links. At promotion keep the same public job ID and populate document/count fields. Historical jobs retain their existing field values; additive fields must not fabricate missing telemetry. Nulls for the new pre-intake states are an approved contract extension requiring coordinated API/UI/fixture updates, not a claim that old clients already support them. Deterministic rejection before promotion remains a terminal submission/job response with no clinical row.

### Background preparation

Open the staged file in an isolated preparation process. Validate the PDF manifest/page count, then decode or render, measure, normalize, and save one page at a time. Enforce pixel limits before allocation where possible. Close page/pixmap/image buffers before moving to the next page; retain only bounded metadata, not whole-file image/NumPy lists.

Use private application-owned staging directories, atomic file finalization, stable original-page numbering, normalization identity, and content hashes. File and database checkpoints must be recoverable after a crash. Never declare preparation complete until all required page files and the manifest are durable. A file written without a matching committed checkpoint is not reusable by inference.

### Strictly ephemeral spool and confirmed deletion

Raw bytes may exist only in restricted `data/spool/` (or the equivalent isolated test root), excluded from static serving, exports, backups, and git. Apply the same privacy/lifetime controls to multipart temporary files and partial uploads. Normalized page images remain the canonical OCR/crop/review coordinate space; retain current image encoding and preparation parameters. Permanent original-file archival and download are rejected for Phase 1.

- After all normalized pages and their manifest/checkpoints are durable and successful preparation is committed, close raw-file handles and immediately unlink the raw spool. A completed early window does not establish complete preparation. After a deterministic rejection, first commit its terminal status and safe error code, then close handles and immediately unlink. Rejections include byte/pixel limits, password protection, corrupt/invalid format, and hard quality failure, not page count. Never retain these for debugging.
- Unexpected parser/renderer crashes (`exit_reason: "error"` with a crash category) may retain the failed raw spool **only** with explicit `DEBUG_RETAIN_FAILED_SPOOL=1`, default off. Timeouts, cancellations, normal errors, and deterministic failures do not qualify. Record debug retention explicitly; it remains private, excluded from backups, quota-accounted, and subject to owner erasure. No implicit archive or silent indefinite retention of ordinary failures.
- `spool_deleted_at` is set only after confirmed absence following unlink (or a recovery check confirming a prior unlink). Preserve the processing/rejection outcome separately from `spool_cleanup_state: pending | deleted | failed | debug_retained`. Failed removal records a safe reason and recoverable pending cleanup, not a deletion timestamp or success event. Windows locked files require retry after child-tree exit, not suppressing the failure.
- Persist cleanup intent with the preparation/rejection transaction. Recover both crash windows: committed outcome before unlink, and unlink before the deletion timestamp commit. Retry scoped removal before admitting more expensive work; unresolved cleanup blocks further admission rather than accumulating raw files. Preparation artifacts remain usable; cleanup recovery is not clinical reprocessing.
- Disconnects, disk-full, duplicate races, and incomplete spool writes also close/unlink owned partial files. Reconcile only application-generated paths recorded for this intake; never delete existing clinical images or unrelated files. Remove owned incomplete normalized preparation files on rejection without touching valid document sources.

## 3. Batch and process contract

### Finite admission

In a short SQLite transaction, atomically claim up to `MAX_BATCH_SUBMISSIONS = 10` pending submissions in stable order and assign a durable `batch_id`. A second coordinator cannot claim the same active batch. Freeze membership; later uploads wait for the next batch, even if some frozen submissions reject.

Prepare one frozen submission at a time to establish exact page counts, without an upload page-count limit. After preparation/cleanup barriers, pack short documents into ≤20-page whole-document worksets in frozen order: 15+15 becomes 15 then 15; 14+12 becomes 14 then 12. A longer document runs alone in consecutive ≤20-page windows: 39 becomes 20 then 19; never fill its last window with another document. Do not reorder for bin-packing or fill spare capacity with new arrivals.

Long documents may span planned OCR/Qwen lifecycles, but not logical document/context or publication boundaries. Complete their OCR windows, derive existing complete-document routing/rules, then run eligible Qwen windows and perform one final clinical save. Confirm each tree's exit before the next expensive stage; finish the current long document before advancing to another document/workset. Configuration caps the internal window, not total uploaded pages. Empty/rejected snapshots complete without loading models. Section 8 owns deadline, storage and semantic-equivalence acceptance.

### Lifecycle

Execute expensive preparation and OCR stages in disposable Windows `spawn` children; the Qwen stage owns a managed `llama-server` subprocess. The coordinator invokes existing rules over persisted OCR artifacts without retaining an OCR instance. Keep the current classify/extract/verify ordering and prompts unchanged in this systems-only phase.

1. Admit one expensive stage; do not overlap preparation, primary OCR, fallback OCR, or VLM runtime lifetimes across batches.
2. Pass identifiers, paths, and immutable settings to children, not SQLAlchemy engines, image arrays, or live model objects. Children construct and close their own database connections.
3. Set `os.environ["CUDA_VISIBLE_DEVICES"] = ""` inside each OCR child before importing model runtimes. Explicitly configure ONNX CPU execution and the existing four intra-op threads; select Paddle's installed-version CPU device (`device="cpu"` or `use_gpu=False`, as supported). Validate actual providers/device. Hiding CUDA devices alone is not proof of CPU-only execution.
4. Import ONNX/Paddle model libraries only inside the isolated execution path. No coordinator-owned OCR singleton; a child-local reusable OCR instance is permitted within its stage.
5. Write and commit each completed page artifact immediately, with engine/model and render/preprocess identity. Close the transaction before the next model call. Preserve independently versioned artifacts rather than reading an arbitrary newest cache entry.
6. Supervise with a hard monotonic deadline, cooperative shutdown where possible, then terminate, wait at most 5 seconds, kill, and wait at most another 5 seconds. These are bounded tree-wide escalation waits, not unbounded waits per descendant. On Windows assign the tree to a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, or use `psutil.Process(proc.pid).children(recursive=True)` with child-first termination/kill and verified exit of all owned processes. A wrapper's exit or `proc.terminate()` alone is not tree cleanup. The plan selects kill-on-close Job Objects as the primary Windows guard, attached before children can create descendants; handles must not be inherited by children. Track process identities to avoid killing a reused PID. Job Object assignment failure stops the stage; never silently fall back to unsupervised execution. Monitor normal root exit too, so surviving grandchildren cannot hold the next stage hostage.
7. Require `exitcode == 0` for a successful preparation/OCR child, validated committed artifacts, and confirmed owned-tree exit before advancing its checkpoint. Deterministic rejection is an explicit terminal intake outcome, not success. A managed server stopped by the coordinator may have a termination exit code: successful VLM requests/artifacts and verified shutdown are required independently. A successful server shutdown alone does not establish successful VLM requests; operation outcome and cleanup outcome are separate.
8. If exit cannot be confirmed, record cleanup failure and stop admission. Do not start another model on top of an uncertain resident process.

Per-stage deadlines must account for admitted page count and separate Qwen startup/request budgets. Do not silently shorten the existing 30-second startup or 120-second request timeout, or label any timeout OOM without evidence. Tune only after measurement and approval.

The local coordinator must spawn and own Qwen, then terminate/wait for that owned process at stage exit, including errors and cancellation. If the configured local port is occupied by an unowned server, fail with a specific operational error; do not reuse it or kill it. External/remote-server mode and Ollama migration are outside Phase 1.

Require an active session/resolved base URL for every VLM request. Readiness and inference use the same endpoint. Remove the inference fallback to a different global URL; update all callers and lifecycle tests.

Fallback is a separate CPU process, not a second resident stack. Preserve the existing RapidOCR-initialization-failure fallback trigger. New bad-page/low-confidence fallback criteria are not invented here; require separately agreed triggers before expanding behavior. Retain the primary outcome and actual fallback engine identity.

On crash or restart, resume only the incomplete work in a frozen batch, using validated artifacts. Never automatically rerun an existing terminal or reviewed document. Existing accounts, observations, medications, directives, and review/audit decisions remain unchanged. Explicit retries of existing clinical records still require a review-preserving design outside this phase.

## 4. Telemetry and diagnostics contract

Use a bounded stage measurement record in SQLite or an equivalently ownership-controlled local artifact; do not build a general logging platform. Keep coarse job events compatible with `SPEC-processing.md`. Repeated samples are reduced to stage summaries with bounded storage, not unbounded additions to the 500-event UI history.

Record before start, during execution, and after confirmed exit:

| Field | Meaning |
|---|---|
| `batch_id`, `stage_name`, stage attempt | Operational identities; actual preparation/OCR/VLM stage |
| `coordinator_rss_mb` | Coordinator resident working set, not private working set |
| `coordinator_private_bytes_mb` | `psutil.Process().memory_info().private` on Windows if supported; private committed bytes, not RSS/private working set |
| `child_observed_peak_rss_mb` | Maximum sampled child working set; record sampler interval and coverage |
| `system_avail_ram_mb` | Available physical RAM at before/observed minimum/after points |
| `gpu_device_used_mb`, `gpu_device_free_mb` | Device-wide dedicated-memory metrics before/observed peak/after; identify device/backend |
| `pages_processed`, `duration_ms` | Committed page count and monotonic elapsed duration |
| `exit_reason`, `cleanup_outcome` | `ok`, `timeout`, evidenced `oom`, `error`, or cancellation; exit confirmation separately |

Before/after samples alone cannot establish a peak. Use a bounded sampler and label observed peaks honestly. Device-wide GPU use includes Windows/other applications and is not per-child attribution. Missing/unsupported WDDM or GPU readings are null with an availability reason, never zero. Compare after-exit readings to baseline with measured uncertainty; do not assert zero desktop VRAM or exact immediate reclamation. A post-exit allocation that cannot be attributed to Smriti must not be called a leaked Smriti model.

Pinned `psutil` in `requirements.txt` is approved for implementation; do not add `pynvml`. Sample coordinator RSS/private bytes, child RSS, and system available RAM every 1.0–2.0 seconds, recording actual interval/coverage and process identity. Account for owned descendants separately so a Python wrapper is not mistaken for the model's memory; distinguish per-process RSS from tree-wide sampled RSS (shared mappings can be double-counted).

GPU measurement uses installed `nvidia-smi`. Choose one streamed `nvidia-smi --query-gpu=timestamp,memory.used,memory.free --format=csv,noheader,nounits -l 2` process per stage, with a bounded pipe reader, or pre/post queries plus discrete polling **no faster than every 2 seconds** and no overlapping queries. Do not spawn one GPU query per RAM sample. Queries/initial stream readiness have a 3-second deadline; a streamed process's whole lifetime is not limited to 3 seconds. No valid new stream sample within 3 seconds is a stalled measurement, not a fresh zero. Bound buffers, record sample timestamps, and terminate/wait/close the sampler and reader at stage exit, timeout, or driver failure. Sampler children are owned and included in supervision.

Unavailable executable, timeout, unsupported WDDM readings, nonnumeric values, or driver/query failures produce null GPU metrics with `reason: "nvidia_smi_unavailable_or_timeout"`. Partial sample coverage is identified; do not reuse stale readings as current before/after values. Monitoring failure must not prevent shutdown or turn successful processing into a fabricated hardware result.

No medical values, document text, patient metadata, filenames, credentials, images, prompts, raw model responses, or unsanitized model stderr in telemetry. Report OOM only from a recognized bounded operational signal, not inference from a timeout. Logs may identify engine versions, image dimensions, counts, request token budgets, process exit codes, and numeric hardware measurements.

For `/v1/models` 404 only, record the observed client host/port and a recognized user-agent family plus an opaque fingerprint; omit unknown raw user-agent text. Arbitrary request headers are untrusted and may contain sensitive text or log-control characters. Never log cookies, authorization, query strings, or request bodies. This is a diagnostic clue, not proof of the responsible process; no general request-dump middleware.

## 5. Files, style, and executable checks

Affected boundaries: `api/routers/documents.py`, `api/routers/jobs.py`, `smriti/ingest.py`, `smriti/preprocess.py` callers, `smriti/ocr.py`, `smriti/stage.py`, `smriti/worker.py`, `smriti/vlm.py`, `smriti/config.py`, `smriti/db.py`, operational migrations, and existing job telemetry. Update `web/src/pages/Intake.jsx`, `web/src/components/JobProgress.jsx`, associated fixtures/tests, and API/runtime/privacy documentation for unknown counts and deferred rejection. Do not change dashboard clinical aggregation or `smriti/summary.py`.

Keep adapters and helpers small and consistent with existing Python/JavaScript style. Configuration stays in `smriti/config.py`; runtime entry points must be spawn-safe. Supervision records distinct operation and cleanup errors. No new queue service, Redis, Celery, HTTP client wrapper, model package, or renderer dependency.

Example boundary shape (contract illustration, not an implemented API):

```python
with engine.begin() as conn:
    save_stage_artifact(conn, content_hash, page, stage, model_version, artifact)
# No inference while the transaction is open.
```

Existing executable regression commands, run separately from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ingest.py tests/test_worker.py tests/test_ocr.py tests/test_vlm.py tests/test_jobs.py tests/test_job_progress.py tests/test_db.py tests/test_system.py -q
npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/JobProgress.unit.test.jsx src/test/App.system.test.jsx
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test
npm --prefix web run build
git diff --check
```

Supervision/telemetry tests and an isolated benchmark command are planned in `tasks/plan.md` §12; new commands are not implemented yet. No command here authorizes live-record processing.

## 6. Acceptance and testing

- **Spooling:** synthetic upload during a fake VLM stage reaches durable pending intake with unknown pages; no renderer/model import or execution occurs in the HTTP path. Oversize input, disconnects, disk-full, duplicate races, and another account's access fail safely.
- **Preparation:** multi-page fixtures retain at most one page's buffers, preserve existing quality/text-layer/handwriting outcomes, and expose precise deferred failures. Successful preparation atomically creates document/consent/job with the same public job ID; failures create none. No fabricated page totals or broken source links.
- **Spool privacy:** success, deterministic rejects, timeout/cancel, and ordinary failure delete raw/partial spools; only an unexpected parser/renderer crash with the explicit debug flag may retain one. Test both commit/unlink crash windows, locked-file deletion failure/retry, actual `spool_deleted_at`, backup/static exclusion, and owner erasure.
- **Admission:** continuous new submissions cannot alter or indefinitely extend a frozen batch. Competing coordinators cannot duplicate claims. Test 10-submission cap, ≤20 internal windows, 21/39/41-page documents, 20+1, 15+15, 14+12, mixed rejects and all-rejected snapshots; range boundaries never split clinical context or publication.
- **Isolation:** a real synthetic spawned process exits before another stage enters; timeout/error/cancellation tests confirm cleanup escalation, bounded waits, descendant cleanup, and no advancement when cleanup is unconfirmed. Coordinator does not retain/import model runtimes.
- **VLM ownership:** busy unowned port fails without termination; owned startup/inference/cleanup failures are distinguishable; custom session endpoint is used for both readiness and inference. No silently optional verification.
- **Recovery:** a crash after page N preserves N committed artifacts, resumes only missing work, and cannot publish an incomplete document or modify previously reviewed clinical rows. Test artifact-version mismatch and interrupted file/database finalization.
- **Telemetry:** deterministic fake sampler tests distinguish RSS/private bytes, descendant RAM, observed peaks, absent metrics, stage operation/cleanup outcomes, and actual engine identity. Verify 1–2s RAM / ≥2s GPU intervals, 3s query/stall deadline, unavailable-reason nulls, bounded stream buffers, and sampler exit on every path. Privacy sentinel tests reject raw medical/model/header content in telemetry and narrow diagnostics.
- **UI:** unknown totals are indeterminate; pending intake, rendering, later quality/capacity failure, model failures, and readiness to review stay distinct. Keep full-document page counts across windows and historical page-limit errors readable. Polling survives navigation/reload/account boundaries and stops on terminal outcomes. Preserve keyboard and reduced-motion behavior.
- **Real hardware evidence:** after separate authorization, use 3-5 selected multi-page PDFs in an isolated database/upload directory, with the live worker stopped so it cannot contend. Compare identical settings/corpus with a pre-change baseline where safely available. Report workload dimensions, model/runtime versions, stage durations, observed RAM/VRAM before/peak/after, and all failures. Do not infer clinical accuracy, universal stability, or causality from this small sample.

## 7. Boundaries and approval record

**Always:** preserve accounts, stored records, reviewed facts, current trust rules, hard input validation, ownership/consent, truthful progress, and scoped cleanup of owned resources. Preserve metadata privacy and canonical normalized-page coordinates; no inverse-transform browser overlay work in this phase.

**Ask first:** implementation plan and task checklist before coding; changes beyond the approved additive storage/null-count contracts, pinned `psutil`, and ephemeral spool policy; stage deadlines and changes to approved page/submission budgets or DPI/quality; live restart/migration; any real-record benchmark or reprocessing. Dependency installation occurs only in the later authorized implementation environment, not during this documentation task.

**Never:** reset data; overwrite reviewed extraction rows; silently reuse/kill an unowned server; change GPU driver policy; add remote inference; publish unverified drafts; enable handwritten vision crops; change segmentation/extraction prompts or clinical semantics under this systems fix.

All four original gates were approved by the user on **2026-11-05**. The subsequent approved §8 requirements supersede gate 4's page-count/whole-document lifecycle policy; the table preserves the original decisions, not current long-PDF acceptance:

| Gate | Approved contract |
|---|---|
| 1 — retention | Strictly ephemeral restricted `data/spool/`, excluded from static serving/backups; unlink after durable preparation or deterministic rejection, confirmed `spool_deleted_at`; crash-only debug retention opt-in. Permanent archival rejected. |
| 2 — operational staging | Additive `submissions`/`stage_batches` (or equivalent operational staging); defer document creation and preserve positive counts; pending/preparing job responses have null document/page totals. |
| 3 — measurement | Pinned `psutil`, no `pynvml`; 1–2s RAM and streamed/≥2s GPU measurement with 3s deadlines and explicit null/unavailable reasons. |
| 4 — admission | Freeze ≤10 submissions, prepare sequentially, then pack ≤20-page whole-document worksets; no planned document split across OCR/Qwen lifecycles. |

Deferred architecture contracts: section/table-block verification coverage (including OCR omissions), direct-page evidence separate from inherited identity/date context, boundary-edit context invalidation, source-preserving revisions, and safe medical-history/chart publication. A future boundary edit must retain the original human decision as history while invalidating the affected current context-dependent eligibility; it must not erase that decision or claim its inherited context remains valid. These require their own clinical schema/review specification.

`docs/SRS.md` and `SPEC-intake.md` record these approved exceptions. The user also approved `tasks/plan.md` §12 implementation/storage/API details and initial guardrails, then the checklist in `tasks/todo.md`, on 2026-11-05. Implementation is authorized within that checklist, not completed. Approval is not measured hardware success or permission to migrate/restart/reprocess live records.

## 8. Approved long-PDF requirements amendment — 2026-11-05

Status: **requirements approved by the user on 2026-11-05 (“okay proceed”); revised plan in `tasks/plan.md` §13 awaits review; no changed-contract implementation/checklist approval claimed**. This extends `runtime-stages`/`intake`, not the clinical capability map. Requirements authority is `docs/SRS.md` v1.3 §3.1.16. Sections 1–3/6/7 and `SPEC-intake.md` now reflect approved requirements; retain RT-01–03 historical results and review the revised plan/tasks before changed-contract code.

### 8.1 Objective and explicit assumptions

Accept the user's 39-page PDF, and longer PDFs, without a configured document page-count maximum. Remove the `max_pages`/`SMRITI_MAX_PAGES` rejection policy rather than substituting a larger arbitrary number. Preserve one uploaded document, one public job ID, original page numbering and source links. Internal execution windows must not create additional uploads or clinical reports merely because a window ends.

- “Any length” means **no page-count rejection**, not unlimited bytes, pixels, disk, processing time or guaranteed completion on this hardware. Keep the current 25 MiB default byte limit and 50,000,000-pixel per-page limit, password/format/quality checks, consent and ownership. These resource limits are separate from document length.
- Keep the approved one-coordinator/one-expensive-tree rule, ≤10 frozen submissions, existing models/prompts, 300-DPI rendering, normalization/WebP parameters, CPU OCR/fallback policy, mandatory eligible printed verification and handwritten numeric exclusions/skips.
- Keep ≤20 as a configurable **internal page-window ceiling**, not an upload limit. Large-document windows preserve frozen document order; new arrivals cannot refill or extend the batch. No new queue service or model tuning.
- Preserve all accounts, stored medical facts, human review decisions and uploaded images. Requirements approval does not authorize live startup/migration, cleanup rerun, real-record processing, commit or push.

### 8.2 Intake, disk lifetime and promotion

HTTP only validates and streams bounded chunks to the restricted ephemeral raw spool. Background manifest inspection establishes the complete source-page count without allocating all page images. Pending/preparing document links and public totals remain null until successful promotion under the existing contract; internal source counts may guide supervision without inventing a clinical document.

Prepare and durably checkpoint one page at a time. Release renderer/Pillow/NumPy buffers before the next page. Persist page metadata/quality/text-layer sidecars incrementally; neither the manifest nor the quality payload may require retaining every page's detailed metadata in memory. Store compact durable references/counts and read details in bounded ranges. Maintain the existing public quality/source behavior; serialized JSON limits must not become a hidden maximum page count.

Raw spool quota alone does not bound expanded normalized images and processing artifacts. Account separately for prepared output and private OCR/rules/VLM artifacts, including temporary writes; reserve bounded output capacity before allocation/write, keep a finite free-space reserve, and enforce actual disk-write failures. Capacity failure is a safe, truthful operational outcome with recoverable cleanup, never `too_many_pages`, silently reduced DPI, skipped pages, or a fabricated successful preparation. Numeric disk defaults must be explicit, finite and labeled unmeasured in the subsequent plan; do not imply the current raw-spool settings already enforce this.

Promote document/consent/same-ID job only after **all** required normalized pages and the complete manifest are durable. Retain raw only for this preparation lifetime; delete it after durable complete preparation or terminal rejection/failure under the existing crash-only debug exception. Completing the first window is not permission to delete raw needed for the remaining pages. On later preparation failure, remove only that attempt's incomplete outputs; never delete pre-existing sources or invent a partial clinical document.

### 8.3 Bounded execution and unchanged document semantics

Documents of ≤20 pages may retain the approved whole-document packing behavior. A document larger than the internal cap runs alone in consecutive ranges of at most that cap: 39 pages → 1–20, 21–39; 41 → 1–20, 21–40, 41. Do not fill its last window with another document. Preserve 15+15 and 14+12 as separate short-document worksets. All original pages occur exactly once in the planned ranges; eligible engine page counts may be smaller due to valid artifacts/text layers or recorded handwriting skips.

For a long document, complete and persist the bounded OCR windows, derive the existing document-wide classification/rules/context, then run bounded eligible Qwen windows and final cross-check/publication. A window is a resource-lifetime boundary, **not** a new classification, date/facility, medication, report or directive boundary. Every expensive window requires confirmed owned-tree shutdown before another starts. Initialization-failure fallback remains a separate CPU child with the existing trigger only.

Replace the worker's accumulating `pages`, `texts`, combined-text copies and candidate/VLM lists with bounded reads/private persisted intermediates as needed. Whole-document classification, metadata precedence, report continuation, medication deduplication, prose grounding and directive offsets/cross-page matches must match the current semantics. Do not approximate this by invoking existing document helpers independently on each window. Tests must prove equivalence across a page-20/21 boundary before claiming compatibility; unresolved streaming semantics block acceptance rather than justify silent changes.

Validate all Qwen page outcomes at the **complete-document** boundary: valid empty arrays and explicitly unavailable pages permit OCR-only review under §13.9, not a claim of successful independent reading. One successful window cannot hide a later failure. Persist exact identity-bound page outcomes/engines immediately. No clinical rows or `done` publish after a partial window. Stream validated final candidates into one document transaction; any final-save failure rolls it back.

### 8.4 Supervision, recovery and bounded bookkeeping

Keep preparation's initial 300s guardrail per bounded preparation range (≤20 pages), with a separate finite 300s manifest-inspection budget. A supervisor may own successive range processes or enforce nonextendable range deadlines within one supervised preparation tree; process mechanics belong in the amended plan. A stalled page cannot renew its budget via progress/heartbeats. The user approved this replacement of the former 300s-per-entire-submission contract; it is not a measured performance budget.

Keep OCR `60s + 120s × required pages` and VLM `startup + 240s × missing eligible pages + overhead` default per admitted window under §13.9, retaining finite startup/request wall-clock limits and two tree-wide cleanup waits of ≤5s each. No document-sized model lifecycle. Model startup overhead may grow with windows; measure it rather than promising speedup.

Use bounded durable current-range/cursor summaries plus per-page checkpoints; do not serialize every possible window/attempt/sample into one ever-growing batch JSON array. The existing operational schema limits submissions to 20 pages and batches to 10 worksets, so config/ingest edits alone cannot implement this contract. Extend only operational storage through a reviewed forward upgrade from the existing code schema, preserving fresh/v8/v9/v10 upgrade behavior and all clinical tables/count/ownership/cleanup invariants. Do not rewrite a historical migration to pretend prior schema versions supported long PDFs.

After confirmed prior-owner/tree exit, recover only missing or invalid **new-phase** page/range artifacts with exact identities. After raw deletion, prepared durable pages are the only input; missing sources fail safely. Window checkpoints cannot cause a completed/reviewed/populated clinical document to be replaced. Keep attempt/sample/event history bounded and privacy-safe; progress counts remain document-wide and never reset to zero at a window boundary or imply whole-document completion at 20/39.

### 8.5 Files, style and executable checks

Use the existing Python/JavaScript style and short per-page transactions illustrated in §5; keep environment configuration in `smriti/config.py` and spawn targets importable. Reuse `stage_artifact`, normalized sources and the existing job-progress writer. No new dependencies or generic scheduling framework.

Affected boundaries: `smriti/config.py`, `smriti/ingest.py`, `smriti/stage.py`, `smriti/worker.py`, runtime supervision, `smriti/schema.sql`, `smriti/db.py`, the next verified-free operational migration, intake/job API callers and error mappings. Document-wide helper callers in `smriti/classify.py`, `smriti/extract.py`, `smriti/metadata.py`, `smriti/directives.py`, `smriti/prose.py`, `smriti/reports.py` need bounded-read compatibility without changing clinical decisions. Reach tests/fixtures, environment/deployment instructions, `docs/API.md`, `SPEC-intake.md`, the SRS, plan/checklist and existing Intake/JobProgress only where compatibility requires it. Leave `smriti/summary.py` unchanged.

Run these existing commands separately in the background, using only synthetic inputs/isolated databases/spool/uploads. They are future implementation verification, not claimed results for this documentation change:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_runtime_stages.py tests/test_ingest.py tests/test_text_layer.py tests/test_db.py tests/test_jobs.py tests/test_job_progress.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_worker.py tests/test_extract.py tests/test_metadata.py tests/test_directives.py tests/test_reports.py tests/test_review.py tests/test_system.py -q
npm --prefix web test -- src/test/Intake.integration.test.jsx src/test/JobProgress.unit.test.jsx src/test/App.system.test.jsx
.\.venv\Scripts\python.exe -m pytest -q
npm --prefix web test
npm --prefix web run build
git diff --check
```

### 8.6 Acceptance and testing

- Synthetic valid PDFs with 21, 39 and 41 pages reach same-ID successful preparation without page-count rejection, with exact page files/links/counts. Scheduling-only fixtures cover hundreds/thousands of pages without rendering them or materializing every workset; no claim of real-corpus/hardware success.
- Unit/property-style range cases for 1/20/21/39/40/41 and larger counts prove complete ordered nonoverlapping coverage, ≤20-page windows, unchanged short-document packing, frozen ≤10 membership and no late admission. Fresh and forward-upgrade tests accept >20 prepared pages and more than 10 execution windows without weakening positive clinical counts or overwriting historical data.
- Instrument synthetic page/metadata/artifact readers to assert one live rendered/normalized page and bounded metadata/candidate/window buffers independent of total pages. Test output reservations, expansion beyond raw size, disk-full/locked cleanup and bounded manifest/quality/progress/telemetry storage. Such assertions are not measured RAM/VRAM proof.
- Equivalence fixtures put continued reports, conflicting later dates/facilities, medication duplicates and directives spanning newline/page boundaries around 20/21; compare document-wide routing, fields, source boxes, report ranges, precedence and directive spans with the existing small-fixture semantics. Empty-first-window/later-result Qwen tests preserve document-wide validation; later-window failure never becomes `done`.
- Crash/timeout/cancellation after page 20 preserve valid artifacts, stop/reap owned trees, clean raw only at the permitted lifetime boundary and resume only missing new work. Per-range deadlines remain finite and cannot be renewed by heartbeats. Failure after page 38 and final-transaction failure publish no partial medical rows; terminal/reviewed/populated documents never rerun.
- API/UI fixtures show one job with correct full-document totals, global page 21/39 progress, no window-boundary percentage reset and no early review-ready state. Legacy historical `too_many_pages` outcomes remain safely readable even though new intake no longer emits that policy rejection. Account/consent/ownership, byte/pixel/quality rejection and accessible polling retain their existing coverage.

### 8.7 Boundaries and open decisions

**Always:** validate byte/pixel/quality/privacy/ownership boundaries, retain strict spool deletion and identity-safe supervised cleanup, preserve clinical semantics, test bounded reads and complete-document atomicity, report actual measurements and unavailable evidence.

**Ask first:** live rollout, historical unknown checkpoint recovery, real files/models, hardware calibration, model/DPI tuning and clinical-semantic changes. Changed-contract MVP implementation and provisional storage/decoded-input/native-memory/deadline guards were subsequently selected under §13.7; do not reopen that historical approval loop.

**Never:** merely raise/delete the rejection while the eager HTTP/render/worker accumulation path remains; replace it with a hidden page/manifest/workset cap; silently truncate/skip pages; publish partial clinical facts; reset or overwrite user data; assert arbitrary-length completion, lower RAM/VRAM use or better accuracy without evidence.

Selected MVP decisions: retained byte/pixel limits, ≤20 internal windows, ≤10 frozen FIFO submissions and 300s-per-preparation-range policy. Provisional 2 GiB active-output/1 GiB free-space/decoded-input/native-memory/helper guards and explicit affected-submission capacity failure are recorded in §13.7 and `tasks/todo.md`, not measured hardware fit. RT-22 remains separately authorized. RT-01–03 results remain historical evidence for their original contracts; LP follow-up tests cover the changed implementation.

## 9. Approved adapter/diagnostic/Queue fixes — 2026-11-07

The user selected “Finish fixes first” before specifying new clinical phases. Correct the installed RapidOCR 1.4.4 adapter using its flat constructor options and real detector/classifier/recognizer ONNX session interfaces; enforce existing CPU/four-thread/recognition-batch-one settings and cache the engine only after provider validation. Synthetic stubs prove the adapter call shape, not model performance or hardware fit.

Retain Qwen HTTP/connection/observed-server-exit/transfer and malformed response/output categories through allowlisted runtime vocabulary and committed private diagnostics. HTTP status is bounded metadata; bodies, raw exceptions and uncontrolled output remain excluded. Valid empty arrays permit OCR-only review under §13.9; malformed arrays/items/nonfinite values are failed unavailable readings, not successful emptiness. Code/status survive cleanup in durable failed-operation context.

The owner-only compact Active/Recent listing and `#/queue`/source-page navigation are specified in `SPEC-processing.md` and `docs/API.md` §5. Listing legacy jobs is read-only and must never claim/recover them. No change to schema, model flags/prompts/DPI, isolated ≤20-page lifetimes, frozen ≤10 FIFO submissions, capacity failure, historical checkpoint fence or one final clinical save. `StageResult.success` still requires terminal `ok` plus confirmed cleanup; post-completion nonzero process-finalization exits remain diagnostic, not proof of failed durable work.

Smart page filtering after OCR, clinical confidence thresholds, a dedicated `#/review`/human-verification provenance policy, visit-date improvements and medication reconciliation remain separately specified work. No OCR-only fallback, clinical-policy expansion, live restart/migration, stored-job recovery, real files/models or hardware benchmark is authorized by this fix.

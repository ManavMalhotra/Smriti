# Data Model

Status: draft. Implements SRS §3.4. Schema v11 adds operational staging and relaxes operational page/window counts without rebuilding v9 clinical tables. See `specs/SPEC-runtime-stages.md` and the isolated migration evidence in `tasks/todo.md`. Live rollout is separately gated; schema changes use migrations, not resets.

---

## 1. Entity relationships

```
patient ──1─*── document ──1─*── report ──1─*── observation
  │                │
  │                ├──1─1── consent
  │                ├──1─*── directive
  │                ├──1─*── handwriting_field
  │                ├──1─*── egress
  │                ├──1─*── page_text
  │                └──1─1── job (current)
  │
  ├──1─*── medication
  └──1─*── auth_session

audit   (polymorphic, append-only)
```

## 2. Conventions

- SQLite, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.
- All ids are opaque UUIDv4 strings.
- All timestamps are ISO 8601 UTC strings, stored as `TEXT`.
- All boxes are `[x0, y0, x1, y1]`, normalised 0–1, stored as JSON `TEXT`.
- Numeric lab values are stored as **canonical decimal strings** in `value_num TEXT`. Floats are produced only at the API boundary for charts. This keeps `Decimal` exactness end to end.
- One exclusive coordinator freezes at most ten FIFO submissions; SQLite writer transactions fence state changes.
- New prepared page images live under `data/uploads/<submission-id>/page_<n>.webp`; historical stored paths remain valid.
- The content hash is `SHA-256(patient_id || NUL || file bytes)`. It is unique globally but patient-scoped in practice, so duplicate detection cannot match another patient's upload.

## 3. Tables

### 3.1 `patient`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `alias` | TEXT | NOT NULL — the only display identifier |
| `dob` | TEXT | NULL |
| `sex` | TEXT | NULL, CHECK in (`M`,`F`,`O`) |
| `username` | TEXT | NULL — local login name |
| `password_hash` | TEXT | NULL — scrypt hash |
| `created_at` | TEXT | NOT NULL |

`CREATE UNIQUE INDEX idx_patient_username ON patient(username COLLATE NOCASE) WHERE username IS NOT NULL;`

No name, phone, address, or Aadhaar column exists. `alias` is display-only; `username` is a credential. A v1 patient with `username IS NULL` is claimed by the first registration when it is the only unowned patient.

### 3.2 `auth_session`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `patient_id` | TEXT | FK → patient, NOT NULL, ON DELETE CASCADE |
| `token_hash` | TEXT | NOT NULL, UNIQUE — SHA-256 of the cookie token |
| `created_at` | TEXT | NOT NULL |
| `expires_at` | TEXT | NOT NULL |

The raw token is never stored. The cookie is `HttpOnly`, `SameSite=Strict`, and `Secure` only when TLS is terminated.

### 3.3 `document`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `patient_id` | TEXT | FK → patient, NOT NULL, ON DELETE CASCADE |
| `doc_type` | TEXT | NOT NULL, CHECK in (`lab_report`,`prescription`,`pharmacy`,`other`) |
| `capture_type` | TEXT | NOT NULL, CHECK in (`printed`,`handwritten`) — derived server-side |
| `doc_date` | TEXT | NULL |
| `collection_date` | TEXT | NULL |
| `lab_name` | TEXT | NULL |
| `image_path` | TEXT | NOT NULL — relative to `upload_dir` |
| `page_count` | INTEGER | NOT NULL, default 1, CHECK ≥ 1 |
| `quality_score` | REAL | NULL |
| `quality_json` | TEXT | NULL |
| `content_hash` | TEXT | NOT NULL, UNIQUE |
| `status` | TEXT | NOT NULL, CHECK in (`queued`,`processing`,`done`,`failed`,`rejected_quality`) |
| `doc_type_confidence` | REAL | NULL |
| `processed_at` | TEXT | NULL |
| `created_at` | TEXT | NOT NULL |

`UNIQUE(content_hash)` makes re-upload idempotent within a patient. Upload stores `doc_type='other'` until the worker classifies the page text. There is no per-page `document` row; pages are files under `image_path`.

### 3.3a `report` (schema v8)

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL, ON DELETE CASCADE |
| `patient_id` | TEXT | FK → patient, NOT NULL, ON DELETE CASCADE |
| `category` | TEXT | NOT NULL, CHECK in (`lab`,`imaging`,`prescription`,`discharge`,`pathology`,`other`) |
| `report_type` | TEXT | NOT NULL — original `doc_type`, e.g. `ct`, `lab_report` |
| `report_date` | TEXT | NULL — the timeline date |
| `facility_name` | TEXT | NULL |
| `title` | TEXT | NULL |
| `summary` | TEXT | NULL — impression or findings slice |
| `page_start` | INTEGER | NOT NULL, CHECK ≥ 1 |
| `page_end` | INTEGER | NOT NULL, CHECK ≥ `page_start` |
| `status` | TEXT | NOT NULL, CHECK in (`auto`,`review`,`rejected`) |
| `reason` | TEXT | NULL |
| `model_version` | TEXT | NULL |
| `created_at` | TEXT | NOT NULL |

One upload can contain several reports. The worker groups consecutive pages by detected date and facility; a page without either continues the current report. A report without a date, or with category `other`, starts in `review`. The report is the timeline item; observations inside it are optional searchable facts.

### 3.4 `page_text`

| Column | Type | Constraints |
|---|---|---|
| `document_id` | TEXT | FK → document, NOT NULL, ON DELETE CASCADE |
| `page` | INTEGER | NOT NULL, CHECK ≥ 1 |
| `text` | TEXT | NOT NULL |
| `engine` | TEXT | NOT NULL |
| `created_at` | TEXT | NOT NULL |

Primary key `(document_id, page)`. OCR text is local-only and is never included in a typed projection.

### 3.5 `consent`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `scope` | TEXT | NOT NULL — `local` \| `local_plus_projection` |
| `version` | TEXT | NOT NULL — consent form version |
| `granted_at` | TEXT | NOT NULL |
| `revoked_at` | TEXT | NULL |

A document with no row here is never queued (`FR-ING-09`). A revoked row blocks egress (`FR-EGR-03`). The upload form writes the first row.

### 3.6 `observation`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `report_id` | TEXT | FK → report, NULL, ON DELETE SET NULL |
| `analyte_id` | TEXT | NULL until mapped |
| `label_raw` | TEXT | NULL — label as printed |
| `label_norm` | TEXT | NULL — search/group key |
| `value_num` | TEXT | NULL — canonical decimal string |
| `value_text` | TEXT | NULL — as printed or prose |
| `unit_raw` | TEXT | NULL |
| `unit_norm` | TEXT | NULL |
| `ref_low` | TEXT | NULL |
| `ref_high` | TEXT | NULL |
| `flag_printed` | TEXT | NULL |
| `bbox_json` | TEXT | NOT NULL |
| `page` | INTEGER | NOT NULL |
| `engine` | TEXT | NOT NULL |
| `confidence` | REAL | NULL |
| `status` | TEXT | NOT NULL, CHECK in (`auto`,`review`,`rejected`) |
| `reason` | TEXT | NULL |
| `mapping_rule` | TEXT | NULL, CHECK in (`exact`,`synonym`,`unresolved`) |
| `source` | TEXT | NULL, CHECK in (`text_layer`,`ocr`) |
| `model_version` | TEXT | NULL |
| `fact_type` | TEXT | NOT NULL, default `lab`, CHECK in (`lab`,`measurement`,`impression`,`imaging_finding`,`diagnosis`,`recommendation`,`note`,`other`) |
| `evidence_quote` | TEXT | NULL |
| `created_at` | TEXT | NOT NULL |

**Invariants enforced by trigger or test:**

- `status='auto'` requires either a mapped numeric value (`analyte_id IS NOT NULL` and `value_num IS NOT NULL`) or a non-null `value_text`.
- No `auto` row may belong to a document with `capture_type='handwritten'` (SI-01).
- A handwritten document may only produce observations with `analyte_id IS NULL` (SI-02) — in practice the worker produces none.
- `ref_low`/`ref_high` are written once and never updated (DR-02).
- The worker writes every extracted observation as `review`; only the review endpoint sets `auto` or `rejected`. A review action appends `audit` rows; the original value is retained in audit when corrected.

### 3.7 `directive`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `span_text` | TEXT | NOT NULL |
| `span_start` | INTEGER | NOT NULL |
| `span_end` | INTEGER | NOT NULL |
| `action_type` | TEXT | NOT NULL |
| `timing_type` | TEXT | NOT NULL, CHECK in (`relative`,`absolute`,`conditional`,`prn`) |
| `time_value` | INTEGER | NULL |
| `time_unit` | TEXT | NULL, CHECK in (`day`,`week`,`month`,`year`) |
| `anchor_event` | TEXT | NOT NULL, CHECK in (`collection_date`,`doc_date`,`unknown`) |
| `condition_text` | TEXT | NULL |
| `target` | TEXT | NULL |
| `anchor_date` | TEXT | NULL |
| `due_date` | TEXT | NULL |
| `state` | TEXT | NOT NULL, CHECK in (`open`,`done`,`superseded`,`unknown_date`) |

There is deliberately **no** `today` value in `anchor_event`. SI-10 is enforced by the type system, not by discipline.

Check: `timing_type IN ('conditional','prn')` ⇒ `due_date IS NULL`.

### 3.8 `medication`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `patient_id` | TEXT | FK → patient, NOT NULL |
| `brand_raw` | TEXT | NOT NULL |
| `salt` | TEXT | NULL |
| `dose` | TEXT | NULL |
| `freq` | TEXT | NULL |
| `start_date` | TEXT | NULL |
| `status` | TEXT | NOT NULL, CHECK in (`prescribed`,`reported_stopped`,`reported_ongoing`) |
| `reported_at` | TEXT | NULL |
| `source_doc_id` | TEXT | FK → document, NULL for patient reports |

Append-only. A state change is an insert, never an update.

### 3.9 `handwriting_field`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `page` | INTEGER | NOT NULL |
| `bbox_json` | TEXT | NOT NULL |
| `field_type` | TEXT | NOT NULL, CHECK in (`drug`,`dose`,`frequency`,`duration`,`directive`,`other`) |
| `model_top1` | TEXT | NULL |
| `candidates_json` | TEXT | NULL |
| `human_value` | TEXT | NULL |
| `action` | TEXT | NULL, CHECK in (`accept`,`correct`,`reject`,`add`) |
| `ms_to_verify` | INTEGER | NULL |
| `status` | TEXT | NOT NULL, CHECK in (`review`,`resolved`) |

`status='resolved'` requires `action IS NOT NULL`. There is no `auto` value in the CHECK list.

### 3.10 `egress`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `payload_sha256` | TEXT | NOT NULL |
| `model_id` | TEXT | NULL |
| `prompt_version` | TEXT | NULL |
| `schema_version` | TEXT | NOT NULL |
| `outcome` | TEXT | NOT NULL, CHECK in (`sent`,`refused_no_consent`,`refused_schema`,`failed`,`cached`) |
| `reason` | TEXT | NULL |
| `ts` | TEXT | NOT NULL |

No column can hold payload content. Logging the payload is structurally impossible, not merely forbidden. When cloud document reading or Gemini review is approved, every outbound call writes an audit row here with `payload_sha256`, `model_id='gemini-3.8-flash-high'`, `outcome`, and `ts`. Document review in the frontend displays these rows under Audit & Cloud Review Logs.

### 3.10a `stage_artifact`

| Column | Type | Constraints |
|---|---|---|
| `content_hash` | TEXT | NOT NULL — content hash or entity key |
| `page` | INTEGER | NOT NULL, CHECK ≥ 1 |
| `stage` | TEXT | NOT NULL — e.g. `ocr`, `redaction`, `standardized_clinical_summary` |
| `model_version` | TEXT | NOT NULL |
| `artifact_json` | TEXT | NOT NULL |
| `created_at` | TEXT | NOT NULL |

Primary key `(content_hash, page, stage, model_version)`. Caches pipeline intermediate stages and structured clinical summaries without modifying baseline clinical tables.

### 3.11 `audit`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `entity` | TEXT | NOT NULL |
| `entity_id` | TEXT | NOT NULL |
| `field` | TEXT | NULL |
| `old` | TEXT | NULL |
| `new` | TEXT | NULL |
| `actor` | TEXT | NOT NULL |
| `ts` | TEXT | NOT NULL |

Append-only. `UPDATE` and `DELETE` are rejected by trigger (NFR-08). Auth login failures/successes are audit rows with `entity='auth'`.

### 3.12 `jobs`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `state` | TEXT | NOT NULL, CHECK in (`queued`,`running`,`done`,`failed`) |
| `page` | INTEGER | NOT NULL, default 0 |
| `total` | INTEGER | NOT NULL |
| `error` | TEXT | NULL |
| `stage` | TEXT | NULL; current operational stage |
| `progress_json` | TEXT | NULL; bounded operational snapshot/history (v9) |
| `ts` | TEXT | NOT NULL |

`page` remains the number of completed OCR/text-layer pages. `progress_json` holds current stage/model/page counts, UTC boundary timestamps, terminal monotonic elapsed time, per-attempt verification state, failure context, and at most 500 ordered events. `events_truncated` counts omitted older events; current state survives truncation. Messages are allowlisted operational messages, not medical content or model replies. Historical rows retain null telemetry. Writes update the existing job only, so telemetry cannot recreate a deleted job. Document deletion cascades to the job and its history. See `docs/API.md` §5 for the public snapshot fields.

## 4. Indexes

```sql
CREATE INDEX idx_doc_patient_date ON document(patient_id, collection_date);
CREATE INDEX idx_doc_status       ON document(status);
CREATE INDEX idx_obs_analyte      ON observation(analyte_id, document_id);
CREATE INDEX idx_obs_doc_status   ON observation(document_id, status);
CREATE INDEX idx_dir_doc_state    ON directive(document_id, state);
CREATE INDEX idx_med_patient      ON medication(patient_id, status);
CREATE INDEX idx_hwf_doc_status   ON handwriting_field(document_id, status);
CREATE INDEX idx_egress_doc       ON egress(document_id, ts);
CREATE INDEX idx_jobs_state       ON jobs(state, ts);
CREATE INDEX idx_share_patient    ON share_token(patient_id, expires_at);
CREATE UNIQUE INDEX idx_patient_username ON patient(username COLLATE NOCASE)
    WHERE username IS NOT NULL;
CREATE INDEX idx_auth_session_patient ON auth_session(patient_id, expires_at);
```

New processing admission uses `idx_submissions_pending`, frozen batch membership and an exclusive coordinator lock; historical queued jobs without submission metadata are not automatically claimed.

## 5. State machines

```
document:  queued → processing → done
                     └─────────▶ failed
           (upload) ───────────▶ rejected_quality

observation: review ──accept──▶ auto
             review ──correct─▶ auto
             review ──reject──▶ rejected
             (worker) ────────▶ review

job:       queued → running → done | failed

directive: open → done | superseded | unknown_date
```

`rejected` is terminal for charting purposes. The row stays for evaluation (DR-04). The worker writes only `review`; the review endpoint writes `auto` or `rejected` and audits the transition. `documents[].review_count` is computed from `observation.status='review'`, not stored.

## 6. Migrations

`smriti/schema.sql` is the fresh v11 source of truth; `smriti/db.py` applies numbered migrations to older databases. `smriti/migrations/002_auth_ocr.sql` upgrades a v1 database:

- adds `patient.username`, `patient.password_hash`
- adds `document.doc_type_confidence`, `document.processed_at`
- adds `observation.label_raw`
- creates `auth_session` and `page_text`
- creates the username and session indexes

Existing patients, documents, consent, and jobs are preserved. The first registration claims the sole unowned patient. Back up `data/smriti.db` before starting a build that migrates it.

`009_job_progress.sql` adds only nullable `jobs.progress_json` to v8. Existing accounts, sessions, documents, accepted observations, and jobs are preserved; old documents are not reprocessed. Before deployment, stop the server/worker and make a consistent database backup (including SQLite WAL state, or checkpoint it while stopped). Starting the new application applies the migration; do not edit or reset a live database to enable progress history.

## 7. Deletion

`DELETE /api/patients/{id}`:

1. Serialize against owner spooling, revoke consent and pause admission; confirm owned stage/sampler/coordinator exit.
2. Validate and clean owned spool/debug/partial/scratch/source files while cleanup paths remain in SQLite. Failure returns `503 cleanup_failed`, leaves retry metadata and keeps admission paused.
3. In the final transaction, record erased frozen-member receipts, delete owned submissions and account/clinical rows, and append the patient deletion audit. Preserve other owners and existing append-only audit; do not refill frozen membership from late arrivals.
4. Restart the local coordinator only after confirmed cleanup. Do not log deleted medical content.

Backups are not part of the database and must be deleted separately. A surviving backup is a data breach.

## 8. What is deliberately absent

No external identity provider, no roles, no admin/operator account, no client-side medical-data store, and no implemented share link. Local accounts exist only to isolate patients on one machine. The printed-value review loop is implemented; P3 normalisation/safety and P4 medication/directive state changes are not implemented in this schema version.

## 9. Operational staging (v10/v11)

- `submissions`: owner/public-job identity, private raw path/byte count and patient-scoped hash, consent/overrides, pending/preparing/promoted or terminal state, preparation manifest, progress, frozen batch position and independent cleanup intent/outcome/timestamps. Owner/document FKs are restrictive until explicit cleanup. Prepared page totals are positive with no page-count cap in v11.
- `stage_batches`: at most ten immutable ordered member IDs, exclusive active-batch guard, fenced coordinator ownership, compact v1 pass/member/next-page/current-window/active-attempt cursor and bounded current-stage measurement summaries. V11 removes the old ten-workset cursor cap, not membership bounds. Unknown historical checkpoint shapes remain fenced; migration preserves them rather than guessing recovery.
- `output_reservations`: atomically accounts provisional in-flight output/storage headroom. Durable sources/clinical rows still occupy physical disk after scratch/reservations are released.
- Private `.runtime/<job-id>/` page artifacts/candidate SQLite contain processing evidence, not published clinical rows. Complete-document rules and private report associations precede one fenced atomic clinical save. Terminal/reviewed/populated records are never replacement-written.
- Job history retains at most 500 code-owned events plus current state/latest failure; bounded JSON constraints remain. File/terminal diagnostics are independent best-effort operator data, not the append-only medical audit and not an account export.

Migration 010 is frozen historical v9→v10; migration 011 rebuilds only the operational submissions/batches to relax counts while preserving rows/FKs/indexes/triggers. Backups exclude raw spool, debug originals, `.runtime` and diagnostic logs. No migration against live data is part of implementation verification.

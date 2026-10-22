# Data Model

Status: draft. Implements SRS §3.4. Any change here is a migration, not an edit.

---

## 1. Entity relationships

```
patient ──1─*── document ──1─*── observation
                   │
                   ├──1─1── consent
                   ├──1─*── directive
                   ├──1─*── handwriting_field
                   ├──1─*── egress
                   └──1─1── job (current)

patient ──1─*── medication

audit   (polymorphic, append-only)
```

## 2. Conventions

- SQLite, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.
- All ids are opaque UUIDv4 strings.
- All timestamps are ISO 8601 UTC strings, stored as `TEXT`.
- All boxes are `[x0, y0, x1, y1]`, normalised 0–1, stored as JSON `TEXT`.
- Numeric lab values are stored as **canonical decimal strings** in `value_num TEXT`. Floats are produced only at the API boundary for charts. This keeps `Decimal` exactness end to end.
- One writer. The worker claims jobs with `BEGIN IMMEDIATE`.

## 3. Tables

### 3.1 `patient`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `alias` | TEXT | NOT NULL — the only display identifier |
| `dob` | TEXT | NULL |
| `sex` | TEXT | NULL, CHECK in (`M`,`F`,`O`) |
| `created_at` | TEXT | NOT NULL |

No name, phone, address, or Aadhaar column exists. A real name cannot be stored by accident.

### 3.2 `document`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `patient_id` | TEXT | FK → patient, NOT NULL |
| `doc_type` | TEXT | NOT NULL, CHECK in (`lab_report`,`prescription`,`pharmacy`,`other`) |
| `capture_type` | TEXT | NOT NULL, CHECK in (`printed`,`handwritten`) — derived server-side |
| `doc_date` | TEXT | NULL |
| `collection_date` | TEXT | NULL |
| `lab_name` | TEXT | NULL |
| `image_path` | TEXT | NOT NULL — relative to `data/uploads` |
| `page` | INTEGER | NOT NULL, default 1 |
| `quality_score` | REAL | NULL |
| `content_hash` | TEXT | NOT NULL, UNIQUE with `page` |
| `status` | TEXT | NOT NULL, CHECK in (`queued`,`processing`,`done`,`failed`,`rejected_quality`) |
| `created_at` | TEXT | NOT NULL |

`UNIQUE(content_hash, page)` is what makes re-upload idempotent.

### 3.3 `consent`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `scope` | TEXT | NOT NULL — `local` \| `local_plus_projection` |
| `version` | TEXT | NOT NULL — consent form version |
| `granted_at` | TEXT | NOT NULL |
| `revoked_at` | TEXT | NULL |

A document with no row here is never queued (`FR-ING-09`). A revoked row blocks egress (`FR-EGR-03`).

### 3.4 `observation`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `analyte_id` | TEXT | NULL until mapped |
| `value_num` | TEXT | NULL — canonical decimal string |
| `value_text` | TEXT | NULL — as printed |
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
| `created_at` | TEXT | NOT NULL |

**Invariants enforced by trigger or test:**

- `status='auto'` requires `analyte_id IS NOT NULL` and `value_num IS NOT NULL`.
- No `auto` row may belong to a document with `capture_type='handwritten'` (SI-01).
- A handwritten document may only produce observations with `analyte_id IS NULL` (SI-02) — in practice it produces none.
- `ref_low`/`ref_high` are written once and never updated (DR-02).

### 3.5 `directive`

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

### 3.6 `medication`

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

### 3.7 `handwriting_field`

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

### 3.8 `egress`

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

No column can hold payload content. Logging the payload is structurally impossible, not merely forbidden.

### 3.9 `audit`

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

Append-only. `UPDATE` and `DELETE` are rejected by trigger (NFR-08).

### 3.10 `jobs`

| Column | Type | Constraints |
|---|---|---|
| `id` | TEXT | PK |
| `document_id` | TEXT | FK → document, NOT NULL |
| `state` | TEXT | NOT NULL, CHECK in (`queued`,`running`,`done`,`failed`) |
| `page` | INTEGER | NOT NULL, default 0 |
| `total` | INTEGER | NOT NULL |
| `error` | TEXT | NULL |
| `ts` | TEXT | NOT NULL |

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
```

`idx_jobs_state` is the claim index; the worker does `SELECT ... WHERE state='queued' ORDER BY ts LIMIT 1` inside `BEGIN IMMEDIATE`.

## 5. State machines

```
document:  queued → processing → done
                     └─────────▶ failed
           (upload) ───────────▶ rejected_quality

observation: review ──accept──▶ auto
             review ──correct─▶ auto
             review ──reject──▶ rejected
             (gate) ──────────▶ rejected   [terminal, never charted]

job:       queued → running → done | failed
failed ──retry──▶ queued

directive: open → done | superseded | unknown_date
```

`rejected` is terminal for charting purposes. The row stays for evaluation (DR-04).

## 6. Deletion

`DELETE /api/patients/{id}` in one transaction:

1. Delete `handwriting_field`, `directive`, `observation`, `medication`, `egress`, `consent`, `jobs`, `document` rows for the patient.
2. Delete files under `data/uploads/<hash>/` for every document.
3. Insert one `audit` row: `{entity:'patient', entity_id:id, field:'deleted', new:'true'}`.
4. Do not log what was deleted.

Backups are not part of the database and must be deleted separately. A surviving backup is a data breach.

## 7. What is deliberately absent

No `user` table, no roles, no sessions, no password store. Authentication is out of scope; the deployment model is one operator on one machine, plus a PIN-gated read-only share link. Adding accounts without adding a threat model would be worse than not having them.

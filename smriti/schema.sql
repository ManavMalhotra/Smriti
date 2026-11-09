-- Smriti schema v11.
-- One `document` row per prepared upload; pending uploads live in `submissions`.
-- Page images live under `image_path`/<page>.webp; boxes are normalised JSON arrays.

PRAGMA journal_mode = WAL;

BEGIN;

CREATE TABLE patient (
    id          TEXT PRIMARY KEY,
    alias       TEXT NOT NULL,
    dob         TEXT,
    sex         TEXT CHECK (sex IN ('M', 'F', 'O')),
    username    TEXT,
    password_hash TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE document (
    id               TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    doc_type         TEXT NOT NULL CHECK (doc_type IN (
                         'lab_report', 'prescription', 'pharmacy',
                         'discharge_summary', 'ct', 'mri', 'xray',
                         'pathology', 'radiology', 'other'
                     )),
    capture_type     TEXT NOT NULL CHECK (capture_type IN ('printed', 'handwritten')),
    doc_date         TEXT,
    collection_date  TEXT,
    registration_date TEXT,
    report_date      TEXT,
    patient_uhid     TEXT,
    patient_mrd      TEXT,
    doctor_reg_no    TEXT,
    hospital         TEXT,
    facility_name    TEXT,
    lab_name         TEXT,
    image_path       TEXT NOT NULL,             -- relative to upload_dir, never a user filename
    page_count       INTEGER NOT NULL DEFAULT 1 CHECK (page_count >= 1),
    quality_score    REAL,                      -- minimum page score
    quality_json     TEXT,                      -- per-page scores and applied steps
    content_hash     TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'failed', 'rejected_quality')),
    doc_type_confidence REAL,
    processed_at     TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE report (
    id            TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    patient_id    TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    category      TEXT NOT NULL CHECK (category IN (
                      'lab', 'imaging', 'prescription', 'discharge',
                      'pathology', 'other'
                  )),
    report_type   TEXT NOT NULL,
    report_date   TEXT,
    facility_name TEXT,
    title         TEXT,
    summary       TEXT,
    page_start    INTEGER NOT NULL CHECK (page_start >= 1),
    page_end      INTEGER NOT NULL CHECK (page_end >= page_start),
    status        TEXT NOT NULL CHECK (status IN ('auto', 'review', 'rejected')),
    reason        TEXT,
    model_version TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE consent (
    id           TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL UNIQUE REFERENCES document(id) ON DELETE CASCADE,
    scope        TEXT NOT NULL CHECK (scope IN ('local', 'local_plus_projection')),
    version      TEXT NOT NULL,
    granted_at   TEXT NOT NULL,
    revoked_at   TEXT
);

CREATE TABLE observation (
    id             TEXT PRIMARY KEY,
    document_id    TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    report_id      TEXT REFERENCES report(id) ON DELETE SET NULL,
    analyte_id     TEXT,
    label_raw      TEXT,
    label_norm     TEXT,
    value_num      TEXT,
    value_text     TEXT,
    unit_raw       TEXT,
    unit_norm      TEXT,
    ref_low        TEXT,
    ref_high       TEXT,
    flag_printed   TEXT,
    bbox_json      TEXT NOT NULL,
    page           INTEGER NOT NULL CHECK (page >= 1),
    engine         TEXT NOT NULL,
    confidence     REAL,
    status         TEXT NOT NULL CHECK (status IN ('auto', 'review', 'rejected')),
    reason         TEXT,
    mapping_rule   TEXT CHECK (mapping_rule IN ('exact', 'synonym', 'unresolved')),
    source         TEXT CHECK (source IN ('text_layer', 'ocr')),
    model_version  TEXT,
    fact_type      TEXT NOT NULL DEFAULT 'lab' CHECK (fact_type IN (
                       'lab', 'measurement', 'impression', 'imaging_finding',
                       'diagnosis', 'recommendation', 'note', 'other'
                   )),
    evidence_quote TEXT,
    created_at     TEXT NOT NULL,
    CHECK (status <> 'auto' OR (analyte_id IS NOT NULL AND value_num IS NOT NULL) OR value_text IS NOT NULL)
);

CREATE TABLE directive (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    span_text       TEXT NOT NULL,
    span_start      INTEGER NOT NULL CHECK (span_start >= 0),
    span_end        INTEGER NOT NULL CHECK (span_end >= span_start),
    action_type     TEXT NOT NULL,
    timing_type     TEXT NOT NULL CHECK (timing_type IN ('relative', 'absolute', 'conditional', 'prn')),
    time_value      INTEGER CHECK (time_value IS NULL OR time_value >= 0),
    time_unit       TEXT CHECK (time_unit IN ('day', 'week', 'month', 'year')),
    anchor_event    TEXT NOT NULL CHECK (anchor_event IN ('collection_date', 'doc_date', 'unknown')),
    condition_text  TEXT,
    target          TEXT,
    anchor_date     TEXT,
    due_date        TEXT,
    state           TEXT NOT NULL CHECK (state IN ('open', 'done', 'superseded', 'unknown_date')),
    CHECK (timing_type NOT IN ('conditional', 'prn') OR due_date IS NULL)
);

CREATE TABLE medication (
    id             TEXT PRIMARY KEY,
    patient_id     TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    brand_raw      TEXT NOT NULL,
    salt           TEXT,
    dose           TEXT,
    freq           TEXT,
    start_date     TEXT,
    status         TEXT NOT NULL CHECK (status IN ('prescribed', 'reported_stopped', 'reported_ongoing')),
    reported_at    TEXT,
    source_doc_id  TEXT REFERENCES document(id) ON DELETE SET NULL
);

CREATE TABLE handwriting_field (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page            INTEGER NOT NULL CHECK (page >= 1),
    bbox_json       TEXT NOT NULL,
    field_type      TEXT NOT NULL CHECK (field_type IN ('drug', 'dose', 'frequency', 'duration', 'directive', 'other')),
    model_top1      TEXT,
    candidates_json TEXT,
    human_value     TEXT,
    action          TEXT CHECK (action IN ('accept', 'correct', 'reject', 'add')),
    ms_to_verify    INTEGER CHECK (ms_to_verify IS NULL OR ms_to_verify >= 0),
    status          TEXT NOT NULL CHECK (status IN ('review', 'resolved')),
    CHECK (status <> 'resolved' OR action IS NOT NULL)
);

CREATE TABLE egress (
    id              TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    payload_sha256  TEXT NOT NULL,
    model_id        TEXT,
    prompt_version  TEXT,
    schema_version  TEXT NOT NULL,
    outcome         TEXT NOT NULL CHECK (outcome IN ('sent', 'refused_no_consent', 'refused_schema', 'failed', 'cached')),
    reason          TEXT,
    ts              TEXT NOT NULL
);

CREATE TABLE audit (
    id         TEXT PRIMARY KEY,
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    field      TEXT,
    old        TEXT,
    new        TEXT,
    actor      TEXT NOT NULL,
    ts         TEXT NOT NULL
);

CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    state        TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
    stage        TEXT NOT NULL DEFAULT 'stage_ocr',
    page         INTEGER NOT NULL DEFAULT 0 CHECK (page >= 0),
    total        INTEGER NOT NULL CHECK (total >= 1),
    error        TEXT,
    progress_json TEXT,
    ts           TEXT NOT NULL
);

CREATE TABLE stage_artifact (
    content_hash  TEXT NOT NULL,
    page          INTEGER NOT NULL CHECK (page >= 1),
    stage         TEXT NOT NULL,
    model_version TEXT NOT NULL,
    artifact_json TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (content_hash, page, stage, model_version)
);

CREATE TABLE share_token (
    id           TEXT PRIMARY KEY,
    patient_id   TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    pin_hash     TEXT NOT NULL,
    expires_at   TEXT NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    locked_at    TEXT,
    revoked_at   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE auth_session (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);

CREATE TABLE page_text (
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL CHECK (page >= 1),
    text        TEXT NOT NULL,
    engine      TEXT NOT NULL,
    source      TEXT CHECK (source IN ('text_layer', 'ocr')),
    model_version TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (document_id, page)
);

CREATE TABLE "stage_batches" (
    id                 TEXT NOT NULL PRIMARY KEY,
    state              TEXT NOT NULL CHECK (state IN ('preparing', 'processing', 'cleanup_failed', 'done', 'failed', 'cancelled')),
    owner_token        TEXT NOT NULL,
    owner_pid          INTEGER NOT NULL CHECK (owner_pid >= 1),
    owner_created_at   REAL NOT NULL CHECK (owner_created_at > 0),
    membership_json    TEXT NOT NULL CHECK (CASE WHEN json_valid(membership_json) THEN
                           json_type(membership_json) = 'array' AND json_array_length(membership_json) BETWEEN 1 AND 10
                           AND length(CAST(membership_json AS BLOB)) <= 4096 ELSE 0 END),
    worksets_json      TEXT CHECK (worksets_json IS NULL OR CASE WHEN json_valid(worksets_json) THEN
                           json_type(worksets_json) = 'array' AND json_array_length(worksets_json) <= 10
                           AND length(CAST(worksets_json AS BLOB)) <= 65536 ELSE 0 END),
    workset_index      INTEGER NOT NULL DEFAULT 0 CHECK (workset_index >= 0),
    stage              TEXT NOT NULL DEFAULT 'preparing',
    attempt            INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    checkpoints_json   TEXT NOT NULL DEFAULT '{}' CHECK (CASE WHEN json_valid(checkpoints_json) THEN
                           json_type(checkpoints_json) = 'object' AND length(CAST(checkpoints_json AS BLOB)) <= 65536 ELSE 0 END),
    telemetry_json     TEXT NOT NULL DEFAULT '{}' CHECK (CASE WHEN json_valid(telemetry_json) THEN
                           json_type(telemetry_json) = 'object' AND length(CAST(telemetry_json AS BLOB)) <= 262144 ELSE 0 END),
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    finished_at        TEXT
);

CREATE TABLE "submissions" (
    job_id                     TEXT NOT NULL PRIMARY KEY,
    -- RESTRICT preserves cleanup paths until owner erasure explicitly cleans them.
    patient_id                 TEXT NOT NULL REFERENCES patient(id) ON DELETE RESTRICT,
    content_hash               TEXT NOT NULL,
    spool_path                 TEXT NOT NULL UNIQUE,
    spool_bytes                INTEGER NOT NULL CHECK (spool_bytes >= 1),
    consent_scope              TEXT NOT NULL CHECK (consent_scope IN ('local', 'local_plus_projection')),
    consent_version            TEXT NOT NULL,
    consent_granted_at         TEXT NOT NULL,
    consent_revoked_at         TEXT,
    requested_doc_type         TEXT CHECK (requested_doc_type IN (
                                   'lab_report', 'prescription', 'pharmacy', 'discharge_summary',
                                   'ct', 'mri', 'xray', 'pathology', 'radiology', 'other')),
    requested_doc_date         TEXT,
    requested_collection_date  TEXT,
    state                      TEXT NOT NULL DEFAULT 'pending_intake' CHECK (state IN (
                                   'pending_intake', 'preparing', 'promoted', 'rejected', 'failed', 'cancelled')),
    stage                      TEXT NOT NULL DEFAULT 'pending_intake',
    error_code                 TEXT,
    document_id                TEXT UNIQUE REFERENCES document(id) ON DELETE RESTRICT,
    total_pages                INTEGER CHECK (total_pages >= 1),
    batch_id                   TEXT REFERENCES "stage_batches"(id) ON DELETE RESTRICT,
    batch_position             INTEGER CHECK (batch_position BETWEEN 0 AND 9),
    preparation_manifest_json  TEXT CHECK (preparation_manifest_json IS NULL OR CASE WHEN json_valid(preparation_manifest_json) THEN
                                   json_type(preparation_manifest_json) = 'object'
                                   AND length(CAST(preparation_manifest_json AS BLOB)) <= 262144 ELSE 0 END),
    progress_json              TEXT CHECK (progress_json IS NULL OR CASE WHEN json_valid(progress_json) THEN
                                   json_type(progress_json) = 'object' AND length(CAST(progress_json AS BLOB)) <= 262144 ELSE 0 END),
    spool_cleanup_requested_at TEXT,
    spool_cleanup_state        TEXT NOT NULL DEFAULT 'pending' CHECK (spool_cleanup_state IN ('pending', 'deleted', 'failed', 'debug_retained')),
    spool_cleanup_error_code   TEXT,
    spool_deleted_at           TEXT,
    created_at                 TEXT NOT NULL,
    updated_at                 TEXT NOT NULL,
    CHECK ((state = 'promoted' AND document_id IS NOT NULL AND total_pages IS NOT NULL)
        OR (state <> 'promoted' AND document_id IS NULL AND total_pages IS NULL)),
    CHECK ((batch_id IS NULL) = (batch_position IS NULL)),
    CHECK ((spool_cleanup_state = 'deleted') = (spool_deleted_at IS NOT NULL)),
    CHECK (spool_cleanup_state = 'pending' OR spool_cleanup_requested_at IS NOT NULL)
);

CREATE UNIQUE INDEX idx_stage_batches_active ON stage_batches((1))
    WHERE state IN ('preparing', 'processing', 'cleanup_failed');
CREATE UNIQUE INDEX idx_submissions_live_hash ON submissions(patient_id, content_hash)
    WHERE state IN ('pending_intake', 'preparing', 'promoted');
CREATE UNIQUE INDEX idx_submissions_batch_position ON submissions(batch_id, batch_position)
    WHERE batch_id IS NOT NULL;
CREATE INDEX idx_submissions_pending ON submissions(state, created_at, job_id);
CREATE INDEX idx_submissions_owner ON submissions(patient_id, created_at);
CREATE INDEX idx_submissions_cleanup ON submissions(spool_cleanup_state)
    WHERE spool_cleanup_requested_at IS NOT NULL;

CREATE TRIGGER stage_batches_membership_frozen
BEFORE UPDATE OF membership_json ON stage_batches
WHEN NEW.membership_json IS NOT OLD.membership_json
BEGIN
    SELECT RAISE(ABORT, 'batch membership is frozen');
END;

CREATE TRIGGER submissions_batch_frozen
BEFORE UPDATE OF batch_id, batch_position ON submissions
WHEN OLD.batch_id IS NOT NULL AND (NEW.batch_id IS NOT OLD.batch_id OR NEW.batch_position IS NOT OLD.batch_position)
     AND (SELECT state FROM stage_batches WHERE id = OLD.batch_id) <> 'done'
BEGIN
    SELECT RAISE(ABORT, 'submission batch membership is frozen');
END;

CREATE TRIGGER submissions_prepared_owner_insert
BEFORE INSERT ON submissions
WHEN NEW.document_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM document d JOIN jobs j ON j.document_id = d.id
    WHERE d.id = NEW.document_id AND d.patient_id = NEW.patient_id AND j.id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'prepared submission must match owner and public job');
END;

CREATE TRIGGER submissions_prepared_owner_update
BEFORE UPDATE OF document_id, patient_id, job_id ON submissions
WHEN NEW.document_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM document d JOIN jobs j ON j.document_id = d.id
    WHERE d.id = NEW.document_id AND d.patient_id = NEW.patient_id AND j.id = NEW.job_id
)
BEGIN
    SELECT RAISE(ABORT, 'prepared submission must match owner and public job');
END;

CREATE INDEX idx_doc_patient_date ON document(patient_id, collection_date);
CREATE INDEX idx_doc_status       ON document(status);
CREATE INDEX idx_report_patient_date ON report(patient_id, report_date);
CREATE INDEX idx_report_document  ON report(document_id, page_start);
CREATE INDEX idx_obs_analyte      ON observation(analyte_id, document_id);
CREATE INDEX idx_obs_doc_status   ON observation(document_id, status);
CREATE INDEX idx_obs_report       ON observation(report_id, status);
CREATE INDEX idx_dir_doc_state    ON directive(document_id, state);
CREATE INDEX idx_med_patient      ON medication(patient_id, status);
CREATE INDEX idx_hwf_doc_status   ON handwriting_field(document_id, status);
CREATE INDEX idx_egress_doc       ON egress(document_id, ts);
CREATE INDEX idx_jobs_state       ON jobs(state, ts);
CREATE INDEX idx_stage_artifact_lookup ON stage_artifact(content_hash, page, stage);
CREATE INDEX idx_share_patient    ON share_token(patient_id, expires_at);
CREATE UNIQUE INDEX idx_patient_username ON patient(username COLLATE NOCASE)
    WHERE username IS NOT NULL;
CREATE INDEX idx_auth_session_patient ON auth_session(patient_id, expires_at);
CREATE INDEX idx_audit_lookup ON audit(entity, entity_id, field, ts);

CREATE TRIGGER audit_no_update
BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit is append-only');
END;

CREATE TRIGGER audit_no_delete
BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit is append-only');
END;

CREATE TRIGGER observation_no_auto_handwritten_insert
BEFORE INSERT ON observation
WHEN NEW.status = 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN
    SELECT RAISE(ABORT, 'SI-01: handwritten observation cannot be auto');
END;

CREATE TRIGGER observation_no_auto_handwritten_update
BEFORE UPDATE ON observation
WHEN NEW.status = 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN
    SELECT RAISE(ABORT, 'SI-01: handwritten observation cannot be auto');
END;

CREATE TRIGGER observation_no_numeric_handwritten_insert
BEFORE INSERT ON observation
WHEN NEW.value_num IS NOT NULL
 AND NEW.status <> 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN
    SELECT RAISE(ABORT, 'SI-02: no numeric laboratory value from a handwritten document');
END;

CREATE TRIGGER observation_no_numeric_handwritten_update
BEFORE UPDATE ON observation
WHEN NEW.value_num IS NOT NULL
 AND NEW.status <> 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN
    SELECT RAISE(ABORT, 'SI-02: no numeric laboratory value from a handwritten document');
END;

PRAGMA user_version = 12;

COMMIT;


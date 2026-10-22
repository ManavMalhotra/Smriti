-- Smriti schema v1.
-- One `document` row per upload; page images live under `image_path`/<page>.webp.
-- Boxes are normalised JSON arrays; decimal lab values are canonical strings.

PRAGMA journal_mode = WAL;

BEGIN;

CREATE TABLE patient (
    id          TEXT PRIMARY KEY,
    alias       TEXT NOT NULL,
    dob         TEXT,
    sex         TEXT CHECK (sex IN ('M', 'F', 'O')),
    created_at  TEXT NOT NULL
);

CREATE TABLE document (
    id               TEXT PRIMARY KEY,
    patient_id       TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    doc_type         TEXT NOT NULL CHECK (doc_type IN ('lab_report', 'prescription', 'pharmacy', 'other')),
    capture_type     TEXT NOT NULL CHECK (capture_type IN ('printed', 'handwritten')),
    doc_date         TEXT,
    collection_date  TEXT,
    lab_name         TEXT,
    image_path       TEXT NOT NULL,             -- relative to upload_dir, never a user filename
    page_count       INTEGER NOT NULL DEFAULT 1 CHECK (page_count >= 1),
    quality_score    REAL,                      -- minimum page score
    quality_json     TEXT,                      -- per-page scores and applied steps
    content_hash     TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'failed', 'rejected_quality')),
    created_at       TEXT NOT NULL
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
    id            TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    analyte_id    TEXT,
    value_num     TEXT,
    value_text    TEXT,
    unit_raw      TEXT,
    unit_norm     TEXT,
    ref_low       TEXT,
    ref_high      TEXT,
    flag_printed  TEXT,
    bbox_json     TEXT NOT NULL,
    page          INTEGER NOT NULL CHECK (page >= 1),
    engine        TEXT NOT NULL,
    confidence    REAL,
    status        TEXT NOT NULL CHECK (status IN ('auto', 'review', 'rejected')),
    reason        TEXT,
    mapping_rule  TEXT CHECK (mapping_rule IN ('exact', 'synonym', 'unresolved')),
    created_at    TEXT NOT NULL,
    CHECK (status <> 'auto' OR (analyte_id IS NOT NULL AND value_num IS NOT NULL))
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
    page         INTEGER NOT NULL DEFAULT 0 CHECK (page >= 0),
    total        INTEGER NOT NULL CHECK (total >= 1),
    error        TEXT,
    ts           TEXT NOT NULL
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

PRAGMA user_version = 1;

COMMIT;

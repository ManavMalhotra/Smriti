-- v5 -> v6: allow accepting prose/text observations and index audit table.
PRAGMA journal_mode = WAL;

BEGIN;

CREATE TABLE IF NOT EXISTS audit (
    id         TEXT PRIMARY KEY,
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    field      TEXT,
    old        TEXT,
    new        TEXT,
    actor      TEXT NOT NULL,
    ts         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_lookup ON audit(entity, entity_id, field, ts);

CREATE TABLE observation_v6 (
    id            TEXT PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    analyte_id    TEXT,
    label_raw     TEXT,
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
    source        TEXT CHECK (source IN ('text_layer', 'ocr')),
    model_version TEXT,
    created_at    TEXT NOT NULL,
    CHECK (status <> 'auto' OR (analyte_id IS NOT NULL AND value_num IS NOT NULL) OR value_text IS NOT NULL)
);

INSERT INTO observation_v6
    (id, document_id, analyte_id, label_raw, value_num, value_text,
     unit_raw, unit_norm, ref_low, ref_high, flag_printed, bbox_json,
     page, engine, confidence, status, reason, mapping_rule, source,
     model_version, created_at)
SELECT
    id, document_id, analyte_id, label_raw, value_num, value_text,
    unit_raw, unit_norm, ref_low, ref_high, flag_printed, bbox_json,
    page, engine, confidence, status, reason, mapping_rule, source,
    model_version, created_at
FROM observation;
DROP TABLE observation;
ALTER TABLE observation_v6 RENAME TO observation;

CREATE INDEX idx_obs_analyte      ON observation(analyte_id, document_id);
CREATE INDEX idx_obs_doc_status   ON observation(document_id, status);

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
    SELECT RAISE(ABORT, 'SI-02: handwritten observation cannot have numeric value');
END;

CREATE TRIGGER observation_no_numeric_handwritten_update
BEFORE UPDATE ON observation
WHEN NEW.value_num IS NOT NULL
 AND NEW.status <> 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN
    SELECT RAISE(ABORT, 'SI-02: handwritten observation cannot have numeric value');
END;

PRAGMA user_version = 6;

COMMIT;

-- v2 -> v3: imaging/pathology document types and per-record provenance.
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

BEGIN;

-- SQLite cannot alter a CHECK constraint, so the table is rebuilt.
CREATE TABLE document_new (
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
    lab_name         TEXT,
    image_path       TEXT NOT NULL,
    page_count       INTEGER NOT NULL DEFAULT 1 CHECK (page_count >= 1),
    quality_score    REAL,
    quality_json     TEXT,
    content_hash     TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'failed', 'rejected_quality')),
    doc_type_confidence REAL,
    processed_at     TEXT,
    created_at       TEXT NOT NULL
);

INSERT INTO document_new
    (id, patient_id, doc_type, capture_type, doc_date, collection_date, lab_name,
     image_path, page_count, quality_score, quality_json, content_hash, status,
     doc_type_confidence, processed_at, created_at)
SELECT
    id, patient_id, doc_type, capture_type, doc_date, collection_date, lab_name,
    image_path, page_count, quality_score, quality_json, content_hash, status,
    doc_type_confidence, processed_at, created_at
FROM document;

DROP TABLE document;
ALTER TABLE document_new RENAME TO document;

CREATE INDEX idx_doc_patient_date ON document(patient_id, collection_date);
CREATE INDEX idx_doc_status       ON document(status);

ALTER TABLE observation ADD COLUMN source TEXT CHECK (source IN ('text_layer', 'ocr'));
ALTER TABLE observation ADD COLUMN model_version TEXT;

ALTER TABLE page_text ADD COLUMN source TEXT CHECK (source IN ('text_layer', 'ocr'));
ALTER TABLE page_text ADD COLUMN model_version TEXT;

PRAGMA user_version = 3;

COMMIT;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;

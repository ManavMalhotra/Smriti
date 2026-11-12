BEGIN;
CREATE TABLE IF NOT EXISTS medication (
    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    brand_raw TEXT NOT NULL, salt TEXT, dose TEXT, freq TEXT, start_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('prescribed', 'reported_stopped', 'reported_ongoing')),
    reported_at TEXT, source_doc_id TEXT REFERENCES document(id) ON DELETE SET NULL
);
ALTER TABLE observation ADD COLUMN clinical_json TEXT;
ALTER TABLE medication ADD COLUMN clinical_json TEXT;
ALTER TABLE medication ADD COLUMN page INTEGER;
ALTER TABLE medication ADD COLUMN bbox_json TEXT;
ALTER TABLE medication ADD COLUMN engine TEXT;
CREATE TABLE cloud_consent (
    document_id TEXT PRIMARY KEY REFERENCES document(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('awaiting', 'approved', 'declined', 'processing', 'completed', 'failed')),
    extra_boxes_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);
PRAGMA user_version = 13;
COMMIT;

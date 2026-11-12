-- v7 -> v8: logical reports and searchable facts.
PRAGMA journal_mode = WAL;

BEGIN;

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

-- Existing documents were one timeline item before v8. Backfill one report
-- each so no historical observation loses its source.
INSERT INTO report
    (id, document_id, patient_id, category, report_type, report_date,
     facility_name, title, summary, page_start, page_end, status, reason,
     model_version, created_at)
SELECT
    lower(hex(randomblob(16))),
    d.id,
    d.patient_id,
    CASE
        WHEN d.doc_type = 'lab_report' THEN 'lab'
        WHEN d.doc_type IN ('ct', 'mri', 'xray', 'radiology') THEN 'imaging'
        WHEN d.doc_type IN ('prescription', 'pharmacy') THEN 'prescription'
        WHEN d.doc_type = 'discharge_summary' THEN 'discharge'
        WHEN d.doc_type = 'pathology' THEN 'pathology'
        ELSE 'other'
    END,
    d.doc_type,
    COALESCE(d.collection_date, d.report_date, d.doc_date, d.registration_date),
    COALESCE(d.facility_name, d.lab_name),
    COALESCE(d.facility_name, d.lab_name, 'Report'),
    NULL,
    1,
    d.page_count,
    CASE
        WHEN COALESCE(d.collection_date, d.report_date, d.doc_date, d.registration_date) IS NULL
          OR d.doc_type = 'other'
        THEN 'review'
        ELSE 'auto'
    END,
    'Backfilled during schema v8 migration; review report date and category.',
    'migration-008',
    d.created_at
FROM document d;

ALTER TABLE observation ADD COLUMN report_id TEXT REFERENCES report(id) ON DELETE SET NULL;
ALTER TABLE observation ADD COLUMN label_norm TEXT;
ALTER TABLE observation ADD COLUMN fact_type TEXT NOT NULL DEFAULT 'lab' CHECK (fact_type IN (
    'lab', 'measurement', 'impression', 'imaging_finding',
    'diagnosis', 'recommendation', 'note', 'other'
));
ALTER TABLE observation ADD COLUMN evidence_quote TEXT;

UPDATE observation
SET report_id = (
    SELECT r.id FROM report r
    WHERE r.document_id = observation.document_id
    LIMIT 1
);

UPDATE observation
SET fact_type = CASE
        WHEN analyte_id IS NOT NULL THEN 'lab'
        WHEN value_num IS NOT NULL THEN 'measurement'
        ELSE 'note'
    END,
    label_norm = NULLIF(lower(trim(COALESCE(label_raw, ''))), ''),
    evidence_quote = CASE WHEN value_num IS NULL THEN value_text ELSE NULL END;

CREATE INDEX idx_report_patient_date ON report(patient_id, report_date);
CREATE INDEX idx_report_document ON report(document_id, page_start);
CREATE INDEX idx_obs_report ON observation(report_id, status);

PRAGMA user_version = 8;

COMMIT;

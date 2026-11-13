-- Smriti migration 015: Allow human overrides on handwritten/low-quality documents

DROP TRIGGER IF EXISTS observation_no_auto_handwritten_insert;
DROP TRIGGER IF EXISTS observation_no_auto_handwritten_update;
DROP TRIGGER IF EXISTS observation_no_numeric_handwritten_insert;
DROP TRIGGER IF EXISTS observation_no_numeric_handwritten_update;

CREATE TRIGGER observation_no_auto_handwritten_insert BEFORE INSERT ON observation
WHEN NEW.status = 'auto' AND NEW.engine != 'human' AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN SELECT RAISE(ABORT, 'SI-01: handwritten observation cannot be auto'); END;
CREATE TRIGGER observation_no_auto_handwritten_update BEFORE UPDATE ON observation
WHEN NEW.status = 'auto' AND NEW.engine != 'human' AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN SELECT RAISE(ABORT, 'SI-01: handwritten observation cannot be auto'); END;
CREATE TRIGGER observation_no_numeric_handwritten_insert BEFORE INSERT ON observation
WHEN NEW.value_num IS NOT NULL AND NEW.engine != 'human' AND NEW.status <> 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN SELECT RAISE(ABORT, 'SI-02: no numeric laboratory value from a handwritten document'); END;
CREATE TRIGGER observation_no_numeric_handwritten_update BEFORE UPDATE ON observation
WHEN NEW.value_num IS NOT NULL AND NEW.engine != 'human' AND NEW.status <> 'auto'
 AND (SELECT capture_type FROM document WHERE id = NEW.document_id) = 'handwritten'
BEGIN SELECT RAISE(ABORT, 'SI-02: no numeric laboratory value from a handwritten document'); END;

PRAGMA user_version = 15;

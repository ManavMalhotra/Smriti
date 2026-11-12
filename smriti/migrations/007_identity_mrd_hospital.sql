-- v6 -> v7: patient_mrd and hospital identity fields.
PRAGMA journal_mode = WAL;

BEGIN;

ALTER TABLE document ADD COLUMN patient_mrd TEXT;
ALTER TABLE document ADD COLUMN hospital TEXT;

PRAGMA user_version = 7;

COMMIT;

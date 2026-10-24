-- v3 -> v4: identity separation (doctor_reg_no vs patient_uhid) and discrete date tracking.
PRAGMA journal_mode = WAL;

BEGIN;

ALTER TABLE document ADD COLUMN registration_date TEXT;
ALTER TABLE document ADD COLUMN report_date TEXT;
ALTER TABLE document ADD COLUMN patient_uhid TEXT;
ALTER TABLE document ADD COLUMN doctor_reg_no TEXT;
ALTER TABLE document ADD COLUMN facility_name TEXT;

PRAGMA user_version = 4;

COMMIT;

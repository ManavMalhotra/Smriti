BEGIN;

ALTER TABLE document ADD COLUMN display_name TEXT;
ALTER TABLE document ADD COLUMN verified_date TEXT;

PRAGMA user_version = 14;
COMMIT;

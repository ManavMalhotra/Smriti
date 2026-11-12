BEGIN;
ALTER TABLE jobs ADD COLUMN progress_json TEXT;
PRAGMA user_version = 9;
COMMIT;

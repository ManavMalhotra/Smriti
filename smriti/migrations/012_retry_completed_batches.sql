-- v11 -> v12: allow a promoted job to re-enter the queue after its batch completed.
-- Membership stays frozen while a batch is still active.
PRAGMA journal_mode = WAL;
BEGIN;
DROP TRIGGER IF EXISTS submissions_batch_frozen;
CREATE TRIGGER submissions_batch_frozen
BEFORE UPDATE OF batch_id, batch_position ON submissions
WHEN OLD.batch_id IS NOT NULL AND (NEW.batch_id IS NOT OLD.batch_id OR NEW.batch_position IS NOT OLD.batch_position)
     AND (SELECT state FROM stage_batches WHERE id = OLD.batch_id) <> 'done'
BEGIN
    SELECT RAISE(ABORT, 'submission batch membership is frozen');
END;
PRAGMA user_version = 12;
COMMIT;

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from smriti import erasure
from smriti.coordinator import CleanupBlocked, Coordinator
from smriti.service import Service
from smriti.spool import owner_lock
from tests.test_preparation import inline_supervisor, submit
from tests.test_service import Diagnostics
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


def erase(spool_db, settings):
    erasure.erase_owner(spool_db, settings, {"id": "p1"}, Service(spool_db, settings, Diagnostics()))


def test_pending_owner_erasure_removes_only_owned_raw_and_rows(spool_db, settings):
    job = submit(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, content_hash, status, created_at) VALUES ('other', 'p2', 'other', 'printed', 'other', 'other-hash', 'done', '2026-11-06')"))
    other = settings.upload_dir / "other"
    other.mkdir(parents=True)
    (other / "page_1.webp").write_bytes(b"OTHER_OWNER")
    erase(spool_db, settings)
    assert not (settings.spool_dir / f"{job}.raw").exists()
    assert (other / "page_1.webp").read_bytes() == b"OTHER_OWNER"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT id FROM patient")).scalar_one() == "p2"
        assert conn.execute(text("SELECT COUNT(*) FROM submissions")).scalar_one() == 0


def test_locked_source_keeps_cleanup_metadata_and_can_be_retried(monkeypatch, spool_db, settings):
    job = submit(spool_db, settings)
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        controller.process_batch()
    original = Path.unlink
    def locked(path, *args, **kwargs):
        if path.suffix == ".webp":
            raise PermissionError("PRIVATE_LOCK_ERROR")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", locked)
        with pytest.raises(CleanupBlocked):
            erase(spool_db, settings)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT image_path FROM document WHERE patient_id = 'p1'")).scalar_one() == job
        assert conn.execute(text("SELECT consent_revoked_at FROM submissions")).scalar_one() is not None
    erase(spool_db, settings)
    assert not (settings.upload_dir / job).exists()


def test_erased_member_of_interrupted_frozen_batch_is_skipped_without_replacement(spool_db, settings):
    job = submit(spool_db, settings)
    with Coordinator(spool_db, settings) as controller:
        assert controller._load_or_freeze() == [job]
    erase(spool_db, settings)
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT membership_json FROM stage_batches")).scalar_one()) == [job]
        assert conn.execute(text("SELECT state FROM stage_batches")).scalar_one() == "done"


def test_live_spooling_fences_erasure_without_deleting_the_account(spool_db, settings):
    with owner_lock(settings, "p1"):
        with pytest.raises(OSError):
            erase(spool_db, settings)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM patient WHERE id = 'p1'")).scalar_one() == 1


@pytest.mark.parametrize("cursor", [{"version": 1}, {"version": 2}, {"version": 1, "member": 0, "next_page": 1, "pass": "ocr", "active": {"name": "unowned"}}])
def test_malformed_checkpoint_cannot_terminate_trees_or_delete_files(monkeypatch, spool_db, settings, cursor):
    job = submit(spool_db, settings)
    with Coordinator(spool_db, settings) as controller:
        controller._load_or_freeze()
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE stage_batches SET checkpoints_json = :cursor"), {"cursor": json.dumps(cursor)})
    monkeypatch.setattr(erasure, "recover_stage_job", lambda *args: pytest.fail("No unvalidated recovery"))
    with pytest.raises(CleanupBlocked):
        erase(spool_db, settings)
    assert (settings.spool_dir / f"{job}.raw").exists()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM patient WHERE id = 'p1'")).scalar_one() == 1


def test_erasing_one_frozen_owner_preserves_other_member_and_later_arrivals(spool_db, settings):
    from smriti.spool import spool_upload
    from tests.test_spool import chunks
    from tests.test_preparation import pdf_bytes
    import asyncio

    first = submit(spool_db, settings)
    second = asyncio.run(spool_upload(spool_db, settings, chunks(pdf_bytes(2)), patient_id="p2", consent_scope="local")).job_id
    with Coordinator(spool_db, settings) as controller:
        assert controller._load_or_freeze() == [first, second]
    late = asyncio.run(spool_upload(spool_db, settings, chunks(pdf_bytes(3)), patient_id="p2", consent_scope="local")).job_id
    erase(spool_db, settings)
    with Coordinator(spool_db, settings, supervisor=inline_supervisor) as controller:
        assert controller.process_batch()
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT membership_json FROM stage_batches")).scalar_one()) == [first, second]
        assert conn.execute(text("SELECT state FROM jobs WHERE id = :job"), {"job": second}).scalar_one() == "done"
        assert conn.execute(text("SELECT state FROM submissions WHERE job_id = :job"), {"job": late}).scalar_one() == "pending_intake"

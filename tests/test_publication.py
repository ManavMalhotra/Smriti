from __future__ import annotations

import pytest
from sqlalchemy import text

from smriti import processing_helpers, publication
from smriti.processing_store import submission
from smriti.spool import SpoolError
from smriti.job_progress import read_progress
from tests.test_processing_helpers import rules
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


def ready(spool_db, settings):
    job, context = rules(spool_db, settings)
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'running' WHERE id = :id"), {"id": job})
    return job, context


def test_final_atomic_publication_retains_pages_and_completes_once(spool_db, settings):
    job, context = ready(spool_db, settings)
    publication.publication_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "done"
        assert conn.execute(text("SELECT COUNT(*) FROM page_text")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM report")).scalar_one() == 1
        progress = read_progress(conn.execute(text("SELECT progress_json FROM jobs")).scalar_one())
        assert progress["elapsed_seconds"] >= progress["events"][-1]["duration_seconds"]
    with pytest.raises(SpoolError, match="cancelled"):
        publication.publication_target(context, lambda *args, **kwargs: None)
    assert (settings.upload_dir / job / "page_1.webp").exists()


def test_late_insert_failure_rolls_back_pages_reports_and_done(spool_db, settings):
    job, context = ready(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("CREATE TRIGGER synthetic_save_failure BEFORE INSERT ON page_text BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"))
    with pytest.raises(Exception):
        publication.publication_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state FROM jobs")).scalar_one() == "running"
        for table in ("page_text", "observation", "medication", "directive", "report"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0


def test_revoked_or_populated_document_cannot_be_republished(spool_db, settings):
    job, context = ready(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE consent SET revoked_at = '2026-11-05'"))
    with pytest.raises(SpoolError, match="cancelled"):
        publication.publication_target(context, lambda *args, **kwargs: None)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM report")).scalar_one() == 0

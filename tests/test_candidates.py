from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti.candidates import Candidates, candidate_path
from smriti.extract import ExtractedMedication
from smriti.reports import ReportDraft
from smriti.spool import SpoolError, spool_upload
from tests.test_spool import chunks, spool_db
from tests.test_worker import _field

pytestmark = pytest.mark.integration


def pending(spool_db, settings):
    return asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-private-candidates"), patient_id="p1", consent_scope="local")).job_id


def test_first_seen_dedup_last_qwen_match_and_private_report_resolution(spool_db, settings):
    job = pending(spool_db, settings)
    with Candidates(spool_db, settings, job, {"job_id": job}, create=True) as scratch:
        first = _field("92", engine="ocr")
        scratch.add("field", first, dedup=("glucose", "92", 1), match_key="glucose")
        scratch.add("field", replace(first, reason="later"), dedup=("glucose", "92", 1), match_key="glucose")
        scratch.add("vlm", first, dedup=("glucose", 1), match_key="glucose", replace=True)
        scratch.add("vlm", replace(first, value_num="93"), dedup=("glucose", 1), match_key="glucose", replace=True)
        scratch.add("checked", first)
        scratch.add("medication", ExtractedMedication("synthetic", "1 mg", None, .9), dedup=("synthetic", "1 mg", None))
        report = ReportDraft(id="report", category="lab", report_type="lab_report", report_date=None,
                             facility_name=None, title="Synthetic", summary=None, page_start=1,
                             page_end=21, status="review", reason=None)
        scratch.add_report(report)
        scratch.associate_reports()
        assert list(scratch.rows("field"))[0][1]["reason"] == first.reason
        assert scratch.matching("vlm", 1, "glucose")["value_num"] == "93"
        assert list(scratch.rows("checked"))[0][2] == report.id
        actual = scratch.size()
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())["reserved_bytes"] == actual
        assert conn.execute(text("SELECT COUNT(*) FROM observation")).scalar_one() == 0
    with Candidates(spool_db, settings, job, {"job_id": job}) as scratch:
        assert scratch.count("field") == 1
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        Candidates(spool_db, settings, job, {"job_id": "changed"})


def test_quota_failure_precedes_private_database_creation(spool_db, settings):
    job = pending(spool_db, settings)
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        Candidates(spool_db, replace(settings, active_output_bytes=1), job, {}, create=True)
    assert not candidate_path(settings, job).exists()


def test_link_or_unowned_candidate_database_is_never_overwritten(spool_db, settings):
    job = pending(spool_db, settings)
    path = candidate_path(settings, job)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"USER_WORK")
    with pytest.raises(Exception):
        Candidates(spool_db, settings, job, {}, create=True)
    assert path.read_bytes() == b"USER_WORK"


def test_valid_unowned_sqlite_is_checked_read_only_before_any_write(spool_db, settings):
    import sqlite3

    job = pending(spool_db, settings)
    path = candidate_path(settings, job)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE user_work (value TEXT)")
        conn.execute("INSERT INTO user_work VALUES ('preserved')")
    before = path.read_bytes()
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        Candidates(spool_db, settings, job, {}, create=True)
    assert path.read_bytes() == before

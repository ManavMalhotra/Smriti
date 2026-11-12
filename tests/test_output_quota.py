from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti.output_quota import bounded_bytes, release_output, reserve_output, write_reserved
from smriti.spool import SpoolError, spool_upload
from tests.test_spool import chunks, spool_db

pytestmark = pytest.mark.integration


def submission(engine, settings, index=1):
    return asyncio.run(spool_upload(engine, settings, chunks(b"%PDF-" + str(index).encode()), patient_id="p1", consent_scope="local")).job_id


def reserved(engine, job_id):
    with engine.connect() as conn:
        value = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).scalar_one()
    return json.loads(value)["reserved_bytes"]


def test_output_capacity_is_independent_of_page_count_and_stays_durable(spool_db, settings):
    settings = replace(settings, active_output_bytes=100)
    job_id = submission(spool_db, settings)
    reserve_output(spool_db, settings, job_id, 60)
    assert reserved(spool_db, job_id) == 60
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        reserve_output(spool_db, settings, job_id, 41)
    assert reserved(spool_db, job_id) == 60
    release_output(spool_db, job_id, 30)
    reserve_output(spool_db, settings, job_id, 70)
    assert reserved(spool_db, job_id) == 100


def test_concurrent_reservations_cannot_exceed_global_quota(spool_db, settings):
    settings = replace(settings, active_output_bytes=100)
    jobs = [submission(spool_db, settings, index) for index in range(2)]
    barrier = threading.Barrier(2)
    outcomes = []

    def attempt(job_id):
        barrier.wait(timeout=5)
        try:
            reserve_output(spool_db, settings, job_id, 75)
            outcomes.append("reserved")
        except SpoolError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=attempt, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["capacity_exhausted", "reserved"]


def test_file_writes_account_temp_wal_and_actual_bytes(spool_db, settings, tmp_path):
    job = submission(spool_db, settings)
    path = tmp_path / "owned.json"
    write_reserved(spool_db, settings, job, path, b"synthetic")
    assert path.read_bytes() == b"synthetic" and not path.with_name("owned.json.tmp").exists()
    assert reserved(spool_db, job) == len(b"synthetic")
    assert bounded_bytes(path, 9) == b"synthetic"
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        bounded_bytes(path, 8)
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        write_reserved(spool_db, settings, job, path, b"new")
    assert path.read_bytes() == b"synthetic"
    assert reserved(spool_db, job) > 9  # Failed duplicate/temp writes remain charged until confirmed cleanup.


def test_revoked_or_failed_submission_cannot_reserve_more_output(spool_db, settings):
    job = submission(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed' WHERE job_id = :id"), {"id": job})
    with pytest.raises(SpoolError, match="cancelled"):
        reserve_output(spool_db, settings, job, 1)


def test_release_cannot_hide_unowned_or_unreserved_bytes(spool_db, settings):
    job = submission(spool_db, settings)
    reserve_output(spool_db, settings, job, 1)
    with pytest.raises(ValueError, match="unreserved"):
        release_output(spool_db, job, 2)
    assert reserved(spool_db, job) == 1


def test_empty_reservation_release_and_atomic_manifest_initialization(spool_db, settings):
    job = submission(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = '{}' WHERE job_id = :id"), {"id": job})
    release_output(spool_db, job, 0)
    assert reserved(spool_db, job) == 0
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        reserve_output(spool_db, replace(settings, active_output_bytes=1), job, 2, manifest_changes={"version": 2})
    with spool_db.connect() as conn:
        assert json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job}).scalar_one()) == {"reserved_bytes": 0}
    reserve_output(spool_db, settings, job, 2, manifest_changes={"version": 2})
    assert reserved(spool_db, job) == 2

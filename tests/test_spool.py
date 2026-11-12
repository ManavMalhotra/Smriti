from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace

import pytest
from sqlalchemy import text

from smriti.db import create_db_engine, init_db
from smriti.spool import SpoolError, delete_spool, recover_spool, spool_upload

pytestmark = pytest.mark.integration


@pytest.fixture
def spool_db(settings):
    init_db(settings.db_path)
    engine = create_db_engine(settings.db_path)
    with engine.begin() as conn:
        for patient in ("p1", "p2"):
            conn.execute(text("INSERT INTO patient (id, alias, created_at) VALUES (:id, 'synthetic', '2026-01-01')"), {"id": patient})
    yield engine
    engine.dispose()


async def chunks(data, split=7):
    for offset in range(0, len(data), split):
        yield data[offset:offset + split]


def test_bounded_spool_preserves_patient_hash_unknown_counts_and_no_clinical_rows(spool_db, settings):
    data = b"%PDF-SYNTHETIC_NOT_DECODED"
    result = asyncio.run(spool_upload(spool_db, settings, chunks(data), patient_id="p1", consent_scope="local"))
    assert result.document_id is None and result.status == "pending_intake"
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT * FROM submissions")).mappings().one()
        assert row["content_hash"] == hashlib.sha256(b"p1\0" + data).hexdigest()
        assert row["spool_bytes"] == len(data)
        assert row["total_pages"] is None and row["document_id"] is None
        assert json.loads(row["progress_json"])["events"][0]["event"] == "intake_accepted"
        for table in ("document", "jobs", "consent", "observation", "report"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0
    assert (settings.spool_dir / f"{result.job_id}.raw").read_bytes() == data
    assert not list(settings.spool_dir.glob("*.part"))
    marker = json.loads((settings.spool_dir / f"{result.job_id}.reservation").read_text())
    assert marker["state"] == "ready" and marker["bytes"] == settings.max_upload_bytes


def test_duplicate_uploads_converge_on_one_pending_job_but_not_across_owners(spool_db, settings):
    data = b"%PDF-SYNTHETIC"

    async def upload(patient):
        return await spool_upload(spool_db, settings, chunks(data), patient_id=patient, consent_scope="local")

    async def race():
        return await asyncio.gather(upload("p1"), upload("p1"))

    first, second = asyncio.run(race())
    assert first.job_id == second.job_id and first.duplicate != second.duplicate
    other = asyncio.run(upload("p2"))
    assert other.job_id != first.job_id
    assert len(list(settings.spool_dir.glob("*.raw"))) == 2
    assert len(list(settings.spool_dir.glob("*.reservation"))) == 2


@pytest.mark.parametrize("data,code", [(b"", "invalid_file"), (b"invalid", "unsupported_type"), (b"%PDF-" + b"x" * 100, "too_large")])
def test_bad_input_removes_only_owned_partials(spool_db, settings, data, code):
    settings = replace(settings, max_upload_bytes=50)
    settings.spool_dir.mkdir()
    keep = settings.spool_dir / "keep.txt"
    keep.write_text("user work")
    with pytest.raises(SpoolError, match=code):
        asyncio.run(spool_upload(spool_db, settings, chunks(data), patient_id="p1", consent_scope="local"))
    assert keep.read_text() == "user work"
    assert not list(settings.spool_dir.glob("*.raw"))
    assert not list(settings.spool_dir.glob("*.part"))
    assert not list(settings.spool_dir.glob("*.reservation"))


def test_disconnect_and_cancellation_clean_ephemeral_partial(spool_db, settings):
    async def disconnected():
        yield b"%PDF-"
        raise ConnectionError("PRIVATE_SENTINEL")

    with pytest.raises(SpoolError, match="disconnected"):
        asyncio.run(spool_upload(spool_db, settings, disconnected(), patient_id="p1", consent_scope="local"))
    assert not list(settings.spool_dir.glob("*.part"))
    assert not list(settings.spool_dir.glob("*.reservation"))

    async def cancelled():
        yield b"%PDF-"
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(spool_upload(spool_db, settings, cancelled(), patient_id="p1", consent_scope="local"))
    assert not list(settings.spool_dir.glob("*.part"))
    assert not list(settings.spool_dir.glob("*.reservation"))


def test_raw_slots_and_spooler_reservations_are_bounded(spool_db, settings):
    settings = replace(settings, max_upload_bytes=100)
    with spool_db.begin() as conn:
        conn.execute(text("INSERT INTO patient (id, alias, created_at) VALUES ('p3', 'synthetic', '2026-01-01')"))

    async def held_upload(started, release, index):
        async def held():
            started.set()
            await release.wait()
            yield b"%PDF-" + str(index).encode()
        return await spool_upload(spool_db, settings, held(), patient_id=f"p{index + 1}", consent_scope="local")

    async def race():
        starts, release = [asyncio.Event(), asyncio.Event()], asyncio.Event()
        tasks = [asyncio.create_task(held_upload(starts[index], release, index)) for index in range(2)]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in starts)), timeout=5)
        try:
            with pytest.raises(SpoolError, match="capacity_exhausted"):
                await spool_upload(spool_db, settings, chunks(b"%PDF-third"), patient_id="p3", consent_scope="local")
        finally:
            release.set()
            await asyncio.gather(*tasks)
    asyncio.run(race())
    for index in range(2, 20):
        asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-" + str(index).encode()), patient_id="p1", consent_scope="local"))
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-overflow"), patient_id="p1", consent_scope="local"))
    assert len(list(settings.spool_dir.glob("*.raw"))) == 20
    assert len(list(settings.spool_dir.glob("*.reservation"))) == 20


def test_low_disk_space_fails_before_source_read(monkeypatch, spool_db, settings):
    from smriti import spool
    monkeypatch.setattr(spool.shutil, "disk_usage", lambda _: type("Disk", (), {"free": 0})())

    async def never_read():
        raise AssertionError("Must not read input without capacity")
        yield b""

    with pytest.raises(SpoolError, match="capacity_exhausted"):
        asyncio.run(spool_upload(spool_db, settings, never_read(), patient_id="p1", consent_scope="local"))
    assert not list(settings.spool_dir.glob("*.reservation"))


def test_cleanup_requires_terminal_state_and_records_confirmed_absence(spool_db, settings):
    result = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-failed"), patient_id="p1", consent_scope="local"))
    assert not delete_spool(spool_db, settings, result.job_id)
    assert (settings.spool_dir / f"{result.job_id}.raw").exists()
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed' WHERE job_id = :id"), {"id": result.job_id})
    assert delete_spool(spool_db, settings, result.job_id)
    assert delete_spool(spool_db, settings, result.job_id)
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT spool_cleanup_state, spool_deleted_at, spool_cleanup_requested_at FROM submissions")).one()
        assert row[0] == "deleted" and row[1] is not None and row[2] is not None
    assert not list(settings.spool_dir.glob("*.raw"))
    assert not list(settings.spool_dir.glob("*.reservation"))


def test_locked_raw_cleanup_failure_is_durable_and_retryable(monkeypatch, spool_db, settings):
    from pathlib import Path

    result = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-failed"), patient_id="p1", consent_scope="local"))
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed' WHERE job_id = :id"), {"id": result.job_id})
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path.suffix == ".raw":
            raise PermissionError("PRIVATE_SENTINEL")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", locked)
        assert not delete_spool(spool_db, settings, result.job_id)
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT spool_cleanup_state, spool_deleted_at, spool_cleanup_error_code FROM submissions")).one()
        assert row == ("failed", None, "cleanup_failed")
    assert delete_spool(spool_db, settings, result.job_id)


def test_spool_module_does_not_import_decoders_or_model_runtimes():
    import subprocess

    result = subprocess.run([sys.executable, "-c",
        "import smriti.spool,sys; assert not any(m in sys.modules for m in ('cv2','pymupdf','PIL','torch','paddle','onnxruntime'))"],
        check=True, capture_output=True, timeout=10)
    assert result.returncode == 0


def test_recovery_removes_dead_orphans_and_preserves_unrelated_files(spool_db, settings):
    from smriti.private_paths import private_directory

    private_directory(settings.spool_dir)
    key = "a" * 32
    (settings.spool_dir / f"{key}.reservation").write_text(json.dumps({"version": 1, "state": "writing", "bytes": settings.max_upload_bytes,
        "owner_pid": 2**30, "owner_created_at": 1}))
    (settings.spool_dir / f"{key}.part").write_bytes(b"partial")
    (settings.spool_dir / "keep.txt").write_bytes(b"USER_WORK")
    (settings.spool_dir / ("b" * 32 + ".raw")).write_bytes(b"orphan")
    assert recover_spool(spool_db, settings)
    assert not list(settings.spool_dir.glob("*.part"))
    assert not list(settings.spool_dir.glob("*.raw"))
    assert (settings.spool_dir / "keep.txt").read_bytes() == b"USER_WORK"


def test_recovery_preserves_live_writers_and_repairs_committed_marker(spool_db, settings):
    import psutil
    from smriti.private_paths import private_directory

    private_directory(settings.spool_dir)
    process = psutil.Process()
    key = "a" * 32
    marker = settings.spool_dir / f"{key}.reservation"
    marker.write_text(json.dumps({"version": 1, "state": "writing", "bytes": settings.max_upload_bytes,
        "owner_pid": process.pid, "owner_created_at": process.create_time()}))
    partial = settings.spool_dir / f"{key}.part"
    partial.write_bytes(b"live partial")
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-ready"), patient_id="p1", consent_scope="local")).job_id
    ready = settings.spool_dir / f"{job}.reservation"
    ready.unlink()
    assert recover_spool(spool_db, settings)
    assert partial.read_bytes() == b"live partial"
    assert json.loads(ready.read_text())["state"] == "ready"


def test_raw_orphans_count_toward_admission_before_recovery(spool_db, settings):
    from smriti.private_paths import private_directory

    private_directory(settings.spool_dir)
    for index in range(20):
        (settings.spool_dir / f"{index:032x}.raw").write_bytes(b"orphan")
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-new"), patient_id="p1", consent_scope="local"))
    assert recover_spool(spool_db, settings)
    assert not list(settings.spool_dir.glob("*.raw"))


def test_recovery_cannot_release_raw_before_failed_output_cleanup(spool_db, settings):
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-failed"), patient_id="p1", consent_scope="local")).job_id
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed', preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job, "manifest": json.dumps({"reserved_bytes": 1024})})
    assert not recover_spool(spool_db, settings)
    assert (settings.spool_dir / f"{job}.raw").exists()


def test_recovery_locked_orphan_blocks_admission_without_deleting_user_work(monkeypatch, spool_db, settings):
    from pathlib import Path
    from smriti.private_paths import private_directory

    private_directory(settings.spool_dir)
    orphan = settings.spool_dir / ("a" * 32 + ".raw")
    orphan.write_bytes(b"orphan")
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path == orphan:
            raise PermissionError("PRIVATE_SENTINEL")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", locked)
        assert not recover_spool(spool_db, settings)
    assert orphan.exists()
    assert recover_spool(spool_db, settings)


def test_recovery_finds_missing_database_only_source_and_preserves_output_charge(spool_db, settings):
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-missing"), patient_id="p1", consent_scope="local")).job_id
    for suffix in ("raw", "reservation"):
        (settings.spool_dir / f"{job}.{suffix}").unlink()
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job, "manifest": json.dumps({"reserved_bytes": 1024})})
    assert not recover_spool(spool_db, settings)
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT state, error_code, spool_cleanup_requested_at, preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job}).one()
    assert row[0:2] == ("failed", "source_missing") and row[2] is not None
    assert json.loads(row[3])["reserved_bytes"] == 1024
    assert not recover_spool(spool_db, settings)


def test_recovery_confirms_prior_unlink_and_repairs_deleted_timestamp(spool_db, settings):
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-unlinked"), patient_id="p1", consent_scope="local")).job_id
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed' WHERE job_id = :id"), {"id": job})
    for suffix in ("raw", "reservation"):
        (settings.spool_dir / f"{job}.{suffix}").unlink()
    assert recover_spool(spool_db, settings)
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT spool_cleanup_state, spool_deleted_at FROM submissions")).one()[0] == "deleted"
        assert conn.execute(text("SELECT spool_deleted_at FROM submissions")).scalar_one() is not None


def test_delete_spool_itself_preserves_terminal_expanded_output_barrier(spool_db, settings):
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-charged"), patient_id="p1", consent_scope="local")).job_id
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'failed', preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job, "manifest": json.dumps({"reserved_bytes": 1})})
    assert not delete_spool(spool_db, settings, job)
    assert (settings.spool_dir / f"{job}.raw").exists()

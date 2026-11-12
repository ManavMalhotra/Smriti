from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace

import pymupdf
import pytest
from sqlalchemy import text

from smriti import preparation
from smriti.runtime import StageResult, run_stage
from smriti.spool import spool_upload
from tests.test_spool import chunks, spool_db

pytestmark = pytest.mark.integration
windows = pytest.mark.skipif(os.name != "nt", reason="Windows supervised preparation")


def pdf_bytes(pages):
    document = pymupdf.open()
    try:
        for number in range(pages):
            page = document.new_page(width=300, height=300)
            for line in range(15):
                page.insert_text((15, 20 + line * 17), f"SYNTHETIC TEST row {line} page {number + 1}", fontsize=9)
        return document.tobytes()
    finally:
        document.close()


def submit(engine, settings, pages=1):
    return asyncio.run(spool_upload(engine, settings, chunks(pdf_bytes(pages), split=1024),
                                   patient_id="p1", consent_scope="local")).job_id


@windows
@pytest.mark.parametrize("pages", [21, 39, 41])
def test_long_synthetic_pdf_prepares_one_document_and_deletes_raw(spool_db, settings, pages):
    job = submit(spool_db, settings, pages)
    calls = []

    def supervised(target, context, **kwargs):
        calls.append((target.rsplit(":", 1)[1], context.get("start"), context.get("end")))
        return run_stage(target, context, **kwargs)

    result = preparation.prepare_submission(spool_db, settings, job, supervisor=supervised)
    assert result.success, result
    ranges = [(start, end) for target, start, end in calls if target == "preparation_target"]
    assert ranges == [(start, min(start + 19, pages)) for start in range(1, pages + 1, 20)]
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT document_id, total_pages, spool_cleanup_state, spool_deleted_at, preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job}).one()
        assert row[1:4] == (pages, "deleted", row[3]) and row[3] is not None
        manifest = json.loads(row[4])
        assert manifest["prepared_pages"] == manifest["validated_pages"] == pages
        assert len(row[4]) < 2048
        assert conn.execute(text("SELECT id, document_id, total FROM jobs")).one() == (job, row[0], pages)
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM consent")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM observation")).scalar_one() == 0
        quality = json.loads(conn.execute(text("SELECT quality_json FROM document")).scalar_one())
        assert quality["page_count"] == pages and quality["pages"] == []
    assert len(list((settings.upload_dir / job).glob("page_*.webp"))) == pages
    assert len(list((settings.upload_dir / job).glob("page_*.meta.json"))) == pages
    assert not list(settings.spool_dir.glob("*.raw"))


@windows
def test_later_window_failure_publishes_nothing_and_cleans_only_owned_output(spool_db, settings):
    settings = replace(settings, max_workset_pages=1)
    job = submit(spool_db, settings, 2)
    keep = settings.upload_dir / "existing-user-source"
    keep.mkdir(parents=True)
    (keep / "page_1.webp").write_bytes(b"KEEP")

    def failing(target, context, **kwargs):
        if target.endswith("preparation_target") and context["start"] == 2:
            assert (settings.spool_dir / f"{job}.raw").exists()
            return StageResult("timeout", True, -1, 0)
        return run_stage(target, context, **kwargs)

    result = preparation.prepare_submission(spool_db, settings, job, supervisor=failing)
    assert result.status == "timeout"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0
        row = conn.execute(text("SELECT state, error_code, spool_cleanup_state, preparation_manifest_json FROM submissions")).one()
        assert row[:3] == ("failed", "preparation_timeout", "deleted")
        assert json.loads(row[3])["reserved_bytes"] == 0
    assert (keep / "page_1.webp").read_bytes() == b"KEEP"
    assert not (settings.upload_dir / ".runtime" / job).exists()


@windows
def test_unconfirmed_tree_cleanup_keeps_raw_and_prevents_promotion(spool_db, settings):
    job = submit(spool_db, settings)
    result = preparation.prepare_submission(spool_db, settings, job,
        supervisor=lambda *args, **kwargs: StageResult("cleanup_failed", False, None, 0))
    assert result.status == "cleanup_failed" and not result.success
    assert (settings.spool_dir / f"{job}.raw").exists()
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0
        assert conn.execute(text("SELECT state FROM submissions")).scalar_one() == "preparing"


@windows
def test_invalid_format_fails_in_background_without_clinical_rows(spool_db, settings):
    job = asyncio.run(spool_upload(spool_db, settings, chunks(b"%PDF-not-a-real-file"), patient_id="p1", consent_scope="local" )).job_id
    result = preparation.prepare_submission(spool_db, settings, job)
    assert result.status == "invalid_format"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state, error_code, spool_cleanup_state FROM submissions")).one() == ("rejected", "invalid_format", "deleted")
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0


@windows
def test_output_capacity_failure_does_not_wait_for_its_own_batch(spool_db, settings):
    job = submit(spool_db, settings)
    settings = replace(settings, active_output_bytes=1)
    result = preparation.prepare_submission(spool_db, settings, job)
    assert result.status == "capacity_exhausted" and result.cleanup_confirmed
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT state, error_code, spool_cleanup_state FROM submissions")).one() == ("failed", "capacity_exhausted", "deleted")


@windows
def test_changed_preparation_identity_never_reuses_old_pages(spool_db, settings):
    job = submit(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'preparing' WHERE job_id = :id"), {"id": job})
    context = {"settings": preparation.settings_context(settings), "job_id": job}
    result = run_stage("smriti.preparation:inspection_target", context, timeout_seconds=10, cpu_only=True)
    assert result.success
    result = preparation.prepare_submission(spool_db, replace(settings, quality_blur=settings.quality_blur + 1), job)
    assert result.status == "prepared_artifact_invalid"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0


def inline_supervisor(target, context, **kwargs):
    """Fault injection only; the long-document tests above use real owned Windows children."""
    from importlib import import_module

    module, name = target.split(":")
    def report(event, **fields):
        if kwargs.get("on_event") is not None:
            kwargs["on_event"]({"event": event, **fields})
    try:
        getattr(import_module(module), name)(context, report)
        return StageResult("ok", True, 0, 0)
    except Exception as exc:
        return StageResult(getattr(exc, "code", "stage_exception"), True, 0, 0)


def inspected(spool_db, settings):
    job = submit(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("UPDATE submissions SET state = 'preparing' WHERE job_id = :id"), {"id": job})
    context = {"settings": preparation.settings_context(settings), "job_id": job}
    preparation.inspection_target(context, lambda *args, **kwargs: None)
    return job, context


def test_resume_reuses_durable_page_after_checkpoint_interruption(monkeypatch, spool_db, settings):
    job, context = inspected(spool_db, settings)
    original = preparation._update_manifest

    def interrupted(engine, job_id, changes):
        if "prepared_pages" in changes:
            raise RuntimeError("synthetic crash between file durability and checkpoint")
        return original(engine, job_id, changes)

    with monkeypatch.context() as scoped:
        scoped.setattr(preparation, "_update_manifest", interrupted)
        with pytest.raises(RuntimeError):
            preparation.preparation_target({**context, "start": 1, "end": 1}, lambda *args, **kwargs: None)
    image = preparation._prepared_dir(settings, job) / "page_1.webp"
    before = image.read_bytes()
    monkeypatch.setattr(preparation, "_prepare_page", lambda *args: pytest.fail("Durable valid page must not render again"))
    result = preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor)
    assert result.success
    assert (settings.upload_dir / job / "page_1.webp").read_bytes() == before
    with spool_db.connect() as conn:
        manifest = json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())
    assert manifest["reserved_bytes"] == preparation.SQL_HEADROOM_BYTES + sum(path.stat().st_size for path in (settings.upload_dir / job).iterdir())


@pytest.mark.parametrize("corrupt", [False, True])
def test_resume_repairs_only_incomplete_new_page_and_reconciles_charge(monkeypatch, spool_db, settings, corrupt):
    job, context = inspected(spool_db, settings)
    root = preparation._prepared_dir(settings, job)
    root.mkdir(parents=True)
    (root / "page_1.webp").write_bytes(b"partial synthetic image")
    (root / "page_1.words.json.tmp").write_bytes(b"partial")
    if corrupt:
        (root / "page_1.meta.json").write_bytes(b"invalid")
    from smriti.output_quota import reserve_output
    reserve_output(spool_db, settings, job, 64 * 1024)
    assert preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor).success
    with spool_db.connect() as conn:
        manifest = json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions")).scalar_one())
    assert manifest["reserved_bytes"] == preparation.SQL_HEADROOM_BYTES + sum(path.stat().st_size for path in (settings.upload_dir / job).iterdir())
    assert not list((settings.upload_dir / job).glob("*.tmp"))


def test_final_promotion_transaction_rolls_back_all_rows(spool_db, settings):
    job = submit(spool_db, settings)
    with spool_db.begin() as conn:
        conn.execute(text("CREATE TRIGGER synthetic_promotion_failure BEFORE INSERT ON consent BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"))
    result = preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor)
    assert not result.success
    with spool_db.connect() as conn:
        for table in ("document", "jobs", "consent", "audit", "observation"):
            assert conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one() == 0
        assert conn.execute(text("SELECT state, spool_cleanup_state FROM submissions")).one() == ("failed", "deleted")
    assert not (settings.upload_dir / job).exists()


@pytest.mark.parametrize("debug,status,retained", [(False, "crash", False), (True, "crash", True), (True, "timeout", False)])
def test_debug_retention_is_explicit_and_crash_only(spool_db, settings, debug, status, retained):
    settings = replace(settings, debug_retain_failed_spool=debug)
    job = submit(spool_db, settings)
    result = preparation.prepare_submission(spool_db, settings, job,
        supervisor=lambda *args, **kwargs: StageResult(status, True, -1, 0))
    assert result.status == status
    assert (settings.spool_dir / f"{job}.raw").exists() == retained
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT spool_cleanup_state FROM submissions")).scalar_one() == ("debug_retained" if retained else "deleted")


def test_locked_output_keeps_charge_raw_and_durable_cleanup_failure(monkeypatch, spool_db, settings):
    from pathlib import Path

    job, context = inspected(spool_db, settings)
    preparation.preparation_target({**context, "start": 1, "end": 1}, lambda *args, **kwargs: None)
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path.suffix == ".webp":
            raise PermissionError("PRIVATE_SENTINEL")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", locked)
        assert not preparation.fail_preparation(spool_db, settings, job, StageResult("timeout", True, -1, 0))
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT spool_cleanup_state, spool_deleted_at, preparation_manifest_json FROM submissions")).one()
        assert row[0] == "failed" and row[1] is None and json.loads(row[2])["reserved_bytes"] > 0
    assert (settings.spool_dir / f"{job}.raw").exists()
    assert preparation.fail_preparation(spool_db, settings, job, StageResult("timeout", True, -1, 0))


def test_terminal_promoted_document_and_source_cannot_be_replaced(spool_db, settings):
    from smriti.spool import SpoolError

    job = submit(spool_db, settings)
    assert preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor).success
    path = settings.upload_dir / job / "page_1.webp"
    original = path.read_bytes()
    with pytest.raises(SpoolError, match="cancelled"):
        preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor)
    assert not preparation.fail_preparation(spool_db, settings, job, StageResult("timeout", True, -1, 0))
    assert path.read_bytes() == original


def test_revocation_before_promotion_publishes_nothing(spool_db, settings):
    job = submit(spool_db, settings)

    def revoke(target, context, **kwargs):
        result = inline_supervisor(target, context, **kwargs)
        if target.endswith("validation_target"):
            with spool_db.begin() as conn:
                conn.execute(text("UPDATE submissions SET consent_revoked_at = '2026-11-05' WHERE job_id = :id"), {"id": job})
        return result

    result = preparation.prepare_submission(spool_db, settings, job, supervisor=revoke)
    assert result.status == "cancelled"
    with spool_db.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0
        assert conn.execute(text("SELECT state, spool_cleanup_state FROM submissions")).one() == ("cancelled", "deleted")


def test_page_buffers_are_released_before_the_next_page(monkeypatch, spool_db, settings):
    import weakref
    from PIL import Image
    from smriti import quality

    job = submit(spool_db, settings, 2)
    images, metrics = [], []
    original_image, original_measure, original_page = Image.frombytes, quality.measure, preparation._prepare_page

    def tracked_image(*args, **kwargs):
        image = original_image(*args, **kwargs)
        images.append(weakref.ref(image))
        return image

    def tracked_measure(*args, **kwargs):
        metric = original_measure(*args, **kwargs)
        metrics.append(weakref.ref(metric))
        return metric

    def tracked_page(*args, **kwargs):
        assert not any(ref() is not None for ref in images + metrics)
        return original_page(*args, **kwargs)

    monkeypatch.setattr(Image, "frombytes", tracked_image)
    monkeypatch.setattr(quality, "measure", tracked_measure)
    monkeypatch.setattr(preparation, "_prepare_page", tracked_page)
    assert preparation.prepare_submission(spool_db, settings, job, supervisor=inline_supervisor).success
    assert len(images) >= 2 and len(metrics) == 2
    assert not any(ref() is not None for ref in images + metrics)

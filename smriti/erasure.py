"""Owner erasure keeps durable cleanup receipts until owned work and files are gone."""

import json
import os
import re

from sqlalchemy import text

from smriti.auth import audit
from smriti.coordinator import CleanupBlocked, validate_checkpoint
from smriti.preparation import fail_preparation
from smriti.private_paths import check_path
from smriti.processing_store import cleanup_processing
from smriti.runtime import CoordinatorLock, StageResult, recover_stage_job, sampler_job_name
from smriti.spool import _now, delete_spool, owner_lock


def _source_files(settings, relative):
    if not isinstance(relative, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", relative):
        raise CleanupBlocked("Source ownership cannot be validated")
    root = settings.upload_dir / relative
    check_path(root)
    if not root.exists():
        return
    if not root.is_dir():
        raise CleanupBlocked("Source ownership cannot be validated")
    with os.scandir(root) as entries:
        for entry in entries:
            path = root / entry.name
            check_path(path)
            if not re.fullmatch(r"page_[1-9][0-9]*\.(?:webp|words\.json|meta\.json)", entry.name) or not path.is_file():
                raise CleanupBlocked("Source ownership cannot be validated")
            yield path


def erase_owner(engine, settings, patient, service):
    """Caller authenticates the owner. Failure preserves DB paths and keeps admission fenced."""
    with service.guard, owner_lock(settings, patient["id"]):
        with engine.begin() as conn:
            conn.execute(text("UPDATE submissions SET consent_revoked_at = COALESCE(consent_revoked_at, :now) WHERE patient_id = :id"),
                         {"id": patient["id"], "now": _now()})
            conn.execute(text("UPDATE consent SET revoked_at = COALESCE(revoked_at, :now) WHERE document_id IN (SELECT id FROM document WHERE patient_id = :id)"),
                         {"id": patient["id"], "now": _now()})
        if not service.pause():
            raise CleanupBlocked("Owned work shutdown is unconfirmed")
        try:
            with CoordinatorLock(settings.db_path):
                _erase_stopped(engine, settings, patient)
        except (OSError, ValueError):
            raise CleanupBlocked("Owned file cleanup is unconfirmed") from None
        service.start()


def _erase_stopped(engine, settings, patient):
    owner = patient["id"]
    with engine.connect() as conn:
        batch = conn.execute(text("SELECT * FROM stage_batches WHERE state IN ('preparing', 'processing', 'cleanup_failed')")).mappings().first()
        jobs = conn.execute(text("SELECT job_id FROM submissions WHERE patient_id = :id"), {"id": owner}).scalars().all()
    cursor = None
    if batch is not None and set(jobs).intersection(json.loads(batch["membership_json"])):
        cursor = json.loads(batch["checkpoints_json"])
        validate_checkpoint(json.loads(batch["membership_json"]), cursor)
        active = cursor.get("active")
        if active:
            if (not recover_stage_job(active.get("name"), settings.cleanup_wait_seconds)
                    or not recover_stage_job(sampler_job_name(active.get("name")), settings.cleanup_wait_seconds)):
                raise CleanupBlocked("Owned work shutdown is unconfirmed")
            cursor["active"] = None
        cursor["erased"] = list(dict.fromkeys([*cursor.get("erased", []), *(job for job in json.loads(batch["membership_json"]) if job in jobs)]))
    for job in jobs:
        with engine.connect() as conn:
            state = conn.execute(text("SELECT state FROM submissions WHERE job_id = :id"), {"id": job}).scalar_one()
        cleaned = (cleanup_processing(engine, settings, job) and delete_spool(engine, settings, job)
                   if state == "promoted" else fail_preparation(engine, settings, job, StageResult("cancelled", True, 0, 0)))
        if not cleaned:
            raise CleanupBlocked("Disposable cleanup is unconfirmed")
    with engine.connect() as conn:
        docs = conn.execute(text("SELECT id, image_path, content_hash FROM document WHERE patient_id = :id"), {"id": owner}).all()
    for _, relative, _ in docs:
        for _ in _source_files(settings, relative):
            pass  # Validate every entry before removing this source set.
    for _, relative, _ in docs:
        for path in _source_files(settings, relative):
            path.unlink()
        root = settings.upload_dir / relative
        if root.exists():
            root.rmdir()
    with engine.begin() as conn:
        if cursor is not None:
            conn.execute(text("UPDATE stage_batches SET checkpoints_json = :cursor WHERE id = :id"),
                         {"id": batch["id"], "cursor": json.dumps(cursor, separators=(",", ":"))})
        for document, _, content_hash in docs:
            conn.execute(text("DELETE FROM stage_artifact WHERE content_hash = :hash"), {"hash": content_hash})
        conn.execute(text("DELETE FROM submissions WHERE patient_id = :id"), {"id": owner})
        conn.execute(text("DELETE FROM patient WHERE id = :id"), {"id": owner})
        audit(conn, entity="patient", entity_id=owner, field="deleted", old=None, new="true", actor="owner")

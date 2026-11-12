"""Durable in-flight reservations in the existing compact submission manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import text

from smriti.private_paths import check_path
from smriti.spool import SpoolError, check_free_space


def reserve_output(engine, settings, job_id, amount, *, manifest_changes=None):
    if type(amount) is not int or amount <= 0:
        raise ValueError("Output reservations must be positive integer bytes")
    check_free_space(settings, settings.upload_dir, settings.db_path.parent)
    with engine.begin() as conn:
        # Acquire SQLite's writer before reading the global sum; concurrent children cannot over-reserve.
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        row = conn.execute(text("SELECT preparation_manifest_json, state, consent_revoked_at FROM submissions WHERE job_id = :id"), {"id": job_id}).first()
        if row is None or row[1] not in {"pending_intake", "preparing", "promoted"} or row[2] is not None:
            raise SpoolError("cancelled")
        manifest = json.loads(row[0] or "{}")
        total = conn.execute(text("SELECT COALESCE(SUM(COALESCE(json_extract(preparation_manifest_json, '$.reserved_bytes'), 0)), 0) FROM submissions")).scalar_one()
        if total + amount > settings.active_output_bytes:
            raise SpoolError("capacity_exhausted")
        if manifest_changes is not None:
            if "reserved_bytes" in manifest_changes:
                raise ValueError("Manifest changes cannot overwrite reservations")
            manifest.update(manifest_changes)
        manifest["reserved_bytes"] = manifest.get("reserved_bytes", 0) + amount
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":"))})


def release_output(engine, job_id, amount):
    if type(amount) is not int or amount < 0:
        raise ValueError("Output release must be nonnegative integer bytes")
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        raw = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).scalar_one_or_none()
        if raw is None:
            return
        manifest = json.loads(raw)
        if amount > manifest.get("reserved_bytes", 0):
            raise ValueError("Cannot release unreserved output")
        manifest["reserved_bytes"] = manifest.get("reserved_bytes", 0) - amount
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":"))})


def reconcile_output(engine, settings, job_id, amount):
    """Replace a crash-era charge only after the caller confirms tree exit and scans owned output."""
    if type(amount) is not int or amount < 0:
        raise ValueError("Reconciled output must be nonnegative integer bytes")
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        row = conn.execute(text("SELECT preparation_manifest_json, state, consent_revoked_at FROM submissions WHERE job_id = :id"), {"id": job_id}).first()
        if row is None or row[1] != "preparing" or row[2] is not None:
            raise SpoolError("cancelled")
        manifest = json.loads(row[0] or "{}")
        total = conn.execute(text("SELECT COALESCE(SUM(COALESCE(json_extract(preparation_manifest_json, '$.reserved_bytes'), 0)), 0) FROM submissions")).scalar_one()
        if total - manifest.get("reserved_bytes", 0) + amount > settings.active_output_bytes:
            raise SpoolError("capacity_exhausted")
        manifest["reserved_bytes"] = amount
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"),
                     {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":"))})


def write_reserved(engine, settings, job_id, path: Path, payload: bytes):
    if len(payload) > settings.max_artifact_bytes:
        raise SpoolError("capacity_exhausted")
    check_path(path)
    temporary = path.with_name(path.name + ".tmp")
    check_path(temporary)
    # Account the incoming duplicate plus conservative SQLite/WAL headroom before either write.
    headroom = 64 * 1024
    reserve_output(engine, settings, job_id, len(payload) + headroom)
    with temporary.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    if path.exists():
        raise SpoolError("prepared_artifact_invalid")
    temporary.replace(path)
    release_output(engine, job_id, headroom)


def bounded_bytes(path: Path, limit: int) -> bytes:
    check_path(path)
    with path.open("rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise SpoolError("capacity_exhausted")
    return payload

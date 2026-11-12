"""Bounded, decoder-free intake. Raw files are ephemeral, not clinical records."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

import psutil
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from smriti.config import MAX_SPOOL_RAW_FILES, SPOOL_CHUNK_BYTES, Settings
from smriti.job_progress import record_progress
from smriti.private_paths import check_path, private_directory
from smriti.runtime import CoordinatorLock

_MARKER = re.compile(r"[0-9a-f]{32}\.reservation\Z")
_DOC_TYPES = {"lab_report", "prescription", "pharmacy", "discharge_summary", "ct", "mri", "xray", "pathology", "radiology", "other"}


class SpoolError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SubmissionResult:
    job_id: str | None
    document_id: str | None = None
    status: str = "pending_intake"
    duplicate: bool = False


def _now():
    return datetime.now(timezone.utc).isoformat()


def check_free_space(settings, *paths):
    for path in paths:
        while not path.exists():
            path = path.parent
        if shutil.disk_usage(path).free < settings.min_free_disk_bytes:
            raise SpoolError("capacity_exhausted")


def _markers(settings):
    markers = []
    raw_keys = set()
    # Bound inspection even if an unrelated process floods this private directory.
    with os.scandir(settings.spool_dir) as entries:
        for index, entry in enumerate(entries):
            if index >= 128:
                raise SpoolError("capacity_exhausted")
            if re.fullmatch(r"[0-9a-f]{32}\.(?:part|raw)", entry.name):
                path = settings.spool_dir / entry.name
                check_path(path)
                if not path.is_file() or path.stat().st_size > settings.max_upload_bytes:
                    raise SpoolError("spool_state_invalid")
                raw_keys.add(entry.name[:32])
            if not _MARKER.fullmatch(entry.name):
                continue
            path = settings.spool_dir / entry.name
            check_path(path)
            with path.open("rb") as source:
                payload = source.read(1025)
            if len(payload) > 1024:
                raise SpoolError("spool_state_invalid")
            try:
                marker = json.loads(payload)
                if marker["version"] != 1 or marker["state"] not in ("writing", "ready"):
                    raise ValueError
                if type(marker["bytes"]) is not int or marker["bytes"] < 1:
                    raise ValueError
                if (type(marker["owner_pid"]) is not int or marker["owner_pid"] < 1
                        or type(marker["owner_created_at"]) not in (int, float)
                        or not math.isfinite(marker["owner_created_at"]) or marker["owner_created_at"] <= 0):
                    raise ValueError
                marker["key"] = entry.name[:32]
                markers.append(marker)
            except (ValueError, TypeError, KeyError):
                raise SpoolError("spool_state_invalid") from None
    # A crash can leave a raw file without its marker; it still consumes a complete slot.
    for key in raw_keys - {marker["key"] for marker in markers}:
        markers.append({"key": key, "bytes": settings.max_upload_bytes, "state": "orphan"})
    return markers


def _reserve(settings, key):
    private_directory(settings.spool_dir)
    check_free_space(settings, settings.spool_dir, settings.db_path.parent)
    marker_path = settings.spool_dir / f"{key}.reservation"
    created = False
    try:
        with CoordinatorLock(settings.spool_dir / "spool-admission"):
            markers = _markers(settings)
            if (len(markers) >= MAX_SPOOL_RAW_FILES
                    or sum(marker["bytes"] for marker in markers) + settings.max_upload_bytes > MAX_SPOOL_RAW_FILES * settings.max_upload_bytes
                    or sum(marker["state"] == "writing" for marker in markers) >= settings.max_spoolers):
                raise SpoolError("capacity_exhausted")
            process = psutil.Process()
            payload = {"version": 1, "state": "writing", "bytes": settings.max_upload_bytes,
                       "owner_pid": process.pid, "owner_created_at": process.create_time()}
            with marker_path.open("xb") as marker:
                created = True
                marker.write(json.dumps(payload, separators=(",", ":")).encode())
                marker.flush()
                os.fsync(marker.fileno())
    except OSError:
        if created:
            try:
                marker_path.unlink()
            except OSError:
                raise SpoolError("cleanup_failed") from None
        raise SpoolError("spool_busy_or_disk_error") from None


def _remove_owned(settings, key):
    for suffix in ("part", "raw", "reservation.tmp"):
        path = settings.spool_dir / f"{key}.{suffix}"
        check_path(path)
        path.unlink(missing_ok=True)
        if path.exists():
            raise SpoolError("cleanup_failed")
    marker = settings.spool_dir / f"{key}.reservation"
    check_path(marker)
    marker.unlink(missing_ok=True)


def _duplicate(conn, patient_id, content_hash):
    row = conn.execute(text("""
        SELECT job_id, document_id, state FROM submissions
        WHERE patient_id = :patient AND content_hash = :hash
          AND state IN ('pending_intake', 'preparing', 'promoted')
        UNION ALL
        SELECT j.id, d.id, d.status FROM document d LEFT JOIN jobs j ON j.document_id = d.id
        WHERE d.patient_id = :patient AND d.content_hash = :hash LIMIT 1
    """), {"patient": patient_id, "hash": content_hash}).first()
    if row is None:
        return None
    return SubmissionResult(row[0], row[1], row[2], True)


def owner_lock(settings, patient_id):
    private_directory(settings.spool_dir / ".owners")
    return CoordinatorLock(settings.spool_dir / ".owners" / hashlib.sha256(patient_id.encode("utf-8")).hexdigest())


async def spool_upload(engine, settings: Settings, chunks, *, patient_id: str, consent_scope: str,
                       doc_type: str | None = None, doc_date: date | None = None,
                       collection_date: date | None = None, consent_version="1.0", form_fields=None) -> SubmissionResult:
    lock = owner_lock(settings, patient_id)
    try:
        lock.__enter__()
    except OSError:
        raise SpoolError("spool_busy_or_disk_error") from None
    try:
        return await _spool_upload(engine, settings, chunks, patient_id=patient_id, consent_scope=consent_scope,
                                  doc_type=doc_type, doc_date=doc_date, collection_date=collection_date,
                                  consent_version=consent_version, form_fields=form_fields)
    finally:
        lock.__exit__(None, None, None)


async def _spool_upload(engine, settings: Settings, chunks, *, patient_id: str, consent_scope: str,
                       doc_type: str | None = None, doc_date: date | None = None,
                       collection_date: date | None = None, consent_version="1.0", form_fields=None) -> SubmissionResult:
    if settings.demo:
        raise SpoolError("demo_read_only")
    if consent_scope not in {"local", "local_plus_projection"} or doc_type is not None and doc_type not in _DOC_TYPES:
        raise SpoolError("invalid_metadata")
    if consent_version != "1.0" or any(value is not None and not isinstance(value, date) for value in (doc_date, collection_date)):
        raise SpoolError("invalid_metadata")
    with engine.connect() as conn:
        if conn.execute(text("SELECT 1 FROM patient WHERE id = :id"), {"id": patient_id}).first() is None:
            raise SpoolError("not_found")
    key = uuid.uuid4().hex
    _reserve(settings, key)
    partial = settings.spool_dir / f"{key}.part"
    raw = settings.spool_dir / f"{key}.raw"
    digest = hashlib.sha256(patient_id.encode("utf-8") + b"\0")
    size = 0
    header = b""
    accepted = False
    try:
        with partial.open("xb") as output:
            async for chunk in chunks:
                if not isinstance(chunk, bytes) or len(chunk) > SPOOL_CHUNK_BYTES:
                    raise SpoolError("invalid_chunk")
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise SpoolError("too_large")
                check_free_space(settings, settings.spool_dir)
                digest.update(chunk)
                header = (header + chunk[:16])[:16] if len(header) < 16 else header
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        if form_fields is not None:
            if form_fields.get("patient_id") != patient_id:
                raise SpoolError("forbidden")
            consent_scope = form_fields.get("consent_scope")
            doc_type = form_fields.get("doc_type") or None
            if consent_scope not in {"local", "local_plus_projection"} or doc_type is not None and doc_type not in _DOC_TYPES:
                raise SpoolError("invalid_metadata")
            try:
                doc_date = date.fromisoformat(form_fields["doc_date"]) if form_fields.get("doc_date") else None
                collection_date = date.fromisoformat(form_fields["collection_date"]) if form_fields.get("collection_date") else None
            except (ValueError, TypeError):
                raise SpoolError("invalid_metadata") from None
        if size == 0:
            raise SpoolError("invalid_file")
        if not header.startswith((b"%PDF-", b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
            raise SpoolError("unsupported_type")
        partial.replace(raw)
        check_free_space(settings, settings.db_path.parent)
        now = _now()
        try:
            with engine.begin() as conn:
                duplicate = _duplicate(conn, patient_id, digest.hexdigest())
                if duplicate is not None:
                    return duplicate
                conn.execute(text("""
                    INSERT INTO submissions (job_id, patient_id, content_hash, spool_path, spool_bytes,
                        consent_scope, consent_version, consent_granted_at, requested_doc_type,
                        requested_doc_date, requested_collection_date, created_at, updated_at)
                    VALUES (:id, :patient, :hash, :path, :bytes, :scope, :version, :now, :type, :date, :collection, :now, :now)
                """), {"id": key, "patient": patient_id, "hash": digest.hexdigest(), "path": str(raw), "bytes": size,
                       "scope": consent_scope, "version": consent_version, "now": now, "type": doc_type,
                       "date": doc_date.isoformat() if doc_date else None,
                       "collection": collection_date.isoformat() if collection_date else None})
                record_progress(conn, key, "intake_accepted")
            accepted = True
        except IntegrityError:
            with engine.connect() as conn:
                duplicate = _duplicate(conn, patient_id, digest.hexdigest())
            if duplicate is None:
                raise SpoolError("intake_failed") from None
            return duplicate
        with CoordinatorLock(settings.spool_dir / "spool-admission"):
            _ready_marker(settings, key)
        return SubmissionResult(key)
    except ConnectionError:
        raise SpoolError("disconnected") from None
    except OSError:
        if accepted:
            # Acceptance is durable; stale writing reservations are reconciled during recovery.
            return SubmissionResult(key)
        raise SpoolError("disk_error") from None
    finally:
        if not accepted:
            try:
                _remove_owned(settings, key)
            except (OSError, ValueError):
                raise SpoolError("cleanup_failed") from None


def delete_spool(engine, settings, job_id) -> bool:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT spool_path, spool_cleanup_state, state, preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).first()
        if row is None:
            return False
        if row[2] not in {"promoted", "rejected", "failed", "cancelled"}:
            return False
        if row[2] != "promoted" and json.loads(row[3] or "{}").get("reserved_bytes", 0):
            return False
        conn.execute(text("UPDATE submissions SET spool_cleanup_requested_at = COALESCE(spool_cleanup_requested_at, :now) WHERE job_id = :id"), {"id": job_id, "now": _now()})
    try:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id) or row[0] != str(settings.spool_dir / f"{job_id}.raw"):
            raise SpoolError("spool_state_invalid")
        _remove_owned(settings, job_id)
    except (OSError, ValueError, SpoolError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE submissions SET spool_cleanup_state = 'failed', spool_cleanup_error_code = 'cleanup_failed' WHERE job_id = :id"), {"id": job_id})
        return False
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET spool_cleanup_state = 'deleted', spool_cleanup_error_code = NULL, spool_deleted_at = :now WHERE job_id = :id"), {"id": job_id, "now": _now()})
    return True


def _ready_marker(settings, key):
    marker = settings.spool_dir / f"{key}.reservation"
    temporary = settings.spool_dir / f"{key}.reservation.tmp"
    check_path(marker)
    check_path(temporary)
    process = psutil.Process()
    reservation = {"version": 1, "state": "ready", "bytes": settings.max_upload_bytes,
                   "owner_pid": process.pid, "owner_created_at": process.create_time()}
    temporary.unlink(missing_ok=True)
    with temporary.open("xb") as output:
        output.write(json.dumps(reservation, separators=(",", ":")).encode())
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(marker)


def recover_spool(engine, settings) -> bool:
    """Call after prior expensive-tree exit. Live writers keep their slots; unknown names stay untouched."""
    private_directory(settings.spool_dir)
    try:
        with CoordinatorLock(settings.spool_dir / "spool-admission"):
            markers = {marker["key"]: marker for marker in _markers(settings)}
            # Temporary reservation writes may be the only remaining file after an interrupted cleanup.
            with os.scandir(settings.spool_dir) as entries:
                for index, entry in enumerate(entries):
                    if index >= 128:
                        raise SpoolError("capacity_exhausted")
                    if re.fullmatch(r"[0-9a-f]{32}\.reservation\.tmp", entry.name):
                        markers.setdefault(entry.name[:32], {"state": "orphan"})
            for key, marker in markers.items():
                with engine.connect() as conn:
                    exists = conn.execute(text("SELECT 1 FROM submissions WHERE job_id = :id"), {"id": key}).first()
                if exists is None:
                    if marker["state"] == "writing":
                        try:
                            if psutil.Process(marker["owner_pid"]).create_time() == marker["owner_created_at"]:
                                continue
                        except psutil.NoSuchProcess:
                            pass
                        except psutil.Error:
                            return False  # Cannot confirm owner exit; never guess from a failed read.
                    _remove_owned(settings, key)
                elif not _recover_submission(engine, settings, key):
                    return False
            # Keyset reads also find committed rows without any remaining directory entry.
            cursor = ""
            while True:
                with engine.connect() as conn:
                    keys = conn.execute(text("""SELECT job_id FROM submissions WHERE job_id > :cursor
                        AND (state IN ('pending_intake', 'preparing') OR spool_cleanup_state IN ('pending', 'failed')
                             OR (state != 'promoted' AND COALESCE(json_extract(preparation_manifest_json, '$.reserved_bytes'), 0) > 0))
                        ORDER BY job_id LIMIT 20"""), {"cursor": cursor}).scalars().all()
                if not keys:
                    break
                for key in keys:
                    if key not in markers and not _recover_submission(engine, settings, key):
                        return False
                cursor = keys[-1]
            return True
    except (OSError, ValueError, SpoolError):
        return False


def _recover_submission(engine, settings, key):
    with engine.connect() as conn:
        row = conn.execute(text("SELECT state, spool_path, spool_bytes, preparation_manifest_json, spool_cleanup_state, consent_revoked_at FROM submissions WHERE job_id = :id"), {"id": key}).first()
    if row is None or not re.fullmatch(r"[0-9a-f]{32}", key):
        return False
    if row[0] in {"pending_intake", "preparing"}:
        raw = settings.spool_dir / f"{key}.raw"
        check_path(raw)
        if row[5] is not None or row[1] != str(raw) or not raw.is_file() or raw.stat().st_size != row[2]:
            with engine.begin() as conn:
                record_progress(conn, key, "intake_cancelled" if row[5] is not None else "intake_failed",
                                error_code="cancelled" if row[5] is not None else "source_missing")
                conn.execute(text("UPDATE submissions SET spool_cleanup_requested_at = COALESCE(spool_cleanup_requested_at, :now) WHERE job_id = :id"), {"id": key, "now": _now()})
            return False  # The coordinator must confirm expanded-output cleanup before releasing raw.
        _ready_marker(settings, key)
        return True
    if row[4] == "debug_retained":
        return True
    return delete_spool(engine, settings, key)

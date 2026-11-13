"""Job state for the authenticated patient's UI poll loop."""

from __future__ import annotations

import json
import shutil
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.errors import api_error
from smriti.auth import audit, current_patient
from smriti.job_progress import EVENTS, INTAKE_ERRORS, progress_transaction, read_progress, record_progress
from smriti.observability import safe_engine
from smriti.runtime import FAILURE_CODES
from smriti.spool import _now

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    request: Request,
    scope: Literal["all", "active", "failed", "recent"] = "active",
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=2**31 - 1),
    patient: dict = Depends(current_patient),
) -> dict:
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text("""
            WITH owned AS (
                SELECT j.id, j.state, j.document_id, j.total, d.doc_type, d.created_at,
                       j.progress_json, COALESCE(json_extract(j.progress_json, '$.stage'), j.stage) AS stage,
                       s.error_code, c.status AS cloud_state
                FROM jobs j JOIN document d ON d.id = j.document_id
                LEFT JOIN submissions s ON s.job_id = j.id
                LEFT JOIN cloud_consent c ON c.document_id = d.id
                WHERE d.patient_id = :patient_id
                  AND (:scope = 'all' OR (:scope = 'failed' AND j.state = 'failed')
                    OR (:scope = 'active' AND j.state IN ('queued', 'running'))
                    OR (:scope = 'recent' AND j.state IN ('done', 'failed')))
                UNION ALL
                SELECT s.job_id, CASE s.state WHEN 'pending_intake' THEN 'queued'
                            WHEN 'preparing' THEN 'running' ELSE 'failed' END,
                       NULL, NULL, s.requested_doc_type, s.created_at, s.progress_json, s.stage, s.error_code, NULL
                FROM submissions s WHERE s.patient_id = :patient_id AND s.state <> 'promoted'
                  AND (:scope = 'all' OR (:scope = 'failed' AND s.state IN ('rejected', 'failed', 'cancelled'))
                    OR (:scope = 'active' AND s.state IN ('pending_intake', 'preparing'))
                    OR (:scope = 'recent' AND s.state IN ('rejected', 'failed', 'cancelled')))
            )
            SELECT id, state, document_id, total, doc_type, created_at, stage, error_code, cloud_state,
                   json_extract(progress_json, '$.model') AS model,
                   json_extract(progress_json, '$.current_page') AS current_page,
                   json_extract(progress_json, '$.completed_pages') AS completed_pages,
                   json_extract(progress_json, '$.stage_total') AS stage_total,
                   json_extract(progress_json, '$.started_at') AS started_at,
                   json_extract(progress_json, '$.finished_at') AS finished_at,
                   json_extract(progress_json, '$.elapsed_seconds') AS elapsed_seconds,
                   json_extract(progress_json, '$.events[#-1].event') AS latest_event
            FROM owned
            ORDER BY CASE WHEN :scope = 'active' THEN created_at END ASC, created_at DESC, id
            LIMIT :limit OFFSET :offset
        """), {"patient_id": patient["id"], "scope": scope, "limit": limit + 1, "offset": offset}).mappings().all()
    items = []
    for row in rows[:limit]:
        item = dict(row)
        event = EVENTS.get(item.pop("latest_event"))
        item["activity"] = event[2] if event else {"queued": "Waiting for the local worker", "running": "Processing locally",
                                                 "done": "Results saved; ready to review", "failed": "Local processing failed"}[item["state"]]
        item["model"] = safe_engine(item["model"])
        if item["error_code"] not in FAILURE_CODES | INTAKE_ERRORS.keys():
            item["error_code"] = "preparation_failed" if item["state"] == "failed" and item["document_id"] is None else None
        item["total_pages"] = item["total"]
        item["status"] = "awaiting_cloud_consent" if item.pop("cloud_state") == "awaiting" and item["state"] in {"queued", "running"} else item["state"]
        items.append(item)
    return {"jobs": items, "has_more": len(rows) > limit, "offset": offset, "limit": limit}


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    if not request.app.state.service.accepting:
        api_error(503, "service_unavailable", "Local processing is paused. Try again after recovery.")
    engine = request.app.state.engine
    with progress_transaction(engine) as conn:
        # Acquire the write lock before checking ownership or coordinator membership.
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        owned = conn.execute(
            text("""SELECT j.id, j.state, d.id AS document_id, d.image_path, s.state AS submission_state,
                           s.batch_id, b.state AS batch_state, s.preparation_manifest_json,
                           s.consent_revoked_at, c.revoked_at, c.document_id AS consent_id, j.total
                    FROM jobs j JOIN document d ON d.id = j.document_id
                    LEFT JOIN submissions s ON s.job_id = j.id
                    LEFT JOIN stage_batches b ON b.id = s.batch_id
                    LEFT JOIN consent c ON c.document_id = d.id
                    WHERE j.id = :id AND d.patient_id = :patient_id
                      AND j.state IN ('failed', 'queued') AND d.status IN ('failed', 'queued')"""),
            {"id": job_id, "patient_id": patient["id"]},
        ).mappings().first()
        if owned is None:
            api_error(404, "not_found", f"No retryable job {job_id}.")
        image_path = owned.get("image_path")
        if image_path:
            root = request.app.state.settings.upload_dir.resolve()
            target = (root / image_path).resolve()
            if not target.exists() or not target.is_dir():
                api_error(409, "file_missing", "Document source files are missing on disk and cannot be retried.")
        if owned["submission_state"] != "promoted":
            api_error(409, "source_unavailable", "This upload has no prepared source for retry.")
        if owned["consent_id"] is None or owned["consent_revoked_at"] is not None or owned["revoked_at"] is not None:
            api_error(409, "consent_revoked", "Consent is required before retrying this document.")
        if owned["batch_id"] is not None and owned["batch_state"] != "done":
            api_error(409, "job_active", "This document is still owned by a processing batch. Wait for cleanup.")
        manifest = json.loads(owned["preparation_manifest_json"])
        if manifest.get("processing", {}).get("cleanup") not in (None, "confirmed"):
            api_error(409, "cleanup_failed", "Processing cleanup is unconfirmed. Local recovery is required.")
        for table, owner in (("observation", "document_id"), ("report", "document_id"),
                             ("page_text", "document_id"), ("directive", "document_id"),
                             ("medication", "source_doc_id"), ("handwriting_field", "document_id")):
            if conn.execute(text(f"SELECT 1 FROM {table} WHERE {owner} = :id LIMIT 1"), {"id": owned["document_id"]}).first():
                api_error(409, "results_exist", "This document already has saved results; retry will not replace them.")
        # Completed cleanup deleted scratch; readiness flags must not reuse those deleted artifacts.
        manifest.pop("processing", None)
        try:
            conn.execute(text("""UPDATE submissions SET error_code = NULL, batch_id = NULL, batch_position = NULL,
                                 preparation_manifest_json = :manifest WHERE job_id = :id"""),
                         {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":"))})
        except IntegrityError:
            # The batch it belongs to is still active; re-freezing is not allowed.
            api_error(409, "job_active", "This document is already being processed.")
        conn.execute(text("UPDATE jobs SET state = 'queued', page = 0, error = NULL WHERE id = :id"), {"id": job_id})
        conn.execute(text("""UPDATE document SET status = 'queued'
                              WHERE id = (SELECT document_id FROM jobs WHERE id = :id)"""), {"id": job_id})
        record_progress(conn, job_id, "retry_queued", completed=0, total=owned["total"])
        conn.execute(text("""UPDATE cloud_consent SET status = 'awaiting', extra_boxes_json = '{}', updated_at = :now
            WHERE document_id = :id AND status <> 'declined'
              AND EXISTS (SELECT 1 FROM consent WHERE document_id = :id AND scope = 'local_plus_projection')"""),
                     {"id": owned["document_id"], "now": _now()})
    return {"id": job_id, "state": "queued"}


@router.delete("/{job_id}", status_code=204)
def delete_failed_job(
    job_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> None:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    engine = request.app.state.engine
    with engine.connect() as conn:
        owned = conn.execute(
            text("""SELECT j.state, d.id AS document_id, d.image_path, d.content_hash
                    FROM jobs j JOIN document d ON d.id = j.document_id
                    WHERE j.id = :id AND d.patient_id = :patient_id"""),
            {"id": job_id, "patient_id": patient["id"]},
        ).mappings().first()
        prepared = conn.execute(
            text("SELECT 1 FROM submissions WHERE job_id = :id AND patient_id = :patient_id"),
            {"id": job_id, "patient_id": patient["id"]},
        ).first()
    if owned is None and prepared is None:
        api_error(404, "not_found", f"Unknown job {job_id}.")
    if owned is not None:
        if owned["state"] != "failed":
            api_error(409, "job_not_failed", "Only failed jobs can be deleted.")
        from smriti.processing_store import cleanup_processing
        from smriti.spool import delete_spool

        if not (cleanup_processing(engine, settings, job_id) and delete_spool(engine, settings, job_id)):
            api_error(503, "cleanup_failed", "Cleanup is unconfirmed; try again.")
        source_dir = settings.upload_dir / owned["image_path"]
        try:
            shutil.rmtree(source_dir)
        except FileNotFoundError:
            pass
        except OSError:
            api_error(503, "cleanup_failed", "Source cleanup is unconfirmed; try again.")
        try:
            source_dir.lstat()
        except FileNotFoundError:
            pass
        except OSError:
            api_error(503, "cleanup_failed", "Source cleanup is unconfirmed; try again.")
        else:
            api_error(503, "cleanup_failed", "Source cleanup is unconfirmed; try again.")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM stage_artifact WHERE content_hash = :hash"), {"hash": owned["content_hash"]})
            conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
            conn.execute(text("DELETE FROM submissions WHERE job_id = :id"), {"id": job_id})
            audit(conn, entity="document", entity_id=owned["document_id"], field="deleted", old=None, new="true", actor="owner")
            conn.execute(text("DELETE FROM document WHERE id = :id"), {"id": owned["document_id"]})
    else:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM submissions WHERE job_id = :id"), {"id": job_id})


@router.get("/{job_id}")
def get_job(
    job_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    with request.app.state.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT j.id, j.state, j.page, j.total, j.error, j.progress_json,
                       j.document_id, j.total AS total_pages, (SELECT error_code FROM submissions WHERE job_id = j.id) AS error_code,
                       NULL AS submission_stage,
                       (SELECT status FROM cloud_consent WHERE document_id = j.document_id) AS cloud_state
                FROM jobs j
                JOIN document d ON d.id = j.document_id
                WHERE j.id = :id AND d.patient_id = :patient_id
                UNION ALL
                SELECT s.job_id, CASE s.state WHEN 'pending_intake' THEN 'queued'
                           WHEN 'preparing' THEN 'running' ELSE 'failed' END,
                       0, NULL, NULL, s.progress_json, NULL, NULL, s.error_code, s.stage, NULL
                FROM submissions s
                WHERE s.job_id = :id AND s.patient_id = :patient_id AND s.state <> 'promoted'
                LIMIT 1
                """
            ),
            {"id": job_id, "patient_id": patient["id"]},
        ).first()
    if row is None:
        api_error(404, "not_found", f"Unknown job {job_id}.")
    progress = read_progress(row[5])
    error_code = row[8]
    error = row[4]
    if row[9] is not None:
        progress["stage"] = row[9]
        if row[1] == "failed":
            error_code = error_code if error_code in INTAKE_ERRORS else "preparation_failed"
            error = INTAKE_ERRORS[error_code]
        else:
            error_code = None
    elif error_code not in FAILURE_CODES | INTAKE_ERRORS.keys():
        error_code = None
    logging = request.app.state.diagnostics.health()
    return {
        "id": row[0],
        "state": row[1],
        "status": "awaiting_cloud_consent" if row[10] == "awaiting" and row[1] in {"queued", "running"} else row[1],
        "page": row[2],
        "total": row[3],
        "error": error,
        "document_id": row[6],
        "total_pages": row[7],
        "error_code": error_code,
        "support_id": row[0],
        "logging": {name: {"available": bool(logging.get(name, {}).get("available")),
                           "degraded": not logging.get(name, {}).get("available") or bool(logging.get(name, {}).get("failures"))
                               or any(logging.get(name, {}).get("dropped", {}).values())}
                    for name in ("file", "terminal")},
        **progress,
    }

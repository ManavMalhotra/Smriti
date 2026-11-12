"""Bounded operational job events. Messages are code-owned, never document content."""

from __future__ import annotations

import json
import logging
import math
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text

EVENTS = {
    "intake_accepted": ("pending_intake", "info", "Upload queued for inspection"),
    "preparing": ("preparing", "info", "Preparing source pages"),
    "prepared": ("queued", "success", "Source prepared; waiting for local processing"),
    "intake_rejected": ("failed", "error", "Upload rejected during inspection"),
    "intake_failed": ("failed", "error", "Source preparation failed"),
    "intake_cancelled": ("failed", "warning", "Source preparation cancelled"),
    "intake_cleanup_failed": ("preparing", "error", "Could not confirm source preparation shutdown"),
    "started": ("ocr_loading", "info", "Starting local processing"),
    "recovered": ("queued", "warning", "Processing was interrupted; queued to resume"),
    "recovering": (None, "warning", "Processing interrupted; validating saved progress before retry"),
    "ocr_loading": ("ocr_loading", "info", "Loading the OCR engine"),
    "ocr_reading": ("ocr", "info", "Reading page with local OCR"),
    "cache_hit": ("ocr", "info", "Reusing cached page reading"),
    "text_layer": ("ocr", "info", "Reading the PDF text layer; OCR not needed"),
    "page_read": ("ocr", "success", "Page reading complete"),
    "ocr_finished": ("ocr", "success", "All pages read; extraction still pending"),
    "classifying": ("classification", "info", "Detecting document type"),
    "classified": ("classification", "success", "Document type detected"),
    "extracting": ("extraction", "info", "Extracting fields using local rules"),
    "handwriting_filtered": ("extraction", "warning", "Handwritten numeric fields excluded"),
    "awaiting_cloud_consent": ("awaiting_cloud_consent", "warning", "Review redacted pages or keep this document offline"),
    "cloud_reading": ("extraction", "info", "Reading user-approved redacted pages with Gemini"),
    "cloud_failed": ("extraction", "warning", "Cloud extraction unavailable; local readings retained for review"),
    "qwen_loading": ("qwen_loading", "info", "Loading Qwen3-VL for the independent reading"),
    "qwen_reused": ("qwen_loading", "info", "Reusing the running local Qwen3-VL server"),
    "qwen_ready": ("qwen_loading", "success", "Qwen3-VL is ready"),
    "qwen_reading": ("qwen", "info", "Qwen3-VL is reading page independently"),
    "qwen_page": ("qwen", "success", "Qwen3-VL page reading complete"),
    "qwen_unavailable_page": ("qwen", "warning", "Independent page reading unavailable; OCR retained for review"),
    "qwen_skipped": ("qwen", "warning", "Handwritten page skipped by Qwen3-VL"),
    "qwen_disabled": ("extraction", "warning", "Qwen3-VL disabled; no independent model verification"),
    "handwritten_mode": ("extraction", "warning", "Handwritten document; model verification skipped"),
    "cross_check": ("cross_check", "info", "Comparing OCR and Qwen3-VL readings"),
    "cross_checked": ("cross_check", "success", "Readings compared; extracted fields still require review"),
    "verification_partial": ("cross_check", "warning", "Some independent readings unavailable; unmatched OCR fields require review"),
    "verification_unavailable": ("cross_check", "warning", "No independent fields confirmed; OCR-only results require review"),
    "unloading": ("cleanup", "info", "Stopping the spawned Qwen3-VL server"),
    "unloaded": ("cleanup", "success", "Spawned Qwen3-VL server stopped"),
    "cleanup_failed": ("cleanup", "error", "Could not confirm model shutdown"),
    "saving": ("saving", "info", "Saving extracted results and source links"),
    "done": ("done", "success", "Results saved; ready to review"),
    "operation_failed": (None, "error", "Model operation failed; cleaning up resources"),
    "failed": (None, "error", "Local processing failed; document remains stored"),
}

INTAKE_STATES = {
    "intake_accepted": "pending_intake", "preparing": "preparing",
    "intake_rejected": "rejected", "intake_failed": "failed", "intake_cancelled": "cancelled",
    "intake_cleanup_failed": "preparing",
}
INTAKE_ERRORS = {
    "invalid_format": "The upload could not be read. Try a readable PDF or image.",
    "password_protected": "Password-protected PDFs cannot be processed.",
    "page_limit": "The upload exceeds the allowed page count.",
    "pixel_limit": "An image exceeds the allowed pixel count.",
    "capacity_exhausted": "Processing exceeded the available storage or decoded-input capacity.",
    "memory_limit": "Processing exceeded its memory limit.",
    "rejected_quality": "The source pages did not pass the quality checks.",
    "preparation_timeout": "Source preparation exceeded its time limit.",
    "preparation_crash": "The source reader stopped unexpectedly.",
    "preparation_failed": "Source preparation failed. Try uploading again.",
    "disk_error": "The source could not be stored.",
    "consent_revoked": "Processing consent was revoked.",
    "source_missing": "The pending source is unavailable. Upload it again.",
    "prepared_artifact_invalid": "Prepared source pages are incomplete or invalid.",
    "cancelled": "Source preparation was cancelled.",
}


def read_progress(raw: str | None) -> dict:
    if raw:
        return json.loads(raw)
    return {
        "stage": None, "model": None, "current_page": None, "completed_pages": None, "stage_total": None,
        "started_at": None, "updated_at": None, "finished_at": None,
        "elapsed_seconds": None, "events": [], "events_truncated": 0,
        "verification_state": None, "failure_context": None, "latest_failure": None,
    }


@contextmanager
def progress_transaction(engine):
    """Forward only committed progress; a rolled-back save must never announce completion."""
    entries = []
    with engine.begin() as conn:
        conn.info["smriti_progress"] = entries
        try:
            yield conn
        finally:
            conn.info.pop("smriti_progress", None)
    report = engine.get_execution_options().get("progress_report")
    if report is not None:
        from smriti.observability import safe_event

        for job_id, entry in entries:
            payload = safe_event(entry["event"], job_id=job_id, stage=entry["stage"],
                                 engine=entry.get("model"), sequence=entry["sequence"], page=entry.get("page"),
                                 count=entry.get("count"), total=entry.get("total"),
                                 code=entry.get("code"), status=entry.get("status"),
                                 duration_ms=entry["duration_seconds"] * 1000 if "duration_seconds" in entry else None)
            fields = json.loads(payload)
            try:
                report("progress", progress_event=fields.pop("event"),
                       **{key: value for key, value in fields.items() if key not in {"schema_version", "timestamp", "level", "message"}})
            except Exception:
                logging.getLogger(__name__).warning("Diagnostic delivery unavailable")


def record_progress(
    conn, job_id: str, event: str, *, model: str | None = None,
    page: int | None = None, completed: int | None = None,
    duration: float | None = None, count: int | None = None,
    error_type: str | None = None, elapsed: float | None = None,
    total: int | None = None,
    error_code: str | None = None,
    http_status: int | None = None,
    failed_stage: str | None = None,
) -> bool:
    if event not in EVENTS:
        raise ValueError("Unknown processing event")
    for value in (page, completed, count, total):
        if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
            raise ValueError("Progress counts must be nonnegative integers")
    for value in (duration, elapsed):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("Progress durations must be finite and nonnegative")
    from smriti.runtime import FAILURE_CODES

    if error_code is not None and error_code not in INTAKE_ERRORS.keys() | FAILURE_CODES:
        raise ValueError("Unknown error code")
    if http_status is not None and (type(http_status) is not int or not 400 <= http_status <= 599
                                    or error_code != "qwen_http_error" or event != "operation_failed"):
        raise ValueError("Invalid model HTTP failure status")
    if failed_stage is not None and (event not in {"failed", "operation_failed"} or failed_stage not in {"inspection", "preparing", "ocr", "qwen", "extraction", "cross_check", "saving"}):
        raise ValueError("Invalid failed stage")
    row = conn.execute(text("""
        SELECT progress_json, 'job' AS storage, state FROM jobs WHERE id = :id
        UNION ALL
        SELECT progress_json, 'submission' AS storage, state FROM submissions
        WHERE job_id = :id AND state <> 'promoted'
        LIMIT 1
    """), {"id": job_id}).first()
    if row is None:
        return False
    submission = row[1] == "submission"
    if submission:
        if error_code is not None and error_code not in INTAKE_ERRORS:
            raise ValueError("Unknown intake error code")
        if event not in INTAKE_STATES or total is not None or model is not None or error_type is not None:
            raise ValueError("Unprepared submissions require intake events and unknown totals")
        if error_code is not None and event not in ("intake_rejected", "intake_failed", "intake_cancelled"):
            raise ValueError("Intake error codes require a terminal event")
        if row[2] not in ("pending_intake", "preparing"):
            return False
        if event == "intake_accepted" and row[2] != "pending_intake":
            return False
    elif event in INTAKE_STATES:
        return False
    elif error_code is not None and event not in {"operation_failed", "failed"}:
        raise ValueError("Processing error codes require a failure event")
    from smriti.observability import safe_engine

    model = safe_engine(model)
    if error_type not in {"TimeoutError", "MemoryError", "OSError", "RuntimeError"}:
        error_type = None
    progress = read_progress(row[0])
    stage, level, message = EVENTS[event]
    now = datetime.now(timezone.utc).isoformat()
    if failed_stage is not None and not progress.get("failure_context"):
        same_stage = (progress.get("stage") or "").startswith(failed_stage)
        progress["failure_context"] = {"stage": failed_stage, "model": model or (progress.get("model") if same_stage else None),
                                       "current_page": page if page is not None else progress.get("current_page") if same_stage else None}
    if failed_stage is not None:
        stage = progress["failure_context"]["stage"]
        model = progress["failure_context"]["model"]
        page = progress["failure_context"]["current_page"]
    if event in ("started", "recovered", "intake_accepted"):
        progress.update(started_at=progress.get("started_at") or now, finished_at=None, elapsed_seconds=None, verification_state=None, failure_context=None)
    if event in ("qwen_disabled", "handwritten_mode"):
        progress["verification_state"] = "skipped"
    elif event == "qwen_loading":
        progress["verification_state"] = "running"
    elif event in {"qwen_skipped", "qwen_unavailable_page", "verification_partial"}:
        progress["verification_state"] = "partial"
    elif event == "verification_unavailable":
        progress["verification_state"] = "unavailable"
    elif event == "cross_checked" and progress.get("verification_state") != "partial":
        progress["verification_state"] = "compared"
    if event in ("operation_failed", "failed", "cleanup_failed", "intake_cleanup_failed") and (not progress.get("failure_context") or event in ("cleanup_failed", "intake_cleanup_failed")):
        progress["failure_context"] = {key: progress.get(key) for key in ("stage", "model", "current_page")}
    if error_code is not None and not submission and progress.get("failure_context"):
        progress["failure_context"].setdefault("code", error_code)
        if http_status is not None:
            progress["failure_context"].setdefault("status", http_status)
    if stage is not None:
        progress.update(stage=stage, model=model, current_page=page, completed_pages=completed, stage_total=total)
    sequence = progress["events"][-1]["sequence"] + 1 if progress["events"] else 1
    entry = {"sequence": sequence, "timestamp": now, "level": level, "stage": progress["stage"], "event": event, "message": message}
    for key, value in {"model": model, "page": page, "duration_seconds": duration, "count": count, "total": total,
                       "error_type": error_type, "code": error_code, "status": http_status}.items():
        if value is not None:
            entry[key] = round(value, 3) if key == "duration_seconds" else value
    if level == "error":
        progress["latest_failure"] = dict(entry)
    progress["events"].append(entry)
    if len(progress["events"]) > 500:
        progress["events_truncated"] += len(progress["events"]) - 500
        progress["events"] = progress["events"][-500:]
    progress["updated_at"] = now
    if event in ("done", "failed", "intake_rejected", "intake_failed", "intake_cancelled"):
        if elapsed is None and progress.get("started_at"):
            elapsed = max(0, (datetime.fromisoformat(now) - datetime.fromisoformat(progress["started_at"])).total_seconds())
        progress.update(finished_at=now, elapsed_seconds=round(elapsed, 3) if elapsed is not None else None)
    if submission:
        if event in ("intake_rejected", "intake_failed", "intake_cancelled"):
            error_code = error_code or ("cancelled" if event == "intake_cancelled" else "preparation_failed")
        result = conn.execute(text("""
            UPDATE submissions SET progress_json = :progress, stage = :stage,
                state = :state, error_code = :error_code, updated_at = :now
            WHERE job_id = :id AND state = :old_state AND progress_json IS :old_progress
        """), {
            "id": job_id, "progress": json.dumps(progress), "stage": progress["stage"],
            "state": INTAKE_STATES[event], "error_code": error_code, "now": now,
            "old_state": row[2], "old_progress": row[0],
        })
        if result.rowcount == 1 and "smriti_progress" in conn.info:
            conn.info["smriti_progress"].append((job_id, entry))
        return result.rowcount == 1
    result = conn.execute(
        text("UPDATE jobs SET progress_json = :progress, stage = :stage, page = COALESCE(:ocr_page, page) WHERE id = :id AND progress_json IS :old_progress"),
        {"id": job_id, "stage": progress["stage"], "progress": json.dumps(progress), "old_progress": row[0],
         "ocr_page": completed if event in {"cache_hit", "page_read", "ocr_finished"} else None},
    )
    if result.rowcount == 1 and "smriti_progress" in conn.info:
        conn.info["smriti_progress"].append((job_id, entry))
    return result.rowcount == 1

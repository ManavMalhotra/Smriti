"""Document upload, consent, metadata, extraction, and page-image endpoints."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from fastapi import Body
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import audit, current_patient, owned_document
from smriti.clinical_summary import invalidate_patient_digest
from smriti.http_intake import receive_upload
from smriti.ingest import record_consent, redaction_preview, record_cloud_consent
from smriti.models import ConsentCreate, CloudConsentCreate, DocumentUpdate, ManualObservationCreate
from smriti.observability import safe_engine
from smriti.reports import category_for
from smriti.spool import SpoolError
from smriti.summary import build_summary

router = APIRouter(prefix="/documents", tags=["documents"])

def _decimal_string(raw: str) -> str:
    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, AttributeError):
        api_error(400, "validation_error", "Value must be a number.", field="value_num")
    if not value.is_finite():
        api_error(400, "validation_error", "Value must be finite.", field="value_num")
    if value == 0:
        return "0"
    if not -12 <= value.adjusted() <= 12 or len(value.as_tuple().digits) > 15:
        api_error(400, "validation_error", "Value is outside the range a lab result can have.", field="value_num")
    canonical = format(value.normalize(), "f")
    return "0" if canonical in ("-0", "") else canonical


@router.get("")
def list_documents(request: Request, limit: int = Query(20, ge=1, le=50),
                   offset: int = Query(0, ge=0, le=2**31 - 1),
                   filter: str = Query("All", pattern="^(All|Prescriptions|Lab reports|Scans & discharge|Needs review)$"),
                   patient: dict = Depends(current_patient)) -> dict:
    with request.app.state.engine.connect() as conn:
        rows = conn.execute(text("""
            WITH uploads AS (
                SELECT d.id, d.id AS document_id, d.display_name, d.doc_type,
                       d.verified_date, d.doc_date, d.collection_date, d.registration_date,
                       d.report_date, COALESCE(d.facility_name, d.lab_name) AS facility_name,
                       d.page_count, d.status, d.processed_at, d.created_at,
                       (SELECT COUNT(*) FROM observation o WHERE o.document_id = d.id AND o.status = 'review') +
                       (SELECT COUNT(*) FROM report r WHERE r.document_id = d.id AND r.status = 'review') AS review_count,
                       j.id AS job_id, j.state AS job_state,
                       CASE WHEN j.state = 'failed' AND d.status = 'failed' AND s.state = 'promoted'
                            AND s.consent_revoked_at IS NULL AND c.revoked_at IS NULL AND c.document_id IS NOT NULL
                            AND (s.batch_id IS NULL OR b.state = 'done')
                            AND COALESCE(json_extract(s.preparation_manifest_json, '$.processing.cleanup'), 'confirmed') = 'confirmed'
                            AND NOT EXISTS (
                                SELECT 1 FROM observation WHERE document_id = d.id UNION ALL
                                SELECT 1 FROM report WHERE document_id = d.id UNION ALL
                                SELECT 1 FROM page_text WHERE document_id = d.id UNION ALL
                                SELECT 1 FROM directive WHERE document_id = d.id UNION ALL
                                SELECT 1 FROM medication WHERE source_doc_id = d.id UNION ALL
                                SELECT 1 FROM handwriting_field WHERE document_id = d.id)
                            THEN 1 ELSE 0 END AS retryable
                FROM document d
                LEFT JOIN jobs j ON j.id = (SELECT id FROM jobs WHERE document_id = d.id ORDER BY ts DESC, id DESC LIMIT 1)
                LEFT JOIN submissions s ON s.job_id = j.id
                LEFT JOIN consent c ON c.document_id = d.id
                LEFT JOIN stage_batches b ON b.id = s.batch_id
                WHERE d.patient_id = :patient_id
                UNION ALL
                SELECT s.job_id, NULL, NULL, s.requested_doc_type, NULL,
                       s.requested_doc_date, s.requested_collection_date, NULL, NULL, NULL,
                       NULL, s.state, NULL, s.created_at, 0, s.job_id,
                       CASE s.state WHEN 'pending_intake' THEN 'queued' WHEN 'preparing' THEN 'running' ELSE 'failed' END, 0
                FROM submissions s WHERE s.patient_id = :patient_id AND s.state <> 'promoted'
            )
            SELECT * FROM uploads
            WHERE (:filter = 'All'
                OR (:filter = 'Prescriptions' AND doc_type IN ('prescription', 'pharmacy'))
                OR (:filter = 'Lab reports' AND doc_type = 'lab_report')
                OR (:filter = 'Scans & discharge' AND doc_type IN ('ct', 'mri', 'xray', 'radiology', 'pathology', 'discharge_summary'))
                OR (:filter = 'Needs review' AND (status <> 'done' OR review_count > 0)))
            ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset
        """), {"patient_id": patient["id"], "limit": limit + 1, "offset": offset, "filter": filter}).mappings().all()
    return {"documents": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit,
            "offset": offset, "limit": limit}

@router.patch("/{document_id}")
def update_document(document_id: str, payload: DocumentUpdate, request: Request,
                    patient: dict = Depends(current_patient)) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        api_error(400, "validation_error", "No document fields supplied.")
    for field in ("display_name", "facility_name"):
        if field in updates and updates[field] is not None:
            updates[field] = updates[field].strip() or None
    for field in ("display_name", "facility_name"):
        if updates.get(field) == "":
            updates[field] = None
    with request.app.state.engine.begin() as conn:
        row = owned_document(conn, document_id, patient["id"])
        old = row._mapping
        changed = [(field, old[field], value.isoformat() if hasattr(value, "isoformat") else value)
                   for field, value in updates.items()
                   if old[field] != (value.isoformat() if hasattr(value, "isoformat") else value)]
        if changed:
            params = {field: new for field, _, new in changed} | {"id": document_id}
            assignments = ", ".join(f"{field} = :{field}" for field, _, _ in changed)
            conn.execute(text(f"UPDATE document SET {assignments} WHERE id = :id"), params)
            for field, old_value, new_value in changed:
                audit(conn, entity="document", entity_id=document_id, field=field,
                      old=old_value, new=new_value, actor=patient["username"] or patient["alias"])

            # Cascade verified_date / doc_type / facility_name to linked reports
            if "verified_date" in updates:
                new_date = updates["verified_date"].isoformat() if hasattr(updates["verified_date"], "isoformat") else updates["verified_date"]
                conn.execute(text("UPDATE report SET report_date = :rep_date WHERE document_id = :id"),
                             {"rep_date": new_date, "id": document_id})
            if "doc_type" in updates and updates["doc_type"]:
                new_type = updates["doc_type"]
                new_cat = category_for(new_type)
                conn.execute(text("UPDATE report SET category = :cat, report_type = :rep_type WHERE document_id = :id"),
                             {"cat": new_cat, "rep_type": new_type, "id": document_id})
            if "facility_name" in updates and updates["facility_name"]:
                conn.execute(text("UPDATE report SET facility_name = :fac WHERE document_id = :id"),
                             {"fac": updates["facility_name"], "id": document_id})

            invalidate_patient_digest(conn, patient["id"])

        current = conn.execute(text("SELECT display_name, doc_type, doc_date, verified_date, facility_name FROM document WHERE id=:id"),
                               {"id": document_id}).mappings().one()
        return {
            "document": dict(current),
            "summary": build_summary(conn, patient["id"]),
        }


@router.delete("/{document_id}")
def delete_document(document_id: str, request: Request,
                    patient: dict = Depends(current_patient)) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    settings = request.app.state.settings
    with request.app.state.engine.begin() as conn:
        doc = owned_document(conn, document_id, patient["id"])
        image_path = doc._mapping["image_path"]

        # Cascade delete across all linked tables
        conn.execute(text("DELETE FROM submissions WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM medication WHERE source_doc_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM observation WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM directive WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM report WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM page_text WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM jobs WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM handwriting_field WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM cloud_consent WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM consent WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM egress WHERE document_id = :id"), {"id": document_id})
        conn.execute(text("DELETE FROM stage_artifact WHERE content_hash = :id OR content_hash = :image_path"),
                     {"id": document_id, "image_path": image_path})
        conn.execute(text("DELETE FROM document WHERE id = :id"), {"id": document_id})

        if image_path:
            root = settings.upload_dir.resolve()
            target = (root / image_path).resolve()
            if target != root and root in target.parents and target.is_dir():
                shutil.rmtree(target, ignore_errors=True)

        audit(conn, entity="document", entity_id=document_id, field="status",
              old="active", new="deleted", actor=patient["username"] or patient["alias"])
        invalidate_patient_digest(conn, patient["id"])
        return {
            "deleted": True,
            "document_id": document_id,
            "summary": build_summary(conn, patient["id"]),
        }


@router.post("/{document_id}/observations", status_code=201)
def create_manual_observation(
    document_id: str,
    payload: ManualObservationCreate,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    with request.app.state.engine.begin() as conn:
        doc = owned_document(conn, document_id, patient["id"])
        doc_map = doc._mapping
        if payload.page > doc_map["page_count"]:
            api_error(422, "invalid_page", "The source page is outside this document.")

        report_row = conn.execute(
            text("SELECT id FROM report WHERE document_id = :doc AND page_start <= :page AND page_end >= :page ORDER BY page_start DESC LIMIT 1"),
            {"doc": document_id, "page": payload.page},
        ).first()
        report_id = report_row[0] if report_row else None

        value_num = None
        if payload.value_num is not None:
            value_num = _decimal_string(payload.value_num)
        value_text = payload.value_text or value_num or ""
        now = datetime.now(timezone.utc).isoformat()
        obs_id = str(uuid.uuid4())
        bbox = payload.bbox or [0.0, 0.0, 1.0, 1.0]
        rule = "exact" if payload.analyte_id else "unresolved"

        conn.execute(
            text("""
                INSERT INTO observation (
                    id, document_id, report_id, analyte_id, label_raw, label_norm,
                    fact_type, value_num, value_text, unit_raw, unit_norm,
                    ref_low, ref_high, flag_printed, bbox_json, page,
                    engine, confidence, status, reason, mapping_rule, source,
                    model_version, created_at
                ) VALUES (
                    :id, :document_id, :report_id, :analyte_id, :label_raw, :label_norm,
                    'lab', :value_num, :value_text, :unit_raw, :unit_norm,
                    :ref_low, :ref_high, :flag_printed, :bbox_json, :page,
                    'human', 1.0, 'auto', 'Added manually by human.', :mapping_rule, NULL,
                    'human@1.0', :created_at
                )
            """),
            {
                "id": obs_id,
                "document_id": document_id,
                "report_id": report_id,
                "analyte_id": payload.analyte_id.strip() if payload.analyte_id else None,
                "label_raw": payload.raw_label.strip(),
                "label_norm": payload.analyte_id or payload.raw_label.strip().lower(),
                "value_num": value_num,
                "value_text": value_text,
                "unit_raw": payload.unit_norm,
                "unit_norm": payload.unit_norm.strip() if payload.unit_norm else None,
                "ref_low": payload.ref_low.strip() if payload.ref_low else None,
                "ref_high": payload.ref_high.strip() if payload.ref_high else None,
                "flag_printed": payload.flag.strip() if payload.flag else None,
                "bbox_json": json.dumps(bbox),
                "page": payload.page,
                "mapping_rule": rule,
                "created_at": now,
            },
        )
        actor = patient["username"] or patient["alias"]
        audit(conn, entity="observation", entity_id=obs_id, field="status", old=None, new="auto", actor=actor)
        if value_num:
            audit(conn, entity="observation", entity_id=obs_id, field="value_num", old=None, new=value_num, actor=actor)
        invalidate_patient_digest(conn, patient["id"])

        created = conn.execute(
            text("""
                SELECT id, document_id, report_id, analyte_id, label_raw, label_norm,
                       fact_type, evidence_quote, value_num, value_text, unit_raw,
                       unit_norm, ref_low, ref_high, flag_printed, bbox_json, page,
                       engine, confidence, status, reason, mapping_rule, source,
                       model_version, created_at
                FROM observation WHERE id = :id
            """),
            {"id": obs_id},
        ).mappings().one()

        return {
            "observation": dict(created),
            "summary": build_summary(conn, patient["id"]),
        }


@router.post("/{document_id}/quick-entry")
def save_quick_entry(document_id: str, request: Request, payload: dict = Body(...),
                     patient: dict = Depends(current_patient)) -> dict:
    """Save human-entered metadata for a page where handwriting is unsafe to infer."""
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    doc_type = payload.get("doc_type", "prescription")
    if doc_type not in {"prescription", "pharmacy", "discharge_summary", "lab_report", "other"}:
        api_error(422, "invalid_doc_type", "Choose a supported document type.")
    raw_date = payload.get("doc_date")
    try:
        doc_date = date.fromisoformat(raw_date).isoformat() if raw_date else None
    except (TypeError, ValueError):
        api_error(422, "invalid_date", "Enter a valid document date.")
    facility = str(payload.get("facility_name") or "").strip()[:160] or None
    entries = payload.get("medications", [])
    if not isinstance(entries, list) or len(entries) > 30:
        api_error(422, "invalid_medications", "Add no more than 30 medications.")
    with request.app.state.engine.begin() as conn:
        document = owned_document(conn, document_id, patient["id"])
        conn.execute(text("UPDATE document SET doc_type=:type, doc_date=COALESCE(:date, doc_date), facility_name=COALESCE(:facility, facility_name) WHERE id=:id"),
                     {"type": doc_type, "date": doc_date, "facility": facility, "id": document_id})
        saved = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()[:160]
            if not name:
                continue
            dose = str(entry.get("dose") or "").strip()[:100] or None
            freq = str(entry.get("frequency") or "").strip()[:100] or None
            try:
                page = int(entry.get("page", 1))
            except (TypeError, ValueError):
                api_error(422, "invalid_page", "Enter a valid source page.")
            if not 1 <= page <= document._mapping["page_count"]:
                api_error(422, "invalid_page", "The source page is outside this document.")
            conn.execute(text("""INSERT INTO medication (id, patient_id, brand_raw, dose, freq, start_date, status, source_doc_id, clinical_json, page, engine)
                VALUES (:id, :patient, :name, :dose, :freq, :date, 'prescribed', :doc, :clinical, :page, 'human_entry')"""),
                {"id": str(uuid.uuid4()), "patient": patient["id"], "name": name, "dose": dose, "freq": freq,
                 "date": doc_date, "doc": document_id, "page": page,
                 "clinical": json.dumps({"category": "medication", "event_date": doc_date})})
            saved += 1
    return {"document_id": document_id, "doc_type": doc_type, "doc_date": doc_date, "facility_name": facility, "medications_saved": saved}

@router.post("", status_code=202)
async def upload_document(
    request: Request,
    patient: dict = Depends(current_patient),
):
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    if not request.app.state.service.accepting:
        api_error(503, "service_unavailable", "Local processing is paused. Try again after recovery.")
    try:
        result = await receive_upload(request.app.state.engine, settings, request, patient["id"])
    except SpoolError as exc:
        errors = {
            "forbidden": (403, "Uploads must belong to the signed-in account."),
            "not_found": (404, "The upload owner is unavailable."),
            "unsupported_type": (415, "Upload a JPEG, PNG, or PDF."),
            "too_large": (413, "The upload exceeds the byte limit."),
            "invalid_file": (422, "The uploaded file is empty."),
            "invalid_metadata": (400, "Check the upload metadata and consent."),
            "invalid_multipart": (400, "Send one file with valid upload fields."),
            "capacity_exhausted": (503, "Local upload capacity is unavailable. Try again later."),
            "spool_busy_or_disk_error": (503, "Local upload storage is busy or unavailable. Try again."),
            "cleanup_failed": (503, "Upload cleanup is unconfirmed. Local recovery is required."),
            "disk_error": (503, "The upload could not be stored. Try again."),
            "disconnected": (400, "The upload was interrupted."),
        }
        status, message = errors.get(exc.code, (500, "The upload failed. Try again."))
        api_error(status, exc.code if exc.code in errors else "intake_failed", message)
    if result.duplicate:
        with request.app.state.engine.connect() as conn:
            duplicate = conn.execute(
                text(
                    "SELECT doc_type, page_count FROM document WHERE id = :id"
                ),
                {"id": result.document_id},
            ).first()
        return JSONResponse(
            status_code=409,
            content={
                "document_id": result.document_id,
                "job_id": result.job_id,
                "status": result.status,
                "duplicate": True,
                "doc_type": duplicate[0] if duplicate else "other",
                "page_count": duplicate[1] if duplicate else None,
            },
        )

    request.app.state.diagnostics.emit("intake_accepted", component="http", job_id=result.job_id)
    return {
        "document_id": result.document_id,
        "job_id": result.job_id,
        "pages": None,
        "status": result.status,
    }


@router.post("/{document_id}/consent", status_code=201)
def set_consent(
    document_id: str,
    payload: ConsentCreate | CloudConsentCreate,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    with request.app.state.engine.connect() as conn:
        owned_document(conn, document_id, patient["id"])

    if isinstance(payload, CloudConsentCreate):
        try:
            return record_cloud_consent(request.app.state.engine, settings, document_id, payload,
                                        patient["username"] or patient["alias"])
        except SpoolError as exc:
            api_error(409, exc.code, "Redaction consent is unavailable or the source pages changed. Refresh the queue.")

    consent = record_consent(
        request.app.state.engine,
        document_id,
        payload.scope,
        payload.version,
        actor=patient["username"] or patient["alias"],
    )
    if consent is None:
        api_error(404, "not_found", f"Unknown document {document_id}.")
    return consent


@router.get("/{document_id}/redaction-preview")
def get_redaction_preview(document_id: str, request: Request, offset: int = Query(0, ge=0, le=2**31 - 1),
                          patient: dict = Depends(current_patient)):
    with request.app.state.engine.connect() as conn:
        owned_document(conn, document_id, patient["id"])
    try:
        return JSONResponse(redaction_preview(request.app.state.engine, request.app.state.settings, document_id, offset),
                            headers={"Cache-Control": "no-store"})
    except SpoolError as exc:
        api_error(409, exc.code, "No cloud redaction preview is awaiting consent.")


@router.get("/{document_id}")
def get_document(
    document_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
    page: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0, le=2**63 - 1024),
) -> dict:
    with request.app.state.engine.connect() as conn:
        document = owned_document(conn, document_id, patient["id"])
        document_map = document._mapping
        selected_page = page if page is not None else 1 if document_map["page_count"] > 20 else None
        if selected_page is not None and selected_page > document_map["page_count"]:
            api_error(404, "not_found", "Unknown source page.")
        params = {"id": document_id, "page": selected_page, "offset": offset}
        consent = conn.execute(
            text(
                """
                SELECT scope, granted_at, revoked_at
                FROM consent WHERE document_id = :id
                """
            ),
            {"id": document_id},
        ).first()
        egress_rows = _bounded_rows(conn,
            text(
                """
                SELECT id, payload_sha256, model_id, prompt_version,
                       schema_version, outcome, reason, ts
                FROM egress WHERE document_id = :id ORDER BY ts, id LIMIT 101 OFFSET :offset
                """
            ),
            params, ("model_id", "prompt_version", "schema_version", "outcome", "reason"),
        )
        job_rows = conn.execute(text("SELECT state, ts, progress_json FROM jobs WHERE document_id=:id ORDER BY ts, id"),
                                {"id": document_id}).mappings().all()
        page_rows = _bounded_rows(conn,
            text(
                """
                SELECT page, text, engine, source, model_version FROM page_text
                WHERE document_id = :id AND (:page IS NULL OR page = :page) ORDER BY page LIMIT 20
                """
            ),
            params, ("text", "engine", "source", "model_version"),
        )
        report_rows = _bounded_rows(conn,
            text(
                """
                SELECT r.id, r.category, r.report_type, r.report_date,
                       r.facility_name, r.title, r.summary, r.page_start, r.page_end,
                       r.status, r.reason, r.model_version, r.created_at,
                       (SELECT COUNT(*) FROM observation o
                        WHERE o.report_id = r.id) AS fact_count,
                       (SELECT COUNT(*) FROM observation o
                        WHERE o.report_id = r.id AND o.status = 'review') AS review_count
                FROM report r
                WHERE r.document_id = :id
                  AND (:page IS NULL OR (r.page_start <= :page AND r.page_end >= :page))
                ORDER BY r.page_start, r.id LIMIT 101 OFFSET :offset
                """
            ),
            params, ("facility_name", "title", "summary", "reason", "model_version"),
        )
        observation_rows = _bounded_rows(conn,
            text(
                """
                SELECT id, document_id, report_id, analyte_id, label_raw, label_norm,
                       fact_type, evidence_quote, value_num, value_text, unit_raw,
                       unit_norm, ref_low, ref_high, flag_printed, bbox_json, page,
                       engine, confidence, status, reason, mapping_rule, source,
                       model_version, created_at
                FROM observation
                WHERE document_id = :id
                  AND (:page IS NULL OR page = :page)
                ORDER BY page, created_at, id LIMIT 101 OFFSET :offset
                """
            ),
            params, ("id", "document_id", "report_id", "analyte_id", "label_raw", "label_norm", "value_num", "value_text", "unit_raw", "unit_norm", "ref_low", "ref_high", "flag_printed", "evidence_quote", "bbox_json", "reason", "engine", "model_version", "mapping_rule", "source", "created_at"),
        )
        medication_rows = _bounded_rows(conn,
            text(
                """
                SELECT id, brand_raw, salt, dose, freq, start_date, status,
                       reported_at, source_doc_id
                FROM medication
                WHERE source_doc_id = :id
                ORDER BY brand_raw, id LIMIT 101 OFFSET :offset
                """
            ),
            params, ("brand_raw", "salt", "dose", "freq"),
        )

    has_more = any(len(rows) > 100 for rows in (egress_rows, report_rows, observation_rows, medication_rows))
    egress_rows, report_rows, observation_rows, medication_rows = (
        rows[:100] for rows in (egress_rows, report_rows, observation_rows, medication_rows))

    status = document_map["status"]
    page_count = document_map["page_count"]
    pages = (
        [
            {"page": page, "url": f"/api/documents/{document_id}/page/{page}"}
            for page in ([selected_page] if selected_page is not None else range(1, page_count + 1))
        ]
        if status != "rejected_quality"
        else []
    )
    processing_runs = []
    for job in job_rows:
        try:
            progress = json.loads(job["progress_json"] or "{}")
        except (TypeError, ValueError):
            progress = {}
        if not isinstance(progress, dict):
            progress = {}
        events = progress.get("events", [])
        events = [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []
        attempts = []
        for event in events:
            if event.get("event") == "started":
                attempts.append({"started_at": event.get("timestamp") or progress.get("started_at") or job["ts"],
                                 "finished_at": None, "model": safe_engine(event.get("model") or progress.get("model")),
                                 "events": []})
            if not attempts:
                continue
            attempt = attempts[-1]
            if event.get("model"):
                attempt["model"] = safe_engine(event["model"])
            if event.get("event") in {"started", "ocr_loading", "page_read", "text_layer", "classified", "qwen_ready", "done", "failed"}:
                attempt["events"].append({"timestamp": event.get("timestamp"), "stage": event.get("stage"),
                                          "message": event.get("message"), "page": event.get("page")})
            if event.get("event") in {"done", "failed"}:
                attempt["finished_at"] = event.get("timestamp")
        if not attempts:
            attempts.append({"started_at": progress.get("started_at") or job["ts"],
                             "finished_at": progress.get("finished_at"),
                             "model": safe_engine(progress.get("model")), "events": []})
        for number, attempt in enumerate(attempts, start=1):
            attempt["number"] = number
            attempt["elapsed_seconds"] = progress.get("elapsed_seconds") if number == len(attempts) else None
            processing_runs.append(attempt)

    observations = []
    for row in observation_rows:
        mapping = row._mapping
        try:
            bbox = json.loads(mapping["bbox_json"])
        except (TypeError, ValueError, json.JSONDecodeError):
            bbox = [0.0, 0.0, 1.0, 1.0]
        observations.append(
            {
                "id": mapping["id"],
                "document_id": mapping["document_id"],
                "report_id": mapping["report_id"],
                "analyte_id": mapping["analyte_id"],
                "label_raw": mapping["label_raw"],
                "label_norm": mapping["label_norm"],
                "fact_type": mapping["fact_type"],
                "evidence_quote": mapping["evidence_quote"],
                "value_num": mapping["value_num"],
                "value_text": mapping["value_text"],
                "unit_raw": mapping["unit_raw"],
                "unit_norm": mapping["unit_norm"],
                "ref_low": mapping["ref_low"],
                "ref_high": mapping["ref_high"],
                "flag_printed": mapping["flag_printed"],
                "bbox": bbox,
                "page": mapping["page"],
                "engine": mapping["engine"],
                "confidence": mapping["confidence"],
                "status": mapping["status"],
                "reason": mapping["reason"],
                "mapping_rule": mapping["mapping_rule"],
                "source": mapping["source"],
                "model_version": mapping["model_version"],
                "created_at": mapping["created_at"],
            }
        )

    return {
        "id": document_map["id"],
        "patient_id": document_map["patient_id"],
        "doc_type": document_map["doc_type"],
        "display_name": document_map["display_name"],
        "verified_date": document_map["verified_date"],
        "doc_type_confidence": document_map["doc_type_confidence"],
        "capture_type": document_map["capture_type"],
        "doc_date": document_map["doc_date"],
        "collection_date": document_map["collection_date"],
        "registration_date": document_map.get("registration_date"),
        "report_date": document_map.get("report_date"),
        "patient_uhid": document_map.get("patient_uhid"),
        "doctor_reg_no": document_map.get("doctor_reg_no"),
        "facility_name": document_map.get("facility_name"),
        "lab_name": document_map["lab_name"],
        "page_count": page_count,
        "quality_score": document_map["quality_score"],
        "status": status,
        "processed_at": document_map["processed_at"],
        "created_at": document_map["created_at"],
        "consent": (
            {
                "scope": consent[0],
                "granted_at": consent[1],
                "revoked_at": consent[2],
            }
            if consent is not None
            else None
        ),
        "egress": [
            {
                "id": row[0],
                "payload_sha256": row[1],
                "model_id": row[2],
                "prompt_version": row[3],
                "schema_version": row[4],
                "outcome": row[5],
                "reason": row[6],
                "ts": row[7],
            }
            for row in egress_rows
        ],
        "processing_runs": processing_runs,
        "page_text": [
            {
                "page": row[0],
                "text": row[1],
                "engine": row[2],
                "source": row[3],
                "model_version": row[4],
            }
            for row in page_rows
        ],
        "reports": [
            {
                "id": row._mapping["id"],
                "category": row._mapping["category"],
                "report_type": row._mapping["report_type"],
                "report_date": row._mapping["report_date"],
                "facility_name": row._mapping["facility_name"],
                "title": row._mapping["title"],
                "summary": row._mapping["summary"],
                "page_start": row._mapping["page_start"],
                "page_end": row._mapping["page_end"],
                "status": row._mapping["status"],
                "reason": row._mapping["reason"],
                "model_version": row._mapping["model_version"],
                "created_at": row._mapping["created_at"],
                "fact_count": row._mapping["fact_count"],
                "review_count": row._mapping["review_count"],
            }
            for row in report_rows
        ],
        "observations": observations,
        "medications": [
            {
                "id": row._mapping["id"],
                "brand_raw": row._mapping["brand_raw"],
                "salt": row._mapping["salt"],
                "dose": row._mapping["dose"],
                "freq": row._mapping["freq"],
                "start_date": row._mapping["start_date"],
                "status": row._mapping["status"],
                "reported_at": row._mapping["reported_at"],
                "source_doc_id": row._mapping["source_doc_id"],
            }
            for row in medication_rows
        ],
        "pages": pages,
        "detail_page": selected_page,
        "offset": offset,
        "has_more": has_more,
    }


def _bounded_rows(conn, statement, params, text_columns):
    # Size in SQLite before decoding rows; never truncate clinical content to fit a response.
    lengths = " + ".join(f"COALESCE(length(CAST({name} AS BLOB)), 0)" for name in text_columns)
    size = conn.execute(text(f"SELECT COALESCE(SUM({lengths}), 0) FROM ({statement.text})"), params).scalar_one()
    if size > 2 * 1024**2:
        api_error(413, "detail_capacity", "This result range is too large to display. Choose a single source page or a later result range.")
    return conn.execute(statement, params).all()


@router.get("/{document_id}/page/{page_number}")
def get_page(
    document_id: str,
    page_number: int,
    request: Request,
    patient: dict = Depends(current_patient),
) -> FileResponse:
    settings = request.app.state.settings
    with request.app.state.engine.connect() as conn:
        document = conn.execute(
            text(
                """
                SELECT image_path, page_count, status
                FROM document WHERE id = :id AND patient_id = :patient_id
                """
            ),
            {"id": document_id, "patient_id": patient["id"]},
        ).first()

    if document is None:
        api_error(404, "not_found", f"Unknown document {document_id}.")
    image_path, page_count, status = document
    if status == "rejected_quality" or not 1 <= page_number <= page_count:
        api_error(404, "not_found", f"Unknown page {page_number}.")

    root = settings.upload_dir.resolve()
    target = (root / image_path / f"page_{page_number}.webp").resolve()
    try:
        target.relative_to(root)
    except ValueError:
        api_error(404, "not_found", "Page image is unavailable.")
    if not target.is_file():
        api_error(404, "not_found", "Page image is unavailable.")

    return FileResponse(
        target,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=3600"},
    )

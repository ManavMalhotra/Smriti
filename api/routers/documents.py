"""Document upload, consent, metadata, extraction, and page-image endpoints."""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import current_patient, owned_document, require_same_patient
from smriti.ingest import IngestError, ingest_upload, record_consent
from smriti.models import ConsentCreate, DocType

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

_ERROR_STATUS = {
    "not_found": 404,
    "unsupported_type": 415,
    "too_large": 413,
    "quality_rejected": 422,
    "too_many_pages": 422,
    "invalid_file": 422,
    "page_too_large": 422,
    "ingest_failed": 500,
}


def _ingest_error(exc: IngestError) -> None:
    api_error(
        _ERROR_STATUS.get(exc.code, 422),
        exc.code,
        exc.message,
        field="patient_id" if exc.code == "not_found" else "file",
    )


@router.post("", status_code=202)
def upload_document(
    request: Request,
    patient_id: str = Form(...),
    file: UploadFile = File(...),
    doc_type: DocType | None = Form(None),
    consent_scope: Literal["local", "local_plus_projection"] = Form(...),
    doc_date: date | None = Form(None),
    collection_date: date | None = Form(None),
    patient: dict = Depends(current_patient),
):
    settings = request.app.state.settings
    require_same_patient(patient_id, patient)
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        api_error(
            413,
            "too_large",
            f"File exceeds the {settings.max_upload_bytes} byte limit.",
            field="file",
        )

    try:
        result = ingest_upload(
            request.app.state.engine,
            settings,
            patient_id=patient_id,
            data=data,
            doc_type=doc_type or "other",
            consent_scope=consent_scope,
            doc_date=doc_date,
            collection_date=collection_date,
            actor=patient["username"] or patient["alias"],
        )
    except IngestError as exc:
        _ingest_error(exc)

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
                "status": result.status,
                "duplicate": True,
                "doc_type": duplicate[0] if duplicate else "other",
                "page_count": duplicate[1] if duplicate else 0,
            },
        )

    logger.info(
        "Upload accepted for patient %s: document %s (%d pages, job %s)",
        patient_id,
        result.document_id,
        result.pages,
        result.job_id,
    )
    return {
        "document_id": result.document_id,
        "job_id": result.job_id,
        "pages": result.pages,
        "status": result.status,
    }


@router.post("/{document_id}/consent", status_code=201)
def set_consent(
    document_id: str,
    payload: ConsentCreate,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    with request.app.state.engine.connect() as conn:
        owned_document(conn, document_id, patient["id"])

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


@router.get("/{document_id}")
def get_document(
    document_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    with request.app.state.engine.connect() as conn:
        document = owned_document(conn, document_id, patient["id"])
        document_map = document._mapping
        consent = conn.execute(
            text(
                """
                SELECT scope, granted_at, revoked_at
                FROM consent WHERE document_id = :id
                """
            ),
            {"id": document_id},
        ).first()
        egress_rows = conn.execute(
            text(
                """
                SELECT id, payload_sha256, model_id, prompt_version,
                       schema_version, outcome, reason, ts
                FROM egress WHERE document_id = :id ORDER BY ts
                """
            ),
            {"id": document_id},
        ).all()
        page_rows = conn.execute(
            text(
                """
                SELECT page, text, engine FROM page_text
                WHERE document_id = :id ORDER BY page
                """
            ),
            {"id": document_id},
        ).all()
        observation_rows = conn.execute(
            text(
                """
                SELECT id, analyte_id, label_raw, value_num, value_text, unit_raw,
                       unit_norm, ref_low, ref_high, flag_printed, bbox_json, page,
                       engine, confidence, status, reason, mapping_rule, created_at
                FROM observation
                WHERE document_id = :id
                ORDER BY page, created_at
                """
            ),
            {"id": document_id},
        ).all()
        medication_rows = conn.execute(
            text(
                """
                SELECT id, brand_raw, salt, dose, freq, start_date, status,
                       reported_at, source_doc_id
                FROM medication
                WHERE source_doc_id = :id
                ORDER BY brand_raw
                """
            ),
            {"id": document_id},
        ).all()

    status = document_map["status"]
    page_count = document_map["page_count"]
    pages = (
        [
            {"page": page, "url": f"/api/documents/{document_id}/page/{page}"}
            for page in range(1, page_count + 1)
        ]
        if status not in ("rejected_quality", "failed")
        else []
    )

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
                "analyte_id": mapping["analyte_id"],
                "label_raw": mapping["label_raw"],
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
                "created_at": mapping["created_at"],
            }
        )

    return {
        "id": document_map["id"],
        "patient_id": document_map["patient_id"],
        "doc_type": document_map["doc_type"],
        "doc_type_confidence": document_map["doc_type_confidence"],
        "capture_type": document_map["capture_type"],
        "doc_date": document_map["doc_date"],
        "collection_date": document_map["collection_date"],
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
        "page_text": [
            {"page": row[0], "text": row[1], "engine": row[2]} for row in page_rows
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
    }


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
    if status in ("rejected_quality", "failed") or not 1 <= page_number <= page_count:
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

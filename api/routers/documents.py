"""Document upload, consent, metadata, and page-image endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from api.errors import api_error
from smriti.ingest import IngestError, ingest_upload, record_consent
from smriti.models import ConsentCreate, DocType

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
    doc_type: DocType = Form(...),
    consent_scope: Literal["local", "local_plus_projection"] = Form(...),
    doc_date: date | None = Form(None),
    collection_date: date | None = Form(None),
):
    settings = request.app.state.settings
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
            doc_type=doc_type,
            consent_scope=consent_scope,
            doc_date=doc_date,
            collection_date=collection_date,
        )
    except IngestError as exc:
        _ingest_error(exc)

    if result.duplicate:
        return JSONResponse(
            status_code=409,
            content={
                "document_id": result.document_id,
                "status": result.status,
                "duplicate": True,
            },
        )

    return {
        "document_id": result.document_id,
        "job_id": result.job_id,
        "pages": result.pages,
        "status": result.status,
    }


@router.post("/{document_id}/consent", status_code=201)
def set_consent(document_id: str, payload: ConsentCreate, request: Request) -> dict:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    consent = record_consent(
        request.app.state.engine,
        document_id,
        payload.scope,
        payload.version,
    )
    if consent is None:
        api_error(404, "not_found", f"Unknown document {document_id}.")
    return consent


@router.get("/{document_id}")
def get_document(document_id: str, request: Request) -> dict:
    with request.app.state.engine.connect() as conn:
        document = conn.execute(
            text(
                """
                SELECT id, doc_type, capture_type, doc_date, collection_date,
                       page_count, quality_score, status
                FROM document WHERE id = :id
                """
            ),
            {"id": document_id},
        ).first()
        if document is None:
            api_error(404, "not_found", f"Unknown document {document_id}.")

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

    status = document[7]
    page_count = document[5]
    pages = (
        [
            {"page": page, "url": f"/api/documents/{document_id}/page/{page}"}
            for page in range(1, page_count + 1)
        ]
        if status not in ("rejected_quality", "failed")
        else []
    )

    return {
        "id": document[0],
        "doc_type": document[1],
        "capture_type": document[2],
        "doc_date": document[3],
        "collection_date": document[4],
        "page_count": page_count,
        "quality_score": document[6],
        "status": status,
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
        "pages": pages,
    }


@router.get("/{document_id}/page/{page_number}")
def get_page(document_id: str, page_number: int, request: Request) -> FileResponse:
    settings = request.app.state.settings
    with request.app.state.engine.connect() as conn:
        document = conn.execute(
            text(
                """
                SELECT image_path, page_count, status
                FROM document WHERE id = :id
                """
            ),
            {"id": document_id},
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

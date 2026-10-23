"""Job state for the authenticated patient's UI poll loop."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import current_patient

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
                SELECT j.id, j.state, j.page, j.total, j.error
                FROM jobs j
                JOIN document d ON d.id = j.document_id
                WHERE j.id = :id AND d.patient_id = :patient_id
                """
            ),
            {"id": job_id, "patient_id": patient["id"]},
        ).first()
    if row is None:
        api_error(404, "not_found", f"Unknown job {job_id}.")
    return {
        "id": row[0],
        "state": row[1],
        "page": row[2],
        "total": row[3],
        "error": row[4],
    }

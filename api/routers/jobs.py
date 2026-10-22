"""Job state for the UI poll loop."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

from api.errors import api_error

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    with request.app.state.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, state, page, total, error
                FROM jobs WHERE id = :id
                """
            ),
            {"id": job_id},
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

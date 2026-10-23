"""Patient summary and erase-all. A patient can only access their own record."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import SESSION_COOKIE, audit, current_patient, require_same_patient
from smriti.models import Summary
from smriti.summary import build_summary

router = APIRouter(prefix="/patients", tags=["patients"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/{patient_id}/summary", response_model=Summary)
def get_summary(
    patient_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> Summary:
    require_same_patient(patient_id, patient)
    with request.app.state.engine.connect() as conn:
        return build_summary(conn, patient_id)


@router.delete("/{patient_id}", status_code=204)
def delete_patient(
    patient_id: str,
    request: Request,
    response: Response,
    patient: dict = Depends(current_patient),
) -> None:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    require_same_patient(patient_id, patient)

    engine = request.app.state.engine
    with engine.begin() as conn:
        image_paths = [
            row[0]
            for row in conn.execute(
                text("SELECT image_path FROM document WHERE patient_id = :id"),
                {"id": patient_id},
            )
        ]
        conn.execute(text("DELETE FROM patient WHERE id = :id"), {"id": patient_id})
        audit(
            conn,
            entity="patient",
            entity_id=patient_id,
            field="deleted",
            old=None,
            new="true",
            actor=patient["username"] or patient["alias"],
        )

    # shortcut: files are removed after the DB commit; a crash between the two leaves
    # orphan files. Upgrade to a trash-then-purge deletion job when deletion is audited.
    root = settings.upload_dir.resolve()
    for relative in image_paths:
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    response.delete_cookie(SESSION_COOKIE, path="/")

"""Patient creation and erase-all. Deletion is irreversible by design."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.models import PatientCreate, PatientOut

router = APIRouter(prefix="/patients", tags=["patients"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("", status_code=201, response_model=PatientOut)
def create_patient(payload: PatientCreate, request: Request) -> PatientOut:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    patient_id = str(uuid.uuid4())
    created_at = _now()
    with request.app.state.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO patient (id, alias, dob, sex, created_at)
                VALUES (:id, :alias, :dob, :sex, :created_at)
                """
            ),
            {
                "id": patient_id,
                "alias": payload.alias,
                "dob": payload.dob.isoformat() if payload.dob else None,
                "sex": payload.sex,
                "created_at": created_at,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES (:id, 'patient', :entity_id, 'created', NULL, :new, 'operator', :ts)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "entity_id": patient_id,
                "new": payload.alias,
                "ts": created_at,
            },
        )

    return PatientOut(
        id=patient_id,
        alias=payload.alias,
        sex=payload.sex,
        dob=payload.dob,
        created_at=created_at,
    )


@router.delete("/{patient_id}", status_code=204)
def delete_patient(patient_id: str, request: Request) -> None:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    engine = request.app.state.engine
    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT id FROM patient WHERE id = :id"), {"id": patient_id}
        ).first()
        if exists is None:
            api_error(404, "not_found", f"Unknown patient {patient_id}.")

        image_paths = [
            row[0]
            for row in conn.execute(
                text("SELECT image_path FROM document WHERE patient_id = :id"),
                {"id": patient_id},
            )
        ]
        conn.execute(text("DELETE FROM patient WHERE id = :id"), {"id": patient_id})
        conn.execute(
            text(
                """
                INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES (:id, 'patient', :entity_id, 'deleted', NULL, 'true', 'operator', :ts)
                """
            ),
            {"id": str(uuid.uuid4()), "entity_id": patient_id, "ts": _now()},
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

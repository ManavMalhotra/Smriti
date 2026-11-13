"""Medication review, edit, and deletion endpoints."""

from __future__ import annotations

import json
from datetime import date
from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import audit, current_patient
from smriti.clinical_summary import invalidate_patient_digest
from smriti.models import MedicationUpdate
from smriti.summary import build_summary

router = APIRouter(prefix="/medications", tags=["medications"])


@router.patch("/{medication_id}")
def update_medication(
    medication_id: str,
    payload: MedicationUpdate,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        api_error(400, "validation_error", "No medication fields supplied.")

    with request.app.state.engine.begin() as conn:
        row = conn.execute(
            text("""
                SELECT id, patient_id, brand_raw, salt, dose, freq, start_date,
                       status, reported_at, source_doc_id
                FROM medication
                WHERE id = :id AND patient_id = :patient_id
            """),
            {"id": medication_id, "patient_id": patient["id"]},
        ).first()
        if row is None:
            api_error(404, "not_found", f"Unknown medication {medication_id}.")

        old = row._mapping
        changed = []
        for field, value in updates.items():
            formatted = value.isoformat() if hasattr(value, "isoformat") else value
            if old.get(field) != formatted:
                changed.append((field, old.get(field), formatted))

        if changed:
            params = {field: new for field, _, new in changed} | {"id": medication_id}
            assignments = ", ".join(f"{field} = :{field}" for field, _, _ in changed)
            conn.execute(text(f"UPDATE medication SET {assignments} WHERE id = :id"), params)
            actor = patient["username"] or patient["alias"]
            for field, old_value, new_value in changed:
                audit(conn, entity="medication", entity_id=medication_id, field=field,
                      old=old_value, new=new_value, actor=actor)

        invalidate_patient_digest(conn, patient["id"])

        updated = conn.execute(
            text("""
                SELECT id, brand_raw, salt, dose, freq, start_date, status,
                       reported_at, source_doc_id
                FROM medication WHERE id = :id
            """),
            {"id": medication_id},
        ).mappings().one()

        return {
            "medication": dict(updated),
            "summary": build_summary(conn, patient["id"]),
        }


@router.delete("/{medication_id}")
def delete_medication(
    medication_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    with request.app.state.engine.begin() as conn:
        row = conn.execute(
            text("SELECT id, brand_raw FROM medication WHERE id = :id AND patient_id = :patient_id"),
            {"id": medication_id, "patient_id": patient["id"]},
        ).first()
        if row is None:
            api_error(404, "not_found", f"Unknown medication {medication_id}.")

        conn.execute(text("DELETE FROM medication WHERE id = :id"), {"id": medication_id})
        actor = patient["username"] or patient["alias"]
        audit(conn, entity="medication", entity_id=medication_id, field="status",
              old=row._mapping["brand_raw"], new="deleted", actor=actor)

        invalidate_patient_digest(conn, patient["id"])
        return {
            "deleted": True,
            "medication_id": medication_id,
            "summary": build_summary(conn, patient["id"]),
        }

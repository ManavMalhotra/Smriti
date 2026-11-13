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


@router.post("")
def create_medication(
    payload: dict,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    if request.app.state.settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    brand_raw = str(payload.get("brand_raw") or payload.get("name") or "").strip()
    if not brand_raw:
        api_error(422, "validation_error", "Medicine name is required.", field="brand_raw")

    dose = str(payload.get("dose") or "").strip() or None
    freq = str(payload.get("freq") or payload.get("frequency") or "").strip() or None
    salt = str(payload.get("salt") or "").strip() or None
    source_doc_id = payload.get("source_doc_id") or None
    status = payload.get("status") or "prescribed"
    start_date = payload.get("start_date") or None
    duration = payload.get("duration") or None
    prescribed_by = payload.get("prescribed_by") or None

    clinical = {
        "category": "medication",
        "duration": duration,
        "prescribed_by": prescribed_by,
        "event_date": start_date,
    }

    import uuid
    med_id = str(uuid.uuid4())
    with request.app.state.engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO medication (id, patient_id, brand_raw, salt, dose, freq,
                                        start_date, status, source_doc_id, clinical_json, engine)
                VALUES (:id, :patient_id, :brand_raw, :salt, :dose, :freq,
                        :start_date, :status, :source_doc_id, :clinical_json, 'human_entry')
            """),
            {
                "id": med_id,
                "patient_id": patient["id"],
                "brand_raw": brand_raw,
                "salt": salt,
                "dose": dose,
                "freq": freq,
                "start_date": start_date,
                "status": status,
                "source_doc_id": source_doc_id,
                "clinical_json": json.dumps(clinical),
            },
        )
        actor = patient["username"] or patient["alias"]
        audit(conn, entity="medication", entity_id=med_id, field="status",
              old=None, new="created", actor=actor)
        invalidate_patient_digest(conn, patient["id"])

        created = conn.execute(
            text("SELECT id, brand_raw, salt, dose, freq, start_date, status, source_doc_id, clinical_json FROM medication WHERE id = :id"),
            {"id": med_id},
        ).mappings().one()

        return {
            "medication": dict(created),
            "summary": build_summary(conn, patient["id"]),
        }

"""Review extracted observations. Only the owning patient can accept or reject."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import audit, current_patient
from smriti.models import ObservationReview
from smriti.summary import build_summary

router = APIRouter(prefix="/observations", tags=["review"])


def _decimal_string(raw: str) -> str:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError):
        api_error(400, "validation_error", "Value must be a number.", field="value_num")
    if not value.is_finite():
        api_error(400, "validation_error", "Value must be finite.", field="value_num")
    if value == 0:
        return "0"
    canonical = format(value.normalize(), "f")
    return "0" if canonical in ("-0", "") else canonical


def _bbox(raw: str | None) -> list[float]:
    try:
        values = json.loads(raw or "[]")
        if len(values) == 4:
            return [max(0.0, min(1.0, float(value))) for value in values]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [0.0, 0.0, 1.0, 1.0]


def _observation(row) -> dict:
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "document_id": mapping["document_id"],
        "analyte_id": mapping["analyte_id"],
        "label_raw": mapping["label_raw"],
        "value_num": mapping["value_num"],
        "value_text": mapping["value_text"],
        "unit_raw": mapping["unit_raw"],
        "unit_norm": mapping["unit_norm"],
        "ref_low": mapping["ref_low"],
        "ref_high": mapping["ref_high"],
        "flag_printed": mapping["flag_printed"],
        "bbox": _bbox(mapping["bbox_json"]),
        "page": mapping["page"],
        "engine": mapping["engine"],
        "confidence": mapping["confidence"],
        "status": mapping["status"],
        "reason": mapping["reason"],
        "mapping_rule": mapping["mapping_rule"],
        "created_at": mapping["created_at"],
    }


@router.post("/{observation_id}/review")
def review_observation(
    observation_id: str,
    payload: ObservationReview,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    with request.app.state.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT o.id, o.document_id, o.analyte_id, o.label_raw, o.value_num,
                       o.value_text, o.unit_raw, o.unit_norm, o.ref_low, o.ref_high,
                       o.flag_printed, o.bbox_json, o.page, o.engine, o.confidence,
                       o.status, o.reason, o.mapping_rule, o.created_at,
                       d.patient_id, d.capture_type
                FROM observation o
                JOIN document d ON d.id = o.document_id
                WHERE o.id = :id AND d.patient_id = :patient_id
                """
            ),
            {"id": observation_id, "patient_id": patient["id"]},
        ).first()
        if row is None:
            api_error(404, "not_found", f"Unknown observation {observation_id}.")
        mapping = row._mapping
        if mapping["status"] != "review":
            api_error(409, "already_reviewed", "This field has already been reviewed.")
        if mapping["capture_type"] == "handwritten" and payload.action != "reject":
            api_error(
                409,
                "handwriting_review_required",
                "Handwritten fields need the handwriting review flow.",
            )

        actor = patient["username"] or patient["alias"]
        old_status = mapping["status"]
        old_value = mapping["value_num"]
        old_unit = mapping["unit_norm"]
        value_num = old_value
        value_text = mapping["value_text"]
        unit_norm = old_unit

        if payload.action == "accept":
            if mapping["analyte_id"] is None:
                api_error(409, "unmapped", "Map this field before accepting it.")
            if old_value is None:
                api_error(409, "missing_value", "This field has no numeric value.")
            status = "auto"
            reason = "Accepted during review."
            if payload.unit_norm:
                unit_norm = payload.unit_norm.strip()
        elif payload.action == "correct":
            if mapping["analyte_id"] is None:
                api_error(409, "unmapped", "Map this field before correcting it.")
            if payload.value_num is None:
                api_error(400, "validation_error", "A corrected value is required.", field="value_num")
            value_num = _decimal_string(payload.value_num)
            value_text = value_num
            status = "auto"
            reason = "Corrected during review."
            if payload.unit_norm is not None:
                unit_norm = payload.unit_norm.strip() or None
        else:
            status = "rejected"
            reason = (payload.reason.strip() if payload.reason else "") or "Rejected during review."

        conn.execute(
            text(
                """
                UPDATE observation
                SET status = :status, value_num = :value_num, value_text = :value_text,
                    unit_norm = :unit_norm, reason = :reason
                WHERE id = :id
                """
            ),
            {
                "status": status,
                "value_num": value_num,
                "value_text": value_text,
                "unit_norm": unit_norm,
                "reason": reason,
                "id": observation_id,
            },
        )
        audit(
            conn,
            entity="observation",
            entity_id=observation_id,
            field="status",
            old=old_status,
            new=status,
            actor=actor,
        )
        if value_num != old_value:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="value_num",
                old=old_value,
                new=value_num,
                actor=actor,
            )
        if unit_norm != old_unit:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="unit_norm",
                old=old_unit,
                new=unit_norm,
                actor=actor,
            )

        updated = conn.execute(
            text(
                """
                SELECT id, document_id, analyte_id, label_raw, value_num, value_text,
                       unit_raw, unit_norm, ref_low, ref_high, flag_printed, bbox_json,
                       page, engine, confidence, status, reason, mapping_rule, created_at
                FROM observation WHERE id = :id
                """
            ),
            {"id": observation_id},
        ).first()
        return {
            "observation": _observation(updated),
            "summary": build_summary(conn, patient["id"]),
        }

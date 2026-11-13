"""Review extracted observations. Only the owning patient can accept or reject."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import audit, current_patient
from smriti.clinical_summary import invalidate_patient_digest
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
    if not -12 <= value.adjusted() <= 12 or len(value.as_tuple().digits) > 15:
        api_error(
            400,
            "validation_error",
            "Value is outside the range a lab result can have.",
            field="value_num",
        )
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
        "report_id": mapping.get("report_id"),
        "analyte_id": mapping["analyte_id"],
        "label_raw": mapping["label_raw"],
        "label_norm": mapping.get("label_norm"),
        "fact_type": mapping.get("fact_type"),
        "evidence_quote": mapping.get("evidence_quote"),
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
                SELECT o.id, o.document_id, o.report_id, o.analyte_id, o.label_raw,
                       o.label_norm, o.fact_type, o.evidence_quote, o.value_num,
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

        actor = patient["username"] or patient["alias"]
        old_status = mapping["status"]
        old_value = mapping["value_num"]
        old_text = mapping["value_text"]
        old_unit = mapping["unit_norm"]
        old_label = mapping["label_raw"]
        old_ref_low = mapping["ref_low"]
        old_ref_high = mapping["ref_high"]
        old_flag = mapping["flag_printed"]
        old_engine = mapping["engine"]

        analyte_id = payload.analyte_id.strip() if payload.analyte_id else mapping["analyte_id"]
        label_raw = payload.raw_label.strip() if payload.raw_label else mapping["label_raw"]
        ref_low = payload.ref_low.strip() if payload.ref_low is not None else mapping["ref_low"]
        ref_high = payload.ref_high.strip() if payload.ref_high is not None else mapping["ref_high"]
        flag_printed = payload.flag.strip() if payload.flag is not None else mapping["flag_printed"]

        value_num = old_value
        value_text = old_text
        unit_norm = old_unit
        engine = "human" if payload.action in ("accept", "correct") else old_engine

        if payload.action == "accept":
            if mapping["value_num"] is not None and analyte_id is None:
                api_error(409, "unmapped", "Map this field before accepting it.")
            if mapping["value_num"] is None and mapping["value_text"] is None:
                api_error(409, "missing_value", "This field has no value.")
            status = "auto"
            reason = "Accepted during review."
            if payload.unit_norm:
                unit_norm = payload.unit_norm.strip()
        elif payload.action == "correct":
            if mapping["value_num"] is not None or payload.value_num is not None:
                if analyte_id is None and not payload.raw_label:
                    api_error(409, "unmapped", "Map this field before correcting it.")
                if payload.value_num is None:
                    api_error(
                        400,
                        "validation_error",
                        "A corrected value is required.",
                        field="value_num",
                    )
                value_num = _decimal_string(payload.value_num)
                value_text = value_num
            else:
                if payload.value_text is None or not payload.value_text.strip():
                    api_error(
                        400,
                        "validation_error",
                        "A corrected text value is required.",
                        field="value_text",
                    )
                value_text = payload.value_text.strip()
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
                    unit_norm = :unit_norm, reason = :reason, analyte_id = :analyte_id,
                    label_raw = :label_raw, ref_low = :ref_low, ref_high = :ref_high,
                    flag_printed = :flag_printed, engine = :engine
                WHERE id = :id
                """
            ),
            {
                "status": status,
                "value_num": value_num,
                "value_text": value_text,
                "unit_norm": unit_norm,
                "reason": reason,
                "analyte_id": analyte_id,
                "label_raw": label_raw,
                "ref_low": ref_low,
                "ref_high": ref_high,
                "flag_printed": flag_printed,
                "engine": engine,
                "id": observation_id,
            },
        )
        if analyte_id != mapping["analyte_id"]:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="analyte_id",
                old=mapping["analyte_id"],
                new=analyte_id,
                actor=actor,
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
        if value_text != old_text:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="value_text",
                old=old_text,
                new=value_text,
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
        if label_raw != old_label:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="label_raw",
                old=old_label,
                new=label_raw,
                actor=actor,
            )
        if ref_low != old_ref_low:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="ref_low",
                old=old_ref_low,
                new=ref_low,
                actor=actor,
            )
        if ref_high != old_ref_high:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="ref_high",
                old=old_ref_high,
                new=ref_high,
                actor=actor,
            )
        if flag_printed != old_flag:
            audit(
                conn,
                entity="observation",
                entity_id=observation_id,
                field="flag_printed",
                old=old_flag,
                new=flag_printed,
                actor=actor,
            )

        invalidate_patient_digest(conn, patient["id"])

        updated = conn.execute(
            text(
                """
                SELECT id, document_id, report_id, analyte_id, label_raw, label_norm,
                       fact_type, evidence_quote, value_num, value_text, unit_raw,
                       unit_norm, ref_low, ref_high, flag_printed, bbox_json, page,
                       engine, confidence, status, reason, mapping_rule, created_at
                FROM observation WHERE id = :id
                """
            ),
            {"id": observation_id},
        ).first()
        return {
            "observation": _observation(updated),
            "summary": build_summary(conn, patient["id"]),
        }

"""Patient summary and erase-all. A patient can only access their own record."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import SESSION_COOKIE, audit, current_patient, require_same_patient
from smriti.clinical_summary import get_or_synthesize_summary
from smriti.models import CloudConsentCreate, ReportCategory, StandardizedClinicalSummary, Summary, Timeline
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


@router.get("/{patient_id}/clinical-summary", response_model=StandardizedClinicalSummary)
def get_clinical_summary(
    patient_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
) -> StandardizedClinicalSummary:
    require_same_patient(patient_id, patient)
    with request.app.state.engine.connect() as conn:
        return get_or_synthesize_summary(conn, request.app.state.settings, patient_id)


@router.post("/{patient_id}/clinical-summary/refresh", response_model=StandardizedClinicalSummary)
def refresh_clinical_summary(
    patient_id: str,
    request: Request,
    use_cloud: bool = Query(default=False),
    patient: dict = Depends(current_patient),
) -> StandardizedClinicalSummary:
    require_same_patient(patient_id, patient)
    settings = request.app.state.settings
    if use_cloud and settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    with request.app.state.engine.connect() as conn:
        return get_or_synthesize_summary(
            conn,
            settings,
            patient_id,
            force_refresh=True,
            use_cloud=use_cloud,
        )


@router.post("/{patient_id}/cloud-consent")
def set_patient_cloud_consent(
    patient_id: str,
    request: Request,
    payload: CloudConsentCreate,
    patient: dict = Depends(current_patient),
) -> dict:
    require_same_patient(patient_id, patient)
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")
    approved = payload.approved
    now = _now()
    with request.app.state.engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES (:id, 'patient', :entity_id, 'cloud_consent', NULL, :new, :actor, :ts)
            """),
            {
                "id": str(uuid.uuid4()),
                "entity_id": patient_id,
                "new": "approved" if approved else "declined",
                "actor": patient.get("username") or patient.get("alias") or "patient",
                "ts": now,
            },
        )
    return {"patient_id": patient_id, "approved": approved, "updated_at": now}


def _bbox(raw: str | None) -> list[float]:
    try:
        values = json.loads(raw or "[]")
        if len(values) == 4:
            return [max(0.0, min(1.0, float(value))) for value in values]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [0.0, 0.0, 1.0, 1.0]


@router.get("/{patient_id}/timeline", response_model=Timeline)
def get_timeline(
    patient_id: str,
    request: Request,
    patient: dict = Depends(current_patient),
    category: ReportCategory | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> Timeline:
    require_same_patient(patient_id, patient)
    if from_date and to_date and from_date > to_date:
        api_error(400, "validation_error", "'from' must be before 'to'.", field="from")

    filters = ["r.patient_id = :patient_id", "r.status <> 'rejected'"]
    params: dict[str, object] = {"patient_id": patient_id}
    if category is not None:
        filters.append("r.category = :category")
        params["category"] = category
    if from_date is not None:
        filters.append("r.report_date >= :from_date")
        params["from_date"] = from_date.isoformat()
    if to_date is not None:
        filters.append("r.report_date <= :to_date")
        params["to_date"] = to_date.isoformat()

    with request.app.state.engine.connect() as conn:
        report_rows = conn.execute(
            text(
                f"""
                SELECT r.id, r.document_id, r.category, r.report_type,
                       r.report_date, r.facility_name, r.title, r.summary,
                       r.page_start, r.page_end, r.status, r.reason
                FROM report r
                WHERE {' AND '.join(filters)}
                ORDER BY COALESCE(r.report_date, '9999-12-31') DESC, r.page_start
                """
            ),
            params,
        ).all()
        fact_rows = conn.execute(
            text(
                """
                SELECT o.id, o.report_id, o.document_id, o.fact_type, o.label_raw,
                       o.label_norm, o.value_num, o.value_text, o.unit_norm, o.page,
                       o.bbox_json, o.status, o.reason, o.evidence_quote
                FROM observation o
                JOIN report r ON r.id = o.report_id
                WHERE r.patient_id = :patient_id
                  AND r.status <> 'rejected'
                  AND o.status <> 'rejected'
                ORDER BY o.page, o.created_at
                """
            ),
            {"patient_id": patient_id},
        ).all()

    facts_by_report: dict[str, list[dict]] = {}
    for row in fact_rows:
        mapping = row._mapping
        facts_by_report.setdefault(mapping["report_id"], []).append(
            {
                "id": mapping["id"],
                "report_id": mapping["report_id"],
                "document_id": mapping["document_id"],
                "fact_type": mapping["fact_type"],
                "label_raw": mapping["label_raw"],
                "label_norm": mapping["label_norm"],
                "value_num": mapping["value_num"],
                "value_text": mapping["value_text"],
                "unit_norm": mapping["unit_norm"],
                "page": mapping["page"],
                "bbox": _bbox(mapping["bbox_json"]),
                "status": mapping["status"],
                "reason": mapping["reason"],
                "evidence_quote": mapping["evidence_quote"],
            }
        )

    reports = []
    for row in report_rows:
        mapping = row._mapping
        facts = facts_by_report.get(mapping["id"], [])
        reports.append(
            {
                "id": mapping["id"],
                "document_id": mapping["document_id"],
                "category": mapping["category"],
                "report_type": mapping["report_type"],
                "report_date": mapping["report_date"],
                "facility_name": mapping["facility_name"],
                "title": mapping["title"],
                "summary": mapping["summary"],
                "page_start": mapping["page_start"],
                "page_end": mapping["page_end"],
                "status": mapping["status"],
                "reason": mapping["reason"],
                "review_count": sum(fact["status"] == "review" for fact in facts),
                "facts": facts,
            }
        )

    return {"patient_id": patient_id, "reports": reports}


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

    from smriti.coordinator import CleanupBlocked
    from smriti.erasure import erase_owner

    try:
        erase_owner(request.app.state.engine, settings, patient, request.app.state.service)
    except (CleanupBlocked, OSError):
        api_error(503, "cleanup_failed", "Account deletion is incomplete. Local recovery is required; try again.")

    response.delete_cookie(SESSION_COOKIE, path="/")

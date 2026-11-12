"""Correct report-level metadata. Facts keep their own review endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from api.errors import api_error
from smriti.auth import audit, current_patient
from smriti.models import ReportUpdate

router = APIRouter(prefix="/reports", tags=["reports"])

_FIELDS = ("report_date", "category", "title", "facility_name", "summary")


def _report_row(conn, report_id: str) -> dict:
    row = conn.execute(
        text(
            """
            SELECT r.id, r.document_id, r.category, r.report_type, r.report_date,
                   r.facility_name, r.title, r.summary, r.page_start, r.page_end,
                   r.status, r.reason, r.model_version, r.created_at,
                   (SELECT COUNT(*) FROM observation o
                    WHERE o.report_id = r.id) AS fact_count,
                   (SELECT COUNT(*) FROM observation o
                    WHERE o.report_id = r.id AND o.status = 'review') AS review_count
            FROM report r WHERE r.id = :id
            """
        ),
        {"id": report_id},
    ).first()
    if row is None:
        api_error(404, "not_found", f"Unknown report {report_id}.")
    return dict(row._mapping)


@router.patch("/{report_id}")
def update_report(
    report_id: str,
    payload: ReportUpdate,
    request: Request,
    patient: dict = Depends(current_patient),
) -> dict:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        api_error(400, "validation_error", "No report fields supplied.")
    if "category" in updates and updates["category"] is None:
        api_error(400, "validation_error", "Category cannot be empty.", field="category")

    with request.app.state.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT r.*, d.patient_id
                FROM report r JOIN document d ON d.id = r.document_id
                WHERE r.id = :id AND d.patient_id = :patient_id
                """
            ),
            {"id": report_id, "patient_id": patient["id"]},
        ).first()
        if row is None:
            api_error(404, "not_found", f"Unknown report {report_id}.")
        old = dict(row._mapping)

        changed = []
        params: dict[str, object] = {"id": report_id}
        for field in _FIELDS:
            if field not in updates:
                continue
            value = updates[field]
            if field == "report_date" and value is not None:
                value = value.isoformat()
            if value != old[field]:
                changed.append((field, old[field], value))
                params[field] = value

        if not changed:
            return {"report": _report_row(conn, report_id)}

        status = "auto"
        reason = "Corrected during review."
        report_date = updates.get("report_date", old["report_date"])
        category = updates.get("category", old["category"])
        if report_date is None:
            status = "review"
            reason = "Report date not detected; review required."
        elif category == "other":
            status = "review"
            reason = "Report category is uncertain; review required."

        params["status"] = status
        params["reason"] = reason
        assignments = ", ".join(f"{field} = :{field}" for field, _, _ in changed)
        conn.execute(
            text(
                f"UPDATE report SET {assignments}, status = :status, reason = :reason "
                "WHERE id = :id"
            ),
            params,
        )
        actor = patient["username"] or patient["alias"]
        for field, old_value, new_value in changed:
            audit(
                conn,
                entity="report",
                entity_id=report_id,
                field=field,
                old=old_value,
                new=new_value,
                actor=actor,
            )
        return {"report": _report_row(conn, report_id)}

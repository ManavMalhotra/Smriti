"""Build the frozen summary contract from stored records."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from smriti.analytes import default_unit, display_for
from smriti.clinical_summary import get_or_synthesize_summary, is_valid_medication_name
from smriti.models import (
    Coverage,
    DocumentSummary,
    Excluded,
    Gap,
    MedicationSummary,
    Pending,
    Problem,
    Quarter,
    Result,
    ResultPoint,
    Summary,
    SummaryPatient,
)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _doc_date(row: Any) -> date | None:
    return (
        _parse_date(row.get("verified_date"))
        or
        _parse_date(row["collection_date"])
        or _parse_date(row.get("registration_date"))
        or _parse_date(row.get("report_date"))
        or _parse_date(row["doc_date"])
    )


def _quarter_key(value: date) -> str:
    return f"{value.year}-Q{(value.month - 1) // 3 + 1}"


def _quarter_start(value: date) -> tuple[int, int]:
    return value.year, value.month - (value.month - 1) % 3


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(0, months)


def _normalise_bbox(raw: str | None) -> list[float]:
    try:
        values = json.loads(raw or "[]")
        if len(values) == 4:
            return [max(0.0, min(1.0, float(value))) for value in values]
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return [0.0, 0.0, 1.0, 1.0]


ORGAN_ANALYTES = {
    "blood_immunity": {"hemoglobin", "wbc", "rbc", "platelets", "hematocrit", "mcv", "mch", "mchc", "rdw", "neutrophils", "lymphocytes", "monocytes", "eosinophils", "basophils", "esr", "crp"},
    "kidneys_renal": {"creatinine", "urea", "bun", "egfr", "uric_acid", "sodium", "potassium", "chloride"},
    "heart_lipids": {"cholesterol", "cholesterol_total", "hdl", "ldl", "triglycerides", "vldl"},
    "sugar_metabolism": {"hba1c", "glucose", "glucose_fasting", "glucose_pp", "glucose_random"},
    "liver_digestion": {"alt", "ast", "alp", "ggt", "bilirubin_total", "bilirubin_direct", "albumin", "protein_total"},
    "thyroid_hormones": {"tsh", "t3", "t4", "ft3", "ft4"},
}


def _clinical(raw):
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _bbox_2d(bbox):
    x0, y0, x1, y1 = bbox
    return [round(y0 * 1000), round(x0 * 1000), round(y1 * 1000), round(x1 * 1000)]


def _abnormal(value, low, high, printed=None):
    if printed in {"critical", "positive_finding"}:
        return printed
    if value is None:
        return printed
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "normal" if low is not None and high is not None else None


def _coverage(documents: list[dict[str, Any]], event_dates: list[date] | None = None) -> Coverage:
    today = datetime.now(timezone.utc).date()
    dated = sorted(
        (document for document in documents if document["date"] is not None and document["date"] <= today),
        key=lambda document: document["date"],
    )
    record_dates = sorted(({document["date"] for document in dated} | set(event_dates or [])) -
                          {value for value in (event_dates or []) if value > today})
    if not record_dates:
        return Coverage(first_date=None, last_date=None, quarters=[], gaps=[],
                        undated_documents=sum(document["date"] is None for document in documents),
                        future_documents=sum(document["date"] is not None and document["date"] > today for document in documents))

    first_date = record_dates[0]
    last_date = record_dates[-1]
    counts: dict[str, int] = defaultdict(int)
    for document in dated:
        counts[_quarter_key(document["date"])] += 1

    quarters: list[Quarter] = []
    year, month = _quarter_start(first_date)
    last_start = _quarter_start(last_date)
    while (year, month) <= last_start:
        key = f"{year}-Q{(month - 1) // 3 + 1}"
        quarters.append(Quarter(q=key, documents=counts.get(key, 0)))
        month += 3
        if month > 12:
            year += 1
            month -= 12

    gaps: list[Gap] = []
    for start, end in zip(record_dates, record_dates[1:]):
        months = _months_between(start, end)
        if months >= 6:
            gaps.append(
                Gap(
                    from_date=start,
                    to=end,
                    months=months,
                    text=f"No dated source record for {months} months",
                )
            )

    return Coverage(
        first_date=first_date,
        last_date=last_date,
        quarters=quarters,
        gaps=gaps,
        undated_documents=sum(document["date"] is None for document in documents),
        future_documents=sum(document["date"] is not None and document["date"] > today for document in documents),
    )


def _results(conn: Connection, patient_id: str) -> list[Result]:
    rows = conn.execute(
        text(
            """
            SELECT o.id, o.document_id, o.analyte_id, o.label_raw, o.value_num,
                   o.unit_raw, o.unit_norm, o.ref_low, o.ref_high, o.flag_printed,
                   o.bbox_json, o.page, o.status, o.reason, o.clinical_json, o.engine,
                   d.collection_date, d.registration_date, d.report_date, d.verified_date, d.doc_date, d.created_at
            FROM observation o
            JOIN document d ON d.id = o.document_id
            WHERE d.patient_id = :patient_id
            ORDER BY d.verified_date, d.collection_date, d.doc_date, d.created_at
            """
        ),
        {"patient_id": patient_id},
    ).all()

    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    dated_cloud = {(row.document_id, row.page, row.analyte_id, _parse_float(row.value_num))
                   for row in rows if row.clinical_json and row.status != "rejected"}
    for row in rows:
        if not row.clinical_json and (row.document_id, row.page, row.analyte_id, _parse_float(row.value_num)) in dated_cloud:
            continue
        key = row._mapping["analyte_id"]
        if not key:
            continue
        unit = row._mapping["unit_norm"] or row._mapping["unit_raw"] or default_unit(key)
        unit_key = unit.strip().lower() if unit else None
        group = groups.setdefault(
            (key, unit_key),
            {
                "analyte_id": key,
                "display": display_for(key, row._mapping["label_raw"]),
                "unit": unit,
                "ref_low": None,
                "ref_high": None,
                "points": [],
                "excluded": [],
            },
        )
        if group["ref_low"] is None:
            group["ref_low"] = _parse_float(row._mapping["ref_low"])
        if group["ref_high"] is None:
            group["ref_high"] = _parse_float(row._mapping["ref_high"])

        if row._mapping["status"] == "rejected":
            group["excluded"].append(
                Excluded(
                    document_id=row._mapping["document_id"],
                    reason=row._mapping["reason"] or "Rejected during review",
                )
            )
            continue

        clinical = _clinical(row._mapping["clinical_json"])
        point_date = _parse_date(clinical.get("event_date")) or _doc_date(row._mapping)
        value = _parse_float(row._mapping["value_num"])
        if point_date is None or value is None:
            continue
        group["points"].append(
            ResultPoint(
                date=point_date,
                value=value,
                flag_printed=row._mapping["flag_printed"],
                observation_id=row._mapping["id"],
                document_id=row._mapping["document_id"],
                page=row._mapping["page"],
                bbox=_normalise_bbox(row._mapping["bbox_json"]),
                status=row._mapping["status"],
                ref_min=_parse_float(row._mapping["ref_low"]),
                ref_max=_parse_float(row._mapping["ref_high"]),
                abnormal_flag=_abnormal(value, _parse_float(row._mapping["ref_low"]), _parse_float(row._mapping["ref_high"]), clinical.get("abnormal_flag")),
                engine=row._mapping["engine"],
                source_anchors=clinical.get("source_anchors", []),
            )
        )

    results: list[Result] = []
    for _key, group in sorted(
        groups.items(), key=lambda item: (item[1]["display"], item[1]["unit"] or "")
    ):
        if not group["points"]:
            continue
        results.append(
            Result(
                analyte_id=group["analyte_id"],
                display=group["display"],
                unit=group["unit"] or default_unit(group["analyte_id"]),
                ref_low=group["ref_low"],
                ref_high=group["ref_high"],
                points=sorted(group["points"], key=lambda point: point.date),
                excluded=group["excluded"],
            )
        )
    return results


def build_summary(conn: Connection, patient_id: str) -> Summary:
    patient_row = conn.execute(
        text(
            """
            SELECT id, alias, username, sex, dob, created_at
            FROM patient WHERE id = :id
            """
        ),
        {"id": patient_id},
    ).first()
    patient = SummaryPatient(
        id=patient_row._mapping["id"],
        alias=patient_row._mapping["alias"],
        sex=patient_row._mapping["sex"],
        dob=patient_row._mapping["dob"],
    )

    document_rows = conn.execute(
        text(
            """
            SELECT d.id, d.display_name, d.verified_date, d.doc_type, d.doc_date, d.collection_date, d.registration_date, d.report_date,
                   d.facility_name, d.lab_name, d.page_count, d.status, d.processed_at, d.created_at,
                   (SELECT COUNT(*) FROM observation o
                    WHERE o.document_id = d.id AND o.status = 'review') +
                   (SELECT COUNT(*) FROM report r
                    WHERE r.document_id = d.id AND r.status = 'review') AS review_count
            FROM document d
            WHERE d.patient_id = :patient_id
            ORDER BY COALESCE(d.verified_date, d.collection_date, d.registration_date, d.report_date, d.doc_date) DESC,
                     d.created_at DESC
            """
        ),
        {"patient_id": patient_id},
    ).all()
    documents = [
        {
            "id": row._mapping["id"],
            "display_name": row._mapping["display_name"],
            "verified_date": row._mapping["verified_date"],
            "doc_type": row._mapping["doc_type"],
            "doc_date": row._mapping["doc_date"],
            "collection_date": row._mapping["collection_date"],
            "registration_date": row._mapping.get("registration_date"),
            "report_date": row._mapping["report_date"],
            "facility_name": row._mapping.get("facility_name") or row._mapping.get("lab_name"),
            "page_count": row._mapping["page_count"],
            "status": row._mapping["status"],
            "processed_at": row._mapping["processed_at"],
            "review_count": row._mapping["review_count"],
            "created_at": row._mapping["created_at"],
            "date": _doc_date(row._mapping),
        }
        for row in document_rows
    ]

    source_dates = conn.execute(text("""
        SELECT COALESCE(d.verified_date, r.report_date, d.collection_date, d.registration_date, d.doc_date) AS event_date
        FROM report r JOIN document d ON d.id=r.document_id
        WHERE r.patient_id=:patient_id AND r.status <> 'rejected'
          AND COALESCE(d.verified_date, r.report_date, d.collection_date, d.registration_date, d.doc_date) IS NOT NULL
        UNION ALL
        SELECT json_extract(clinical_json, '$.event_date') AS event_date FROM observation o
        JOIN document d ON d.id=o.document_id
        WHERE d.patient_id=:patient_id AND o.status <> 'rejected' AND json_valid(o.clinical_json)
          AND json_extract(o.clinical_json, '$.event_date') IS NOT NULL
    """), {"patient_id": patient_id}).scalars().all()
    clinical_dates = [parsed for value in source_dates if (parsed := _parse_date(value)) is not None]

    medication_rows = conn.execute(
        text(
            """
            SELECT m.id, brand_raw, salt, dose, freq, m.status, reported_at, source_doc_id, page, bbox_json, engine, clinical_json,
                   COALESCE(start_date, d.doc_date, d.collection_date) AS start_date
            FROM medication m LEFT JOIN document d ON d.id = m.source_doc_id
            WHERE m.patient_id = :patient_id
            ORDER BY brand_raw
            """
        ),
        {"patient_id": patient_id},
    ).all()
    medications = [
        MedicationSummary(
            id=row._mapping["id"],
            brand_raw=row._mapping["brand_raw"],
            salt=row._mapping["salt"],
            dose=row._mapping["dose"],
            freq=row._mapping["freq"],
            state=row._mapping["status"],
            source_doc_id=row._mapping["source_doc_id"],
            reported_at=row._mapping["reported_at"],
            page_num=row._mapping["page"],
            bbox_2d=_bbox_2d(_normalise_bbox(row._mapping["bbox_json"])) if row._mapping["bbox_json"] else None,
            engine=row._mapping["engine"],
            event_date=_parse_date(row._mapping["start_date"]),
            regimen_type=_clinical(row._mapping["clinical_json"]).get("regimen_type"),
            confidence_note=_clinical(row._mapping["clinical_json"]).get("confidence_note"),
            source_anchors=_clinical(row._mapping["clinical_json"]).get("source_anchors", []),
        )
        for row in medication_rows
        if is_valid_medication_name(row._mapping["brand_raw"])
    ]

    directive_rows = conn.execute(
        text(
            """
            SELECT dir.id, dir.span_text, dir.action_type, dir.due_date,
                   dir.anchor_event, dir.state
            FROM directive dir
            JOIN document d ON d.id = dir.document_id
            WHERE d.patient_id = :patient_id
              AND dir.state IN ('open', 'unknown_date')
            ORDER BY dir.due_date IS NULL, dir.due_date
            """
        ),
        {"patient_id": patient_id},
    ).all()
    pending = [
        Pending(
            kind="directive",
            id=row._mapping["id"],
            text=row._mapping["span_text"],
            action_type=row._mapping["action_type"],
            due_date=_parse_date(row._mapping["due_date"]),
            anchor_event=row._mapping["anchor_event"],
            state=row._mapping["state"],
        )
        for row in directive_rows
    ]

    results = _results(conn, patient_id)
    clinical = _clinical_summary(conn, patient_id, results, medications)
    standardized = get_or_synthesize_summary(conn, None, patient_id)
    return Summary(
        patient=patient,
        coverage=_coverage(documents, clinical_dates),
        problems=[Problem(id=item["id"], label=item["title"], source_doc_id=item["doc_id"])
                  for item in clinical["clinical_snapshot"]["primary_diagnoses"]],
        medications=medications,
        results=results,
        pending=pending,
        documents=[
            DocumentSummary(
                id=document["id"],
                display_name=document["display_name"],
                verified_date=document["verified_date"],
                doc_type=document["doc_type"],
                doc_date=document["doc_date"],
                collection_date=document["collection_date"],
                registration_date=document.get("registration_date"),
                report_date=document.get("report_date"),
                facility_name=document.get("facility_name"),
                page_count=document["page_count"],
                status=document["status"],
                processed_at=document["processed_at"],
                review_count=document["review_count"],
            )
            for document in documents
        ],
        standardized_summary=standardized,
        **clinical,
    )


def _clinical_summary(conn, patient_id, results, medications):
    snapshot = {"primary_diagnoses": [], "allergies": [], "major_procedures": []}
    events, systems = [], {}
    rows = conn.execute(text("""SELECT o.*, d.doc_type, d.doc_date, d.collection_date, d.verified_date, d.report_date AS document_report_date,
        r.report_date AS issued_date, r.report_type, r.status AS report_status
        FROM observation o JOIN document d ON d.id = o.document_id LEFT JOIN report r ON r.id = o.report_id
        WHERE d.patient_id = :id AND o.status <> 'rejected' AND (r.status IS NULL OR r.status <> 'rejected')"""), {"id": patient_id})
    for row in rows.mappings():
        clinical = _clinical(row["clinical_json"])
        category = clinical.get("category") or {"lab": "lab_result", "diagnosis": "diagnosis_allergy",
            "imaging_finding": "imaging_radiology", "recommendation": "directive_followup"}.get(row["fact_type"], "other_general")
        issued = row["verified_date"] or clinical.get("report_date") or row["issued_date"] or row["document_report_date"] or row["doc_date"]
        event_date = clinical.get("event_date") or row["collection_date"] or issued
        title = row["label_raw"] or row["label_norm"] or "Clinical finding"
        event = {"id": row["id"], "title": title, "value_text": row["value_text"], "value_num": _parse_float(row["value_num"]),
            "category": category, "organ_system": clinical.get("organ_system"), "event_date": event_date,
            "report_date": issued, "report_type": row["report_type"] or row["doc_type"],
            "doc_id": row["document_id"], "page_num": row["page"], "bbox_2d": _bbox_2d(_normalise_bbox(row["bbox_json"])),
            "engine": row["engine"], "status": row["status"], "date_needs_review": clinical.get("date_needs_review", False),
            "facility_or_doctor": clinical.get("facility_or_doctor"), "source_anchors": clinical.get("source_anchors", []),
            "is_backdated_from_summary": bool(event_date and issued and event_date < issued and row["doc_type"] == "discharge_summary")}
        events.append(event)
        systems[row["id"]] = clinical.get("organ_system")
        if category == "diagnosis_allergy":
            combined = f"{title} {row['value_text'] or ''}"
            allergy = bool(re.search(r"allerg", combined, re.I))
            if not re.search(r"\b(?:no known|nil|denies|negative for)\b", combined, re.I):
                snapshot["allergies" if allergy else "primary_diagnoses"].append(event)
        elif category == "procedure_surgery":
            snapshot["major_procedures"].append(event)
    organ_groups = defaultdict(list)
    for result in results:
        organ = next((systems.get(p.observation_id) for p in result.points if systems.get(p.observation_id)), None)
        organ = organ or next((key for key, ids in ORGAN_ANALYTES.items() if result.analyte_id in ids), "other_general")
        series = [{"date": p.date.isoformat(), "value_num": p.value, "ref_min": p.ref_min, "ref_max": p.ref_max,
            "unit": result.unit, "abnormal_flag": p.abnormal_flag, "doc_id": p.document_id, "page_num": p.page,
            "bbox_2d": _bbox_2d(p.bbox), "status": p.status, "engine": p.engine, "source_anchors": p.source_anchors,
            "observation_id": p.observation_id} for p in result.points]
        organ_groups[organ].append({"analyte_id": result.analyte_id, "title": result.display, "unit": result.unit, "series": series})
    meds = {"active_scheduled": [], "conditional_sos_or": [], "historical_completed": []}
    newest_prescription = max((m.event_date for m in medications if m.event_date and m.state != "reported_stopped"), default=None)
    for medication in medications:
        item = medication.model_dump(mode="json")
        item.update(title=medication.brand_raw, value_text=" · ".join(filter(None, [medication.dose, medication.freq])),
                    doc_id=medication.source_doc_id, event_date=item["event_date"], category="medication", status="review")
        conditional = medication.regimen_type in {"alternative_or", "sos_prn"} or re.search(r"\b(?:OR|SOS|PRN)\b", f"{medication.brand_raw} {medication.dose or ''} {medication.freq or ''}", re.I)
        historical = medication.state == "reported_stopped" or medication.regimen_type == "completed_procedure" or (
            medication.state != "reported_ongoing" and medication.event_date and newest_prescription and medication.event_date < newest_prescription)
        item["current_use_confirmed"] = medication.state == "reported_ongoing"
        group = "historical_completed" if historical else "conditional_sos_or" if conditional else "active_scheduled"
        meds[group].append(item)
        events.append(dict(item, is_backdated_from_summary=False))
    snapshot["major_procedures"].sort(key=lambda item: item["event_date"] or "")
    return {"clinical_snapshot": snapshot, "organ_groups": dict(organ_groups), "medications_timeline": meds,
            "master_timeline": sorted(events, key=lambda item: item.get("event_date") or "", reverse=True)}


build_patient_summary = build_summary

"""Build the frozen summary contract from stored records."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from smriti.analytes import default_unit, display_for
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
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _doc_date(row: Any) -> date | None:
    return (
        _parse_date(row["collection_date"])
        or _parse_date(row.get("registration_date"))
        or _parse_date(row["doc_date"])
        or _parse_date(row["created_at"])
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


def _coverage(documents: list[dict[str, Any]]) -> Coverage:
    dated = sorted(
        (document for document in documents if document["date"] is not None),
        key=lambda document: document["date"],
    )
    if not dated:
        return Coverage(first_date=None, last_date=None, quarters=[], gaps=[])

    first_date = dated[0]["date"]
    last_date = dated[-1]["date"]
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
    unique_dates = sorted({document["date"] for document in dated})
    for start, end in zip(unique_dates, unique_dates[1:]):
        months = _months_between(start, end)
        if months >= 6:
            gaps.append(
                Gap(
                    from_date=start,
                    to=end,
                    months=months,
                    text=f"No data for {months} months",
                )
            )

    return Coverage(
        first_date=first_date,
        last_date=last_date,
        quarters=quarters,
        gaps=gaps,
    )


def _results(conn: Connection, patient_id: str) -> list[Result]:
    rows = conn.execute(
        text(
            """
            SELECT o.id, o.document_id, o.analyte_id, o.label_raw, o.value_num,
                   o.unit_raw, o.unit_norm, o.ref_low, o.ref_high, o.flag_printed,
                   o.bbox_json, o.page, o.status, o.reason,
                   d.collection_date, d.doc_date, d.created_at
            FROM observation o
            JOIN document d ON d.id = o.document_id
            WHERE d.patient_id = :patient_id
            ORDER BY d.collection_date, d.doc_date, d.created_at
            """
        ),
        {"patient_id": patient_id},
    ).all()

    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row._mapping["analyte_id"] or f"unmapped:{row._mapping['label_raw'] or 'unknown'}"
        group = groups.setdefault(
            key,
            {
                "display": display_for(row._mapping["analyte_id"], row._mapping["label_raw"]),
                "unit": row._mapping["unit_norm"] or row._mapping["unit_raw"],
                "ref_low": None,
                "ref_high": None,
                "points": [],
                "excluded": [],
            },
        )
        if group["unit"] is None:
            group["unit"] = row._mapping["unit_norm"] or row._mapping["unit_raw"]
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

        point_date = _doc_date(row._mapping)
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
            )
        )

    results: list[Result] = []
    for key, group in sorted(groups.items(), key=lambda item: item[1]["display"]):
        if not group["points"]:
            continue
        results.append(
            Result(
                analyte_id=key,
                display=group["display"],
                unit=group["unit"] or default_unit(key),
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
            SELECT d.id, d.doc_type, d.doc_date, d.collection_date, d.registration_date,
                   d.facility_name, d.lab_name, d.page_count, d.status, d.created_at,
                   (SELECT COUNT(*) FROM observation o
                    WHERE o.document_id = d.id AND o.status = 'review') AS review_count
            FROM document d
            WHERE d.patient_id = :patient_id
            ORDER BY COALESCE(d.collection_date, d.registration_date, d.doc_date, substr(d.created_at, 1, 10)) DESC,
                     d.created_at DESC
            """
        ),
        {"patient_id": patient_id},
    ).all()
    documents = [
        {
            "id": row._mapping["id"],
            "doc_type": row._mapping["doc_type"],
            "doc_date": row._mapping["doc_date"],
            "collection_date": row._mapping["collection_date"],
            "registration_date": row._mapping.get("registration_date"),
            "facility_name": row._mapping.get("facility_name") or row._mapping.get("lab_name"),
            "page_count": row._mapping["page_count"],
            "status": row._mapping["status"],
            "review_count": row._mapping["review_count"],
            "created_at": row._mapping["created_at"],
            "date": _doc_date(row._mapping),
        }
        for row in document_rows
    ]

    medication_rows = conn.execute(
        text(
            """
            SELECT id, brand_raw, salt, dose, freq, status, reported_at, source_doc_id
            FROM medication
            WHERE patient_id = :patient_id
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
        )
        for row in medication_rows
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

    return Summary(
        patient=patient,
        coverage=_coverage(documents),
        problems=[],
        medications=medications,
        results=_results(conn, patient_id),
        pending=pending,
        documents=[
            DocumentSummary(
                id=document["id"],
                doc_type=document["doc_type"],
                doc_date=document["doc_date"],
                collection_date=document["collection_date"],
                page_count=document["page_count"],
                status=document["status"],
                review_count=document["review_count"],
            )
            for document in documents
        ],
    )

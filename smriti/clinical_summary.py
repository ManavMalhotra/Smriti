"""Build source-linked report summaries without inferring diagnoses from page OCR."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from smriti.config import Settings, load_settings
from smriti.models import (
    StandardizedClinicalSummary,
    YearHistoryEntry,
)
from smriti.stage import get_stage_artifact, save_stage_artifact

logger = logging.getLogger(__name__)

STAGE_NAME = "standardized_clinical_summary_v2"
OFFLINE_ENGINE = "local-rules:summary@2.0"

# Lab test analytes and OCR noise words that should never appear as brand medications
NON_MED_WORDS = {
    "triglycerides", "triglyceride", "protein", "globulin", "albumin",
    "estimated", "egfr", "creatinine", "urea", "bun", "sodium", "potassium",
    "chloride", "cholesterol", "bilirubin", "glucose", "hba1c", "hemoglobin",
    "hb", "hb-", "wbc", "rbc", "platelets", "platelet", "esr", "crp",
    "sgot", "sgpt", "alt", "ast", "alp", "tsh", "t3", "t4", "calcium",
    "phosphorus", "uric", "acid", "ar", "of", "once", "daily", "mg", "ml",
    "normal", "high", "low", "ratio", "serum", "blood", "urine", "stool",
    "total", "direct", "indirect", "fasting", "random", "post", "prandial"
}

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_valid_medication_name(brand: str) -> bool:
    if not brand or len(brand.strip()) < 3:
        return False
    cleaned = brand.strip().lower()
    for prefix in ("tab.", "tab", "cap.", "cap", "inj.", "inj", "syp.", "syp", "t.", "i.", "c."):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip(" .-")
            break
    if not cleaned or len(cleaned) < 2:
        return False
    words = set(re.findall(r"[a-z]+", cleaned))
    if not words:
        return False
    lab_analytes = {
        "triglycerides", "triglyceride", "protein", "globulin", "albumin",
        "estimated", "egfr", "creatinine", "urea", "bun", "sodium", "potassium",
        "chloride", "cholesterol", "bilirubin", "glucose", "hba1c", "hemoglobin",
        "hb", "platelets", "platelet", "sgot", "sgpt", "alt", "ast", "alp", "tsh",
        "calcium", "phosphorus", "uric", "sgot", "sgpt", "differential"
    }
    if words.intersection(lab_analytes):
        return False
    if cleaned in NON_MED_WORDS:
        return False
    return True


def synthesize_patient_summary_offline(conn: Connection, patient_id: str, cloud_error: str | None = None) -> StandardizedClinicalSummary:
    """Build a digest from persisted reports; do not infer diagnoses from unrelated OCR text."""
    patient = conn.execute(
        text("SELECT alias, sex, dob FROM patient WHERE id = :id"),
        {"id": patient_id},
    ).mappings().first()
    if patient is None:
        return StandardizedClinicalSummary(model_id=OFFLINE_ENGINE, generated_at=_now(), cloud_error=cloud_error)

    age = None
    if patient["dob"]:
        try:
            born = date.fromisoformat(patient["dob"][:10])
            today = datetime.now(timezone.utc).date()
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        except (TypeError, ValueError):
            pass

    reports = conn.execute(text("""
        SELECT r.document_id, r.report_date, r.title, r.summary, r.page_start,
               r.status, d.doc_date, d.collection_date, d.registration_date, d.verified_date
        FROM report r JOIN document d ON d.id = r.document_id
        WHERE r.patient_id = :id AND r.status <> 'rejected'
        ORDER BY COALESCE(d.verified_date, r.report_date, d.doc_date, d.collection_date, d.registration_date) DESC,
                 r.created_at DESC
        LIMIT 100
    """), {"id": patient_id}).mappings().all()

    records = []
    for report in reports:
        raw_date = report["verified_date"] or report["report_date"] or report["doc_date"] or report["collection_date"] or report["registration_date"]
        record_date = None
        try:
            record_date = date.fromisoformat(raw_date[:10]) if raw_date else None
        except (TypeError, ValueError):
            pass
        if not report["title"] and not report["summary"]:
            continue
        records.append(YearHistoryEntry(
            year=record_date.year if record_date else None,
            title=report["title"] or "Report",
            summary=report["summary"],
            category="source_record",
            source_doc_id=report["document_id"],
            source_page=report["page_start"],
            exact_date=record_date.isoformat() if record_date else None,
            status=report["status"],
        ))

    return StandardizedClinicalSummary(
        patient_name=patient["alias"],
        age=age,
        gender=patient["sex"],
        year_wise_history=records,
        generated_at=_now(),
        model_id=OFFLINE_ENGINE,
        is_cloud_generated=False,
        cloud_error=cloud_error,
    )

def synthesize_patient_summary_cloud(
    conn: Connection,
    settings: Settings,
    patient_id: str,
    *,
    on_outcome: Any = None,
) -> StandardizedClinicalSummary:
    """Patient summaries stay local until a reviewed, redacted image flow exists."""
    if on_outcome:
        on_outcome("disabled_unredacted_text")
    return synthesize_patient_summary_offline(
        conn, patient_id, cloud_error="Cloud summaries are unavailable until all source pages have approved PII masks."
    )


def get_or_synthesize_summary(
    conn: Connection,
    settings: Settings | None,
    patient_id: str,
    *,
    force_refresh: bool = False,
    use_cloud: bool = False,
) -> StandardizedClinicalSummary:
    """Retrieve existing cached standardized summary or synthesize and cache a new one."""
    if not force_refresh and not use_cloud:
        cached = get_stage_artifact(conn, patient_id, 1, STAGE_NAME)
        if cached:
            try:
                data = json.loads(cached) if isinstance(cached, str) else cached
                return StandardizedClinicalSummary.model_validate(data)
            except Exception:
                pass

    settings = settings or load_settings()
    if use_cloud and settings.gemini_api_key and not settings.demo:
        summary = synthesize_patient_summary_cloud(conn, settings, patient_id)
    else:
        summary = synthesize_patient_summary_offline(conn, patient_id)

    # Cache into stage_artifact if possible
    try:
        save_stage_artifact(
            conn,
            patient_id,
            1,
            STAGE_NAME,
            summary.model_id or OFFLINE_ENGINE,
            summary.model_dump(mode="json"),
        )
        if hasattr(conn, "commit"):
            conn.commit()
    except Exception as exc:
        logger.debug("Could not cache standardized summary: %s", exc)
    return summary

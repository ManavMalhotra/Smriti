"""Split one upload into logical reports and classify the facts inside them.

The split is deliberately conservative: a page with a new date or facility starts
a new report, a page without either continues the current report. Uncertain
splits stay in review instead of being silently guessed.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from smriti.metadata import (
    extract_document_dates,
    extract_document_identifiers,
    parse_date,
)

MODEL_VERSION = "report-segmenter@1.0"

_CATEGORY_BY_DOC_TYPE = {
    "lab_report": "lab",
    "ct": "imaging",
    "mri": "imaging",
    "xray": "imaging",
    "radiology": "imaging",
    "pathology": "pathology",
    "prescription": "prescription",
    "pharmacy": "prescription",
    "discharge_summary": "discharge",
    "other": "other",
}

_CATEGORY_TITLES = {
    "lab": "Lab report",
    "imaging": "Imaging report",
    "prescription": "Prescription",
    "discharge": "Discharge summary",
    "pathology": "Pathology report",
    "other": "Report",
}

_FACT_TYPES = {
    "impression": "impression",
    "findings": "imaging_finding",
    "diagnosis": "diagnosis",
    "advice": "recommendation",
    "recommendation": "recommendation",
    "history": "note",
}


@dataclass
class ReportDraft:
    id: str
    page_start: int
    page_end: int
    report_date: str | None
    category: str
    report_type: str
    facility_name: str | None
    title: str
    summary: str | None
    status: str
    reason: str | None
    model_version: str = MODEL_VERSION


def category_for(doc_type: str) -> str:
    return _CATEGORY_BY_DOC_TYPE.get(doc_type, "other")


def _page_date(text: str) -> str | None:
    dates = extract_document_dates(text)
    labelled = (
        dates.get("collection_date")
        or dates.get("report_date")
        or dates.get("doc_date")
        or dates.get("registration_date")
    )
    if labelled:
        return labelled
    parsed = parse_date(text)
    return parsed.isoformat() if parsed else None


def _same_facility(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    return re.sub(r"[^a-z0-9]+", "", left.lower()) == re.sub(
        r"[^a-z0-9]+", "", right.lower()
    )


def build_reports(
    page_texts: list[str],
    doc_type: str,
    *,
    fallback_facility: str | None = None,
) -> list[ReportDraft]:
    """Group consecutive pages by date and facility. No layout rules."""
    category = category_for(doc_type)
    reports: list[ReportDraft] = []
    current: ReportDraft | None = None

    for page_number, text in enumerate(page_texts, start=1):
        page_date = _page_date(text)
        page_facility = extract_document_identifiers(text).get("facility_name")
        if page_facility is None and not reports:
            page_facility = fallback_facility

        if current is not None and (
            (page_date is None or page_date == current.report_date)
            and _same_facility(page_facility, current.facility_name)
        ):
            current.page_end = page_number
            if current.facility_name is None and page_facility:
                current.facility_name = page_facility
                current.title = page_facility
            continue

        status = "review" if page_date is None or category == "other" else "auto"
        reason = None
        if page_date is None:
            reason = "Report date not detected; review required."
        elif category == "other":
            reason = "Report category is uncertain; review required."

        facility = page_facility
        current = ReportDraft(
            id=str(uuid.uuid4()),
            page_start=page_number,
            page_end=page_number,
            report_date=page_date,
            category=category,
            report_type=doc_type,
            facility_name=facility,
            title=facility or _CATEGORY_TITLES[category],
            summary=None,
            status=status,
            reason=reason,
        )
        reports.append(current)

    return reports


def attach_summaries(reports: list[ReportDraft], sections) -> None:
    """Use the first impression, else findings, as the report-level summary."""
    for report in reports:
        in_range = [
            section
            for section in sections
            if report.page_start <= section.page <= report.page_end
        ]
        preferred = next(
            (section for section in in_range if section.section_name == "impression"),
            None,
        )
        if preferred is None:
            preferred = next(
                (section for section in in_range if section.section_name == "findings"),
                None,
            )
        if preferred is None and in_range:
            preferred = in_range[0]
        if preferred is not None:
            report.summary = preferred.text.strip()[:1000] or None


def iter_reports(page_texts, doc_type, *, fallback_facility=None, sections_for_page=None):
    """Only the current logical report and three possible summary choices stay in memory."""
    current = None
    choices = {}
    category = category_for(doc_type)
    for page_number, page_text in enumerate(page_texts, start=1):
        page_date = _page_date(page_text)
        page_facility = extract_document_identifiers(page_text).get("facility_name")
        if page_facility is None and page_number == 1:
            page_facility = fallback_facility
        if current is not None and ((page_date is None or page_date == current.report_date)
                                    and _same_facility(page_facility, current.facility_name)):
            current.page_end = page_number
            if current.facility_name is None and page_facility:
                current.facility_name = page_facility
                current.title = page_facility
        else:
            if current is not None:
                chosen = choices.get("impression") or choices.get("findings") or choices.get("first")
                if chosen is not None:
                    current.summary = chosen.text.strip()[:1000] or None
                yield current
            reason = "Report date not detected; review required." if page_date is None else (
                "Report category is uncertain; review required." if category == "other" else None)
            current = ReportDraft(id=str(uuid.uuid4()), category=category, report_type=doc_type,
                                  report_date=page_date, facility_name=page_facility,
                                  title=page_facility or _CATEGORY_TITLES[category], summary=None,
                                  page_start=page_number, page_end=page_number,
                                  status="review" if page_date is None or category == "other" else "auto", reason=reason)
            choices = {}
        if sections_for_page is not None:
            for section in sections_for_page(page_number):
                choices.setdefault("first", section)
                if section.section_name in {"impression", "findings"}:
                    choices.setdefault(section.section_name, section)
    if current is not None:
        chosen = choices.get("impression") or choices.get("findings") or choices.get("first")
        if chosen is not None:
            current.summary = chosen.text.strip()[:1000] or None
        yield current


def normalise_label(label: str | None) -> str | None:
    normalised = re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()
    return normalised or None


def fact_type_for(field) -> str:
    clinical = getattr(field, "clinical_metadata", None)
    if clinical:
        return {"lab_result": "lab", "diagnosis_allergy": "diagnosis", "procedure_surgery": "note",
                "imaging_radiology": "imaging_finding", "directive_followup": "recommendation"}.get(clinical["category"], "note")
    if field.analyte_id:
        return "lab"
    label = (field.label_raw or "").lower()
    for marker, fact_type in _FACT_TYPES.items():
        if marker in label:
            return fact_type
    if field.value_num is not None:
        return "measurement"
    return "note"

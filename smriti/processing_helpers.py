"""Complete-document rules over bounded page reads; clinical publication happens later."""

from __future__ import annotations

from datetime import date

from sqlalchemy import text

from smriti import engines
from smriti.bounded_text import document_lines
from smriti.candidates import Candidates
from smriti.classify import classify_pages
from smriti.db import create_db_engine
from smriti.directives import iter_directives
from smriti.extract import ExtractedField, extraction_candidates
from smriti.job_progress import progress_transaction, record_progress
from smriti.metadata import extract_metadata_lines
from smriti.preparation import _settings, page_metadata
from smriti.processing_store import identity, page_texts, page_words, read_page, submission, update_processing
from smriti.prose import extract_prose_with_grounding
from smriti.reports import iter_reports
from smriti.spool import SpoolError, _now


def _progress(engine, job_id, event, **fields):
    with progress_transaction(engine) as conn:
        record_progress(conn, job_id, event, **fields)


def rules_target(context, report):
    settings = _settings(context)
    engine = create_db_engine(settings.db_path).execution_options(progress_report=report)
    try:
        row = submission(engine, context["job_id"])
        update_processing(engine, row["job_id"], rules_ready=False, final_ready=False)
        _progress(engine, row["job_id"], "ocr_finished", completed=row["page_count"], total=row["page_count"])
        _progress(engine, row["job_id"], "classifying")
        classification = classify_pages(page_texts(settings, row))
        doc_type = classification.doc_type if classification.confidence >= .5 else "other"
        metadata = extract_metadata_lines(document_lines(page_texts(settings, row), max_line_bytes=settings.max_page_text_bytes))
        _progress(engine, row["job_id"], "classified")
        field_engine = "text_layer"
        for page in range(1, row["page_count"] + 1):
            data = read_page(settings, row, "ocr", page)
            if data["source"] == "ocr":
                field_engine = data["engine"]
        field_engine = engines.field_engine(field_engine)
        _progress(engine, row["job_id"], "extracting", model=field_engine)
        with Candidates(engine, settings, row["job_id"], identity(row), create=True) as scratch:
            scratch.reset()
            excluded = 0
            for kind, candidate in extraction_candidates(page_words(settings, row), doc_type, row["capture_type"], engine=field_engine):
                if kind == "field":
                    if candidate.value_num is not None and page_metadata(settings, row["job_id"], candidate.page)["capture_type"] == "handwritten":
                        excluded += 1
                        continue
                    dedup = (candidate.analyte_id or candidate.label_raw.lower(), candidate.value_num or "", candidate.page)
                    key = (candidate.analyte_id or candidate.label_raw).strip().lower()
                else:
                    dedup = (candidate.brand_raw.lower(), candidate.dose, candidate.freq)
                    key = None
                scratch.add(kind, candidate, dedup=dedup, match_key=key)
            if excluded:
                _progress(engine, row["job_id"], "handwriting_filtered", count=excluded)
            if doc_type in {"ct", "mri", "xray", "pathology", "discharge_summary", "radiology", "other"}:
                for page in range(1, row["page_count"] + 1):
                    data = read_page(settings, row, "ocr", page)
                    for section in extract_prose_with_grounding(data["text"], page=page, words=data["words"]):
                        scratch.add("section", section)
                        scratch.add("prose", ExtractedField(
                            analyte_id=None, label_raw=section.title, value_num=None, value_text=section.text,
                            unit_raw=None, ref_low=None, ref_high=None, flag_printed=None, bbox=section.bbox,
                            page=section.page, confidence=round(section.grounding_score, 2), mapping_rule="unresolved",
                            engine=field_engine, reason=f"Grounded prose extraction (grounding score: {section.grounding_score:.2f}); review required.",
                            evidence_quote=section.text))
                    report("checkpoint", page=page, count=1)
            for draft in iter_reports(page_texts(settings, row), doc_type, fallback_facility=metadata.get("facility_name"), sections_for_page=scratch.sections):
                scratch.add_report(draft)
            if row["capture_type"] == "printed":
                for directive in iter_directives(document_lines(page_texts(settings, row), keepends=True, max_line_bytes=settings.max_page_text_bytes),
                                                 collection_date=metadata.get("collection_date"), doc_date=metadata.get("doc_date"),
                                                 as_of=date.fromisoformat(context.get("now", _now())[:10])):
                    scratch.add("directive", directive)
        update_processing(engine, row["job_id"], rules_ready=True, doc_type=doc_type,
                          confidence=classification.confidence, metadata=metadata, field_engine=field_engine)
    finally:
        engine.dispose()


def verification_target(context, report):
    from smriti.worker import cross_check_extractions

    settings = _settings(context)
    engine = create_db_engine(settings.db_path).execution_options(progress_report=report)
    try:
        row = submission(engine, context["job_id"])
        if not row["manifest"].get("processing", {}).get("rules_ready"):
            raise SpoolError("prepared_artifact_invalid")
        printed = row["capture_type"] == "printed"
        verify = settings.vlm_enabled
        with Candidates(engine, settings, row["job_id"], identity(row)) as scratch:
            scratch.clear_checked()
            unavailable = 0
            if verify:
                for page in range(1, row["page_count"] + 1):
                    data = read_page(settings, row, "qwen", page)
                    if data is None:
                        raise SpoolError("prepared_artifact_invalid")
                    unavailable += data.get("outcome") == "unavailable"
                    for item in data["fields"]:
                        field = ExtractedField(**item)
                        key = (field.analyte_id or field.label_raw).strip().lower()
                        scratch.add("vlm", field, dedup=(key, page), match_key=key, replace=True)
                # Handwritten readings stay model-only: every observation is persisted for review.
                _progress(engine, row["job_id"], "cross_check" if printed else "handwritten_mode")
            else:
                _progress(engine, row["job_id"], "qwen_disabled")
            for sequence, item, _ in scratch.rows("field"):
                field = ExtractedField(**item)
                if row["capture_type"] == "printed":
                    key = (field.analyte_id or field.label_raw).strip().lower()
                    matched = scratch.matching("vlm", field.page, key)
                    field = cross_check_extractions([field], [ExtractedField(**matched)] if matched else [], [])[0]
                scratch.add("checked", field, dedup=("ocr", sequence))
            if verify:
                class Pages:
                    def __len__(self):
                        return row["page_count"]

                    def __getitem__(self, index):
                        return read_page(settings, row, "ocr", index + 1)["words"]

                for sequence, item, _ in scratch.rows("vlm"):
                    field = ExtractedField(**item)
                    key = (field.analyte_id or field.label_raw).strip().lower()
                    if scratch.matching("field", field.page, key) is None:
                        if printed:
                            field = cross_check_extractions([], [field], Pages())[0]
                        scratch.add("checked", field, dedup=("vlm", sequence))
                if printed:
                    _progress(engine, row["job_id"], "cross_checked", count=scratch.count("checked"))
                    if not scratch.count("vlm"):
                        _progress(engine, row["job_id"], "verification_unavailable")
                    elif unavailable:
                        _progress(engine, row["job_id"], "verification_partial")
            scratch.associate_reports()
        update_processing(engine, row["job_id"], final_ready=True)
        report("checkpoint", count=1)
    finally:
        engine.dispose()

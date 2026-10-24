"""Single background worker: local OCR, classification, and rule extraction."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from smriti import engines, text_layer
from smriti.classify import classify_text
from smriti.config import Settings
from smriti.directives import extract_directives
from smriti.extract import extract_document, words_to_text
from smriti.metadata import extract_document_dates, extract_metadata
from smriti.ocr import OcrWord, get_ocr_engine

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def recover_orphaned_jobs(engine: Engine) -> int:
    """Reset any jobs left in 'running' by a server restart or crash."""
    with engine.begin() as conn:
        res = conn.execute(
            text(
                """
                UPDATE jobs
                SET state = 'queued'
                WHERE state = 'running'
                """
            )
        )
        count = res.rowcount
        if count > 0:
            conn.execute(
                text(
                    """
                    UPDATE document
                    SET status = 'queued'
                    WHERE status = 'processing'
                      AND id IN (SELECT document_id FROM jobs WHERE state = 'queued')
                    """
                )
            )
        return count


def claim_job(engine: Engine) -> dict | None:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT j.id, j.document_id, j.total
                FROM jobs j
                WHERE j.state = 'queued'
                ORDER BY j.ts
                LIMIT 1
                """
            )
        ).first()
        if row is None:
            return None
        updated = conn.execute(
            text("UPDATE jobs SET state = 'running' WHERE id = :id AND state = 'queued'"),
            {"id": row[0]},
        )
        if updated.rowcount == 0:
            return None
        conn.execute(
            text("UPDATE document SET status = 'processing' WHERE id = :id"),
            {"id": row[1]},
        )
        logger.info(
            "[worker] Claimed job %s for document %s (%d pages total)",
            row[0],
            row[1],
            row[2],
        )
        return {"id": row[0], "document_id": row[1], "total": row[2]}


def _page_path(settings: Settings, image_path: str, page: int) -> Path:
    root = settings.upload_dir.resolve()
    target = (root / image_path / f"page_{page}.webp").resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Page image is outside the upload directory.") from exc
    if not target.is_file():
        raise RuntimeError(f"Page image {page} is missing.")
    return target


def _insert_extraction(
    conn,
    document_id: str,
    patient_id: str,
    extraction,
    directives,
    now: str,
    provenance: dict[int, tuple[str, str | None]],
) -> None:
    conn.execute(
        text("DELETE FROM observation WHERE document_id = :id"),
        {"id": document_id},
    )
    conn.execute(
        text("DELETE FROM medication WHERE source_doc_id = :id"),
        {"id": document_id},
    )
    conn.execute(
        text("DELETE FROM directive WHERE document_id = :id"),
        {"id": document_id},
    )
    for field in extraction.fields:
        source, model_version = provenance.get(field.page, (None, None))
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, label_raw, value_num, value_text,
                     unit_raw, unit_norm, ref_low, ref_high, flag_printed, bbox_json,
                     page, engine, confidence, status, reason, mapping_rule, source,
                     model_version, created_at)
                VALUES
                    (:id, :document_id, :analyte_id, :label_raw, :value_num, :value_text,
                     :unit_raw, NULL, :ref_low, :ref_high, :flag_printed, :bbox_json,
                     :page, :engine, :confidence, 'review', :reason, :mapping_rule,
                     :source, :model_version, :created_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "analyte_id": field.analyte_id,
                "label_raw": field.label_raw,
                "value_num": field.value_num,
                "value_text": field.value_text,
                "unit_raw": field.unit_raw,
                "ref_low": field.ref_low,
                "ref_high": field.ref_high,
                "flag_printed": field.flag_printed,
                "bbox_json": json.dumps(field.bbox),
                "page": field.page,
                "engine": field.engine,
                "confidence": field.confidence,
                "reason": field.reason or "Extracted locally; review required.",
                "mapping_rule": field.mapping_rule,
                "source": source,
                "model_version": model_version,
                "created_at": now,
            },
        )
    for medication in extraction.medications:
        conn.execute(
            text(
                """
                INSERT INTO medication
                    (id, patient_id, brand_raw, salt, dose, freq, start_date,
                     status, reported_at, source_doc_id)
                VALUES
                    (:id, :patient_id, :brand_raw, NULL, :dose, :freq, NULL,
                     'prescribed', :reported_at, :source_doc_id)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "patient_id": patient_id,
                "brand_raw": medication.brand_raw,
                "dose": medication.dose,
                "freq": medication.freq,
                "reported_at": now,
                "source_doc_id": document_id,
            },
        )
    for directive in directives:
        conn.execute(
            text(
                """
                INSERT INTO directive
                    (id, document_id, span_text, span_start, span_end, action_type,
                     timing_type, time_value, time_unit, anchor_event, condition_text,
                     target, anchor_date, due_date, state)
                VALUES
                    (:id, :document_id, :span_text, :span_start, :span_end, :action_type,
                     :timing_type, :time_value, :time_unit, :anchor_event, :condition_text,
                     :target, :anchor_date, :due_date, :state)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "span_text": directive.span_text,
                "span_start": directive.span_start,
                "span_end": directive.span_end,
                "action_type": directive.action_type,
                "timing_type": directive.timing_type,
                "time_value": directive.time_value,
                "time_unit": directive.time_unit,
                "anchor_event": directive.anchor_event,
                "condition_text": directive.condition_text,
                "target": directive.target,
                "anchor_date": (
                    directive.anchor_date.isoformat() if directive.anchor_date else None
                ),
                "due_date": directive.due_date.isoformat() if directive.due_date else None,
                "state": directive.state,
            },
        )


def process_job(
    engine: Engine,
    settings: Settings,
    job: dict,
    *,
    ocr_engine=None,
) -> None:
    document_id = job["document_id"]
    with engine.connect() as conn:
        document = conn.execute(
            text(
                """
                SELECT patient_id, image_path, capture_type, page_count
                FROM document WHERE id = :id
                """
            ),
            {"id": document_id},
        ).first()
    if document is None:
        raise RuntimeError(f"Unknown document {document_id}.")
    patient_id, image_path, capture_type, page_count = document
    engine_ocr = ocr_engine or get_ocr_engine(
        settings.ocr_det_model, settings.ocr_rec_model
    )
    engine_name = getattr(engine_ocr, "name", "paddle")

    t_start = time.time()
    logger.info(
        "[worker] Job %s: starting OCR extraction for document %s (%d pages, capture_type='%s', engine='%s')",
        job["id"],
        document_id,
        page_count,
        capture_type,
        engine_name,
    )

    pages: list[list[OcrWord]] = []
    texts: list[str] = []
    text_layer_pages = 0
    provenance: dict[int, tuple[str, str | None]] = {}
    now = _now()
    for page in range(1, page_count + 1):
        page_path = _page_path(settings, image_path, page)
        cached = text_layer.words_path(page_path)
        t_page = time.time()
        if cached.is_file():
            words = text_layer.load_words(cached)
            page_engine = "text_layer"
            page_source = "text_layer"
            page_model = text_layer.MODEL_VERSION
            text_layer_pages += 1
            logger.info(
                "[worker] Job %s: page %d/%d read from the PDF text layer (%d words)",
                job["id"],
                page,
                page_count,
                len(words),
            )
        else:
            logger.info(
                "[worker] Job %s: running OCR on page %d/%d...",
                job["id"],
                page,
                page_count,
            )
            words = engine_ocr.read(page_path)
            page_engine = engine_name
            page_source = "ocr"
            page_model = engine_name
            logger.info(
                "[worker] Job %s: page %d/%d OCR complete in %.1fs (%d words detected)",
                job["id"],
                page,
                page_count,
                time.time() - t_page,
                len(words),
            )
        pages.append(words)
        provenance[page] = (page_source, page_model)
        page_text = words_to_text(words)
        texts.append(page_text)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO page_text
                        (document_id, page, text, engine, source, model_version,
                         created_at)
                    VALUES
                        (:document_id, :page, :text, :engine, :source,
                         :model_version, :created_at)
                    ON CONFLICT(document_id, page) DO UPDATE SET
                        text = excluded.text,
                        engine = excluded.engine,
                        source = excluded.source,
                        model_version = excluded.model_version,
                        created_at = excluded.created_at
                    """
                ),
                {
                    "document_id": document_id,
                    "page": page,
                    "text": page_text,
                    "engine": page_engine,
                    "source": page_source,
                    "model_version": page_model,
                    "created_at": now,
                },
            )
            conn.execute(
                text("UPDATE jobs SET page = :page WHERE id = :id"),
                {"page": page, "id": job["id"]},
            )

    combined_text = "\n".join(texts)
    classification = classify_text(combined_text)
    doc_type = classification.doc_type
    if classification.confidence < 0.5 and doc_type != "other":
        doc_type = "other"
    logger.info(
        "[worker] Job %s: classified text as doc_type='%s' (confidence: %.2f)",
        job["id"],
        doc_type,
        classification.confidence,
    )

    # `engine` is the composite pipeline identity; `source` is recorded per page.
    field_engine = "text_layer" if text_layer_pages == page_count else engine_name
    extraction = extract_document(
        pages, doc_type, capture_type, engine=engines.field_engine(field_engine)
    )
    metadata = extract_metadata(combined_text)
    # Handwritten content is never auto-accepted, including follow-up advice.
    directives = (
        extract_directives(
            combined_text,
            collection_date=metadata.get("collection_date"),
            doc_date=metadata.get("doc_date"),
            as_of=date.fromisoformat(now[:10]),
        )
        if capture_type == "printed"
        else []
    )
    logger.info(
        "[worker] Job %s: extracted %d observation(s), %d medication(s), %d directive(s) (metadata=%s)",
        job["id"],
        len(extraction.fields),
        len(extraction.medications),
        len(directives),
        metadata,
    )

    with engine.begin() as conn:
        _insert_extraction(
            conn, document_id, patient_id, extraction, directives, now, provenance
        )
        conn.execute(
            text(
                """
                UPDATE document
                SET doc_type = :doc_type, doc_type_confidence = :confidence,
                    status = 'done', processed_at = :now,
                    collection_date = COALESCE(collection_date, :collection_date),
                    registration_date = COALESCE(registration_date, :registration_date),
                    report_date = COALESCE(report_date, :report_date),
                    doc_date = COALESCE(doc_date, :doc_date),
                    patient_uhid = COALESCE(patient_uhid, :patient_uhid),
                    doctor_reg_no = COALESCE(doctor_reg_no, :doctor_reg_no),
                    facility_name = COALESCE(facility_name, :facility_name),
                    lab_name = COALESCE(lab_name, :facility_name)
                WHERE id = :id
                """
            ),
            {
                "doc_type": doc_type,
                "confidence": classification.confidence,
                "collection_date": metadata.get("collection_date"),
                "registration_date": metadata.get("registration_date"),
                "report_date": metadata.get("report_date"),
                "doc_date": metadata.get("doc_date"),
                "patient_uhid": metadata.get("patient_uhid"),
                "doctor_reg_no": metadata.get("doctor_reg_no"),
                "facility_name": metadata.get("facility_name"),
                "now": now,
                "id": document_id,
            },
        )
        conn.execute(
            text(
                "UPDATE jobs SET state = 'done', page = total, error = NULL WHERE id = :id"
            ),
            {"id": job["id"]},
        )
    logger.info(
        "[worker] Job %s: document %s completed in %.1fs total",
        job["id"],
        document_id,
        time.time() - t_start,
    )


def process_next(engine: Engine, settings: Settings, *, ocr_engine=None) -> bool:
    job = claim_job(engine)
    if job is None:
        return False
    try:
        process_job(engine, settings, job, ocr_engine=ocr_engine)
    except Exception as exc:
        logger.exception("Document extraction failed for job %s", job["id"])
        message = str(exc)[:500] or exc.__class__.__name__
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE jobs SET state = 'failed', error = :error WHERE id = :id"),
                {"error": message, "id": job["id"]},
            )
            conn.execute(
                text(
                    "UPDATE document SET status = 'failed', processed_at = :now "
                    "WHERE id = :id"
                ),
                {"now": _now(), "id": job["document_id"]},
            )
    return True


def _loop(engine: Engine, settings: Settings, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            worked = process_next(engine, settings)
        except Exception:
            logger.exception("Worker loop failed")
            worked = False
        if not worked:
            stop.wait(settings.worker_poll_seconds)


def start_worker(
    engine: Engine, settings: Settings
) -> tuple[threading.Event, threading.Thread] | None:
    if not settings.worker_enabled:
        return None
    recovered = recover_orphaned_jobs(engine)
    if recovered > 0:
        logger.warning(
            "[worker] Recovered %d interrupted job(s) from previous run; re-queued for processing.",
            recovered,
        )
    logger.info(
        "[worker] Background OCR worker started (polling every %ss)",
        settings.worker_poll_seconds,
    )
    stop = threading.Event()
    thread = threading.Thread(
        target=_loop,
        args=(engine, settings, stop),
        name="smriti-worker",
        daemon=True,
    )
    thread.start()
    return stop, thread

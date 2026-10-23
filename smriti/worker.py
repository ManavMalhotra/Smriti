"""Single background worker: local OCR, classification, and rule extraction."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from smriti.classify import classify_text
from smriti.config import Settings
from smriti.extract import extract_document, words_to_text
from smriti.ocr import OcrWord, get_ocr_engine

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _insert_extraction(conn, document_id: str, patient_id: str, extraction, now: str) -> None:
    conn.execute(
        text("DELETE FROM observation WHERE document_id = :id"),
        {"id": document_id},
    )
    conn.execute(
        text("DELETE FROM medication WHERE source_doc_id = :id"),
        {"id": document_id},
    )
    for field in extraction.fields:
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, label_raw, value_num, value_text,
                     unit_raw, unit_norm, ref_low, ref_high, flag_printed, bbox_json,
                     page, engine, confidence, status, reason, mapping_rule, created_at)
                VALUES
                    (:id, :document_id, :analyte_id, :label_raw, :value_num, :value_text,
                     :unit_raw, NULL, :ref_low, :ref_high, :flag_printed, :bbox_json,
                     :page, :engine, :confidence, 'review', :reason, :mapping_rule, :created_at)
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
                "engine": "paddle+local-rules-v1",
                "confidence": field.confidence,
                "reason": "Extracted locally; review required.",
                "mapping_rule": field.mapping_rule,
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

    pages: list[list[OcrWord]] = []
    texts: list[str] = []
    now = _now()
    for page in range(1, page_count + 1):
        words = engine_ocr.read(_page_path(settings, image_path, page))
        pages.append(words)
        page_text = words_to_text(words)
        texts.append(page_text)
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO page_text (document_id, page, text, engine, created_at)
                    VALUES (:document_id, :page, :text, :engine, :created_at)
                    ON CONFLICT(document_id, page) DO UPDATE SET
                        text = excluded.text,
                        engine = excluded.engine,
                        created_at = excluded.created_at
                    """
                ),
                {
                    "document_id": document_id,
                    "page": page,
                    "text": page_text,
                    "engine": engine_name,
                    "created_at": now,
                },
            )
            conn.execute(
                text("UPDATE jobs SET page = :page WHERE id = :id"),
                {"page": page, "id": job["id"]},
            )

    classification = classify_text("\n".join(texts))
    doc_type = classification.doc_type
    if classification.confidence < 0.5 and doc_type != "other":
        doc_type = "other"
    extraction = extract_document(pages, doc_type, capture_type)

    with engine.begin() as conn:
        _insert_extraction(conn, document_id, patient_id, extraction, now)
        conn.execute(
            text(
                """
                UPDATE document
                SET doc_type = :doc_type, doc_type_confidence = :confidence,
                    status = 'done', processed_at = :now
                WHERE id = :id
                """
            ),
            {
                "doc_type": doc_type,
                "confidence": classification.confidence,
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
    stop = threading.Event()
    thread = threading.Thread(
        target=_loop,
        args=(engine, settings, stop),
        name="smriti-worker",
        daemon=True,
    )
    thread.start()
    return stop, thread

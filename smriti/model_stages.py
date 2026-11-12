"""Spawn targets: lazy CPU OCR, separately disposable fallback, then owned Qwen windows."""

from __future__ import annotations

import json
import hashlib
import time
import base64
import re
import gc
import uuid
from dataclasses import asdict

import psutil
from sqlalchemy import text

from smriti.db import create_db_engine
from smriti.job_progress import progress_transaction, record_progress
from smriti.output_quota import bounded_bytes
from smriti.preparation import _settings, page_metadata
from smriti.processing_store import read_page, save_page, submission, validate_source, validate_words
from smriti.spool import SpoolError


def prepare_cloud_pages(engine, settings, row, scratch, doc_type):
    """Keep a private local preview and editable mask proposals in quota-accounted scratch."""
    if not settings.gemini_api_key or settings.demo:
        return
    from PIL import Image
    from smriti.candidates import MaskReviewPage
    from smriti.preprocess import discover_pii_tokens, encode_preview, propose_pii_masks, to_bgr

    with engine.connect() as conn:
        cloud_requested = conn.execute(text("""SELECT 1 FROM consent WHERE document_id = :id
            AND scope = 'local_plus_projection' AND revoked_at IS NULL"""), {"id": row["document_id"]}).first()
    if not cloud_requested:
        return
    tokens = set()
    for page in range(1, row["page_count"] + 1):
        data = read_page(settings, row, "ocr", page)
        tokens.update(discover_pii_tokens(data["words"]))
    for page in range(1, row["page_count"] + 1):
        data = read_page(settings, row, "ocr", page)
        validate_source(settings, row, page)
        with Image.open(settings.upload_dir / row["image_path"] / f"page_{page}.webp") as image:
            bgr = to_bgr(image)
            masks = propose_pii_masks(data["words"], bgr.shape[1], bgr.shape[0], tokens, bgr)
            jpeg = encode_preview(bgr)
        scratch.add("redaction", MaskReviewPage(page, base64.b64encode(jpeg).decode(), hashlib.sha256(jpeg).hexdigest(), masks),
                    dedup=page, match_key=str(page))
        del bgr, jpeg
        gc.collect()
    if scratch.count("redaction"):
        from smriti.spool import _now
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO cloud_consent (document_id, status, updated_at) VALUES (:id, 'awaiting', :now) ON CONFLICT DO NOTHING"),
                         {"id": row["document_id"], "now": _now()})
        _progress(engine, row["job_id"], "awaiting_cloud_consent")


def extract_approved_cloud_pages(engine, settings, row, scratch):
    from dataclasses import replace
    from PIL import Image
    from smriti.candidates import Candidate
    from smriti.preprocess import apply_pii_masks, to_bgr
    from smriti.spool import _now
    from smriti.vlm import extract_window_with_gemini

    with engine.begin() as conn:
        consent = conn.execute(text("""SELECT cc.status, cc.extra_boxes_json FROM cloud_consent cc
            JOIN consent c ON c.document_id = cc.document_id
            WHERE cc.document_id = :id AND c.scope = 'local_plus_projection' AND c.revoked_at IS NULL"""), {"id": row["document_id"]}).first()
        if not consent or consent[0] != "approved" or not settings.gemini_api_key or settings.demo:
            return
        # Claim before egress; interrupted calls are never automatically sent again.
        claimed = conn.execute(text("""UPDATE cloud_consent SET status = 'processing', updated_at = :now
            WHERE document_id = :id AND status = 'approved'"""),
            {"id": row["document_id"], "now": _now()})
        if claimed.rowcount != 1:
            return
    boxes = json.loads(consent[1])
    failed = False
    _progress(engine, row["job_id"], "cloud_reading", model="gemini-3.8-flash-high")
    for offset in range(0, scratch.count("redaction"), settings.max_workset_pages):
        submission(engine, row["job_id"])  # Recheck owner/local consent before each network window.
        previews = list(scratch.range_rows("redaction", offset, settings.max_workset_pages))
        images, pages = [], []
        for preview in previews:
            validate_source(settings, row, preview["page"])
            jpeg = base64.b64decode(preview["jpeg_base64"], validate=True)
            if hashlib.sha256(jpeg).hexdigest() != preview["sha256"]:
                raise SpoolError("prepared_artifact_invalid")
            with Image.open(settings.upload_dir / row["image_path"] / f"page_{preview['page']}.webp") as image:
                jpeg = apply_pii_masks(to_bgr(image), boxes.get(str(preview["page"]), []), preview["page"])
            images.append(jpeg)
            pages.append(preview["page"])
        digest = hashlib.sha256(b"".join(images)).hexdigest()
        outcomes = []
        fields = extract_window_with_gemini(images, pages, "", settings=settings, on_outcome=lambda *args: outcomes.append(args))
        if outcomes:
            last = outcomes[-1]
            outcome = last[0] if len(last) > 0 else "failed"
            reason = last[1] if len(last) > 1 else None
        else:
            outcome, reason = "failed", "unknown"
        failed |= outcome == "failed"
        with engine.begin() as conn:
            conn.execute(text("""INSERT INTO egress (id, document_id, payload_sha256, model_id, prompt_version, schema_version, outcome, reason, ts)
                VALUES (:id, :doc, :sha, :model, 'redacted-clinical@1', 'window@1', :outcome, :reason, :now)"""),
                {"id": str(uuid.uuid4()), "doc": row["document_id"], "sha": digest, "model": settings.gemini_model_id,
                 "outcome": outcome, "reason": reason, "now": _now()})
        for field in fields:
            metadata = field.clinical_metadata
            key = (metadata["event_date"], field.label_raw.casefold(), field.value_text)
            existing = scratch.deduplicated("cloud", key)
            if existing:
                anchors = existing["clinical_metadata"]["source_anchors"]
                for anchor in metadata["source_anchors"]:
                    if anchor not in anchors:
                        anchors.append(anchor)
                field = Candidate(**existing)
            if row["capture_type"] == "handwritten" and field.value_num is not None:
                field = replace(field, value_num=None, reason="Handwritten numerical lab value withheld; review source.")
            scratch.add("cloud", field, dedup=key, match_key=field.analyte_id or field.label_raw.casefold(), replace=True)
        del images, previews, fields
        gc.collect()
    with engine.begin() as conn:
        conn.execute(text("UPDATE cloud_consent SET status = :status, updated_at = :now WHERE document_id = :id"),
                     {"id": row["document_id"], "status": "failed" if failed else "completed", "now": _now()})
    if failed:
        _progress(engine, row["job_id"], "cloud_failed")


def _members(context, settings):
    members = context["members"]
    if not isinstance(members, list) or not 1 <= len(members) <= settings.max_batch_submissions:
        raise SpoolError("prepared_artifact_invalid")
    total = 0
    for member in members:
        start, end = member["start"], member["end"]
        if type(start) is not int or type(end) is not int or not 1 <= start <= end:
            raise SpoolError("prepared_artifact_invalid")
        total += end - start + 1
    if total > settings.max_workset_pages:
        raise SpoolError("prepared_artifact_invalid")
    return members


def _progress(engine, job_id, event, **fields):
    with progress_transaction(engine) as conn:
        record_progress(conn, job_id, event, **fields)


def ocr_target(context, report):
    from smriti.extract import words_to_text
    from smriti.ocr import OcrWord, PaddleOcrEngine, RapidOcrOnnxEngine
    from smriti import text_layer

    settings = _settings(context)
    if context.get("backend") not in {"rapid", "paddle"}:
        raise SpoolError("prepared_artifact_invalid")
    engine = create_db_engine(settings.db_path).execution_options(progress_report=report)
    ocr = None
    try:
        for member in _members(context, settings):
            row = submission(engine, member["job_id"])
            if member["end"] > row["page_count"]:
                raise SpoolError("prepared_artifact_invalid")
            for page in range(member["start"], member["end"] + 1):
                submission(engine, row["job_id"])
                report("page_started", page=page)
                started = time.monotonic()
                data = read_page(settings, row, "ocr", page)
                if data is not None:
                    _progress(engine, row["job_id"], "cache_hit", page=page, completed=page, total=row["page_count"], model=data["model_version"])
                else:
                    metadata = validate_source(settings, row, page)
                    root = settings.upload_dir / row["image_path"]
                    if metadata["words_sha256"]:
                        _progress(engine, row["job_id"], "text_layer", page=page, total=row["page_count"], model=text_layer.MODEL_VERSION)
                        payload = bounded_bytes(root / f"page_{page}.words.json", settings.max_artifact_bytes)
                        if hashlib.sha256(payload).hexdigest() != metadata["words_sha256"]:
                            raise SpoolError("prepared_artifact_invalid")
                        data = json.loads(payload)
                        words = [OcrWord(**item) for item in data["words"]]
                        source, model = "text_layer", text_layer.MODEL_VERSION
                        page_engine = "text_layer"
                    else:
                        if ocr is None:
                            ocr = (PaddleOcrEngine(settings.ocr_det_model, settings.ocr_rec_model)
                                   if context["backend"] == "paddle" else RapidOcrOnnxEngine())
                            _progress(engine, row["job_id"], "ocr_loading", model=ocr.name, page=page,
                                      completed=page - 1, total=row["page_count"])
                            try:
                                ocr._load()
                            except Exception:
                                raise SpoolError("ocr_unavailable" if context["backend"] == "paddle" else "ocr_initialization_failed") from None
                            report("ready")
                        _progress(engine, row["job_id"], "ocr_reading", page=page, completed=page - 1,
                                  total=row["page_count"], model=ocr.name)
                        try:
                            words = ocr.read(root / f"page_{page}.webp", debug=True)
                        except Exception:
                            raise SpoolError("ocr_unavailable") from None
                        source, model, page_engine = "ocr", ocr.name, ocr.name
                    validate_words(settings, words)
                    page_text = words_to_text(words)
                    if len(page_text.encode("utf-8")) > settings.max_page_text_bytes:
                        raise SpoolError("capacity_exhausted")
                    save_page(engine, settings, row, "ocr", page, words=[asdict(word) for word in words],
                              text=page_text, source=source, model_version=model, engine=page_engine)
                    _progress(engine, row["job_id"], "page_read", page=page, completed=page, total=row["page_count"],
                              model=model, count=len(words), duration=time.monotonic() - started)
                    del words
                    gc.collect()
                report("page_finished", page=page, count=1)
                gc.collect()
    except Exception as exc:
        if "member" in locals():
            exc.job_id = member["job_id"]
        raise
    finally:
        engine.dispose()


def qwen_target(context, report):
    from smriti.vlm import VLM_ENGINE_NAME, VlmSession, extract_page_vlm, is_vlm_available

    settings = _settings(context)
    engine = create_db_engine(settings.db_path).execution_options(progress_report=report)
    session = None
    current_job = None
    current_page = None
    def lifecycle(event, **fields):
        if current_job is not None:
            _progress(engine, current_job, event, model=VLM_ENGINE_NAME, duration=fields.get("duration"),
                      error_type=fields.get("error_type"), page=current_page,
                      failed_stage="qwen" if event == "operation_failed" else None)
    try:
        for member in _members(context, settings):
            row = submission(engine, member["job_id"])
            current_job = row["job_id"]
            eligible = row["page_count"]
            completed = sum(read_page(settings, row, "qwen", page) is not None
                            for page in range(1, member["start"]))
            for page in range(member["start"], member["end"] + 1):
                current_page = page
                submission(engine, row["job_id"])
                if page > row["page_count"]:
                    raise SpoolError("prepared_artifact_invalid")
                validate_source(settings, row, page)
                cached = read_page(settings, row, "qwen", page)
                if cached is not None:
                    completed += 1
                    _progress(engine, row["job_id"], "qwen_unavailable_page" if cached.get("outcome") == "unavailable" else "qwen_page",
                              page=page, completed=completed, total=eligible, model=VLM_ENGINE_NAME)
                    continue
                from smriti.classify import is_boilerplate
                ocr_page = read_page(settings, row, "ocr", page)
                if ocr_page is None:
                    raise SpoolError("prepared_artifact_invalid")
                metadata = page_metadata(settings, row["job_id"], page)
                from smriti.handwriting import needs_page_review
                if needs_page_review(ocr_page["words"], metadata["capture_type"]):
                    save_page(engine, settings, row, "qwen", page, fields=[], model_version=VLM_ENGINE_NAME)
                    completed += 1
                    _progress(engine, row["job_id"], "qwen_unavailable_page", page=page, completed=completed,
                              total=eligible, model=VLM_ENGINE_NAME)
                    continue
                with engine.connect() as conn:
                    cloud_approved = conn.execute(text("SELECT status FROM cloud_consent WHERE document_id = :id"),
                                                  {"id": row["document_id"]}).scalar_one_or_none() == "approved"
                if cloud_approved:
                    from smriti.candidates import Candidates
                    from smriti.processing_store import identity
                    with Candidates(engine, settings, row["job_id"], identity(row)) as scratch:
                        cloud_page = scratch.matching("redaction", page, str(page)) is not None
                    if cloud_page:
                        save_page(engine, settings, row, "qwen", page, fields=[], model_version=VLM_ENGINE_NAME)
                        completed += 1
                        continue
                if ocr_page and is_boilerplate(ocr_page["text"]):
                    save_page(engine, settings, row, "qwen", page, fields=[], model_version=VLM_ENGINE_NAME)
                    completed += 1
                    continue
                if session is None:
                    if not is_vlm_available():
                        raise SpoolError("qwen_unavailable")
                    if psutil.virtual_memory().available < settings.vlm_min_available_bytes:
                        raise SpoolError("qwen_unavailable")
                    _progress(engine, row["job_id"], "qwen_loading", model=VLM_ENGINE_NAME)
                    session = VlmSession(timeout=settings.vlm_startup_seconds, on_event=lifecycle)
                    session.__enter__()
                    report("ready")
                report("page_started", page=page)
                started = time.monotonic()
                _progress(engine, row["job_id"], "qwen_reading", page=page, completed=completed, total=eligible, model=VLM_ENGINE_NAME)
                fields = extract_page_vlm(settings.upload_dir / row["image_path"] / f"page_{page}.webp", page,
                                           session=session, max_artifact_bytes=settings.max_artifact_bytes,
                                           request_seconds=settings.vlm_request_seconds, max_pixels=settings.max_pixels)
                save_page(engine, settings, row, "qwen", page, fields=[asdict(field) for field in fields],
                          model_version=VLM_ENGINE_NAME)
                completed += 1
                _progress(engine, row["job_id"], "qwen_page", page=page, completed=completed, total=eligible,
                          model=VLM_ENGINE_NAME, count=len(fields), duration=time.monotonic() - started)
                report("page_finished", page=page, count=1)
                del fields
                gc.collect()
    except Exception as exc:
        if "member" in locals():
            exc.job_id = member["job_id"]
        if current_job is not None:
            _progress(engine, current_job, "operation_failed", failed_stage="qwen", model=VLM_ENGINE_NAME,
                      page=current_page, error_type=type(exc).__name__, error_code=getattr(exc, "code", None),
                      http_status=getattr(exc, "http_status", None))
        raise
    finally:
        try:
            if session is not None:
                session.__exit__(None, None, None)
        finally:
            engine.dispose()

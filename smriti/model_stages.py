"""Spawn targets: lazy CPU OCR, separately disposable fallback, then owned Qwen windows."""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import asdict

import psutil
from sqlalchemy import text

from smriti.db import create_db_engine
from smriti.job_progress import progress_transaction, record_progress
from smriti.output_quota import bounded_bytes
from smriti.preparation import _settings, page_metadata
from smriti.processing_store import read_page, save_page, submission, validate_source, validate_words
from smriti.spool import SpoolError


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
                report("page_finished", page=page, count=1)
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

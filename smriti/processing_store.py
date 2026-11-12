"""Bounded processing artifacts and durable cleanup ownership for prepared submissions."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
from dataclasses import asdict

from sqlalchemy import text

from smriti.output_quota import bounded_bytes, release_output, write_reserved
from smriti.preparation import SQL_HEADROOM_BYTES, page_metadata
from smriti.private_paths import check_path, private_directory
from smriti.spool import SpoolError, _now, check_free_space

PROCESSING_VERSION = 1


def submission(engine, job_id, *, allow_terminal=False):
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise SpoolError("prepared_artifact_invalid")
    with engine.connect() as conn:
        row = conn.execute(text("""SELECT s.*, d.image_path, d.capture_type, d.page_count,
            j.state AS job_state, d.status AS document_status, c.revoked_at AS consent_revocation
            FROM submissions s JOIN document d ON d.id = s.document_id JOIN consent c ON c.document_id = d.id
            JOIN jobs j ON j.id = s.job_id WHERE s.job_id = :id AND s.state = 'promoted'"""), {"id": job_id}).mappings().first()
    if row is None or not allow_terminal and (row["job_state"] not in {"queued", "running"}
            or row["document_status"] not in {"queued", "processing"} or row["consent_revoked_at"] is not None or row["consent_revocation"] is not None):
        raise SpoolError("cancelled")
    row = dict(row)
    row["manifest"] = json.loads(row["preparation_manifest_json"])
    return row


def identity(row):
    return {"version": PROCESSING_VERSION, "job_id": row["job_id"], "document_id": row["document_id"],
            "source_hash": row["content_hash"], "preparation": row["manifest"]["identity"]}


def update_processing(engine, job_id, **changes):
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        row = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id AND state = 'promoted'"), {"id": job_id}).scalar_one_or_none()
        if row is None:
            raise SpoolError("cancelled")
        manifest = json.loads(row)
        processing = manifest.setdefault("processing", {"version": PROCESSING_VERSION})
        if processing["version"] != PROCESSING_VERSION:
            raise SpoolError("prepared_artifact_invalid")
        processing.update(changes)
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest, updated_at = :now WHERE job_id = :id"),
                     {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":")), "now": _now()})


def artifact_path(settings, job_id, stage, page):
    from smriti.candidates import candidate_path

    if stage not in {"ocr", "qwen"} or type(page) is not int or page < 1:
        raise SpoolError("prepared_artifact_invalid")
    return candidate_path(settings, job_id).parent / "pages" / f"{stage}_{page}.json"


def validate_words(settings, words):
    if len(words) > settings.max_page_words:
        raise SpoolError("capacity_exhausted")
    total = 0
    for word in words:
        if (not isinstance(word.text, str) or len(word.bbox) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (*word.bbox, word.confidence))):
            raise SpoolError("prepared_artifact_invalid")
        total += len(word.text.encode("utf-8")) + 1
        if total > settings.max_page_text_bytes:
            raise SpoolError("capacity_exhausted")


def validate_source(settings, row, page):
    metadata = page_metadata(settings, row["job_id"], page)
    image = settings.upload_dir / row["image_path"] / f"page_{page}.webp"
    if (metadata.get("identity") != row["manifest"]["identity"]
            or metadata.get("capture_type") not in {"printed", "handwritten"}
            or hashlib.sha256(bounded_bytes(image, settings.max_artifact_bytes)).hexdigest() != metadata.get("image_sha256")):
        raise SpoolError("prepared_artifact_invalid")
    return metadata


def save_page(db_engine, settings, row, stage, page, **payload):
    path = artifact_path(settings, row["job_id"], stage, page)
    private_directory(path.parent)
    metadata = page_metadata(settings, row["job_id"], page)
    data = dict(identity=identity(row), image_sha256=metadata["image_sha256"], stage=stage, page=page, **payload)
    encoded = json.dumps(data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    write_reserved(db_engine, settings, row["job_id"], path, encoded)


def read_page(settings, row, stage, page):
    path = artifact_path(settings, row["job_id"], stage, page)
    if not path.exists():
        return None
    try:
        data = json.loads(bounded_bytes(path, settings.max_artifact_bytes))
        metadata = page_metadata(settings, row["job_id"], page)
        if (data["identity"] != identity(row) or data["image_sha256"] != metadata["image_sha256"]
                or data["stage"] != stage or data["page"] != page):
            raise SpoolError("prepared_artifact_invalid")
        if stage == "ocr":
            from smriti.ocr import OcrWord
            from smriti.text_layer import MODEL_VERSION

            words = [OcrWord(**item) for item in data["words"]]
            validate_words(settings, words)
            expected = {"text_layer": {MODEL_VERSION}, "ocr": {
                "rapidocr:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec@onnx+cpu",
                f"paddle:{settings.ocr_det_model}+{settings.ocr_rec_model}",
            }}
            if (data["source"] not in expected or data["model_version"] not in expected[data["source"]]
                    or data["engine"] != ("text_layer" if data["source"] == "text_layer" else data["model_version"])):
                raise SpoolError("prepared_artifact_invalid")
            if len(data["text"].encode("utf-8")) > settings.max_page_text_bytes:
                raise SpoolError("capacity_exhausted")
            data["words"] = words
        else:
            from smriti.extract import ExtractedField
            from smriti.vlm import VLM_ENGINE_NAME
            from smriti.runtime import QWEN_OPERATIONAL_FAILURES

            if data["model_version"] != VLM_ENGINE_NAME or not isinstance(data["fields"], list):
                raise SpoolError("prepared_artifact_invalid")
            outcome = data.get("outcome", "read")
            if (metadata["capture_type"] != "printed"
                    and not (metadata["capture_type"] == "handwritten" and outcome == "read" and not data["fields"])):
                raise SpoolError("prepared_artifact_invalid")
            if (outcome not in {"read", "unavailable"}
                    or outcome == "unavailable" and (data["fields"] or data.get("error_code") not in QWEN_OPERATIONAL_FAILURES)
                    or outcome == "read" and "error_code" in data):
                raise SpoolError("prepared_artifact_invalid")
            for item in data["fields"]:
                field = ExtractedField(**item)
                if (type(field.page) is not int or field.page != page or field.engine != VLM_ENGINE_NAME
                        or not isinstance(field.label_raw, str) or not isinstance(field.value_text, str)
                        or len(field.bbox) != 4
                        or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in (*field.bbox, field.confidence))):
                    raise SpoolError("prepared_artifact_invalid")
        return data
    except (AttributeError, KeyError, TypeError, ValueError):
        raise SpoolError("prepared_artifact_invalid") from None


def page_words(settings, row):
    for page in range(1, row["page_count"] + 1):
        data = read_page(settings, row, "ocr", page)
        if data is None:
            raise SpoolError("prepared_artifact_invalid")
        yield data["words"]


def page_texts(settings, row):
    for page in range(1, row["page_count"] + 1):
        data = read_page(settings, row, "ocr", page)
        if data is None:
            raise SpoolError("prepared_artifact_invalid")
        yield data["text"]


def _owned_files(settings, job_id, *, include_sources=False):
    from smriti.candidates import candidate_path

    root = candidate_path(settings, job_id).parent
    check_path(root)
    if root.exists():
        with os.scandir(root) as entries:
            for entry in entries:
                path = root / entry.name
                check_path(path)
                if entry.name == "pages" and path.is_dir():
                    with os.scandir(path) as pages:
                        for page in pages:
                            target = path / page.name
                            check_path(target)
                            if not re.fullmatch(r"(?:ocr|qwen)_[1-9][0-9]*\.json(?:\.tmp)?", page.name) or not target.is_file():
                                raise SpoolError("cleanup_failed")
                            yield target
                elif re.fullmatch(r"candidates\.sqlite(?:-journal|-wal|-shm)?", entry.name) and path.is_file():
                    yield path
                else:
                    raise SpoolError("cleanup_failed")
    if include_sources:
        root = settings.upload_dir / job_id
        check_path(root)
        with os.scandir(root) as entries:
            for entry in entries:
                path = root / entry.name
                check_path(path)
                if not re.fullmatch(r"page_[1-9][0-9]*\.(?:webp|words\.json|meta\.json)", entry.name) or not path.is_file():
                    raise SpoolError("prepared_artifact_invalid")
                yield path


def reconcile_processing(engine, settings, job_id):
    """Coordinator-only: prior owned trees must have exited before this scan."""
    total = SQL_HEADROOM_BYTES + sum(path.stat().st_size for path in _owned_files(settings, job_id, include_sources=True))
    check_free_space(settings, settings.upload_dir, settings.db_path.parent)
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        raw = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id AND state = 'promoted'"), {"id": job_id}).scalar_one_or_none()
        if raw is None:
            raise SpoolError("cancelled")
        manifest = json.loads(raw)
        charged = conn.execute(text("SELECT COALESCE(SUM(COALESCE(json_extract(preparation_manifest_json, '$.reserved_bytes'), 0)), 0) FROM submissions")).scalar_one()
        if charged - manifest.get("reserved_bytes", 0) + total > settings.active_output_bytes:
            raise SpoolError("capacity_exhausted")
        manifest["reserved_bytes"] = total
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"), {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":"))})


def cleanup_processing(engine, settings, job_id):
    from smriti.candidates import candidate_path

    update_processing(engine, job_id, cleanup="pending")
    try:
        # Validate every name before unlinking anything; retain canonical source files always.
        for _ in _owned_files(settings, job_id):
            pass
        for path in _owned_files(settings, job_id):
            path.unlink()
        root = candidate_path(settings, job_id).parent
        pages = root / "pages"
        if pages.exists():
            pages.rmdir()
        if root.exists():
            root.rmdir()
    except (OSError, ValueError, SpoolError):
        update_processing(engine, job_id, cleanup="failed")
        return False
    with engine.connect() as conn:
        raw = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).scalar_one_or_none()
    if raw is not None:
        release_output(engine, job_id, json.loads(raw).get("reserved_bytes", 0))
        update_processing(engine, job_id, cleanup="confirmed")
    return True

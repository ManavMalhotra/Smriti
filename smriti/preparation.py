"""Model-free supervised preparation: one page at a time, one complete promotion."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import uuid
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from sqlalchemy import text

from smriti.config import SPOOL_CHUNK_BYTES, Settings
from smriti.db import create_db_engine
from smriti.job_progress import progress_transaction, record_progress
from smriti.output_quota import bounded_bytes, reconcile_output, release_output, reserve_output, write_reserved
from smriti.private_paths import check_path, private_directory
from smriti.runtime import StageResult, run_stage
from smriti.spool import SpoolError, _now, delete_spool

PREPARATION_VERSION = 2
PDF_DPI = 300
SQL_HEADROOM_BYTES = 8 * 1024**2


def settings_context(settings):
    return {key: str(value) if isinstance(value, Path) else value for key, value in asdict(settings).items()}


def _settings(context):
    values = dict(context["settings"])
    for name in ("db_path", "upload_dir", "spool_dir", "log_dir"):
        values[name] = Path(values[name])
    return Settings(**values)


def preparation_identity(settings):
    parameters = {name: getattr(settings, name) for name in (
        "quality_blur", "quality_min_short_edge", "quality_max_aspect", "quality_min_ink_ratio",
        "upscale_long_edge", "max_pixels", "max_page_words", "max_page_text_bytes", "max_artifact_bytes",
    )}
    parameters.update(version=PREPARATION_VERSION, dpi=PDF_DPI, webp_quality=90, webp_method=4,
                      pymupdf=version("PyMuPDF"), max_long_edge=1800)
    return hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()


def _submission(engine, settings, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise SpoolError("prepared_artifact_invalid")
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM submissions WHERE job_id = :id"), {"id": job_id}).mappings().first()
    if row is None or row["state"] not in {"pending_intake", "preparing"} or row["consent_revoked_at"] is not None:
        raise SpoolError("cancelled")
    if row["spool_path"] != str(settings.spool_dir / f"{job_id}.raw"):
        raise SpoolError("source_missing")
    return dict(row)


def _verify_raw(row, settings):
    path = Path(row["spool_path"])
    check_path(path)
    if not path.is_file() or path.stat().st_size != row["spool_bytes"]:
        raise SpoolError("source_missing")
    digest = hashlib.sha256(row["patient_id"].encode() + b"\0")
    with path.open("rb") as source:
        while chunk := source.read(SPOOL_CHUNK_BYTES):
            digest.update(chunk)
    if digest.hexdigest() != row["content_hash"]:
        raise SpoolError("source_missing")
    return path


def _update_manifest(engine, job_id, changes):
    with engine.begin() as conn:
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        row = conn.execute(text("SELECT preparation_manifest_json, state, consent_revoked_at FROM submissions WHERE job_id = :id"), {"id": job_id}).first()
        if row is None or row[1] != "preparing" or row[2] is not None:
            raise SpoolError("cancelled")
        manifest = json.loads(row[0] or "{}")
        manifest.update(changes)
        conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest, updated_at = :now WHERE job_id = :id"),
                     {"id": job_id, "manifest": json.dumps(manifest, separators=(",", ":")), "now": _now()})
    return manifest


def inspection_target(context, report):
    import pymupdf
    from PIL import Image

    settings = _settings(context)
    engine = create_db_engine(settings.db_path)
    try:
        row = _submission(engine, settings, context["job_id"])
        path = _verify_raw(row, settings)
        with path.open("rb") as source:
            header = source.read(16)
        if header.startswith(b"%PDF-"):
            try:
                source = pymupdf.open(path)
            except Exception:
                raise SpoolError("invalid_format") from None
            with source:
                if source.needs_pass:
                    raise SpoolError("password_protected")
                pages = source.page_count
            kind = "pdf"
        else:
            try:
                with Image.open(path) as image:
                    if image.width * image.height > settings.max_pixels:
                        raise SpoolError("pixel_limit")
            except SpoolError:
                raise
            except Exception:
                raise SpoolError("invalid_format") from None
            pages, kind = 1, "image"
        if pages < 1:
            raise SpoolError("invalid_format")
        manifest = json.loads(row["preparation_manifest_json"] or "{}")
        identity = preparation_identity(settings)
        if "version" in manifest:
            if (manifest.get("identity") != identity or manifest.get("source_pages") != pages
                    or manifest.get("source_hash") != row["content_hash"] or manifest.get("kind") != kind):
                raise SpoolError("prepared_artifact_invalid")
            _reconcile_preparation(engine, settings, row["job_id"])
            _update_manifest(engine, row["job_id"], {"validated_pages": 0})
        else:
            initial = dict(version=PREPARATION_VERSION, identity=identity, source_pages=pages, kind=kind,
                             source_hash=row["content_hash"],
                            prepared_pages=0, printed_pages=0, handwritten_pages=0, quality_score=1.0,
                            document_id=str(uuid.uuid4()))
            # Identity and SQL headroom commit together; a crash cannot leave an uncharged manifest.
            reserve_output(engine, settings, context["job_id"], SQL_HEADROOM_BYTES, manifest_changes=initial)
        report("checkpoint", page=1, count=pages)
    finally:
        engine.dispose()


def _prepared_dir(settings, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise SpoolError("prepared_artifact_invalid")
    target = settings.upload_dir / job_id
    check_path(target)
    if target.exists():
        return target
    return settings.upload_dir / ".runtime" / job_id / "prepared"


def _reconcile_preparation(engine, settings, job_id):
    total = SQL_HEADROOM_BYTES
    root = _prepared_dir(settings, job_id)
    check_path(root)
    if root.exists():
        with os.scandir(root) as entries:
            for entry in entries:
                path = root / entry.name
                check_path(path)
                if not re.fullmatch(r"page_[1-9][0-9]*\.(?:webp|words\.json|meta\.json)(?:\.tmp)?", entry.name) or not path.is_file():
                    raise SpoolError("prepared_artifact_invalid")
                size = path.stat().st_size
                if size > settings.max_artifact_bytes:
                    raise SpoolError("capacity_exhausted")
                total += size
    reconcile_output(engine, settings, job_id, total)


def page_metadata(settings, job_id, page):
    if type(page) is not int or page < 1:
        raise SpoolError("prepared_artifact_invalid")
    path = _prepared_dir(settings, job_id) / f"page_{page}.meta.json"
    try:
        metadata = json.loads(bounded_bytes(path, settings.max_artifact_bytes))
    except (OSError, ValueError):
        raise SpoolError("prepared_artifact_invalid") from None
    if (not isinstance(metadata, dict) or metadata.get("version") != PREPARATION_VERSION
            or metadata.get("source_page") != page or metadata.get("page") != page):
        raise SpoolError("prepared_artifact_invalid")
    return metadata


def _prepare_page(engine, settings, row, manifest, page_number, source, output_dir):
    import cv2
    import pymupdf
    from PIL import Image, ImageOps
    from smriti import handwriting, quality, text_layer
    from smriti.preprocess import normalise_page, to_bgr

    layer = None
    if manifest["kind"] == "pdf":
        page = source[page_number - 1]
        scale = PDF_DPI / 72
        if page.rect.width * scale * page.rect.height * scale > settings.max_pixels:
            raise SpoolError("pixel_limit")
        raw_words = page.get_text("words", sort=True)
        if len(raw_words) > settings.max_page_words or sum(len(word[4].encode("utf-8")) for word in raw_words) > settings.max_page_text_bytes:
            raise SpoolError("capacity_exhausted")
        layer = text_layer.inspect(raw_words, width=page.cropbox.width, height=page.cropbox.height,
                                   rotation=page.rotation % 360, image_coverage=text_layer._image_coverage(page, page.cropbox))
        del raw_words
        pixmap = page.get_pixmap(dpi=PDF_DPI, colorspace=pymupdf.csRGB, alpha=False)
        if pixmap.width * pixmap.height > settings.max_pixels:
            raise SpoolError("pixel_limit")
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        del pixmap, page
    else:
        from smriti.ingest import _flatten_rgb

        with Image.open(source) as opened:
            if opened.width * opened.height > settings.max_pixels:
                raise SpoolError("pixel_limit")
            orientation = opened.getexif().get(0x0112)
            opened.load()
            image = _flatten_rgb(ImageOps.exif_transpose(opened))
            if orientation:
                image.info["smriti_exif_rotated"] = True
    try:
        bgr = to_bgr(image)
        metrics = quality.measure(bgr)
        capture = handwriting.detect_capture_type(bgr)
        del bgr
        failure = quality.failure(metrics, min_short_edge=settings.quality_min_short_edge, blur_floor=settings.quality_blur,
                                  max_aspect=settings.quality_max_aspect, min_ink_ratio=settings.quality_min_ink_ratio)
        if failure is not None:
            raise SpoolError("rejected_quality")
        bgr, steps = normalise_page(image, upscale_long_edge=settings.upscale_long_edge, geometry=layer is None or not layer.usable)
        encoded = io.BytesIO()
        converted = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        try:
            converted.save(encoded, format="WEBP", quality=90, method=4)
        finally:
            converted.close()
        del bgr
        payload = encoded.getvalue()
        write_reserved(engine, settings, row["job_id"], output_dir / f"page_{page_number}.webp", payload)
        metadata = {"version": PREPARATION_VERSION, "identity": manifest["identity"], "source_page": page_number,
                    "page": page_number, "capture_type": capture, "metrics": metrics.as_dict(), "steps": steps,
                    "duplicate": False, "failure": None, "text_layer": layer.metrics if layer else None,
                    "image_sha256": hashlib.sha256(payload).hexdigest(), "words_sha256": None}
        del payload
        if layer is not None and layer.usable:
            words = {"source": layer.source, "model_version": layer.model_version,
                     "words": [{"text": word.text, "bbox": word.bbox, "confidence": word.confidence} for word in layer.words]}
            payload = json.dumps(words, separators=(",", ":")).encode()
            write_reserved(engine, settings, row["job_id"], output_dir / f"page_{page_number}.words.json", payload)
            metadata["words_sha256"] = hashlib.sha256(payload).hexdigest()
        payload = json.dumps(metadata, separators=(",", ":"), allow_nan=False).encode()
        write_reserved(engine, settings, row["job_id"], output_dir / f"page_{page_number}.meta.json", payload)
        return metadata
    finally:
        image.close()


def preparation_target(context, report):
    import pymupdf

    settings = _settings(context)
    engine = create_db_engine(settings.db_path)
    try:
        row = _submission(engine, settings, context["job_id"])
        manifest = json.loads(row["preparation_manifest_json"] or "{}")
        if manifest.get("identity") != preparation_identity(settings):
            raise SpoolError("prepared_artifact_invalid")
        start, end = context["start"], context["end"]
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= manifest["source_pages"]
                or end - start + 1 > settings.max_workset_pages or start != manifest["prepared_pages"] + 1):
            raise SpoolError("prepared_artifact_invalid")
        path = _verify_raw(row, settings)
        output_dir = _prepared_dir(settings, row["job_id"])
        private_directory(output_dir)
        source = pymupdf.open(path) if manifest["kind"] == "pdf" else path
        try:
            for page_number in range(start, end + 1):
                report("page_started", page=page_number)
                metadata = None
                if (output_dir / f"page_{page_number}.meta.json").exists():
                    try:
                        metadata = _validate_page_files(settings, row["job_id"], page_number, manifest["identity"])
                    except (OSError, ValueError, KeyError, SpoolError):
                        pass  # Raw is still present; only this new attempt's page is repaired.
                if metadata is not None:
                    for suffix in ("webp", "words.json", "meta.json"):
                        path = output_dir / f"page_{page_number}.{suffix}.tmp"
                        check_path(path)
                        path.unlink(missing_ok=True)
                else:
                    removed = False
                    for suffix in ("webp", "words.json", "meta.json"):
                        for name in (f"page_{page_number}.{suffix}", f"page_{page_number}.{suffix}.tmp"):
                            path = output_dir / name
                            check_path(path)
                            removed = removed or path.exists()
                            path.unlink(missing_ok=True)
                    if removed:
                        _reconcile_preparation(engine, settings, row["job_id"])
                    metadata = _prepare_page(engine, settings, row, manifest, page_number, source, output_dir)
                manifest = _update_manifest(engine, row["job_id"], {
                    "prepared_pages": page_number,
                    "printed_pages": manifest["printed_pages"] + (metadata["capture_type"] == "printed"),
                    "handwritten_pages": manifest["handwritten_pages"] + (metadata["capture_type"] == "handwritten"),
                    "quality_score": min(manifest["quality_score"], metadata["metrics"]["score"]),
                })
                report("page_finished", page=page_number, count=1)
        finally:
            if manifest["kind"] == "pdf":
                source.close()
    finally:
        engine.dispose()


def _validate_page_files(settings, job_id, page, identity):
    root = _prepared_dir(settings, job_id)
    metadata = page_metadata(settings, job_id, page)
    if metadata["identity"] != identity:
        raise SpoolError("prepared_artifact_invalid")
    payload = bounded_bytes(root / f"page_{page}.webp", settings.max_artifact_bytes)
    if hashlib.sha256(payload).hexdigest() != metadata["image_sha256"]:
        raise SpoolError("prepared_artifact_invalid")
    del payload
    if metadata["words_sha256"]:
        payload = bounded_bytes(root / f"page_{page}.words.json", settings.max_artifact_bytes)
        if hashlib.sha256(payload).hexdigest() != metadata["words_sha256"]:
            raise SpoolError("prepared_artifact_invalid")
    return metadata


def validation_target(context, report):
    settings = _settings(context)
    engine = create_db_engine(settings.db_path)
    try:
        row = _submission(engine, settings, context["job_id"])
        manifest = json.loads(row["preparation_manifest_json"])
        start, end = context["start"], context["end"]
        if (type(start) is not int or type(end) is not int or not 1 <= start <= end <= manifest["prepared_pages"]
                or end - start + 1 > settings.max_workset_pages or start != manifest.get("validated_pages", 0) + 1):
            raise SpoolError("prepared_artifact_invalid")
        for page in range(start, end + 1):
            _validate_page_files(settings, row["job_id"], page, manifest["identity"])
            report("checkpoint", page=page, count=1)
        _update_manifest(engine, row["job_id"], {"validated_pages": end})
    finally:
        engine.dispose()


def promote_prepared(engine, settings, job_id):
    row = _submission(engine, settings, job_id)
    manifest = json.loads(row["preparation_manifest_json"] or "{}")
    total = manifest.get("source_pages", 0)
    if (total < 1 or manifest.get("prepared_pages") != total or manifest.get("validated_pages") != total
            or manifest.get("identity") != preparation_identity(settings)):
        raise SpoolError("prepared_artifact_invalid")
    root = _prepared_dir(settings, job_id)
    small_quality = [page_metadata(settings, job_id, page) for page in range(1, total + 1)] if total <= 20 else []
    target = settings.upload_dir / job_id
    check_path(target)
    if root != target:
        if target.exists():
            raise SpoolError("prepared_artifact_invalid")
        root.replace(target)
    capture = "handwritten" if manifest["handwritten_pages"] > total / 2 else "printed"
    quality = {"version": PREPARATION_VERSION, "page_count": total, "pages_manifest": True, "pages": small_quality,
               "thresholds": {"min_short_edge": settings.quality_min_short_edge, "blur_floor": settings.quality_blur,
                              "max_aspect": settings.quality_max_aspect, "min_ink_ratio": settings.quality_min_ink_ratio,
                              "upscale_long_edge": settings.upscale_long_edge}}
    with progress_transaction(engine) as conn:
        # Fence revocation/erasure before clinical inserts, using this transaction's writer lock.
        conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": job_id})
        current = conn.execute(text("SELECT state, consent_revoked_at, preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).first()
        if (current is None or current[0] != "preparing" or current[1] is not None
                or current[2] != row["preparation_manifest_json"]):
            raise SpoolError("cancelled")
        now = _now()
        document_id = manifest["document_id"]
        conn.execute(text("""INSERT INTO document (id, patient_id, doc_type, capture_type, doc_date, collection_date,
            image_path, page_count, quality_score, quality_json, content_hash, status, created_at)
            VALUES (:id, :patient, :type, :capture, :date, :collection, :path, :pages, :quality, :metadata, :hash, 'queued', :now)"""),
            {"id": document_id, "patient": row["patient_id"], "type": row["requested_doc_type"] or "other", "capture": capture,
             "date": row["requested_doc_date"], "collection": row["requested_collection_date"], "path": job_id,
             "pages": total, "quality": manifest["quality_score"], "metadata": json.dumps(quality, separators=(",", ":")),
             "hash": row["content_hash"], "now": now})
        consent_id = str(uuid.uuid4())
        conn.execute(text("INSERT INTO consent (id, document_id, scope, version, granted_at) VALUES (:id, :document, :scope, :version, :granted)"),
                     {"id": consent_id, "document": document_id, "scope": row["consent_scope"], "version": row["consent_version"], "granted": row["consent_granted_at"]})
        conn.execute(text("INSERT INTO jobs (id, document_id, state, page, total, ts, progress_json, stage) VALUES (:id, :document, 'queued', 0, :total, :now, :progress, 'queued')"),
                     {"id": job_id, "document": document_id, "total": total, "now": now, "progress": row["progress_json"]})
        result = conn.execute(text("UPDATE submissions SET state = 'promoted', document_id = :document, total_pages = :total, updated_at = :now WHERE job_id = :id AND state = 'preparing' AND consent_revoked_at IS NULL"),
                              {"id": job_id, "document": document_id, "total": total, "now": now})
        if result.rowcount != 1:
            raise SpoolError("cancelled")
        record_progress(conn, job_id, "prepared")
        conn.execute(text("INSERT INTO audit (id, entity, entity_id, field, \"old\", \"new\", actor, ts) VALUES (:id, 'consent', :consent, 'granted', NULL, :scope, 'owner', :now)"),
                     {"id": str(uuid.uuid4()), "consent": consent_id, "scope": row["consent_scope"], "now": row["consent_granted_at"]})
    if not delete_spool(engine, settings, job_id):
        raise SpoolError("cleanup_failed")
    return document_id


def fail_preparation(engine, settings, job_id, result, *, allow_debug=False):
    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise SpoolError("prepared_artifact_invalid")
    if not result.cleanup_confirmed:
        # Do not unlink a file that an unconfirmed child may still be writing.
        return False
    with engine.connect() as conn:
        state = conn.execute(text("SELECT state FROM submissions WHERE job_id = :id"), {"id": job_id}).scalar_one_or_none()
        if state is None or state == "promoted" or conn.execute(text("SELECT 1 FROM document WHERE image_path = :path"), {"path": job_id}).first() is not None:
            return False
    code = {"timeout": "preparation_timeout", "crash": "preparation_crash", "stage_exception": "preparation_failed",
            "io_error": "disk_error"}.get(result.status, result.status)
    from smriti.job_progress import INTAKE_ERRORS

    if code not in INTAKE_ERRORS:
        code = "preparation_failed"
    with progress_transaction(engine) as conn:
        record_progress(conn, job_id, "intake_rejected" if code in {"invalid_format", "password_protected", "pixel_limit", "rejected_quality"}
                        else "intake_cancelled" if code == "cancelled" else "intake_failed", error_code=code)
        conn.execute(text("UPDATE submissions SET spool_cleanup_requested_at = COALESCE(spool_cleanup_requested_at, :now) WHERE job_id = :id"), {"id": job_id, "now": _now()})
    roots = (settings.upload_dir / ".runtime" / job_id / "prepared", settings.upload_dir / job_id)
    try:
        for root in roots:
            check_path(root)
            if root.exists():
                with os.scandir(root) as entries:
                    for entry in entries:
                        path = root / entry.name
                        check_path(path)
                        if not re.fullmatch(r"page_[1-9][0-9]*\.(?:webp|words\.json|meta\.json)(?:\.tmp)?", entry.name) or not path.is_file():
                            raise SpoolError("cleanup_failed")
                        path.unlink()
                root.rmdir()
        private_root = settings.upload_dir / ".runtime" / job_id
        check_path(private_root)
        if private_root.exists():
            private_root.rmdir()
    except (OSError, ValueError, SpoolError):
        with engine.begin() as conn:
            conn.execute(text("UPDATE submissions SET spool_cleanup_state = 'failed', spool_cleanup_error_code = 'cleanup_failed' WHERE job_id = :id"), {"id": job_id})
        return False
    with engine.connect() as conn:
        manifest = conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": job_id}).scalar_one_or_none()
    if manifest:
        release_output(engine, job_id, json.loads(manifest).get("reserved_bytes", 0))
    if allow_debug and result.status == "crash" and settings.debug_retain_failed_spool:
        with engine.begin() as conn:
            conn.execute(text("UPDATE submissions SET spool_cleanup_requested_at = :now, spool_cleanup_state = 'debug_retained' WHERE job_id = :id"), {"id": job_id, "now": _now()})
        return True
    return delete_spool(engine, settings, job_id)


def prepare_submission(engine, settings, job_id, *, stop=None, supervisor=run_stage):
    _submission(engine, settings, job_id)
    try:
        return _prepare_submission(engine, settings, job_id, stop=stop, supervisor=supervisor)
    except SpoolError as exc:
        result = StageResult(exc.code, True, 0, 0)
        fail_preparation(engine, settings, job_id, result)
        return result


def _prepare_submission(engine, settings, job_id, *, stop, supervisor):
    with progress_transaction(engine) as conn:
        record_progress(conn, job_id, "preparing")
    context = {"settings": settings_context(settings), "job_id": job_id}
    result = supervisor("smriti.preparation:inspection_target", context, timeout_seconds=settings.inspection_timeout_seconds,
                        cleanup_wait_seconds=settings.cleanup_wait_seconds, cpu_only=True, memory_limit_bytes=settings.native_memory_bytes, stop=stop)
    if not result.success:
        fail_preparation(engine, settings, job_id, result, allow_debug=True)
        return result
    while True:
        row = _submission(engine, settings, job_id)
        manifest = json.loads(row["preparation_manifest_json"])
        start = manifest["prepared_pages"] + 1
        if start > manifest["source_pages"]:
            break
        end = min(start + settings.max_workset_pages - 1, manifest["source_pages"])
        result = supervisor("smriti.preparation:preparation_target", {**context, "start": start, "end": end},
                            timeout_seconds=settings.preparation_timeout_seconds, cleanup_wait_seconds=settings.cleanup_wait_seconds,
                            cpu_only=True, memory_limit_bytes=settings.native_memory_bytes, stop=stop)
        if not result.success:
            fail_preparation(engine, settings, job_id, result, allow_debug=True)
            return result
    while True:
        row = _submission(engine, settings, job_id)
        manifest = json.loads(row["preparation_manifest_json"])
        start = manifest.get("validated_pages", 0) + 1
        if start > manifest["source_pages"]:
            break
        end = min(start + settings.max_workset_pages - 1, manifest["source_pages"])
        result = supervisor("smriti.preparation:validation_target", {**context, "start": start, "end": end},
                            timeout_seconds=settings.helper_timeout_seconds, cleanup_wait_seconds=settings.cleanup_wait_seconds,
                            cpu_only=True, memory_limit_bytes=settings.native_memory_bytes, stop=stop)
        if not result.success:
            fail_preparation(engine, settings, job_id, result)
            return result
    try:
        promote_prepared(engine, settings, job_id)
    except Exception as exc:
        result = StageResult(getattr(exc, "code", "stage_exception"), True, 0, 0)
        fail_preparation(engine, settings, job_id, result)
    return result

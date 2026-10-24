"""Upload → consent → content hash → quality gate → page files → queued job."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageOps
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from smriti import handwriting, quality
from smriti.config import Settings
from smriti.preprocess import normalise_page, to_bgr

logger = logging.getLogger(__name__)

PDF_DPI = 300


class IngestError(Exception):
    def __init__(self, code: str, message: str, page: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.page = page


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    job_id: str | None
    pages: int
    status: str
    duplicate: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kind(data: bytes) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    raise IngestError("unsupported_type", "Upload a JPEG, PNG, or PDF.")


def _flatten_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def _image_pages(data: bytes, settings: Settings) -> list[Image.Image]:
    try:
        opened = Image.open(io.BytesIO(data))
        if opened.width * opened.height > settings.max_pixels:
            raise IngestError("page_too_large", "Image is too large to process.")
        orientation = opened.getexif().get(0x0112)
        opened.load()
        image = ImageOps.exif_transpose(opened).copy()
        if orientation:
            image.info["smriti_exif_rotated"] = True
        opened.close()
    except IngestError:
        raise
    except Exception as exc:
        raise IngestError("invalid_file", "The image could not be decoded.") from exc
    return [_flatten_rgb(image)]


def _pdf_pages(data: bytes, settings: Settings) -> list[Image.Image]:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise IngestError("invalid_file", "The PDF could not be decoded.") from exc

    try:
        if document.needs_pass:
            raise IngestError("invalid_file", "Password-protected PDFs are not accepted.")
        if document.page_count == 0:
            raise IngestError("invalid_file", "The PDF has no pages.")
        if document.page_count > settings.max_pages:
            raise IngestError(
                "too_many_pages",
                f"PDF has {document.page_count} pages; the limit is {settings.max_pages}.",
            )

        pages: list[Image.Image] = []
        scale = PDF_DPI / 72
        for page in document:
            estimated_pixels = page.rect.width * scale * page.rect.height * scale
            if estimated_pixels > settings.max_pixels:
                raise IngestError("page_too_large", "PDF page is too large to process.")
            pixmap = page.get_pixmap(
                dpi=PDF_DPI, colorspace=pymupdf.csRGB, alpha=False
            )
            if pixmap.width * pixmap.height > settings.max_pixels:
                raise IngestError("page_too_large", "PDF page is too large to process.")
            pages.append(
                Image.frombytes(
                    "RGB", (pixmap.width, pixmap.height), pixmap.samples
                )
            )
        return pages
    finally:
        document.close()


def _build_quality_payload(
    settings: Settings,
    entries: list[dict],
) -> str:
    return json.dumps(
        {
            "thresholds": {
                "min_short_edge": settings.quality_min_short_edge,
                "blur_floor": settings.quality_blur,
                "max_aspect": settings.quality_max_aspect,
                "min_ink_ratio": settings.quality_min_ink_ratio,
                "upscale_long_edge": settings.upscale_long_edge,
            },
            "pages": entries,
        },
        separators=(",", ":"),
    )


def _mark_rejected(
    engine: Engine,
    document_id: str,
    capture_type: str,
    page_count: int,
    quality_score: float,
    quality_json: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE document
                SET status = 'rejected_quality', capture_type = :capture_type,
                    page_count = :page_count, quality_score = :quality_score,
                    quality_json = :quality_json
                WHERE id = :id
                """
            ),
            {
                "id": document_id,
                "capture_type": capture_type,
                "page_count": page_count,
                "quality_score": quality_score,
                "quality_json": quality_json,
            },
        )


def _mark_failed(engine: Engine, document_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE document SET status = 'failed' WHERE id = :id"),
            {"id": document_id},
        )


def _save_page(bgr, path: Path) -> None:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save(path, format="WEBP", quality=90, method=4)


def _find_duplicate(
    engine: Engine, patient_id: str, content_hash: str
) -> tuple[str, str] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT id, status FROM document "
                "WHERE patient_id = :patient_id AND content_hash = :hash"
            ),
            {"patient_id": patient_id, "hash": content_hash},
        ).first()
    return (row[0], row[1]) if row else None


def ingest_upload(
    engine: Engine,
    settings: Settings,
    *,
    patient_id: str,
    data: bytes,
    doc_type: str,
    consent_scope: str,
    doc_date: date | None = None,
    collection_date: date | None = None,
    consent_version: str = "1.0",
    actor: str = "operator",
) -> IngestResult:
    if len(data) == 0:
        raise IngestError("invalid_file", "The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise IngestError(
            "too_large",
            f"File exceeds the {settings.max_upload_bytes} byte limit.",
        )

    with engine.connect() as conn:
        patient = conn.execute(
            text("SELECT id FROM patient WHERE id = :id"), {"id": patient_id}
        ).first()
    if patient is None:
        raise IngestError("not_found", f"Unknown patient {patient_id}.")

    content_hash = hashlib.sha256(
        patient_id.encode("utf-8") + b"\0" + data
    ).hexdigest()
    duplicate = _find_duplicate(engine, patient_id, content_hash)
    if duplicate is not None:
        return IngestResult(
            document_id=duplicate[0],
            job_id=None,
            pages=0,
            status=duplicate[1],
            duplicate=True,
        )

    kind = _kind(data)
    images = (
        _pdf_pages(data, settings) if kind == "pdf" else _image_pages(data, settings)
    )

    document_id = str(uuid.uuid4())
    consent_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    created_at = _now()
    image_path = content_hash

    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO document
                        (id, patient_id, doc_type, capture_type, doc_date,
                         collection_date, image_path, page_count, quality_score,
                         quality_json, content_hash, status, created_at)
                    VALUES
                        (:id, :patient_id, :doc_type, 'handwritten', :doc_date,
                         :collection_date, :image_path, :page_count, NULL,
                         NULL, :content_hash, 'processing', :created_at)
                    """
                ),
                {
                    "id": document_id,
                    "patient_id": patient_id,
                    "doc_type": doc_type,
                    "doc_date": doc_date.isoformat() if doc_date else None,
                    "collection_date": (
                        collection_date.isoformat() if collection_date else None
                    ),
                    "image_path": image_path,
                    "page_count": len(images),
                    "content_hash": content_hash,
                    "created_at": created_at,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO consent
                        (id, document_id, scope, version, granted_at, revoked_at)
                    VALUES (:id, :document_id, :scope, :version, :granted_at, NULL)
                    """
                ),
                {
                    "id": consent_id,
                    "document_id": document_id,
                    "scope": consent_scope,
                    "version": consent_version,
                    "granted_at": created_at,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO audit
                        (id, entity, entity_id, field, "old", "new", actor, ts)
                    VALUES
                        (:id, 'consent', :entity_id, 'granted', NULL, :new,
                         :actor, :ts)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "entity_id": consent_id,
                    "new": consent_scope,
                    "actor": actor,
                    "ts": created_at,
                },
            )
    except IntegrityError:
        duplicate = _find_duplicate(engine, patient_id, content_hash)
        if duplicate is not None:
            return IngestResult(
                document_id=duplicate[0],
                job_id=None,
                pages=0,
                status=duplicate[1],
                duplicate=True,
            )
        raise

    entries: list[dict] = []
    prepared: list[tuple[int, np.ndarray, list[str], int]] = []
    previous_hashes: list[int] = []
    capture_types: list[str] = []
    failure: IngestError | None = None

    try:
        for page_number, image in enumerate(images, start=1):
            bgr = to_bgr(image)
            metrics = quality.measure(bgr)
            capture_type = handwriting.detect_capture_type(bgr)
            capture_types.append(capture_type)
            reason = quality.failure(
                metrics,
                min_short_edge=settings.quality_min_short_edge,
                blur_floor=settings.quality_blur,
                max_aspect=settings.quality_max_aspect,
                min_ink_ratio=settings.quality_min_ink_ratio,
            )
            entry = {
                "source_page": page_number,
                "page": None,
                "metrics": metrics.as_dict(),
                "steps": [],
                "duplicate": False,
                "failure": reason,
            }
            entries.append(entry)
            if reason is not None:
                failure = IngestError(
                    "quality_rejected", f"Page {page_number}: {reason}", page_number
                )
                break

            page_bgr, steps = normalise_page(
                image, upscale_long_edge=settings.upscale_long_edge
            )
            page_hash = quality.dhash(page_bgr)
            # shortcut: PDF pages are not deduped; a template page can differ only
            # in one value, which a perceptual hash cannot see. Upgrade if duplicate
            # PDF pages become a real corpus problem.
            duplicate_page = kind != "pdf" and any(
                quality.is_duplicate(page_hash, prior) for prior in previous_hashes
            )
            if duplicate_page:
                entry["duplicate"] = True
                continue
            previous_hashes.append(page_hash)
            prepared.append((page_number, page_bgr, steps, page_hash))

        handwritten_count = capture_types.count("handwritten")
        capture_type = (
            "handwritten"
            if handwritten_count > len(capture_types) / 2
            else "printed"
        )
        logger.info(
            "Ingest document %s: %d page(s) (%d printed, %d handwritten) => capture_type='%s'",
            document_id,
            len(images),
            capture_types.count("printed"),
            handwritten_count,
            capture_type,
        )

        if failure is not None:
            quality_score = (
                min(entry["metrics"]["score"] for entry in entries)
                if entries
                else 0.0
            )
            _mark_rejected(
                engine,
                document_id,
                capture_type,
                len(images),
                quality_score,
                _build_quality_payload(settings, entries),
            )
            raise failure

        if not prepared:
            raise IngestError("quality_rejected", "No usable pages found.")

        for output_page, (source_page, page_bgr, steps, _page_hash) in enumerate(
            prepared, start=1
        ):
            entries[source_page - 1]["page"] = output_page
            entries[source_page - 1]["steps"] = steps

        quality_score = min(
            entries[source_page - 1]["metrics"]["score"]
            for source_page, _bgr, _steps, _hash in prepared
        )
        quality_json = _build_quality_payload(settings, entries)

        upload_root = settings.upload_dir
        upload_root.mkdir(parents=True, exist_ok=True)
        temp_dir = upload_root / f".tmp-{content_hash}-{uuid.uuid4().hex}"
        target_dir = upload_root / content_hash
        temp_dir.mkdir(parents=True, exist_ok=False)
        try:
            for output_page, (_source, page_bgr, _steps, _hash) in enumerate(
                prepared, start=1
            ):
                _save_page(page_bgr, temp_dir / f"page_{output_page}.webp")
            if target_dir.exists():
                shutil.rmtree(target_dir)
            temp_dir.replace(target_dir)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            _mark_failed(engine, document_id)
            raise IngestError(
                "ingest_failed", "Could not store the page images."
            ) from exc

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE document
                        SET capture_type = :capture_type, page_count = :page_count,
                            quality_score = :quality_score,
                            quality_json = :quality_json, status = 'queued'
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": document_id,
                        "capture_type": capture_type,
                        "page_count": len(prepared),
                        "quality_score": quality_score,
                        "quality_json": quality_json,
                    },
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO jobs
                            (id, document_id, state, page, total, error, ts)
                        VALUES (:id, :document_id, 'queued', 0, :total, NULL, :ts)
                        """
                    ),
                    {
                        "id": job_id,
                        "document_id": document_id,
                        "total": len(prepared),
                        "ts": _now(),
                    },
                )
        except Exception as exc:
            shutil.rmtree(target_dir, ignore_errors=True)
            _mark_failed(engine, document_id)
            raise IngestError(
                "ingest_failed", "Could not queue the document."
            ) from exc

        logger.info(
            "Ingest complete: document %s queued as job %s (%d pages ready for OCR)",
            document_id,
            job_id,
            len(prepared),
        )

        return IngestResult(
            document_id=document_id,
            job_id=job_id,
            pages=len(prepared),
            status="queued",
        )
    except IngestError:
        raise
    except Exception as exc:
        _mark_failed(engine, document_id)
        raise IngestError("ingest_failed", "Document ingestion failed.") from exc


def record_consent(
    engine: Engine,
    document_id: str,
    scope: str,
    version: str,
    *,
    actor: str = "operator",
) -> dict | None:
    with engine.begin() as conn:
        document = conn.execute(
            text("SELECT id FROM document WHERE id = :id"), {"id": document_id}
        ).first()
        if document is None:
            return None

        existing = conn.execute(
            text(
                "SELECT id, scope FROM consent WHERE document_id = :document_id"
            ),
            {"document_id": document_id},
        ).first()
        granted_at = _now()
        if existing is None:
            consent_id = str(uuid.uuid4())
            conn.execute(
                text(
                    """
                    INSERT INTO consent
                        (id, document_id, scope, version, granted_at, revoked_at)
                    VALUES (:id, :document_id, :scope, :version, :granted_at, NULL)
                    """
                ),
                {
                    "id": consent_id,
                    "document_id": document_id,
                    "scope": scope,
                    "version": version,
                    "granted_at": granted_at,
                },
            )
            old_scope = None
        else:
            consent_id = existing[0]
            old_scope = existing[1]
            conn.execute(
                text(
                    """
                    UPDATE consent
                    SET scope = :scope, version = :version,
                        granted_at = :granted_at, revoked_at = NULL
                    WHERE id = :id
                    """
                ),
                {
                    "id": consent_id,
                    "scope": scope,
                    "version": version,
                    "granted_at": granted_at,
                },
            )

        conn.execute(
            text(
                """
                INSERT INTO audit
                    (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES
                    (:id, 'consent', :entity_id, 'scope', :old, :new,
                     :actor, :ts)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "entity_id": consent_id,
                "old": old_scope,
                "new": scope,
                "actor": actor,
                "ts": granted_at,
            },
        )

        return {
            "id": consent_id,
            "document_id": document_id,
            "scope": scope,
            "version": version,
            "granted_at": granted_at,
            "revoked_at": None,
        }

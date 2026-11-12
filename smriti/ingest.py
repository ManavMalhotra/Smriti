"""Consent updates and image flattening; bounded intake/preparation live in separate stages."""

from __future__ import annotations

import uuid
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _flatten_rgb(image):
    from PIL import Image

    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


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
            text("SELECT id, scope FROM consent WHERE document_id = :document_id"),
            {"document_id": document_id},
        ).first()
        granted_at = datetime.now(timezone.utc).isoformat()
        if existing is None:
            consent_id = str(uuid.uuid4())
            conn.execute(
                text("""INSERT INTO consent (id, document_id, scope, version, granted_at, revoked_at)
                    VALUES (:id, :document_id, :scope, :version, :granted_at, NULL)"""),
                {"id": consent_id, "document_id": document_id, "scope": scope,
                 "version": version, "granted_at": granted_at},
            )
            old_scope = None
        else:
            consent_id = existing[0]
            old_scope = existing[1]
            conn.execute(
                text("""UPDATE consent SET scope = :scope, version = :version,
                    granted_at = :granted_at, revoked_at = NULL WHERE id = :id"""),
                {"id": consent_id, "scope": scope, "version": version, "granted_at": granted_at},
            )

        conn.execute(
            text("""INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES (:id, 'consent', :entity_id, 'scope', :old, :new, :actor, :ts)"""),
            {"id": str(uuid.uuid4()), "entity_id": consent_id, "old": old_scope,
             "new": scope, "actor": actor, "ts": granted_at},
        )
        return {"id": consent_id, "document_id": document_id, "scope": scope,
                "version": version, "granted_at": granted_at, "revoked_at": None}


def cloud_candidates(engine, settings, document_id):
    from smriti.candidates import Candidates
    from smriti.processing_store import identity, submission
    from smriti.spool import SpoolError

    with engine.connect() as conn:
        job = conn.execute(text("SELECT id FROM jobs WHERE document_id = :id"), {"id": document_id}).scalar_one_or_none()
        status = conn.execute(text("SELECT status FROM cloud_consent WHERE document_id = :id"), {"id": document_id}).scalar_one_or_none()
    if status != "awaiting" or not job:
        raise SpoolError("cloud_not_awaiting")
    row = submission(engine, job)
    return Candidates(engine, settings, job, identity(row))


def redaction_preview(engine, settings, document_id, offset=0):
    from PIL import Image
    import base64
    import io

    with cloud_candidates(engine, settings, document_id) as scratch:
        count = scratch.count("redaction")
        pages = []
        for item in scratch.range_rows("redaction", offset, 20):
            raw = base64.b64decode(item["jpeg_base64"], validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                width, height = image.size
            masks = [[int(x * 1000 / width), int(y * 1000 / height),
                      max(1, int(w * 1000 / width)), max(1, int(h * 1000 / height)), label, mask_id]
                     for x, y, w, h, label, mask_id in item.get("masks", [])]
            pages.append({"page_num": item["page"], "jpeg_base64": item["jpeg_base64"],
                          "sha256": item["sha256"], "masks": masks})
    return {"pages": pages, "total": count, "offset": offset, "has_more": offset + len(pages) < count}


def record_cloud_consent(engine, settings, document_id, payload, actor):
    from smriti.spool import SpoolError

    with cloud_candidates(engine, settings, document_id) as scratch:
        expected_pages = {str(item["page"]) for _, item, _ in scratch.rows("redaction")}
        if payload.approved and expected_pages != set(payload.extra_redaction_boxes):
            raise SpoolError("incomplete_redaction_review")
        for page in payload.extra_redaction_boxes:
            if scratch.matching("redaction", int(page), page) is None:
                raise SpoolError("invalid_redaction_page")
    status = "approved" if payload.approved else "declined"
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as conn:
        result = conn.execute(text("""UPDATE cloud_consent SET status = :status, extra_boxes_json = :boxes, updated_at = :now
            WHERE document_id = :id AND status = 'awaiting'"""),
            {"id": document_id, "status": status, "boxes": json.dumps(payload.extra_redaction_boxes), "now": now})
        if result.rowcount != 1:
            raise SpoolError("cloud_not_awaiting")
        conn.execute(text('''INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
            VALUES (:audit, 'document', :id, 'redacted_cloud_consent', 'awaiting', :status, :actor, :now)'''),
            {"audit": str(uuid.uuid4()), "id": document_id, "status": status, "actor": actor, "now": now})
    return {"document_id": document_id, "approved": payload.approved, "status": status}

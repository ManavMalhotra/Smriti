"""Stage queue, artifact caching, and VRAM release management.

Processes documents by stage (inspect -> ocr -> extract -> prose) and persists
stage artifacts keyed by (content_hash, page, stage, model_version).
GPU stages drain all pending pages, then terminate/release model context
so that 0 MiB VRAM remains before the next stage runs.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from smriti.ocr import OcrWord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_stage_artifact(
    conn: Connection,
    content_hash: str,
    page: int,
    stage: str,
    model_version: str,
    artifact: Any,
) -> None:
    now = _now()
    if isinstance(artifact, list) and artifact and isinstance(artifact[0], OcrWord):
        payload = [
            {"text": w.text, "bbox": w.bbox, "confidence": w.confidence}
            for w in artifact
        ]
    else:
        payload = artifact

    json_str = json.dumps(payload)
    conn.execute(
        text(
            """
            INSERT INTO stage_artifact
                (content_hash, page, stage, model_version, artifact_json, created_at)
            VALUES
                (:content_hash, :page, :stage, :model_version, :artifact_json, :created_at)
            ON CONFLICT(content_hash, page, stage, model_version) DO UPDATE SET
                artifact_json = excluded.artifact_json,
                created_at = excluded.created_at
            """
        ),
        {
            "content_hash": content_hash,
            "page": page,
            "stage": stage,
            "model_version": model_version,
            "artifact_json": json_str,
            "created_at": now,
        },
    )


def get_stage_artifact(
    conn: Connection,
    content_hash: str,
    page: int,
    stage: str,
    model_version: str | None = None,
) -> Any | None:
    if model_version:
        row = conn.execute(
            text(
                """
                SELECT artifact_json FROM stage_artifact
                WHERE content_hash = :content_hash AND page = :page
                  AND stage = :stage AND model_version = :model_version
                """
            ),
            {
                "content_hash": content_hash,
                "page": page,
                "stage": stage,
                "model_version": model_version,
            },
        ).first()
    else:
        row = conn.execute(
            text(
                """
                SELECT artifact_json FROM stage_artifact
                WHERE content_hash = :content_hash AND page = :page AND stage = :stage
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {
                "content_hash": content_hash,
                "page": page,
                "stage": stage,
            },
        ).first()

    if row is None:
        return None
    return json.loads(row[0])


def load_cached_ocr_words(
    conn: Connection,
    content_hash: str,
    page: int,
    model_version: str | None = None,
) -> list[OcrWord] | None:
    raw = get_stage_artifact(conn, content_hash, page, "ocr", model_version)
    if raw is None or not isinstance(raw, list):
        return None
    return [
        OcrWord(text=item["text"], bbox=item["bbox"], confidence=float(item["confidence"]))
        for item in raw
    ]


def release_gpu_memory() -> None:
    """Explicitly flush CUDA caches and triggers garbage collection to drop VRAM."""
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except (ImportError, Exception):
        pass

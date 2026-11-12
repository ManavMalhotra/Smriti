"""Stage queue, artifact caching, and VRAM release management.

Processes documents by stage (inspect -> ocr -> extract -> prose) and persists
stage artifacts keyed by (content_hash, page, stage, model_version).
The new runtime freezes membership and generates bounded windows lazily.
Owned process exit is required between stages; observed VRAM is not a zero-use guarantee.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from smriti.config import MAX_BATCH_SUBMISSIONS, MAX_WORKSET_PAGES
from smriti.ocr import OcrWord

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def execution_windows(members, cap=MAX_WORKSET_PAGES, *, member_position=0, next_page=1):
    """Frozen FIFO order; large documents run alone, short documents remain whole."""
    if not isinstance(members, (tuple, list)) or not 1 <= len(members) <= MAX_BATCH_SUBMISSIONS:
        raise ValueError("Execution requires 1–10 frozen members")
    if type(cap) is not int or not 1 <= cap <= MAX_WORKSET_PAGES:
        raise ValueError("Execution windows contain at most 20 pages")
    if type(member_position) is not int or not 0 <= member_position <= len(members) or type(next_page) is not int or next_page < 1:
        raise ValueError("Invalid execution cursor")
    for job_id, pages in members:
        if not isinstance(job_id, str) or not job_id or pages is not None and (type(pages) is not int or pages < 1):
            raise ValueError("Invalid frozen member")
    window, count = [], 0
    for position in range(member_position, len(members)):
        job_id, pages = members[position]
        if pages is None:  # A rejected member is never replaced by a later arrival.
            continue
        start = next_page if position == member_position else 1
        if start > pages or pages <= cap and start != 1:
            raise ValueError("Cursor cannot split a short document or pass its last page")
        if pages > cap:
            if window:
                yield {"members": window, "next_member": position, "next_page": start}
                window, count = [], 0
            for page in range(start, pages + 1, cap):
                end = min(page + cap - 1, pages)
                yield {"members": [{"job_id": job_id, "start": page, "end": end}],
                       "next_member": position + 1 if end == pages else position,
                       "next_page": 1 if end == pages else end + 1}
        else:
            if count + pages > cap:
                yield {"members": window, "next_member": position, "next_page": 1}
                window, count = [], 0
            window.append({"job_id": job_id, "start": 1, "end": pages})
            count += pages
    if window:
        yield {"members": window, "next_member": len(members), "next_page": 1}


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


def release_gpu_memory(worker_process: Any | None = None) -> None:
    """Explicitly terminate GPU worker process to unload VRAM.

    Per Architecture Order: 'One GPU model per process. Kill the process to unload.
    No empty_cache() unloads.'
    """
    if worker_process is not None:
        try:
            if hasattr(worker_process, "terminate"):
                worker_process.terminate()
                worker_process.join(timeout=5)
            elif hasattr(worker_process, "kill"):
                worker_process.kill()
        except Exception as exc:
            logger.warning("Failed to terminate GPU worker process: %s", exc)

    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.ipc_collect()
    except (ImportError, Exception):
        pass

"""One atomic clinical save from pre-resolved private candidates, never replacement writes."""

from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import text

from smriti.candidates import Candidates
from smriti.db import create_db_engine
from smriti.extract import ExtractedField
from smriti.job_progress import progress_transaction, record_progress
from smriti.output_quota import reserve_output
from smriti.preparation import SQL_HEADROOM_BYTES, _settings
from smriti.processing_store import identity, read_page, submission
from smriti.reports import fact_type_for, normalise_label
from smriti.spool import SpoolError, _now, check_free_space

_COLUMNS = {
    "report": "id document_id patient_id category report_type report_date facility_name title summary page_start page_end status reason model_version created_at",
    "observation": "id document_id report_id analyte_id label_raw label_norm value_num value_text unit_raw ref_low ref_high flag_printed bbox_json page engine confidence status reason mapping_rule source model_version fact_type evidence_quote clinical_json created_at",
    "medication": "id patient_id brand_raw dose freq status reported_at source_doc_id page bbox_json engine clinical_json start_date",
    "directive": "id document_id span_text span_start span_end action_type timing_type time_value time_unit anchor_event condition_text target anchor_date due_date state",
    "page_text": "document_id page text engine source model_version created_at",
}


def _rows(settings, row, scratch, table, now):
    if table == "report":
        for draft in scratch.reports():
            yield dict(draft, document_id=row["document_id"], patient_id=row["patient_id"], created_at=now)
    elif table == "observation":
        for kind in ("checked", "prose"):
            for _, item, report_id in scratch.rows(kind):
                field = ExtractedField(**item)
                page = read_page(settings, row, "ocr", field.page)
                yield {"id": str(uuid.uuid4()), "document_id": row["document_id"], "report_id": report_id,
                       "analyte_id": field.analyte_id, "label_raw": field.label_raw,
                       "label_norm": field.analyte_id or normalise_label(field.label_raw), "value_num": field.value_num,
                       "value_text": field.value_text, "unit_raw": field.unit_raw, "ref_low": field.ref_low,
                       "ref_high": field.ref_high, "flag_printed": field.flag_printed, "bbox_json": json.dumps(field.bbox),
                       "page": field.page, "engine": field.engine, "confidence": field.confidence, "status": "review",
                       "reason": field.reason or "Extracted locally; review required.", "mapping_rule": field.mapping_rule,
                       "source": page["source"], "model_version": field.engine if field.clinical_metadata else page["model_version"], "fact_type": fact_type_for(field),
                       "evidence_quote": field.evidence_quote or (field.value_text if field.value_num is None else None),
                       "clinical_json": json.dumps(field.clinical_metadata) if field.clinical_metadata else None, "created_at": now}
    elif table == "medication":
        for _, item, _ in scratch.rows("medication"):
            yield {"id": str(uuid.uuid4()), "patient_id": row["patient_id"], "brand_raw": item["brand_raw"],
                   "dose": item["dose"], "freq": item["freq"], "status": "prescribed", "reported_at": now,
                   "source_doc_id": row["document_id"], "page": item.get("page"), "bbox_json": json.dumps(item.get("bbox")) if item.get("bbox") else None,
                   "engine": item.get("engine"), "clinical_json": json.dumps(item["clinical_metadata"]) if item.get("clinical_metadata") else None,
                   "start_date": (item.get("clinical_metadata") or {}).get("event_date")}
    elif table == "directive":
        for _, item, _ in scratch.rows("directive"):
            yield dict(item, id=str(uuid.uuid4()), document_id=row["document_id"])
    elif table == "page_text":
        for page in range(1, row["page_count"] + 1):
            data = read_page(settings, row, "ocr", page)
            yield {"document_id": row["document_id"], "page": page, "text": data["text"],
                   "engine": data["engine"], "source": data["source"], "model_version": data["model_version"], "created_at": now}


def _batches(rows, max_bytes):
    batch, size = [], 0
    for row in rows:
        row_size = len(json.dumps(row, separators=(",", ":"), allow_nan=False).encode("utf-8"))
        if row_size > max_bytes:
            raise SpoolError("capacity_exhausted")
        if batch and (len(batch) == 100 or size + row_size > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += row_size
    if batch:
        yield batch


def publication_target(context, report):
    settings = _settings(context)
    engine = create_db_engine(settings.db_path).execution_options(progress_report=report)
    started = time.monotonic()
    try:
        row = submission(engine, context["job_id"])
        processing = row["manifest"].get("processing", {})
        if not processing.get("final_ready"):
            raise SpoolError("prepared_artifact_invalid")
        with Candidates(engine, settings, row["job_id"], identity(row)) as scratch:
            # Upper-bound new payloads and existing DB/WAL journal exposure before the clinical writer.
            payload_bytes = 0
            now = _now()
            for table in _COLUMNS:
                for batch in _batches(_rows(settings, row, scratch, table, now), settings.max_artifact_bytes):
                    payload_bytes += sum(len(json.dumps(item).encode("utf-8")) for item in batch)
            sqlite_bytes = sum(path.stat().st_size for path in (settings.db_path, settings.db_path.with_name(settings.db_path.name + "-wal")) if path.exists())
            # shortcut: conservative 4x SQL growth plus the existing file/WAL, calibrate only with RT-22.
            reserve_output(engine, settings, row["job_id"], sqlite_bytes + 4 * payload_bytes + SQL_HEADROOM_BYTES)
            with progress_transaction(engine) as conn:
                conn.execute(text("UPDATE submissions SET updated_at = updated_at WHERE job_id = :id"), {"id": row["job_id"]})
                current = conn.execute(text("""SELECT s.consent_revoked_at, j.state, d.status, c.revoked_at
                    FROM submissions s JOIN jobs j ON j.id = s.job_id JOIN document d ON d.id = s.document_id
                    JOIN consent c ON c.document_id = d.id WHERE s.job_id = :id"""), {"id": row["job_id"]}).first()
                if current is None or current[0] is not None or current[3] is not None or current[1] != "running" or current[2] not in {"queued", "processing"}:
                    raise SpoolError("cancelled")
                for table, owner in (("observation", "document_id"), ("medication", "source_doc_id"), ("directive", "document_id"), ("report", "document_id"), ("page_text", "document_id"), ("handwriting_field", "document_id")):
                    if conn.execute(text(f"SELECT 1 FROM {table} WHERE {owner} = :id LIMIT 1"), {"id": row["document_id"]}).first() is not None:
                        raise SpoolError("cancelled")
                record_progress(conn, row["job_id"], "saving", count=scratch.count("checked") + scratch.count("prose"))
                for table, names in _COLUMNS.items():
                    columns = names.split()
                    statement = text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(':' + name for name in columns)})")
                    for batch in _batches(_rows(settings, row, scratch, table, now), settings.max_artifact_bytes):
                        check_free_space(settings, settings.db_path.parent)
                        conn.execute(statement, batch)
                        report("checkpoint", count=len(batch))
                metadata = processing["metadata"]
                conn.execute(text("""UPDATE document SET doc_type = :type, doc_type_confidence = :confidence, status = 'done', processed_at = :now,
                    collection_date = COALESCE(collection_date, :collection_date), registration_date = COALESCE(registration_date, :registration_date),
                    report_date = COALESCE(report_date, :report_date), doc_date = COALESCE(doc_date, :doc_date),
                    patient_uhid = COALESCE(patient_uhid, :patient_uhid), doctor_reg_no = COALESCE(doctor_reg_no, :doctor_reg_no),
                    facility_name = COALESCE(facility_name, :facility_name), lab_name = COALESCE(lab_name, :facility_name) WHERE id = :id"""),
                    dict(metadata, type=processing["doc_type"], confidence=processing["confidence"], now=now, id=row["document_id"]))
                conn.execute(text("UPDATE jobs SET state = 'done', page = total, error = NULL WHERE id = :id"), {"id": row["job_id"]})
                record_progress(conn, row["job_id"], "done", count=scratch.count("checked") + scratch.count("prose"), duration=time.monotonic() - started)
                manifest = json.loads(conn.execute(text("SELECT preparation_manifest_json FROM submissions WHERE job_id = :id"), {"id": row["job_id"]}).scalar_one())
                manifest["processing"].update(final_committed=True, cleanup="pending")
                conn.execute(text("UPDATE submissions SET preparation_manifest_json = :manifest WHERE job_id = :id"),
                             {"id": row["job_id"], "manifest": json.dumps(manifest, separators=(",", ":"))})
    finally:
        engine.dispose()

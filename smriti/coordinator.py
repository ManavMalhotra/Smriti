"""Exclusive local FIFO controller. Models and clinical helpers run only in owned children."""

from __future__ import annotations

import json
import re
import threading
import uuid

import psutil
from sqlalchemy import text

from smriti.job_progress import progress_transaction, record_progress
from smriti.preparation import fail_preparation, page_metadata, prepare_submission, settings_context
from smriti.processing_store import (artifact_path, cleanup_processing, reconcile_processing,
    read_page, save_page, submission, update_processing, validate_source, identity)
from smriti.runtime import CoordinatorLock, StageResult, recover_stage_job, run_stage, sampler_job_name, QWEN_OPERATIONAL_FAILURES
from smriti.spool import SpoolError, _now, delete_spool, recover_spool
from smriti.stage import execution_windows

_TABLE_OWNERS = (("observation", "document_id"), ("report", "document_id"),
                 ("page_text", "document_id"), ("directive", "document_id"),
                 ("medication", "source_doc_id"), ("handwriting_field", "document_id"))


class CleanupBlocked(RuntimeError):
    pass


class StageInterrupted(CleanupBlocked):
    """Unknown supervisor outcome; only validated owned-tree recovery permits retry."""


class CoordinatorStopped(Exception):
    """Confirmed service pause; durable work is left resumable, not failed."""


def validate_checkpoint(members, cursor):
    """Recovery names and erased receipts must be validated before terminating or deleting anything."""
    try:
        if (not isinstance(members, list) or not 1 <= len(members) <= 10
                or any(not isinstance(job, str) or not re.fullmatch(r"[0-9a-f]{32}", job) for job in members)
                or len(set(members)) != len(members) or not isinstance(cursor, dict)
                or type(cursor.get("version")) is not int or cursor["version"] != 1
                or type(cursor.get("member")) is not int or not 0 <= cursor["member"] <= len(members)
                or type(cursor.get("next_page")) is not int or not 1 <= cursor["next_page"] <= 2**63 - 1
                or cursor.get("pass") not in {"preparing", "ocr", "qwen", "rules", "verification", "publication"}):
            raise ValueError
        erased = cursor.get("erased", [])
        if not isinstance(erased, list) or any(job not in members for job in erased) or len(set(erased)) != len(erased):
            raise ValueError
        window = cursor.get("window", [])
        if not isinstance(window, list) or len(window) > 10:
            raise ValueError
        for item in window:
            if (not isinstance(item, dict) or set(item) != {"job_id", "start", "end"}
                    or item["job_id"] not in members or type(item["start"]) is not int
                    or type(item["end"]) is not int or not 1 <= item["start"] <= item["end"] <= 2**63 - 1):
                raise ValueError
        if sum(item["end"] - item["start"] + 1 for item in window) > 20:
            raise ValueError
        active = cursor.get("active")
        if active is not None and (not isinstance(active, dict) or set(active) != {"name", "stage", "jobs"}
                or not isinstance(active["name"], str) or not re.fullmatch(r"[0-9a-f]{32}", active["name"])
                or active["stage"] not in {"inspection", "preparing", "ocr", "qwen", "extraction", "cross_check", "saving"}
                or not isinstance(active["jobs"], list) or not active["jobs"]
                or any(job not in members for job in active["jobs"]) or len(set(active["jobs"])) != len(active["jobs"])):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise CleanupBlocked("Batch checkpoint requires validated recovery") from None


class Coordinator:
    def __init__(self, engine, settings, *, supervisor=run_stage, recover_tree=recover_stage_job,
                 stop=None, diagnostics=None):
        self.engine, self.settings = engine, settings
        self.supervisor, self.recover_tree = supervisor, recover_tree
        self.stop = stop if stop is not None else threading.Event()
        self.diagnostics = diagnostics
        self.engine = engine.execution_options(progress_report=self._report_progress)
        self.token = uuid.uuid4().hex
        self.lock = CoordinatorLock(settings.db_path)
        self.batch = None
        self.cursor = None
        self.held = False

    def __enter__(self):
        self.lock.__enter__()
        self.held = True
        return self

    def __exit__(self, *args):
        self.held = False
        self.lock.__exit__(*args)

    def _emit(self, event, **fields):
        if self.diagnostics is not None:
            try:
                self.diagnostics.emit(event, component="worker", batch_id=self.batch, **fields)
            except Exception:
                pass  # Diagnostic delivery must not change processing or cleanup eligibility.

    def _report_progress(self, event, **fields):
        if event == "progress":
            name = (self.cursor or {}).get("active") or {}
            self._emit(fields.pop("progress_event"), stage_attempt_id=name.get("name"), **fields)

    def _save(self, *, state="processing", stage=None, **changes):
        if not self.held:
            raise RuntimeError("Coordinator lock is required")
        self.cursor.update(changes)
        with self.engine.begin() as conn:
            result = conn.execute(text("""UPDATE stage_batches SET state = :state, stage = :stage,
                checkpoints_json = :cursor, worksets_json = :window, updated_at = :now
                WHERE id = :id AND owner_token = :owner"""),
                {"id": self.batch, "owner": self.token, "state": state,
                 "stage": stage or self.cursor.get("pass", "preparing"),
                 "cursor": json.dumps(self.cursor, separators=(",", ":")),
                 "window": json.dumps(self.cursor.get("window", [])), "now": _now()})
            if result.rowcount != 1:
                raise CleanupBlocked("Coordinator ownership was lost")

    def _run(self, target, context, **options):
        ids = [item["job_id"] for item in context["members"]] if "members" in context else [context["job_id"]]
        name = uuid.uuid4().hex
        stage = {"inspection_target": "inspection", "preparation_target": "preparing",
                 "validation_target": "preparing", "ocr_target": "ocr", "qwen_target": "qwen",
                 "rules_target": "extraction", "verification_target": "cross_check",
                 "publication_target": "saving"}[target.split(":")[1]]
        self._save(stage=stage, active={"name": name, "stage": stage, "jobs": ids})
        self._emit("stage_started", stage=stage, stage_attempt_id=name)
        ranges = context.get("members") or ([{"job_id": ids[0], "start": context["start"], "end": context["end"]}] if "start" in context else [])
        for member in ranges:
            self._emit("window_started", job_id=member["job_id"], stage=stage, stage_attempt_id=name,
                       window_start=member["start"], window_end=member["end"])
        def on_event(message):
            if message["event"] == "progress" and message.get("job_id") in ids:
                self._report_progress(**message)
        try:
            result = self.supervisor(target, context, **options, job_name=name, telemetry_settings=self.settings, on_event=on_event)
        except BaseException:
            self._save(state="cleanup_failed")
            raise StageInterrupted("Stage outcome unavailable; owned recovery required") from None
        self._emit("stage_finished", stage=stage, stage_attempt_id=name, code=result.status,
                   duration_ms=result.duration_seconds * 1000, exit_code=result.exit_code,
                   cleanup_outcome="confirmed" if result.cleanup_confirmed else "unconfirmed")
        from smriti.runtime_telemetry import StageTelemetry

        measurements = result.telemetry or StageTelemetry(self.settings).summary()
        for metric, values in measurements.get("metrics", {}).items():
            self._emit("stage_measurement", stage=stage, stage_attempt_id=name, metric=metric, **values)
        with self.engine.begin() as conn:
            raw = conn.execute(text("SELECT telemetry_json FROM stage_batches WHERE id = :id"), {"id": self.batch}).scalar_one()
            summary = json.loads(raw)
            summary[stage] = {"attempt_id": name, "status": result.status, "duration_seconds": result.duration_seconds,
                              "cleanup_confirmed": result.cleanup_confirmed, "measurements": result.telemetry}
            conn.execute(text("UPDATE stage_batches SET telemetry_json = :summary WHERE id = :id AND owner_token = :owner"),
                         {"id": self.batch, "owner": self.token, "summary": json.dumps(summary, separators=(",", ":"))})
        if not result.cleanup_confirmed:
            self._save(state="cleanup_failed")
            for job in ids:
                self._progress(job, "cleanup_failed" if self._row(job)["state"] == "promoted" else "intake_cleanup_failed")
            raise CleanupBlocked("Owned stage exit is unconfirmed")
        self._save(active=None)
        if self.stop.is_set():
            raise CoordinatorStopped
        return result

    def _progress(self, job, event, **fields):
        with progress_transaction(self.engine) as conn:
            record_progress(conn, job, event, **fields)

    def _clean(self, row):
        if row["state"] == "promoted":
            processing_cleaned = cleanup_processing(self.engine, self.settings, row["job_id"])
            self._emit("processing_deleted" if processing_cleaned else "processing_cleanup_failed", job_id=row["job_id"],
                       cleanup_outcome="confirmed" if processing_cleaned else "unconfirmed")
            cleaned = delete_spool(self.engine, self.settings, row["job_id"]) and processing_cleaned
        elif row["spool_cleanup_state"] == "debug_retained":
            cleaned = True  # Crash opt-in already cleaned partials; only owner erasure removes retained raw.
        else:
            cleaned = fail_preparation(self.engine, self.settings, row["job_id"], StageResult(row["error_code"] or "cancelled", True, 0, 0))
        state = self._row(row["job_id"])["spool_cleanup_state"]
        self._emit("spool_deleted" if state == "deleted" else "spool_debug_retained" if state == "debug_retained" else "spool_cleanup_failed", job_id=row["job_id"],
                   cleanup_outcome="confirmed" if state == "deleted" else "not_required" if state == "debug_retained" else "unconfirmed")
        return cleaned

    def _row(self, job):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT * FROM submissions WHERE job_id = :id"), {"id": job}).mappings().first()

    def _recover_intake(self):
        if recover_spool(self.engine, self.settings):
            return
        cursor = ""
        while True:
            with self.engine.connect() as conn:
                rows = conn.execute(text("""SELECT * FROM submissions WHERE job_id > :cursor
                    AND state IN ('failed', 'rejected', 'cancelled') AND spool_cleanup_state IN ('pending', 'failed')
                    ORDER BY job_id LIMIT 20"""), {"cursor": cursor}).mappings().all()
            if not rows:
                break
            for row in rows:
                if not self._clean(row):
                    raise CleanupBlocked("Ephemeral source cleanup is unconfirmed")
            cursor = rows[-1]["job_id"]
        if not recover_spool(self.engine, self.settings):
            raise CleanupBlocked("Ephemeral source recovery is unconfirmed")

    def _eligible(self, job):
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT s.total_pages FROM submissions s
                JOIN jobs j ON j.id = s.job_id JOIN document d ON d.id = s.document_id
                JOIN consent c ON c.document_id = d.id WHERE s.job_id = :id AND s.state = 'promoted'
                AND s.consent_revoked_at IS NULL AND c.revoked_at IS NULL
                AND j.state IN ('queued', 'running') AND d.status IN ('queued', 'processing')"""), {"id": job}).first()
            if row is None:
                return None
            document = conn.execute(text("SELECT document_id FROM submissions WHERE job_id = :id"), {"id": job}).scalar_one()
            for table, owner in _TABLE_OWNERS:
                if conn.execute(text(f"SELECT 1 FROM {table} WHERE {owner} = :id LIMIT 1"), {"id": document}).first():
                    return None
            return row[0]

    def _fail(self, jobs, code, *, stage=None):
        for job in jobs:
            row = self._row(job)
            if row is None:
                raise CleanupBlocked("Cleanup metadata is missing")
            if row["state"] == "promoted":
                with progress_transaction(self.engine) as conn:
                    changed = conn.execute(text("UPDATE jobs SET state = 'failed', error = 'Local processing failed; source remains stored.' WHERE id = :id AND state IN ('queued', 'running')"), {"id": job})
                    if changed.rowcount:
                        record_progress(conn, job, "failed", failed_stage=stage)
                        conn.execute(text("UPDATE document SET status = 'failed' WHERE id = :id AND status IN ('queued', 'processing')"), {"id": row["document_id"]})
                        conn.execute(text("UPDATE submissions SET error_code = :code WHERE job_id = :id"), {"id": job, "code": code})
            if not self._clean(row):
                self._save(state="cleanup_failed")
                raise CleanupBlocked("Disposable cleanup is unconfirmed")

    def _load_or_freeze(self):
        process = psutil.Process()
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE stage_batches SET updated_at = updated_at WHERE state IN ('preparing', 'processing', 'cleanup_failed')"))
            batch = conn.execute(text("SELECT * FROM stage_batches WHERE state IN ('preparing', 'processing', 'cleanup_failed')")).mappings().first()
            if batch is not None:
                self.batch = batch["id"]
                self.cursor = json.loads(batch["checkpoints_json"])
                conn.execute(text("UPDATE stage_batches SET owner_token = :owner, owner_pid = :pid, owner_created_at = :created, attempt = attempt + 1 WHERE id = :id"),
                             {"id": self.batch, "owner": self.token, "pid": process.pid, "created": process.create_time()})
                members = json.loads(batch["membership_json"])
            else:
                members = conn.execute(text("""SELECT s.job_id FROM submissions s LEFT JOIN jobs j ON j.id = s.job_id
                    WHERE s.batch_id IS NULL AND (s.state IN ('pending_intake', 'preparing')
                        OR (s.state = 'promoted' AND j.state = 'queued'))
                    ORDER BY s.created_at, s.job_id LIMIT :cap"""), {"cap": self.settings.max_batch_submissions}).scalars().all()
                if not members:
                    return []
                self.batch = uuid.uuid4().hex
                self.cursor = {"version": 1, "member": 0, "pass": "preparing", "next_page": 1, "active": None}
                conn.execute(text("""INSERT INTO stage_batches (id, state, owner_token, owner_pid, owner_created_at,
                    membership_json, checkpoints_json, created_at, updated_at) VALUES
                    (:id, 'preparing', :owner, :pid, :created, :members, :cursor, :now, :now)"""),
                    {"id": self.batch, "owner": self.token, "pid": process.pid, "created": process.create_time(),
                     "members": json.dumps(members), "cursor": json.dumps(self.cursor), "now": _now()})
                for position, job in enumerate(members):
                    conn.execute(text("UPDATE submissions SET batch_id = :batch, batch_position = :position WHERE job_id = :id AND batch_id IS NULL"),
                                 {"id": job, "batch": self.batch, "position": position})
        validate_checkpoint(members, self.cursor)
        if any(self._row(job) is None and job not in self.cursor.get("erased", []) for job in members):
            raise CleanupBlocked("Cleanup metadata is missing")
        active = self.cursor.get("active")
        if active:
            if (not self.recover_tree(active.get("name"), self.settings.cleanup_wait_seconds)
                    or not self.recover_tree(sampler_job_name(active.get("name")), self.settings.cleanup_wait_seconds)):
                self._save(state="cleanup_failed")
                raise CleanupBlocked("Prior stage tree is unconfirmed")
            self._save(active=None)
        return members

    def recover(self):
        """Keep admission closed until prior ownership and durable inputs are validated."""
        from smriti.candidates import Candidates, candidate_path

        members = self._load_or_freeze()
        self._recover_intake()
        for job in members:
            if self.stop.is_set():
                raise CoordinatorStopped
            if self._eligible(job) is None:
                continue
            self._progress(job, "recovering")
            try:
                row = submission(self.engine, job)
                processing = row["manifest"].get("processing", {})
                reconcile_processing(self.engine, self.settings, job)
                for page in range(1, row["page_count"] + 1):
                    if self.stop.is_set():
                        raise CoordinatorStopped
                    validate_source(self.settings, row, page)
                    for stage in ("ocr", "qwen"):
                        data = read_page(self.settings, row, stage, page)
                        required = (stage == "ocr" and processing.get("rules_ready")
                                    or stage == "qwen" and processing.get("final_ready") and self.settings.vlm_enabled
                                    and page_metadata(self.settings, job, page)["capture_type"] == "printed"
                                    and row["capture_type"] == "printed")
                        if required and data is None:
                            raise SpoolError("prepared_artifact_invalid")
                if processing.get("rules_ready") and not candidate_path(self.settings, job).exists():
                    raise SpoolError("prepared_artifact_invalid")
                if candidate_path(self.settings, job).exists():
                    with Candidates(self.engine, self.settings, job, identity(row)):
                        pass
            except (SpoolError, OSError, ValueError, KeyError) as exc:
                raise CleanupBlocked("Saved processing artifacts require validated recovery") from exc
        for job in members:
            if self.stop.is_set():
                raise CoordinatorStopped
            if self._eligible(job) is not None:
                self._progress(job, "recovered")

    def _degrade_qwen(self, job, code):
        from smriti.vlm import VLM_ENGINE_NAME

        if code not in QWEN_OPERATIONAL_FAILURES:
            raise SpoolError("prepared_artifact_invalid")
        row = submission(self.engine, job)
        # Commit the decision first: an interrupted marker write must not retry the model.
        update_processing(self.engine, job, qwen_unavailable_reason=code)
        completed = 0
        for page in range(1, row["page_count"] + 1):
            if self.stop.is_set():
                raise CoordinatorStopped
            submission(self.engine, job)
            metadata = validate_source(self.settings, row, page)
            if read_page(self.settings, row, "ocr", page) is None:
                raise SpoolError("prepared_artifact_invalid")
            if metadata["capture_type"] == "handwritten":
                continue
            cached = read_page(self.settings, row, "qwen", page)
            completed += 1
            if cached is None:
                save_page(self.engine, self.settings, row, "qwen", page, fields=[],
                          model_version=VLM_ENGINE_NAME, outcome="unavailable", error_code=code)
                self._progress(job, "qwen_unavailable_page", model=VLM_ENGINE_NAME, page=page,
                               completed=completed, total=row["manifest"]["printed_pages"])

    def _model_pass(self, stage, group):
        if stage == "qwen":
            for job, pages in group:
                if pages is not None and self._eligible(job) is not None:
                    reason = submission(self.engine, job)["manifest"].get("processing", {}).get("qwen_unavailable_reason")
                    if reason is not None:
                        self._degrade_qwen(job, reason)
        while True:
            eligible = [(job, self._eligible(job) if pages is not None else None) for job, pages in group]
            if stage == "qwen":
                for position, (job, pages) in enumerate(eligible):
                    if pages is not None and submission(self.engine, job)["manifest"].get("processing", {}).get("qwen_unavailable_reason"):
                        eligible[position] = (job, None)
            failed = False
            for window in execution_windows(eligible, self.settings.max_workset_pages):
                self._save(**{"pass": stage, "next_page": window["members"][0]["start"], "window": window["members"]})
                count = 0
                for member in window["members"]:
                    try:
                        for page in range(member["start"], member["end"] + 1):
                            metadata = page_metadata(self.settings, member["job_id"], page)
                            required = not metadata["words_sha256"] if stage == "ocr" else metadata["capture_type"] == "printed"
                            if required and not artifact_path(self.settings, member["job_id"], stage, page).exists():
                                count += 1
                    except (SpoolError, OSError, ValueError, KeyError):
                        self._fail([member["job_id"]], "prepared_artifact_invalid", stage=stage)
                        failed = True
                        break
                if failed:
                    break
                context = {"settings": settings_context(self.settings), "members": window["members"]}
                options = dict(timeout_seconds=self.settings.ocr_timeout_seconds(count) if stage == "ocr" else self.settings.vlm_timeout_seconds(count),
                               cleanup_wait_seconds=self.settings.cleanup_wait_seconds, cpu_only=stage == "ocr",
                               memory_limit_bytes=self.settings.native_memory_bytes, stop=self.stop)
                if stage == "ocr":
                    context["backend"] = "rapid"
                else:
                    options["request_timeout_seconds"] = self.settings.vlm_request_seconds
                result = self._run(f"smriti.model_stages:{stage}_target", context, **options)
                if (stage == "ocr" and result.status == "ocr_initialization_failed"
                        and self.settings.ocr_allow_paddle_fallback):
                    context["backend"] = "paddle"
                    result = self._run("smriti.model_stages:ocr_target", context, **options)
                if not result.success:
                    jobs = [item["job_id"] for item in window["members"]]
                    if stage == "qwen" and result.status in QWEN_OPERATIONAL_FAILURES:
                        for job in [result.job_id] if result.job_id in jobs else jobs:
                            try:
                                self._degrade_qwen(job, result.status)
                            except SpoolError as exc:
                                self._fail([job], exc.code, stage=stage)
                        failed = True
                        break  # Rebuild the window so unaffected members still receive their readings.
                    self._fail([result.job_id] if result.job_id in jobs else jobs, result.status, stage=stage)
                    failed = True
                    break  # Rebuild lazily from remaining members; no failed member is replaced.
            if not failed:
                return

    def _helper(self, job, target):
        self._save(**{"pass": target.split("_")[0], "next_page": 1, "window": []})
        timeout = self.settings.helper_timeout_seconds
        if target == "verification_target" and self.settings.gemini_api_key:
            pages = self._row(job)["total_pages"]
            timeout += 120 * ((pages + self.settings.max_workset_pages - 1) // self.settings.max_workset_pages)
        result = self._run(f"smriti.{ 'publication' if target == 'publication_target' else 'processing_helpers'}:{target}",
                           {"settings": settings_context(self.settings), "job_id": job},
                           timeout_seconds=timeout, cpu_only=True,
                           memory_limit_bytes=self.settings.native_memory_bytes,
                           cleanup_wait_seconds=self.settings.cleanup_wait_seconds, stop=self.stop)
        if not result.success:
            self._fail([job], result.status, stage={"rules_target": "extraction", "verification_target": "cross_check", "publication_target": "saving"}[target])
        return result.success

    def process_batch(self):
        if not self.held:
            raise RuntimeError("Coordinator lock is required")
        if self.stop.is_set():
            return False
        members = self._load_or_freeze()
        self._recover_intake()
        if not members:
            return False
        for job in members:
            row = self._row(job)
            if row is None and job in self.cursor.get("erased", []):
                continue
            if row["state"] in {"pending_intake", "preparing"}:
                result = prepare_submission(self.engine, self.settings, job, stop=self.stop, supervisor=self._run)
                row = self._row(job)
                if row["spool_cleanup_state"] == "deleted":
                    self._emit("spool_deleted", job_id=job, stage="preparing", cleanup_outcome="confirmed")
                if not result.success and not self._clean(row):
                    self._save(state="cleanup_failed")
                    raise CleanupBlocked("Preparation cleanup is unconfirmed")
            if row["state"] == "promoted":
                if self._eligible(job) is None:
                    self._fail([job], "cancelled")
                else:
                    try:
                        reconcile_processing(self.engine, self.settings, job)
                    except SpoolError as exc:
                        self._fail([job], exc.code)
                    except (OSError, ValueError):
                        self._fail([job], "prepared_artifact_invalid")
        while self.cursor["member"] < len(members):
            if self.stop.is_set():
                return True
            pairs = [(job, self._eligible(job)) for job in members]
            window = next(execution_windows(pairs, self.settings.max_workset_pages, member_position=self.cursor["member"]), None)
            if window is None:
                break
            group_ids = [item["job_id"] for item in window["members"]]
            group = [(job, self._eligible(job)) for job in group_ids]
            end_member = max(members.index(job) for job in group_ids) + 1
            for job in group_ids:
                with progress_transaction(self.engine) as conn:
                    conn.execute(text("UPDATE jobs SET state = 'running' WHERE id = :id AND state = 'queued'"), {"id": job})
                    conn.execute(text("UPDATE document SET status = 'processing' WHERE id = :id AND status = 'queued'"), {"id": self._row(job)["document_id"]})
                    record_progress(conn, job, "started")
            self._model_pass("ocr", group)
            for job in group_ids:
                if self._eligible(job) is not None:
                    self._helper(job, "rules_target")
            if self.settings.gemini_api_key and not self.settings.demo:
                with self.engine.connect() as conn:
                    awaiting = conn.execute(text("""SELECT 1 FROM cloud_consent cc
                        JOIN consent c ON c.document_id = cc.document_id
                        JOIN submissions s ON s.document_id = cc.document_id
                        WHERE s.batch_id = :batch AND cc.status = 'awaiting'
                          AND c.scope = 'local_plus_projection' AND c.revoked_at IS NULL
                          AND s.consent_revoked_at IS NULL LIMIT 1"""), {"batch": self.batch}).first()
                if awaiting:
                    return False
            if self.settings.vlm_enabled:
                printed = []
                with self.engine.connect() as conn:
                    for job, pages in group:
                        capture = conn.execute(text("SELECT d.capture_type FROM document d JOIN submissions s ON s.document_id = d.id WHERE s.job_id = :id"), {"id": job}).scalar_one()
                        printed.append((job, pages if capture == "printed" else None))
                self._model_pass("qwen", printed)
            for job in group_ids:
                if self._eligible(job) is not None and self._helper(job, "verification_target"):
                    self._helper(job, "publication_target")
                if self._eligible(job) is None:
                    self._fail([job], "cancelled")
                if not self._clean(self._row(job)):
                    self._save(state="cleanup_failed")
                    raise CleanupBlocked("Final disposable cleanup is unconfirmed")
            self._save(member=end_member, next_page=1, window=[])
        self._save(state="done", stage="done", member=len(members), window=[], active=None)
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE stage_batches SET finished_at = :now WHERE id = :id AND owner_token = :owner"), {"id": self.batch, "owner": self.token, "now": _now()})
        return True

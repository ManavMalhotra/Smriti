"""Private, quota-accounted candidates. No clinical rows are used as processing scratch."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from smriti.extract import ExtractedField as Candidate


@dataclass(frozen=True)
class MaskReviewPage:
    page: int
    jpeg_base64: str
    sha256: str
    masks: list


def clinical_candidate(item, engine_name: str | None = None) -> Candidate:
    import re
    from smriti.checks import check_bounds
    from smriti.engines import GEMINI_FLASH_HIGH
    from smriti.resolution import resolve

    if engine_name is None:
        engine_name = GEMINI_FLASH_HIGH

    metadata = item.model_dump(mode="json")
    if item.category == "medication":
        regimen = f"{item.title} {item.value_text}"
        if re.search(r"\bOR\b", regimen, re.I):
            metadata["regimen_type"] = "alternative_or"
        elif re.search(r"\b(?:SOS|PRN)\b", regimen, re.I):
            metadata["regimen_type"] = "sos_prn"
    if item.category == "lab_result" and item.report_date and item.event_date.year > item.report_date.year:
        # Date repair stays explicit and review-required, never silently becoming a verified fact.
        original = item.event_date
        year = item.report_date.year
        while year > 0:
            try:
                corrected = original.replace(year=year)
            except ValueError:
                year -= 1
                continue
            if corrected <= item.report_date:
                break
            year -= 1
        else:
            raise ValueError("Historical lab date cannot be reconciled")
        metadata.update(event_date=corrected.isoformat(), original_event_date=original.isoformat(), date_needs_review=True)
    y0, x0, y1, x1 = item.bbox_2d
    metadata["source_anchors"] = [{"page_num": item.source_page, "bbox_2d": item.bbox_2d}]
    number = str(item.value_num) if item.value_num is not None else None
    low = str(item.ref_min) if item.ref_min is not None else None
    high = str(item.ref_max) if item.ref_max is not None else None
    resolution = resolve(item.title, number, item.unit, low, high) if item.category == "lab_result" else None
    analyte = resolution.analyte_id if resolution else None
    _, bounds_reason = check_bounds(analyte, number)
    return Candidate(analyte_id=analyte, label_raw=item.title, value_num=number, value_text=item.value_text,
        unit_raw=item.unit, ref_low=low, ref_high=high, flag_printed=None,
        bbox=[x0 / 1000, y0 / 1000, x1 / 1000, y1 / 1000], page=item.source_page,
        confidence=.6 if item.confidence_note == "deciphered_handwriting" else .8,
        mapping_rule=resolution.mapping_rule if resolution else "unresolved", engine=engine_name or GEMINI_FLASH_HIGH,
        reason=bounds_reason or ("AI date correction; review required." if metadata.get("date_needs_review")
                                else "Redacted cloud extraction; review required."), clinical_metadata=metadata)

from smriti.output_quota import release_output, reserve_output
from smriti.private_paths import check_path, private_directory
from smriti.spool import SpoolError

APPLICATION_ID = 0x534D5254
CANDIDATE_VERSION = 1


def candidate_path(settings, job_id):
    import re

    if not isinstance(job_id, str) or not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise SpoolError("prepared_artifact_invalid")
    return settings.upload_dir / ".runtime" / job_id / "candidates.sqlite"


class Candidates:
    def __init__(self, engine, settings, job_id, identity, *, create=False):
        self.engine, self.settings, self.job_id = engine, settings, job_id
        self.path = candidate_path(settings, job_id)
        check_path(self.path)
        for suffix in ("-journal", "-wal", "-shm"):
            check_path(self.path.with_name(self.path.name + suffix))
        self.conn = None
        self.identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
        if not self.path.exists():
            if not create:
                raise SpoolError("prepared_artifact_invalid")
            private_directory(self.path.parent)
            charge = 128 * 1024
            reserve_output(engine, settings, job_id, charge)
            # The exclusive file is owned before SQLite touches it; interrupted creation remains charged.
            with self.path.open("xb"):
                pass
            self._open()
            try:
                self.conn.executescript(f"""
                    PRAGMA application_id = {APPLICATION_ID};
                    PRAGMA user_version = {CANDIDATE_VERSION};
                    CREATE TABLE identity (value TEXT NOT NULL);
                    CREATE TABLE candidate (
                        sequence INTEGER PRIMARY KEY, kind TEXT NOT NULL, dedup TEXT NOT NULL,
                        page INTEGER, match_key TEXT, payload TEXT NOT NULL, report_id TEXT,
                        UNIQUE(kind, dedup));
                    CREATE INDEX candidate_kind_order ON candidate(kind, sequence);
                    CREATE INDEX candidate_match ON candidate(kind, page, match_key);
                    CREATE TABLE report (id TEXT PRIMARY KEY, page_start INTEGER NOT NULL,
                        page_end INTEGER NOT NULL, payload TEXT NOT NULL);
                    CREATE INDEX report_pages ON report(page_start);
                """)
                self.conn.execute("INSERT INTO identity VALUES (?)", (self.identity,))
                self.conn.commit()
                release_output(engine, job_id, charge - self.size())
            except BaseException:
                self.close()
                raise
        else:
            probe = sqlite3.connect(self.path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                if (probe.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                        or probe.execute("PRAGMA user_version").fetchone()[0] != CANDIDATE_VERSION
                        or probe.execute("SELECT value FROM identity").fetchone() != (self.identity,)):
                    raise SpoolError("prepared_artifact_invalid")
            finally:
                probe.close()
            self._open()
        try:
            if (self.conn.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID
                    or self.conn.execute("PRAGMA user_version").fetchone()[0] != CANDIDATE_VERSION
                    or self.conn.execute("SELECT value FROM identity").fetchone() != (self.identity,)):
                raise SpoolError("prepared_artifact_invalid")
        except BaseException:
            self.close()
            raise

    def _open(self):
        self.conn = sqlite3.connect(self.path, timeout=5)
        self.conn.execute("PRAGMA journal_mode = DELETE")
        self.conn.execute("PRAGMA cache_size = -2048")
        self.conn.execute("PRAGMA mmap_size = 0")
        self.conn.execute("PRAGMA temp_store = MEMORY")
        self.conn.execute("PRAGMA synchronous = FULL")

    def size(self):
        return sum(path.stat().st_size for path in (self.path, self.path.with_name(self.path.name + "-journal")) if path.exists())

    def _write(self, sql, parameters, payload_bytes=0):
        before = self.size()
        # A rollback journal may copy the whole scratch DB; reserve that plus capped growth first.
        growth = 3 * payload_bytes + 64 * 1024
        charge = before + growth
        reserve_output(self.engine, self.settings, self.job_id, charge)
        self.conn.execute(f"PRAGMA max_page_count = {(before + growth) // 4096}")
        try:
            with self.conn:
                self.conn.execute(sql, parameters)
        except BaseException:
            self.conn.rollback()
            # Keep the charge after a write failure; recovery confirms absence/actual sizes.
            raise
        release_output(self.engine, self.job_id, charge - (self.size() - before))

    def add(self, kind, value, *, dedup=None, match_key=None, replace=False):
        if kind not in {"field", "medication", "vlm", "checked", "prose", "directive", "section", "redaction", "cloud"}:
            raise ValueError("Unknown candidate kind")
        payload = json.dumps(asdict(value), separators=(",", ":"), default=lambda item: item.isoformat(), allow_nan=False)
        size = len(payload.encode("utf-8"))
        if size > self.settings.max_artifact_bytes:
            raise SpoolError("capacity_exhausted")
        if dedup is None:
            dedup = str(self.conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM candidate").fetchone()[0])
        encoded_key = json.dumps(dedup, separators=(",", ":"))
        sql = "INSERT INTO candidate (kind, dedup, page, match_key, payload) VALUES (?, ?, ?, ?, ?) ON CONFLICT(kind, dedup) "
        sql += "DO UPDATE SET payload = excluded.payload" if replace else "DO NOTHING"
        self._write(sql, (kind, encoded_key, getattr(value, "page", None), match_key, payload), size + len(encoded_key.encode("utf-8")))

    def rows(self, kind):
        cursor = self.conn.execute("SELECT sequence, payload, report_id FROM candidate WHERE kind = ? ORDER BY sequence", (kind,))
        for sequence, payload, report_id in cursor:
            yield sequence, json.loads(payload), report_id

    def matching(self, kind, page, key):
        row = self.conn.execute("SELECT payload FROM candidate WHERE kind = ? AND page = ? AND match_key = ? ORDER BY sequence LIMIT 1", (kind, page, key)).fetchone()
        return json.loads(row[0]) if row else None

    def deduplicated(self, kind, key):
        row = self.conn.execute("SELECT payload FROM candidate WHERE kind = ? AND dedup = ?",
                                (kind, json.dumps(key, separators=(",", ":")))).fetchone()
        return json.loads(row[0]) if row else None

    def sections(self, page):
        from smriti.prose import ProseSection

        for (payload,) in self.conn.execute("SELECT payload FROM candidate WHERE kind = 'section' AND page = ? ORDER BY sequence", (page,)):
            yield ProseSection(**json.loads(payload))

    def add_report(self, report):
        payload = json.dumps(asdict(report), separators=(",", ":"), allow_nan=False)
        self._write("INSERT INTO report VALUES (?, ?, ?, ?)", (report.id, report.page_start, report.page_end, payload), len(payload.encode("utf-8")))

    def reports(self):
        for (payload,) in self.conn.execute("SELECT payload FROM report ORDER BY page_start"):
            yield json.loads(payload)

    def associate_reports(self):
        for (sequence, page) in self.conn.execute("SELECT sequence, page FROM candidate WHERE kind IN ('checked', 'prose') ORDER BY sequence"):
            row = self.conn.execute("SELECT id FROM report WHERE page_start <= ? AND page_end >= ? ORDER BY page_start DESC LIMIT 1", (page, page)).fetchone()
            self._write("UPDATE candidate SET report_id = ? WHERE sequence = ?", (row[0] if row else None, sequence))

    def count(self, kind):
        return self.conn.execute("SELECT COUNT(*) FROM candidate WHERE kind = ?", (kind,)).fetchone()[0]

    def range_rows(self, kind, offset=0, limit=20):
        for payload, in self.conn.execute("SELECT payload FROM candidate WHERE kind = ? ORDER BY sequence LIMIT ? OFFSET ?", (kind, limit, offset)):
            yield json.loads(payload)

    def reset(self):
        self._write("DELETE FROM candidate", ())
        self._write("DELETE FROM report", ())

    def clear_checked(self):
        self._write("DELETE FROM candidate WHERE kind IN ('checked', 'vlm')", ())

    def close(self):
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

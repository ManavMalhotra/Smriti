from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from smriti.db import SCHEMA_VERSION, init_db

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "patient",
    "document",
    "report",
    "consent",
    "observation",
    "directive",
    "medication",
    "handwriting_field",
    "egress",
    "audit",
    "jobs",
    "share_token",
    "auth_session",
    "page_text",
    "stage_artifact",
    "submissions",
    "stage_batches",
}


def _insert_patient(conn, patient_id: str = "p1") -> None:
    conn.execute(
        text(
            "INSERT INTO patient (id, alias, created_at) "
            "VALUES (:id, :alias, :created_at)"
        ),
        {"id": patient_id, "alias": "P-01", "created_at": "2026-10-23T00:00:00Z"},
    )


def _insert_document(conn, capture_type: str = "printed", document_id: str = "d1") -> None:
    conn.execute(
        text(
            """
            INSERT INTO document
                (id, patient_id, doc_type, capture_type, image_path,
                 page_count, content_hash, status, created_at)
            VALUES
                (:id, 'p1', 'lab_report', :capture_type, :image_path,
                 1, :content_hash, 'queued', '2026-10-23T00:00:00Z')
            """
        ),
        {
            "id": document_id,
            "capture_type": capture_type,
            "image_path": document_id,
            "content_hash": f"hash-{document_id}",
        },
    )


def _insert_observation(conn, status: str, value_num: str | None, observation_id: str = "o1") -> None:
    conn.execute(
        text(
            """
            INSERT INTO observation
                (id, document_id, analyte_id, value_num, bbox_json, page,
                 engine, status, created_at)
            VALUES
                (:id, 'd1', 'hemoglobin', :value_num, '[0.1,0.2,0.3,0.4]', 1,
                 'test', :status, '2026-10-23T00:00:00Z')
            """
        ),
        {"id": observation_id, "value_num": value_num, "status": status},
    )


def test_schema_creates_all_tables(app):
    with app.state.engine.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        assert EXPECTED_TABLES <= names
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == SCHEMA_VERSION
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1


def test_foreign_keys_are_enforced(app):
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO document
                        (id, patient_id, doc_type, capture_type, image_path,
                         page_count, content_hash, status, created_at)
                    VALUES
                        ('d1', 'missing', 'lab_report', 'printed', 'd1',
                         1, 'hash', 'queued', '2026-10-23T00:00:00Z')
                    """
                )
            )


def test_duplicate_content_hash_is_rejected(app):
    with app.state.engine.begin() as conn:
        _insert_patient(conn)
        _insert_document(conn)
    with pytest.raises(IntegrityError):
        with app.state.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO document
                        (id, patient_id, doc_type, capture_type, image_path,
                         page_count, content_hash, status, created_at)
                    VALUES
                        ('d2', 'p1', 'lab_report', 'printed', 'd2',
                         1, 'hash-d1', 'queued', '2026-10-23T00:00:00Z')
                    """
                )
            )


def test_audit_is_append_only(app):
    with app.state.engine.begin() as conn:
        _insert_patient(conn)
        conn.execute(
            text(
                """
                INSERT INTO audit (id, entity, entity_id, field, "old", "new", actor, ts)
                VALUES ('a1', 'patient', 'p1', 'created', NULL, 'P-01', 'operator',
                        '2026-10-23T00:00:00Z')
                """
            )
        )

    with pytest.raises(IntegrityError, match="append-only"):
        with app.state.engine.begin() as conn:
            conn.execute(text("UPDATE audit SET actor = 'someone' WHERE id = 'a1'"))

    with pytest.raises(IntegrityError, match="append-only"):
        with app.state.engine.begin() as conn:
            conn.execute(text("DELETE FROM audit WHERE id = 'a1'"))


def test_handwritten_observation_cannot_be_auto(app):
    with app.state.engine.begin() as conn:
        _insert_patient(conn)
        _insert_document(conn, capture_type="handwritten")

    with pytest.raises(IntegrityError, match="SI-01"):
        with app.state.engine.begin() as conn:
            _insert_observation(conn, status="auto", value_num="13.2")


def test_handwritten_numeric_value_is_rejected(app):
    with app.state.engine.begin() as conn:
        _insert_patient(conn)
        _insert_document(conn, capture_type="handwritten")

    with pytest.raises(IntegrityError, match="SI-02"):
        with app.state.engine.begin() as conn:
            _insert_observation(conn, status="review", value_num="13.2")


def test_prose_observation_can_be_auto(app):
    with app.state.engine.begin() as conn:
        _insert_patient(conn)
        _insert_document(conn, capture_type="printed")
        conn.execute(
            text(
                """
                INSERT INTO observation
                    (id, document_id, analyte_id, label_raw, value_num, value_text,
                     bbox_json, page, engine, status, created_at)
                VALUES
                    ('o-prose', 'd1', NULL, 'Impression', NULL, 'No acute abnormality.',
                     '[0.1,0.2,0.3,0.4]', 1, 'test', 'auto', '2026-10-23T00:00:00Z')
                """
            )
        )
    with app.state.engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, value_text FROM observation WHERE id = 'o-prose'")
        ).first()
    assert row[0] == "auto"
    assert row[1] == "No acute abnormality."


_V2_SCHEMA = """
CREATE TABLE patient (
    id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    dob TEXT,
    sex TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE document (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patient(id) ON DELETE CASCADE,
    doc_type TEXT NOT NULL CHECK (doc_type IN ('lab_report', 'prescription', 'pharmacy', 'other')),
    capture_type TEXT NOT NULL CHECK (capture_type IN ('printed', 'handwritten')),
    doc_date TEXT,
    collection_date TEXT,
    lab_name TEXT,
    image_path TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 1 CHECK (page_count >= 1),
    quality_score REAL,
    quality_json TEXT,
    content_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'done', 'failed', 'rejected_quality')),
    doc_type_confidence REAL,
    processed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE observation (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    analyte_id TEXT,
    label_raw TEXT,
    value_num TEXT,
    value_text TEXT,
    unit_raw TEXT,
    unit_norm TEXT,
    ref_low TEXT,
    ref_high TEXT,
    flag_printed TEXT,
    bbox_json TEXT NOT NULL,
    page INTEGER NOT NULL,
    engine TEXT NOT NULL,
    confidence REAL,
    status TEXT NOT NULL,
    reason TEXT,
    mapping_rule TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE page_text (
    document_id TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    page INTEGER NOT NULL CHECK (page >= 1),
    text TEXT NOT NULL,
    engine TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, page)
);
CREATE TABLE jobs (
    id           TEXT PRIMARY KEY,
    document_id  TEXT NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    state        TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed')),
    page         INTEGER NOT NULL DEFAULT 0 CHECK (page >= 0),
    total        INTEGER NOT NULL CHECK (total >= 1),
    error        TEXT,
    ts           TEXT NOT NULL
);
CREATE INDEX idx_doc_patient_date ON document(patient_id, collection_date);
CREATE INDEX idx_doc_status ON document(status);
PRAGMA user_version = 2;
"""


def test_v2_database_migrates_to_latest(tmp_path):
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.executescript(_V2_SCHEMA)
    conn.execute(
        "INSERT INTO patient (id, alias, created_at) VALUES ('p1', 'P-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, "
        "page_count, content_hash, status, created_at) "
        "VALUES ('d1', 'p1', 'lab_report', 'printed', 'd1', 1, 'hash', 'done', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO observation (id, document_id, bbox_json, page, engine, status, created_at) "
        "VALUES ('o1', 'd1', '[0.1,0.2,0.3,0.4]', 1, 'paddle', 'review', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO page_text (document_id, page, text, engine, created_at) "
        "VALUES ('d1', 1, 'HbA1c 8.9', 'paddle', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    init_db(path)

    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT doc_type FROM document").fetchone()[0] == "lab_report"
        assert conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM report").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM page_text").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM stage_artifact").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute(
            "SELECT category FROM report WHERE document_id = 'd1'"
        ).fetchone()[0] == "lab"

        doc_columns = {row[1] for row in conn.execute("PRAGMA table_info(document)")}
        assert {
            "registration_date",
            "report_date",
            "patient_uhid",
            "patient_mrd",
            "doctor_reg_no",
            "hospital",
            "facility_name",
        } <= doc_columns

        observation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(observation)")
        }
        page_columns = {row[1] for row in conn.execute("PRAGMA table_info(page_text)")}
        assert {
            "source",
            "model_version",
            "report_id",
            "fact_type",
            "label_norm",
            "evidence_quote",
        } <= observation_columns
        assert {"source", "model_version"} <= page_columns
        assert conn.execute(
            "SELECT report_id FROM observation WHERE id = 'o1'"
        ).fetchone()[0] is not None

        conn.execute(
            "INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, "
            "page_count, content_hash, status, created_at) "
            "VALUES ('d2', 'p1', 'ct', 'printed', 'd2', 1, 'hash-2', 'queued', '2026-01-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, "
                "page_count, content_hash, status, created_at) "
                "VALUES ('d3', 'p1', 'bogus', 'printed', 'd3', 1, 'hash-3', 'queued', '2026-01-01')"
            )
        conn.rollback()
    finally:
        conn.close()


def _historical_v10_schema() -> str:
    # Reuse frozen v9 plus immutable migration 010 instead of copying the entire clinical schema.
    root = Path(__file__).resolve().parents[1]
    return ((root / "tests/fixtures/schema_v9.sql").read_text(encoding="utf-8")
            + (root / "smriti/migrations/010_runtime_stages.sql").read_text(encoding="utf-8"))


@pytest.mark.parametrize("version", [8, 9, 10])
def test_v8_progress_migration_preserves_accounts_and_review(tmp_path, version):
    path = tmp_path / f"v{version}.db"
    with sqlite3.connect(path) as conn:
        schema = (Path(__file__).parent / "fixtures/schema_v9.sql").read_text(encoding="utf-8")
        if version == 10:
            schema = _historical_v10_schema()
        if version == 8:
            schema = schema.replace("    progress_json TEXT,\n", "")
            schema = schema.replace("PRAGMA user_version = 9;", "PRAGMA user_version = 8;")
        conn.executescript(schema)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == version
        operational = conn.execute("SELECT name FROM sqlite_master WHERE name IN ('submissions', 'stage_batches')").fetchall()
        assert len(operational) == (2 if version == 10 else 0)
        conn.execute("INSERT INTO patient (id, alias, username, password_hash, created_at) VALUES ('p1', 'Synthetic', 'test-user', 'kept-hash', '2026-01-01')")
        conn.execute("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('d1', 'p1', 'lab_report', 'printed', 'd1', 1, 'hash', 'done', '2026-01-01')")
        conn.execute("INSERT INTO observation (id, document_id, analyte_id, value_num, bbox_json, page, engine, status, created_at) VALUES ('o1', 'd1', 'hemoglobin', '13.2', '[0,0,1,1]', 1, 'test', 'auto', '2026-01-01')")
        conn.execute("INSERT INTO auth_session (id, patient_id, token_hash, created_at, expires_at) VALUES ('s1', 'p1', 'kept-token-hash', '2026-01-01', '2027-01-01')")
        conn.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('j1', 'd1', 'done', 1, '2026-01-01')")
        conn.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('legacy-pending', 'd1', 'queued', 1, '2026-01-01')")
        conn.execute("INSERT INTO consent (id, document_id, scope, version, granted_at) VALUES ('c1', 'd1', 'local', 'v1', '2026-01-01')")
        conn.execute("INSERT INTO report (id, document_id, patient_id, category, report_type, page_start, page_end, status, created_at) VALUES ('r1', 'd1', 'p1', 'lab', 'lab_report', 1, 1, 'review', '2026-01-01')")
        conn.execute("INSERT INTO audit (id, entity, entity_id, field, old, new, actor, ts) VALUES ('a1', 'observation', 'o1', 'value_num', '13.1', '13.2', 'human', '2026-01-01')")
        conn.execute("INSERT INTO medication (id, patient_id, brand_raw, status, source_doc_id) VALUES ('m1', 'p1', 'Synthetic drug', 'prescribed', 'd1')")
        conn.execute("INSERT INTO directive (id, document_id, span_text, span_start, span_end, action_type, timing_type, anchor_event, state) VALUES ('di1', 'd1', 'Synthetic instruction', 0, 21, 'follow_up', 'prn', 'unknown', 'open')")
        conn.execute("INSERT INTO page_text (document_id, page, text, engine, created_at) VALUES ('d1', 1, 'Synthetic text', 'test', '2026-01-01')")
        conn.execute("INSERT INTO handwriting_field (id, document_id, page, bbox_json, field_type, human_value, action, status) VALUES ('h1', 'd1', 1, '[0,0,1,1]', 'drug', 'Human correction', 'correct', 'resolved')")
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        before = {table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        columns = {table: ', '.join(row[1] for row in conn.execute(f"PRAGMA table_info({table})")) for table in tables}
        old_schema = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND tbl_name NOT IN ('jobs', 'submissions', 'stage_batches') ORDER BY name").fetchall()
    init_db(path)
    init_db(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT state, progress_json FROM jobs WHERE id = 'j1'").fetchone() == ("done", None)
        for table, rows in before.items():
            assert conn.execute(f"SELECT {columns[table]} FROM {table}").fetchall() == rows
        import re
        after_schema = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND tbl_name NOT IN ('jobs', 'submissions', 'stage_batches') ORDER BY name").fetchall()
        # Only the approved clinical columns, document label columns, consent table and trigger human override clauses may differ.
        unchanged = [(kind, name, re.sub(r",\s*(?:clinical_json TEXT|page INTEGER|bbox_json TEXT|engine TEXT|display_name TEXT|verified_date TEXT)(?=[,)])", "", sql)
                      if kind == "table" and name in {"observation", "medication", "document"}
                      else re.sub(r" AND NEW\.engine != 'human'", "", sql) if kind == "trigger" and name.startswith("observation_no_")
                      else sql)
                     for kind, name, sql in after_schema if name != "cloud_consent"]
        assert unchanged == old_schema
        assert {row[1] for row in conn.execute("PRAGMA table_info(medication)")} >= {"clinical_json", "page", "bbox_json", "engine"}
        assert conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM stage_batches").fetchone()[0] == 0
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.fixture(params=["fresh", "upgrade", "v10"])
def runtime_db(tmp_path, request):
    path = tmp_path / "runtime.db"
    if request.param == "upgrade":
        with sqlite3.connect(path) as conn:
            conn.executescript((Path(__file__).parent / "fixtures/schema_v9.sql").read_text(encoding="utf-8"))
    elif request.param == "v10":
        with sqlite3.connect(path) as conn:
            conn.executescript(_historical_v10_schema())
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO patient (id, alias, created_at) VALUES ('p1', 'Synthetic', '2026-01-01')")
    try:
        yield conn
    finally:
        conn.close()


def _insert_submission(conn, **changes):
    values = {
        "job_id": "pending1", "patient_id": "p1", "content_hash": "raw-hash",
        "spool_path": "pending1.raw", "spool_bytes": 123,
        "consent_scope": "local", "consent_version": "v1",
        "consent_granted_at": "2026-01-01", "created_at": "2026-01-01",
        "updated_at": "2026-01-01", **changes,
    }
    conn.execute(f"INSERT INTO submissions ({', '.join(values)}) VALUES ({', '.join(':' + key for key in values)})", values)


def _insert_batch(conn, **changes):
    values = {
        "id": "b1", "state": "preparing", "owner_token": "owner1",
        "owner_pid": 123, "owner_created_at": 123.5,
        "membership_json": '["pending1"]', "created_at": "2026-01-01",
        "updated_at": "2026-01-01", **changes,
    }
    conn.execute(f"INSERT INTO stage_batches ({', '.join(values)}) VALUES ({', '.join(':' + key for key in values)})", values)


def test_submission_defers_clinical_rows_and_keeps_consent(runtime_db):
    _insert_submission(runtime_db, requested_doc_date="2026-01-01", requested_collection_date="2025-12-31")
    assert runtime_db.execute("SELECT job_id, state, stage, document_id, total_pages, consent_granted_at, spool_deleted_at FROM submissions").fetchone() == (
        "pending1", "pending_intake", "pending_intake", None, None, "2026-01-01", None,
    )
    for table in ("document", "consent", "jobs"):
        assert runtime_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert runtime_db.execute("SELECT requested_doc_date, requested_collection_date FROM submissions").fetchone() == ("2026-01-01", "2025-12-31")


@pytest.mark.parametrize("changes", [
    {"job_id": None}, {"patient_id": "missing"}, {"spool_bytes": 0},
    {"consent_scope": "remote"}, {"consent_version": None}, {"consent_granted_at": None},
    {"state": "unknown"}, {"requested_doc_type": "unknown"},
    {"total_pages": 0}, {"total_pages": 21}, {"total_pages": 1},
    {"document_id": "missing", "total_pages": 1, "state": "promoted"},
    {"state": "promoted"}, {"batch_position": 0}, {"batch_id": "missing", "batch_position": 0},
    {"preparation_manifest_json": "[]"}, {"progress_json": "not json"},
    {"progress_json": '{"large":"' + 'x' * 262144 + '"}'},
    {"spool_cleanup_state": "unknown"}, {"spool_deleted_at": "2026-01-02"},
    {"spool_cleanup_state": "deleted", "spool_cleanup_requested_at": "2026-01-02"},
    {"spool_cleanup_state": "failed"},
])
def test_submission_constraints(runtime_db, changes):
    with pytest.raises(sqlite3.IntegrityError):
        _insert_submission(runtime_db, **changes)


def test_live_hash_uniqueness_allows_explicit_rejected_resubmission(runtime_db):
    _insert_submission(runtime_db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_submission(runtime_db, job_id="pending2", spool_path="pending2.raw")
    runtime_db.execute("UPDATE submissions SET state = 'rejected', error_code = 'invalid_format' WHERE job_id = 'pending1'")
    _insert_submission(runtime_db, job_id="pending2", spool_path="pending2.raw")


def test_submission_hash_is_patient_scoped(runtime_db):
    _insert_submission(runtime_db)
    runtime_db.execute("INSERT INTO patient (id, alias, created_at) VALUES ('p2', 'Other', '2026-01-01')")
    _insert_submission(runtime_db, job_id="pending2", patient_id="p2", spool_path="pending2.raw")


def test_promotion_rejects_other_owner_or_changed_public_id(runtime_db):
    _insert_submission(runtime_db)
    runtime_db.execute("INSERT INTO patient (id, alias, created_at) VALUES ('p2', 'Other', '2026-01-01')")
    runtime_db.execute("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('other', 'p2', 'lab_report', 'printed', 'other', 1, 'other-hash', 'queued', '2026-01-01')")
    runtime_db.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('pending1', 'other', 'queued', 1, '2026-01-01')")
    with pytest.raises(sqlite3.IntegrityError, match="owner and public job"):
        runtime_db.execute("UPDATE submissions SET state = 'promoted', document_id = 'other', total_pages = 1 WHERE job_id = 'pending1'")
    with pytest.raises(sqlite3.IntegrityError, match="owner and public job"):
        _insert_submission(runtime_db, job_id="changed", patient_id="p2", spool_path="changed.raw", state="promoted", document_id="other", total_pages=1)


@pytest.mark.parametrize("pages", [1, 39, 1001])
def test_same_id_promotion_and_confirmed_cleanup(runtime_db, pages):
    _insert_submission(runtime_db)
    runtime_db.execute("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('prepared1', 'p1', 'lab_report', 'printed', 'prepared1', ?, 'raw-hash', 'queued', '2026-01-02')", (pages,))
    runtime_db.execute("INSERT INTO consent (id, document_id, scope, version, granted_at) SELECT 'c1', 'prepared1', consent_scope, consent_version, consent_granted_at FROM submissions WHERE job_id = 'pending1'")
    runtime_db.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('pending1', 'prepared1', 'queued', ?, '2026-01-02')", (pages,))
    runtime_db.execute("UPDATE submissions SET state = 'promoted', document_id = 'prepared1', total_pages = ?, spool_cleanup_requested_at = '2026-01-02' WHERE job_id = 'pending1'", (pages,))
    assert runtime_db.execute("SELECT j.id, j.total, c.granted_at FROM jobs j JOIN consent c ON c.document_id = j.document_id").fetchone() == ("pending1", pages, "2026-01-01")
    runtime_db.execute("UPDATE submissions SET spool_cleanup_state = 'failed', spool_cleanup_error_code = 'locked' WHERE job_id = 'pending1'")
    assert runtime_db.execute("SELECT state, spool_deleted_at FROM submissions").fetchone() == ("promoted", None)
    runtime_db.execute("UPDATE submissions SET spool_cleanup_state = 'deleted', spool_deleted_at = '2026-01-03', spool_cleanup_error_code = NULL WHERE job_id = 'pending1'")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_submission(runtime_db, job_id="duplicate", spool_path="duplicate.raw")


@pytest.mark.parametrize("changes", [
    {"id": None}, {"state": "unknown"}, {"owner_pid": 0}, {"owner_created_at": 0},
    {"membership_json": "[]"}, {"membership_json": "{}"},
    {"membership_json": '[' + ','.join('"j"' for _ in range(11)) + ']'},
    {"worksets_json": "{}"}, {"workset_index": -1}, {"attempt": 0},
    {"telemetry_json": "[]"}, {"telemetry_json": '{"large":"' + 'x' * 262144 + '"}'},
    {"checkpoints_json": "bad json"},
])
def test_batch_constraints(runtime_db, changes):
    with pytest.raises(sqlite3.IntegrityError):
        _insert_batch(runtime_db, **changes)


def test_active_batch_guard_and_frozen_membership(runtime_db):
    _insert_batch(runtime_db)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_batch(runtime_db, id="b2")
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        runtime_db.execute("UPDATE stage_batches SET membership_json = '[\"other\"]' WHERE id = 'b1'")
    _insert_submission(runtime_db, batch_id="b1", batch_position=0)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_submission(runtime_db, job_id="pending2", spool_path="pending2.raw", content_hash="other", batch_id="b1", batch_position=0)
    with pytest.raises(sqlite3.IntegrityError, match="frozen"):
        runtime_db.execute("UPDATE submissions SET batch_position = 1 WHERE job_id = 'pending1'")
    runtime_db.execute("UPDATE stage_batches SET state = 'cleanup_failed' WHERE id = 'b1'")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_batch(runtime_db, id="b2")
    runtime_db.execute("UPDATE stage_batches SET state = 'done' WHERE id = 'b1'")
    _insert_batch(runtime_db, id="b2")


def test_unresolved_spool_metadata_survives_owner_delete(runtime_db):
    _insert_submission(runtime_db)
    with pytest.raises(sqlite3.IntegrityError):
        runtime_db.execute("DELETE FROM patient WHERE id = 'p1'")
    assert runtime_db.execute("SELECT spool_path FROM submissions").fetchone() == ("pending1.raw",)


def test_clinical_count_constraints_remain_positive(runtime_db):
    runtime_db.execute("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('d1', 'p1', 'lab_report', 'printed', 'd1', 1, 'hash', 'queued', '2026-01-01')")
    for count in (None, 0, -1):
        with pytest.raises(sqlite3.IntegrityError):
            runtime_db.execute("UPDATE document SET page_count = ?", (count,))
        with pytest.raises(sqlite3.IntegrityError):
            runtime_db.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('j1', 'd1', 'queued', ?, '2026-01-01')", (count,))
    with pytest.raises(sqlite3.IntegrityError):
        runtime_db.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('j1', NULL, 'queued', 1, '2026-01-01')")


def test_fresh_and_migrated_operational_schema_match(tmp_path):
    fresh = tmp_path / "fresh.db"
    upgraded = tmp_path / "upgraded.db"
    with sqlite3.connect(upgraded) as conn:
        conn.executescript((Path(__file__).parent / "fixtures/schema_v9.sql").read_text(encoding="utf-8"))
    init_db(fresh)
    init_db(upgraded)
    query = "SELECT type, name, sql FROM sqlite_master WHERE tbl_name IN ('submissions', 'stage_batches') ORDER BY name"
    with sqlite3.connect(fresh) as fresh_conn, sqlite3.connect(upgraded) as upgraded_conn:
        assert fresh_conn.execute(query).fetchall() == upgraded_conn.execute(query).fetchall()


def test_many_execution_windows_use_one_bounded_current_manifest(runtime_db):
    _insert_batch(runtime_db, workset_index=100_000, worksets_json='[{"start":2000001,"end":2000020}]')
    index, manifest = runtime_db.execute("SELECT workset_index, worksets_json FROM stage_batches").fetchone()
    assert index == 100_000 and len(manifest) < 100


def test_v10_fixture_keeps_original_page_and_window_limits(tmp_path):
    path = tmp_path / "historical.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(_historical_v10_schema())
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        with pytest.raises(sqlite3.IntegrityError):
            _insert_batch(conn, workset_index=11)
        conn.execute("INSERT INTO patient (id, alias, created_at) VALUES ('p1', 'Synthetic', '2026-01-01')")
        conn.execute("INSERT INTO document (id, patient_id, doc_type, capture_type, image_path, page_count, content_hash, status, created_at) VALUES ('d1', 'p1', 'other', 'printed', 'd1', 39, 'hash', 'queued', '2026-01-01')")
        conn.execute("INSERT INTO jobs (id, document_id, state, total, ts) VALUES ('pending1', 'd1', 'queued', 39, '2026-01-01')")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_submission(conn, document_id="d1", total_pages=39, state="promoted")


def test_v10_upgrade_preserves_active_membership_and_cleanup_rows(tmp_path):
    path = tmp_path / "old-operational.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(_historical_v10_schema())
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("INSERT INTO patient (id, alias, created_at) VALUES ('p1', 'Synthetic', '2026-01-01')")
        _insert_batch(conn, state="cleanup_failed", workset_index=10,
                      checkpoints_json='{"source_page":20}', telemetry_json='{"coverage":"partial"}')
        _insert_submission(conn, batch_id="b1", batch_position=0, state="failed",
                           error_code="preparation_timeout", spool_cleanup_requested_at="2026-01-02",
                           spool_cleanup_state="failed", spool_cleanup_error_code="locked",
                           progress_json='{"events":[],"events_truncated":7}')
        before = {table: conn.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("patient", "submissions", "stage_batches")}
        objects = conn.execute("SELECT type, name FROM sqlite_master WHERE tbl_name IN ('submissions','stage_batches') ORDER BY name").fetchall()
    init_db(path)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        for table, rows in before.items():
            assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows
        assert conn.execute("SELECT type, name FROM sqlite_master WHERE tbl_name IN ('submissions','stage_batches') ORDER BY name").fetchall() == objects
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="frozen"):
            conn.execute("UPDATE stage_batches SET membership_json = '[\"other\"]'")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_batch(conn, id="b2")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM patient WHERE id = 'p1'")


def test_v11_failed_upgrade_rolls_back_without_discarding_bad_source_rows(tmp_path):
    path = tmp_path / "invalid-old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(_historical_v10_schema())
        _insert_submission(conn, patient_id="missing-owner")
        before = conn.execute("SELECT * FROM submissions").fetchall()
    with pytest.raises(sqlite3.IntegrityError, match="valid = 1"):
        init_db(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 10
        assert conn.execute("SELECT * FROM submissions").fetchall() == before
        assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE '%_next'").fetchall() == []


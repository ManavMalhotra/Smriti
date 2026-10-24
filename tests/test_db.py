from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from smriti.db import init_db

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "patient",
    "document",
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
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 4
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
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute("SELECT doc_type FROM document").fetchone()[0] == "lab_report"
        assert conn.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM page_text").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        doc_columns = {row[1] for row in conn.execute("PRAGMA table_info(document)")}
        assert {
            "registration_date",
            "report_date",
            "patient_uhid",
            "doctor_reg_no",
            "facility_name",
        } <= doc_columns

        observation_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(observation)")
        }
        page_columns = {row[1] for row in conn.execute("PRAGMA table_info(page_text)")}
        assert {"source", "model_version"} <= observation_columns
        assert {"source", "model_version"} <= page_columns

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

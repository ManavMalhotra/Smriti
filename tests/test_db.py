from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

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
        assert conn.exec_driver_sql("PRAGMA user_version").scalar_one() == 2
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

"""SQLite setup. Migrations are numbered; the schema is a checked-in SQL file."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
MIGRATIONS_PATH = Path(__file__).with_name("migrations")
SCHEMA_VERSION = 6


def _migration_path(version: int) -> Path:
    matches = sorted(MIGRATIONS_PATH.glob(f"{version:03d}_*.sql"))
    if len(matches) != 1:
        raise RuntimeError(f"missing migration for schema version {version}")
    return matches[0]


def init_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"unsupported schema version {version}")
        if version == 0:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if existing:
                raise RuntimeError("database has tables but no schema version")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        else:
            for next_version in range(version + 1, SCHEMA_VERSION + 1):
                conn.executescript(
                    _migration_path(next_version).read_text(encoding="utf-8")
                )
        migrated = conn.execute("PRAGMA user_version").fetchone()[0]
        if migrated != SCHEMA_VERSION:
            raise RuntimeError(
                f"schema migration ended at version {migrated}, expected {SCHEMA_VERSION}"
            )
    finally:
        conn.close()


def create_db_engine(db_path: str | Path) -> Engine:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{path.as_posix()}", future=True)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine

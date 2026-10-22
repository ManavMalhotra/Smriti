"""SQLite setup. Migrations are numbered; the schema is a checked-in SQL file."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def init_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise RuntimeError(f"unsupported schema version {version}")
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if existing:
            raise RuntimeError("database has tables but no schema version")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
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
        cursor.close()

    return engine


def get_connection(request: Request) -> Iterator[Connection]:
    with request.app.state.engine.begin() as conn:
        yield conn

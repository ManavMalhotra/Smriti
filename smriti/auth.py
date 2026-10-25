"""Password hashing, cookie sessions, and ownership checks."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.engine import Connection

from api.errors import api_error

SESSION_COOKIE = "smriti_session"
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
_SCRYPT_LEN = 32
_DUMMY_HASH = (
    "scrypt$16384$8$1$"
    + "00" * 16
    + "$"
    + "00" * _SCRYPT_LEN
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, n, r, p, salt_hex, digest_hex = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: Connection, patient_id: str, ttl_days: int) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute(
        text("DELETE FROM auth_session WHERE expires_at <= :now"),
        {"now": _iso(now)},
    )
    conn.execute(
        text(
            """
            INSERT INTO auth_session (id, patient_id, token_hash, created_at, expires_at)
            VALUES (:id, :patient_id, :token_hash, :created_at, :expires_at)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "patient_id": patient_id,
            "token_hash": hash_token(token),
            "created_at": _iso(now),
            "expires_at": _iso(now + timedelta(days=ttl_days)),
        },
    )
    return token


def delete_session(conn: Connection, token: str) -> None:
    conn.execute(
        text("DELETE FROM auth_session WHERE token_hash = :token_hash"),
        {"token_hash": hash_token(token)},
    )


def _patient_row_to_dict(row) -> dict:
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "alias": mapping["alias"],
        "username": mapping["username"],
        "sex": mapping["sex"],
        "dob": mapping["dob"],
        "created_at": mapping["created_at"],
    }


def current_patient(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        api_error(401, "unauthorized", "Sign in to continue.")
    with request.app.state.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT p.id, p.alias, p.username, p.sex, p.dob, p.created_at
                FROM auth_session s
                JOIN patient p ON p.id = s.patient_id
                WHERE s.token_hash = :token_hash AND s.expires_at > :now
                """
            ),
            {"token_hash": hash_token(token), "now": _iso(_now())},
        ).first()
    if row is None:
        api_error(401, "session_expired", "Your session has expired. Sign in again.")
    return _patient_row_to_dict(row)


def require_same_patient(patient_id: str, patient: dict) -> None:
    if patient_id != patient["id"]:
        api_error(403, "forbidden", "You can only access your own records.")


def owned_document(conn: Connection, document_id: str, patient_id: str):
    row = conn.execute(
        text(
            """
            SELECT * FROM document
            WHERE id = :id AND patient_id = :patient_id
            """
        ),
        {"id": document_id, "patient_id": patient_id},
    ).first()
    if row is None:
        api_error(404, "not_found", f"Unknown document {document_id}.")
    return row


def audit(
    conn: Connection,
    *,
    entity: str,
    entity_id: str,
    field: str,
    old: str | None,
    new: str | None,
    actor: str,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO audit (id, entity, entity_id, field, old, new, actor, ts)
            VALUES (:id, :entity, :entity_id, :field, :old, :new, :actor, :ts)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "entity": entity,
            "entity_id": entity_id,
            "field": field,
            "old": old,
            "new": new,
            "actor": actor,
            "ts": _iso(_now()),
        },
    )

"""Patient account registration, login, and session lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from api.errors import api_error
from smriti.auth import (
    SESSION_COOKIE,
    audit,
    create_session,
    current_patient,
    delete_session,
    hash_password,
    verify_password,
)
from smriti.models import LoginRequest, PatientOut, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _set_session_cookie(response: Response, token: str, ttl_days: int) -> None:
    # The local app is served over HTTP; enable Secure when TLS is terminated.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl_days * 24 * 60 * 60,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )


def _patient_out(row, *, username: str | None = None) -> PatientOut:
    mapping = row._mapping
    return PatientOut(
        id=mapping["id"],
        alias=mapping["alias"],
        username=username if username is not None else mapping.get("username"),
        sex=mapping["sex"],
        dob=mapping["dob"],
        created_at=mapping["created_at"],
    )


@router.post("/register", status_code=201, response_model=PatientOut)
def register(payload: RegisterRequest, request: Request, response: Response) -> PatientOut:
    settings = request.app.state.settings
    if settings.demo:
        api_error(403, "demo_read_only", "The demo profile is read-only.")

    alias = payload.alias.strip()
    if not alias:
        api_error(400, "validation_error", "Alias is required.", field="alias")
    username = payload.username.strip()
    patient_id = str(uuid.uuid4())
    created_at = _now().isoformat()
    password_hash = hash_password(payload.password)

    try:
        with request.app.state.engine.begin() as conn:
            # A v1 database has no accounts. The first account claims the sole
            # unowned patient so existing local records stay reachable.
            legacy = conn.execute(
                text(
                    "SELECT id FROM patient WHERE username IS NULL "
                    "ORDER BY created_at LIMIT 2"
                )
            ).all()
            claimed = False
            if len(legacy) == 1:
                patient_id = legacy[0][0]
                updated = conn.execute(
                    text(
                        """
                        UPDATE patient
                        SET alias = :alias,
                            dob = COALESCE(:dob, dob),
                            sex = COALESCE(:sex, sex),
                            username = :username,
                            password_hash = :password_hash
                        WHERE id = :id AND username IS NULL
                        """
                    ),
                    {
                        "id": patient_id,
                        "alias": alias,
                        "dob": payload.dob.isoformat() if payload.dob else None,
                        "sex": payload.sex,
                        "username": username,
                        "password_hash": password_hash,
                    },
                )
                claimed = updated.rowcount == 1

            if not claimed:
                conn.execute(
                    text(
                        """
                        INSERT INTO patient
                            (id, alias, dob, sex, username, password_hash, created_at)
                        VALUES
                            (:id, :alias, :dob, :sex, :username, :password_hash, :created_at)
                        """
                    ),
                    {
                        "id": patient_id,
                        "alias": alias,
                        "dob": payload.dob.isoformat() if payload.dob else None,
                        "sex": payload.sex,
                        "username": username,
                        "password_hash": password_hash,
                        "created_at": created_at,
                    },
                )
            audit(
                conn,
                entity="patient",
                entity_id=patient_id,
                field="claimed" if claimed else "created",
                old=None,
                new=alias,
                actor=username,
            )
            token = create_session(conn, patient_id, settings.session_ttl_days)
    except IntegrityError:
        api_error(409, "username_taken", "That username is already in use.", field="username")

    _set_session_cookie(response, token, settings.session_ttl_days)
    with request.app.state.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, alias, username, sex, dob, created_at
                FROM patient WHERE id = :id
                """
            ),
            {"id": patient_id},
        ).first()
    return _patient_out(row)


@router.post("/login", response_model=PatientOut)
def login(payload: LoginRequest, request: Request, response: Response) -> PatientOut:
    settings = request.app.state.settings
    username = payload.username.strip()
    audit_name = username.lower()
    since = (_now() - timedelta(minutes=settings.login_window_minutes)).isoformat()

    with request.app.state.engine.connect() as conn:
        failures = conn.execute(
            text(
                """
                SELECT COUNT(*) FROM audit
                WHERE entity = 'auth' AND entity_id = :entity_id
                  AND field = 'login_failed' AND ts >= :since
                """
            ),
            {"entity_id": audit_name, "since": since},
        ).scalar_one()
        row = conn.execute(
            text(
                """
                SELECT id, alias, username, sex, dob, created_at, password_hash
                FROM patient WHERE username = :username COLLATE NOCASE
                """
            ),
            {"username": username},
        ).first()

    if failures >= settings.login_attempts:
        api_error(429, "too_many_attempts", "Too many sign-in attempts. Try again shortly.")

    if row is None or not verify_password(payload.password, row._mapping["password_hash"]):
        with request.app.state.engine.begin() as conn:
            audit(
                conn,
                entity="auth",
                entity_id=audit_name,
                field="login_failed",
                old=None,
                new=None,
                actor=audit_name,
            )
        api_error(401, "invalid_credentials", "Invalid username or password.")

    with request.app.state.engine.begin() as conn:
        token = create_session(conn, row._mapping["id"], settings.session_ttl_days)
        audit(
            conn,
            entity="auth",
            entity_id=audit_name,
            field="login_success",
            old=None,
            new=None,
            actor=audit_name,
        )

    _set_session_cookie(response, token, settings.session_ttl_days)
    return _patient_out(row)


@router.post("/logout", status_code=204)
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with request.app.state.engine.begin() as conn:
            delete_session(conn, token)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=PatientOut)
def me(patient: dict = Depends(current_patient)) -> PatientOut:
    return PatientOut(**patient)

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from smriti.app import create_app
from smriti.observability import safe_event

pytestmark = pytest.mark.integration


class CaptureDiagnostics:
    def __init__(self, settings):
        self.events = []
        self.closed = False

    def start(self):
        return self

    def emit(self, event, **fields):
        payload = safe_event(event, **fields)
        if payload:
            self.events.append(json.loads(payload))
        return payload is not None

    def health(self):
        return {name: {"available": True, "written": 0, "failures": 0, "dropped": {}, "unconfirmed": 0, "last_write_ms": None, "crash_loss": "unavailable"} for name in ("file", "terminal")}

    def close(self):
        self.closed = True


def test_app_and_uvicorn_channels_never_format_private_messages(monkeypatch, settings, capfd):
    monkeypatch.setattr("smriti.app.Diagnostics", CaptureDiagnostics)
    app = create_app(settings)
    secret = "PRIVATE_MEDICAL_PASSWORD_PATH"
    @app.get("/synthetic-private")
    def error():
        logging.getLogger("uvicorn.error").exception(secret)
        logging.getLogger("smriti.app").warning("private %s", secret)
        raise RuntimeError(secret)
    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app) as client:
        response = client.get(f"/synthetic-private?patient={secret}", headers={"Authorization": secret})
        assert response.status_code == 500
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
        assert response.json()["error"]["support_id"] == response.headers["X-Request-ID"]
    assert secret not in response.text + json.dumps(app.state.diagnostics.events) + "".join(capfd.readouterr())
    assert {event["event"] for event in app.state.diagnostics.events} >= {"service_error", "service_warning", "request_failed", "service_stopped"}


def test_launcher_sanitizes_startup_exception_without_loading_live_app(monkeypatch, capfd):
    from smriti import server

    monkeypatch.setattr("sys.argv", ["smriti.server"])
    def fail(*args, **kwargs):
        assert kwargs["access_log"] is False
        raise RuntimeError("PRIVATE_STARTUP_PATH")
    monkeypatch.setattr(server.uvicorn, "run", fail)
    assert server.main() == 1
    output = "".join(capfd.readouterr())
    assert "PRIVATE_STARTUP_PATH" not in output and "service_error" in output


def test_successful_job_list_polls_are_suppressed_but_failures_are_logged(monkeypatch, settings):
    from tests.factory import make_patient

    monkeypatch.setattr("smriti.app.Diagnostics", CaptureDiagnostics)
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        make_patient(client)
        before = len(app.state.diagnostics.events)
        assert client.get("/api/jobs").status_code == 200
        assert not any(event["event"] == "request_finished" for event in app.state.diagnostics.events[before:]), json.dumps(app.state.diagnostics.events[before:])
    assert any(event["event"] == "request_finished" and event["status"] == 401 and event["route"] == "/api/jobs" for event in app.state.diagnostics.events)


def test_narrow_model_404_uses_observed_client_address_and_only_safe_ua_identity(monkeypatch, settings):
    monkeypatch.setattr("smriti.app.Diagnostics", CaptureDiagnostics)
    app = create_app(settings)
    secret = "PRIVATE_MEDICAL_PASSWORD_PATH"
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 45678)) as client:
        client.get("/api/health")
        assert not any(event["event"] == "request_finished" for event in app.state.diagnostics.events)
        assert client.get(f"/v1/models?private={secret}", headers={"user-agent": f"python-httpx/0.28 {secret}", "host": secret}).status_code == 404
        client.get("/unmatched", headers={"user-agent": secret})
    events = [event for event in app.state.diagnostics.events if event["event"] == "model_endpoint_not_found"]
    assert len(events) == 1
    assert events[0]["host"] == "127.0.0.1" and events[0]["port"] == 45678
    assert events[0]["ua_family"] == "httpx" and re.fullmatch(r"[0-9a-f]{16}", events[0]["ua_fingerprint"])
    assert secret not in json.dumps(app.state.diagnostics.events)


@pytest.mark.parametrize("failure", ["startup", "shutdown"])
def test_lifecycle_failure_closes_diagnostics_and_restores_all_log_handlers(monkeypatch, settings, failure):
    from unittest.mock import Mock

    monkeypatch.setattr("smriti.app.Diagnostics", CaptureDiagnostics)
    app = create_app(settings)
    logger = logging.getLogger("synthetic-private-handler")
    handler = logging.NullHandler()
    logger.addHandler(handler)
    before = [(item, item.handlers[:], item.level, item.propagate) for item in (logging.getLogger(), logger, logging.getLogger("uvicorn.error"))]
    if failure == "startup":
        monkeypatch.setattr(app.state.service, "start", Mock(side_effect=RuntimeError("PRIVATE_STARTUP_SENTINEL")))
    else:
        monkeypatch.setattr(app.state.service, "pause", lambda: False)
    try:
        with pytest.raises(RuntimeError):
            with TestClient(app):
                assert handler not in logger.handlers
        assert app.state.diagnostics.closed
        for item, handlers, level, propagate in before:
            assert (item.handlers, item.level, item.propagate) == (handlers, level, propagate)
    finally:
        logger.removeHandler(handler)
        app.state.engine.dispose()

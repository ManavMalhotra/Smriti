from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smriti.app import create_app
from smriti.config import Settings


_LAYERS = {"unit", "integration", "system"}


def pytest_collection_modifyitems(config, items):
    unmarked = [
        item.nodeid
        for item in items
        if not any(marker.name in _LAYERS for marker in item.iter_markers())
    ]
    if unmarked:
        raise pytest.UsageError(
            "Every test needs a unit, integration, or system marker: "
            + ", ".join(unmarked)
        )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    loopback = {"127.0.0.1", "::1", "localhost"}

    def is_loopback(address) -> bool:
        return isinstance(address, tuple) and address[0] in loopback

    def connect(self, address, *args, **kwargs):
        if is_loopback(address):
            return original_connect(self, address, *args, **kwargs)
        raise RuntimeError("network access is disabled in tests")

    def connect_ex(self, address, *args, **kwargs):
        if is_loopback(address):
            return original_connect_ex(self, address, *args, **kwargs)
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "smriti.db",
        upload_dir=tmp_path / "uploads",
        spool_dir=tmp_path / "spool",
        log_dir=tmp_path / "logs",
        worker_enabled=False,
        vlm_enabled=False,
    )


@pytest.fixture
def app(settings: Settings, monkeypatch):
    from tests.test_app_diagnostics import CaptureDiagnostics

    monkeypatch.setattr("smriti.app.Diagnostics", CaptureDiagnostics)
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client

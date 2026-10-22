from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from smriti.app import create_app
from smriti.config import Settings


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
    return Settings(db_path=tmp_path / "smriti.db", upload_dir=tmp_path / "uploads")


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client

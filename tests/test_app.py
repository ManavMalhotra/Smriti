from dataclasses import replace

import pytest

from smriti.app import create_app
from smriti.config import BASE_DIR

pytestmark = pytest.mark.integration


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "profile": "local-gpu"}


def test_upload_dir_inside_static_root_is_rejected(settings):
    with pytest.raises(ValueError):
        create_app(
            replace(settings, upload_dir=BASE_DIR / "web" / "dist" / "uploads")
        )

import pytest
from sqlalchemy import text

from tests.factory import make_patient

pytestmark = pytest.mark.integration


def post(client, owner, data=b"%PDF-SYNTHETIC_NOT_DECODED"):
    return client.post("/api/documents", data={"patient_id": owner, "consent_scope": "local"}, files={"file": ("synthetic.pdf", data, "application/pdf")})


def test_http_upload_spools_only_then_resolves_pending_duplicate(client, app, monkeypatch):
    from smriti import preparation

    monkeypatch.setattr(preparation, "prepare_submission", lambda *args, **kwargs: pytest.fail("No HTTP preparation"))
    owner = make_patient(client)
    response = post(client, owner)
    assert response.status_code == 202
    result = response.json()
    assert result["document_id"] is result["pages"] is None
    assert result["status"] == "pending_intake"
    pending = client.get(f"/api/jobs/{result['job_id']}").json()
    assert pending["total_pages"] is pending["document_id"] is None
    assert pending["stage"] == "pending_intake"
    duplicate = post(client, owner)
    assert duplicate.status_code == 409 and duplicate.json()["job_id"] == result["job_id"]
    with app.state.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0
        assert conn.execute(text("SELECT COUNT(*) FROM submissions")).scalar_one() == 1


def test_closed_admission_rejects_before_receiving_source(client, app):
    owner = make_patient(client)
    app.state.service.accepting = False
    assert post(client, owner).status_code == 503
    assert not list(app.state.settings.spool_dir.glob("*.raw"))


def test_form_owner_is_checked_and_invalid_body_leaves_no_raw(client, app):
    make_patient(client)
    assert post(client, "other").status_code == 403
    assert client.post("/api/documents", content=b"untrusted").status_code == 400
    assert not list(app.state.settings.spool_dir.glob("*.raw"))

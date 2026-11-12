import pytest
from sqlalchemy import text

from tests.factory import make_patient

pytestmark = pytest.mark.integration


def source(client, app, settings, pages=1001):
    patient = make_patient(client)
    root = settings.upload_dir / "synthetic-range"
    root.mkdir()
    (root / "page_21.webp").write_bytes(b"SYNTHETIC_SOURCE")
    with app.state.engine.begin() as conn:
        conn.execute(text("""INSERT INTO document (id, patient_id, doc_type, capture_type,
            image_path, page_count, content_hash, status, created_at) VALUES
            ('range-doc', :patient, 'lab_report', 'printed', 'synthetic-range', :pages, 'range-hash', 'failed', '2026-11-06')"""),
            {"patient": patient, "pages": pages})
        conn.execute(text("""INSERT INTO page_text (document_id, page, text, engine, created_at)
            VALUES ('range-doc', :page, :text, 'synthetic', '2026-11-06')"""),
            [{"page": page, "text": f"SYNTHETIC PAGE {page}"} for page in (1, 21)])
        conn.execute(text("""INSERT INTO observation (id, document_id, value_text, bbox_json,
            page, engine, status, created_at) VALUES (:id, 'range-doc', :value, '[]',
            :page, 'synthetic', 'review', '2026-11-06')"""),
            [{"id": f"range-{index:03}", "value": f"SYNTHETIC {index}", "page": 21} for index in range(105)])
    return patient


def test_long_detail_defaults_to_page_one_and_reads_whole_bounded_ranges(client, app, settings):
    source(client, app, settings)
    default = client.get("/api/documents/range-doc").json()
    assert default["detail_page"] == 1 and len(default["pages"]) == 1
    assert [page["page"] for page in default["page_text"]] == [1]
    first = client.get("/api/documents/range-doc?page=21").json()
    last = client.get("/api/documents/range-doc?page=21&offset=100").json()
    assert len(first["observations"]) == 100 and first["has_more"]
    assert len(last["observations"]) == 5 and not last["has_more"]
    assert {row["id"] for row in first["observations"]}.isdisjoint(row["id"] for row in last["observations"])
    assert first["pages"] == [{"page": 21, "url": "/api/documents/range-doc/page/21"}]
    assert client.get(first["pages"][0]["url"]).content == b"SYNTHETIC_SOURCE"
    assert client.get("/api/documents/range-doc?page=1002").status_code == 404
    assert client.get("/api/documents/range-doc?page=0").status_code == 400


def test_detail_oversize_is_rejected_before_python_decodes_result_rows(client, app, settings):
    source(client, app, settings)
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE page_text SET text = :text WHERE page = 21"), {"text": "X" * (2 * 1024**2 + 1)})
    response = client.get("/api/documents/range-doc?page=21")
    assert response.status_code == 413 and response.json()["error"]["code"] == "detail_capacity"
    assert client.get("/api/documents/range-doc?page=1").status_code == 200


def test_result_ranges_are_owner_scoped(client, app, settings):
    source(client, app, settings)
    make_patient(client, alias="Other")
    assert client.get("/api/documents/range-doc?page=21&offset=100").status_code == 404
    assert client.get("/api/documents/range-doc/page/21").status_code == 404

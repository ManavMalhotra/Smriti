import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from smriti.job_progress import record_progress
from tests.factory import make_patient, pdf_bytes, upload

pytestmark = pytest.mark.integration


def test_library_lists_accepted_uploads_before_preparation_and_after_failure(client, app):
    patient = make_patient(client)
    response = client.post('/api/documents', data={'patient_id': patient, 'consent_scope': 'local'},
                           files={'file': ('PRIVATE.pdf', pdf_bytes(1), 'application/pdf')})
    assert response.status_code == 202
    job = response.json()['job_id']
    row = client.get('/api/documents').json()['documents'][0]
    assert row['id'] == row['job_id'] == job
    assert row['document_id'] is None and row['page_count'] is None
    assert row['status'] == 'pending_intake' and not row['retryable']
    with app.state.engine.begin() as conn:
        record_progress(conn, job, 'intake_failed', error_code='source_missing')
    row = client.get('/api/documents').json()['documents'][0]
    assert row['status'] == row['job_state'] == 'failed'
    assert row['document_id'] is None


def test_library_keeps_failed_and_completed_documents_with_owner_scoped_pagination(client, app):
    patient = make_patient(client)
    first = upload(client, patient, pdf_bytes(1), content_type='application/pdf').json()
    second = upload(client, patient, pdf_bytes(2), content_type='application/pdf').json()
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'failed' WHERE id = :id"), {'id': first['job_id']})
        conn.execute(text("UPDATE document SET status = 'failed' WHERE id = :id"), {'id': first['document_id']})
        conn.execute(text("UPDATE jobs SET state = 'done' WHERE id = :id"), {'id': second['job_id']})
        conn.execute(text("UPDATE document SET status = 'done' WHERE id = :id"), {'id': second['document_id']})
    response = client.get('/api/documents')
    rows = response.json()['documents']
    assert {row['id'] for row in rows} == {first['document_id'], second['document_id']}
    failed = next(row for row in rows if row['id'] == first['document_id'])
    assert failed['job_id'] == first['job_id'] and failed['retryable']
    assert failed['page_count'] == 1
    assert not any(key in response.text for key in ('spool_path', 'password_hash', 'content_hash', 'preparation_manifest_json'))
    page = client.get('/api/documents?limit=1').json()
    assert page['has_more'] and len(page['documents']) == 1
    next_page = client.get('/api/documents?limit=1&offset=1').json()
    assert not next_page['has_more']
    assert next_page['documents'][0]['id'] != page['documents'][0]['id']
    with TestClient(app) as other:
        make_patient(other, alias='Other')
        assert other.get('/api/documents').json()['documents'] == []


def test_library_filters_before_pagination(client, app):
    patient = make_patient(client)
    prescription = upload(client, patient, pdf_bytes(1), content_type='application/pdf').json()
    lab_report = upload(client, patient, pdf_bytes(2), content_type='application/pdf').json()
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE document SET doc_type = 'prescription' WHERE id = :id"), {'id': prescription['document_id']})
        conn.execute(text("UPDATE document SET doc_type = 'lab_report' WHERE id = :id"), {'id': lab_report['document_id']})
    page = client.get('/api/documents?filter=Prescriptions&limit=1').json()
    assert [row['document_id'] for row in page['documents']] == [prescription['document_id']]
    assert not page['has_more']


def test_library_retains_legacy_documents_without_recovery_metadata(client, app):
    patient = make_patient(client)
    result = upload(client, patient, pdf_bytes(1), content_type='application/pdf').json()
    with app.state.engine.begin() as conn:
        conn.execute(text('DELETE FROM submissions WHERE job_id = :id'), {'id': result['job_id']})
        conn.execute(text("UPDATE jobs SET state = 'failed' WHERE id = :id"), {'id': result['job_id']})
        conn.execute(text("UPDATE document SET status = 'failed' WHERE id = :id"), {'id': result['document_id']})
    row = client.get('/api/documents').json()['documents'][0]
    assert row['document_id'] == result['document_id'] and not row['retryable']
    assert client.post(f"/api/jobs/{result['job_id']}/retry").status_code == 409


@pytest.mark.parametrize('query', ['limit=0', 'limit=51', 'offset=-1'])
def test_library_rejects_invalid_pagination(client, query):
    make_patient(client)
    assert client.get('/api/documents?' + query).status_code == 400


def test_duplicate_failed_upload_links_to_the_existing_inventory_and_queue_job(client, app):
    patient = make_patient(client)
    data = pdf_bytes(1)
    first = upload(client, patient, data, content_type='application/pdf').json()
    with app.state.engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET state = 'failed' WHERE id = :id"), {'id': first['job_id']})
        conn.execute(text("UPDATE document SET status = 'failed' WHERE id = :id"), {'id': first['document_id']})
    duplicate = client.post('/api/documents', data={'patient_id': patient, 'consent_scope': 'local'},
                            files={'file': ('same.pdf', data, 'application/pdf')})
    assert duplicate.status_code == 409
    assert duplicate.json()['document_id'] == first['document_id']
    assert duplicate.json()['job_id'] == first['job_id']
    rows = client.get('/api/documents').json()['documents']
    assert len(rows) == 1 and rows[0]['retryable']
    assert client.get('/api/jobs?scope=all').json()['jobs'][0]['id'] == first['job_id']

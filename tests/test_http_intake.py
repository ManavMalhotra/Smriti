from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from starlette.requests import Request
from sqlalchemy import text

from smriti.http_intake import receive_upload
from smriti.spool import SpoolError
from tests.test_spool import spool_db

pytestmark = pytest.mark.integration


def multipart(parts, boundary=b"synthetic-boundary"):
    body = bytearray()
    for name, value, filename in parts:
        body.extend(b"--" + boundary + b"\r\nContent-Disposition: form-data; name=\"" + name + b"\"")
        if filename:
            body.extend(b"; filename=\"" + filename + b"\"")
        body.extend(b"\r\n\r\n" + value + b"\r\n")
    return bytes(body + b"--" + boundary + b"--\r\n")


def request(body, split=7, headers=None):
    pieces = iter(body[i:i + split] for i in range(0, len(body), split))

    async def receive():
        part = next(pieces, None)
        return {"type": "http.request", "body": part or b"", "more_body": part is not None}

    return Request({"type": "http", "method": "POST", "path": "/api/documents", "headers": headers or [
        (b"content-type", b"multipart/form-data; boundary=synthetic-boundary")]}, receive)


@pytest.mark.parametrize("file_first", [True, False])
def test_upload_is_bounded_unknown_count_and_accepts_arbitrary_part_order(spool_db, settings, file_first):
    fields = [(b"patient_id", b"p1", None), (b"consent_scope", b"local_plus_projection", None)]
    file = (b"file", b"%PDF-synthetic-decoder-free", b"PRIVATE_FILENAME")
    result = asyncio.run(receive_upload(spool_db, settings, request(multipart([file, *fields] if file_first else [*fields, file])), "p1"))
    assert result.document_id is None
    with spool_db.connect() as conn:
        row = conn.execute(text("SELECT consent_scope, total_pages FROM submissions")).one()
        assert row == ("local_plus_projection", None)
        assert conn.execute(text("SELECT COUNT(*) FROM document")).scalar_one() == 0


@pytest.mark.parametrize("parts,code", [
    ([(b"patient_id", b"p2", None), (b"consent_scope", b"local", None), (b"file", b"%PDF-x", b"x")], "forbidden"),
    ([(b"patient_id", b"p1", None), (b"file", b"%PDF-x", b"x")], "invalid_metadata"),
    ([(b"patient_id", b"p1", None), (b"patient_id", b"p1", None), (b"file", b"%PDF-x", b"x")], "invalid_multipart"),
    ([(b"file", b"%PDF-x", b"x"), (b"file", b"%PDF-y", b"y")], "invalid_multipart"),
    ([(b"unknown", b"x", None), (b"file", b"%PDF-x", b"x")], "invalid_multipart"),
])
def test_untrusted_metadata_and_multiple_files_leave_no_accepted_source(spool_db, settings, parts, code):
    with pytest.raises(SpoolError, match=code):
        asyncio.run(receive_upload(spool_db, settings, request(multipart(parts)), "p1"))
    assert not list(settings.spool_dir.glob("*.raw"))
    assert not list(settings.spool_dir.glob("*.part"))


def test_truncated_multipart_is_not_accepted(spool_db, settings):
    body = multipart([(b"patient_id", b"p1", None), (b"consent_scope", b"local", None), (b"file", b"%PDF-x", b"x")])
    with pytest.raises(SpoolError, match="invalid_multipart"):
        asyncio.run(receive_upload(spool_db, settings, request(body[:-25]), "p1"))
    assert not list(settings.spool_dir.glob("*.raw"))


def test_file_and_request_byte_limits_are_independent_of_content_length(spool_db, settings):
    settings = replace(settings, max_upload_bytes=20)
    body = multipart([(b"patient_id", b"p1", None), (b"consent_scope", b"local", None), (b"file", b"%PDF-" + b"x" * 30, b"x")])
    with pytest.raises(SpoolError, match="too_large"):
        asyncio.run(receive_upload(spool_db, settings, request(body, split=len(body)), "p1"))
    headers = [(b"content-type", b"multipart/form-data; boundary=synthetic-boundary"), (b"content-length", b"9999999999")]
    with pytest.raises(SpoolError, match="too_large"):
        asyncio.run(receive_upload(spool_db, settings, request(b"", headers=headers), "p1"))

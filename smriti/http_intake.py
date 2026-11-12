"""One bounded multipart file, directly into the private raw spool; no automatic temp upload."""

from __future__ import annotations

from python_multipart import MultipartParser
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import parse_options_header
from starlette.requests import ClientDisconnect

from smriti.config import MAX_MULTIPART_FIELDS, MULTIPART_OVERHEAD_BYTES, SPOOL_CHUNK_BYTES
from smriti.spool import SpoolError, spool_upload


async def receive_upload(engine, settings, request, patient_id):
    content_type = request.headers.get("content-type", "")
    if len(content_type) > 1024:
        raise SpoolError("invalid_multipart")
    media, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if media != b"multipart/form-data" or not boundary or len(boundary) > 70:
        raise SpoolError("invalid_multipart")
    length = request.headers.get("content-length")
    if length is not None:
        if not length.isascii() or not length.isdigit() or len(length) > 20:
            raise SpoolError("invalid_multipart")
        if int(length) > settings.max_request_bytes:
            raise SpoolError("too_large")
    fields, headers, chunks = {}, {}, []
    current = {"header": bytearray(), "value": bytearray(), "data": bytearray(), "name": None}
    file_count, part_count, total, file_bytes = 0, 0, 0, 0
    finished = False

    def part_begin():
        nonlocal part_count
        part_count += 1
        if part_count > MAX_MULTIPART_FIELDS + 1:
            raise SpoolError("invalid_multipart")
        headers.clear()
        current.update(header=bytearray(), value=bytearray(), data=bytearray(), name=None)

    def header_field(data, start, end):
        current["header"].extend(data[start:end])
        if len(current["header"]) > 128:
            raise SpoolError("invalid_multipart")

    def header_value(data, start, end):
        current["value"].extend(data[start:end])
        if len(current["value"]) > 4096:
            raise SpoolError("invalid_multipart")

    def header_end():
        key = bytes(current["header"]).lower()
        if key in headers or len(headers) >= 4:
            raise SpoolError("invalid_multipart")
        headers[key] = bytes(current["value"])
        current.update(header=bytearray(), value=bytearray())

    def headers_finished():
        nonlocal file_count
        disposition, params = parse_options_header(headers.get(b"content-disposition", b""))
        if disposition != b"form-data":
            raise SpoolError("invalid_multipart")
        name = params.get(b"name", b"")
        if b"filename" in params:
            if name != b"file" or file_count:
                raise SpoolError("invalid_multipart")
            file_count += 1
            current["name"] = "file"
        else:
            try:
                name = name.decode("ascii")
            except UnicodeError:
                raise SpoolError("invalid_multipart") from None
            if name not in {"patient_id", "consent_scope", "doc_type", "doc_date", "collection_date"} or name in fields:
                raise SpoolError("invalid_multipart")
            current["name"] = name

    def part_data(data, start, end):
        nonlocal file_bytes
        if current["name"] == "file":
            file_bytes += end - start
            if file_bytes > settings.max_upload_bytes:
                raise SpoolError("too_large")
            chunks.append(data[start:end])
        else:
            current["data"].extend(data[start:end])
            if len(current["data"]) > 1024:
                raise SpoolError("invalid_metadata")

    def part_end():
        if current["name"] != "file":
            try:
                fields[current["name"]] = current["data"].decode("utf-8")
            except UnicodeError:
                raise SpoolError("invalid_metadata") from None

    def end():
        nonlocal finished
        finished = True

    parser = MultipartParser(boundary, {"on_part_begin": part_begin, "on_header_field": header_field,
        "on_header_value": header_value, "on_header_end": header_end, "on_headers_finished": headers_finished,
        "on_part_data": part_data, "on_part_end": part_end, "on_end": end}, max_size=settings.max_request_bytes)

    async def file_chunks():
        nonlocal total
        try:
            async for incoming in request.stream():
                total += len(incoming)
                if total > settings.max_request_bytes:
                    raise SpoolError("too_large")
                for offset in range(0, len(incoming), SPOOL_CHUNK_BYTES):
                    parser.write(incoming[offset:offset + SPOOL_CHUNK_BYTES])
                    for chunk in chunks:
                        yield chunk
                    chunks.clear()
                    if total - file_bytes > MULTIPART_OVERHEAD_BYTES:
                        # Check overhead only after all portions of the current ASGI chunk are parsed.
                        if offset + SPOOL_CHUNK_BYTES >= len(incoming):
                            raise SpoolError("invalid_multipart")
            parser.finalize()
            if not finished or file_count != 1:
                raise SpoolError("invalid_multipart")
        except MultipartParseError:
            raise SpoolError("invalid_multipart") from None
        except ClientDisconnect:
            raise SpoolError("disconnected") from None
        finally:
            parser.close()

    # The authenticated owner is fixed before spooling; form consent/metadata is checked before acceptance.
    return await spool_upload(engine, settings, file_chunks(), patient_id=patient_id,
                              consent_scope=fields.get("consent_scope", "local"), form_fields=fields)

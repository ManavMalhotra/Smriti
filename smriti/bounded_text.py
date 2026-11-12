"""Exact joined-document lines without retaining the joined document."""

from smriti.spool import SpoolError

_BREAKS = "\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029"


def document_lines(page_texts, *, separator="\n", keepends=False, max_line_bytes=1024**2):
    pending = ""
    first = True
    for page in page_texts:
        for piece in (page,) if first else (separator, page):
            parts = (pending + piece).splitlines(keepends=True)
            pending = ""
            if parts and (parts[-1][-1] not in _BREAKS or parts[-1].endswith("\r")):
                pending = parts.pop()
            for raw in parts:
                if len(raw.encode("utf-8")) > max_line_bytes:
                    raise SpoolError("capacity_exhausted")
                yield raw if keepends else raw.splitlines()[0]
            if len(pending.encode("utf-8")) > max_line_bytes:
                raise SpoolError("capacity_exhausted")
        first = False
    if pending:
        yield pending if keepends else pending.splitlines()[0]

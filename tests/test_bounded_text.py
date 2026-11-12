from __future__ import annotations

import random

import pytest

from smriti.bounded_text import document_lines
from smriti.classify import classify_pages, classify_text
from smriti.metadata import extract_metadata, extract_metadata_lines
from smriti.spool import SpoolError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("pages", [[], [""], ["a", "b"], ["a\r", "b"], ["a\n", ""], ["\r", "\n"],
                                   ["a\u2028b\x85c", "last"], ["", "", "last"], ["\n", "\r", "\n"]])
def test_lines_and_unicode_offsets_match_exact_join(pages):
    text = "\n".join(pages)
    assert list(document_lines(iter(pages))) == text.splitlines()
    assert list(document_lines(iter(pages), keepends=True)) == text.splitlines(keepends=True)


def test_unbounded_logical_line_is_rejected_never_truncated():
    with pytest.raises(SpoolError, match="capacity_exhausted"):
        list(document_lines(["a" * 11], max_line_bytes=10))


def test_streamed_classification_preserves_presence_and_arbitrary_whitespace():
    pages = ["CT CHEST\nSerum investigation 23", *("\t" for _ in range(1000)), "mg/dl\nTab.",
             *("\t" for _ in range(1000)), "aspirin\nCT CHEST"]
    assert classify_pages(iter(pages)) == classify_text("\n".join(pages))
    pages = ["a" + "9" * 1000 + " mg/dl"]
    assert classify_pages(iter(pages)) == classify_text("\n".join(pages))


def test_streamed_classification_equivalence_on_generated_boundary_cases():
    randomizer = random.Random(7)
    tokens = ["CT CHEST", "HRCT", "Serum", "Creatinine", "Tab.", "aspirin", "2.9", "mg/dl", "µiu/ml",
              "5 %abc", "a23", "3", "\t", "Ω", "١٢.٣", "Invoice", "discharge summary", "cholesterol"]
    for _ in range(200):
        pages = [" ".join(randomizer.choices(tokens, k=randomizer.randrange(0, 15))) for _ in range(randomizer.randrange(1, 5))]
        assert classify_pages(iter(pages)) == classify_text("\n".join(pages)), pages


def test_streamed_metadata_keeps_global_precedence_and_facility_line_budget():
    pages = ["DOB: 01/01/1990\nSample Date: 02/11/2025\nPatient UHID: ABCD1234", *["continuation"] * 18,
             "LATE HOSPITAL\nDate: 03/11/2025\nMCI Reg No: DOC123"]
    text = "\n".join(pages)
    assert extract_metadata_lines(document_lines(iter(pages))) == extract_metadata(text)
    assert extract_metadata_lines(document_lines(iter(pages)))["facility_name"] is None

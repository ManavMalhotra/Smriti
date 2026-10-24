from __future__ import annotations

from smriti.assembly import assemble_page
from smriti.ocr import OcrWord


def _word(text: str, y: float, x: float, width: float = 0.1) -> OcrWord:
    return OcrWord(text=text, bbox=[x, y, x + width, y + 0.04], confidence=0.98)


def test_rows_and_cells_are_assigned():
    words = [
        _word("HbA1c", 0.10, 0.10, 0.15),
        _word("8.9", 0.10, 0.60, 0.06),
        _word("%", 0.10, 0.68, 0.03),
        _word("Glucose", 0.20, 0.10, 0.15),
        _word("126", 0.20, 0.60, 0.06),
    ]
    layout = assemble_page(words)
    assert len(layout.regions) == 1
    assert len(layout.rows) == 2
    assert layout.regions[0].columns == 2
    assert layout.rows[0].text == "HbA1c 8.9 %"
    assert layout.rows[1].cells[0].text == "Glucose"


def test_blank_gap_splits_table_regions():
    words = [
        _word("HbA1c", 0.10, 0.10),
        _word("8.9", 0.10, 0.60),
        _word("Creatinine", 0.50, 0.10),
        _word("1.1", 0.50, 0.60),
    ]
    layout = assemble_page(words)
    assert len(layout.regions) == 2
    assert [row.text for row in layout.rows] == ["HbA1c 8.9", "Creatinine 1.1"]


def test_empty_page_has_no_regions():
    assert assemble_page([]).regions == ()

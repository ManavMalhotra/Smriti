"""Whitespace table assembly over OCR words.

The OCR adapter produces word boxes. This module groups those boxes into rows,
then into cells and table regions using only whitespace. A merged-cell layout
that whitespace cannot separate stays a single cell and is left for review.
"""

from __future__ import annotations

from dataclasses import dataclass

from smriti.ocr import OcrWord


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _bbox(words: tuple[OcrWord, ...] | list[OcrWord]) -> tuple[float, float, float, float]:
    return (
        _clamp(min(word.bbox[0] for word in words)),
        _clamp(min(word.bbox[1] for word in words)),
        _clamp(max(word.bbox[2] for word in words)),
        _clamp(max(word.bbox[3] for word in words)),
    )


@dataclass(frozen=True)
class Cell:
    words: tuple[OcrWord, ...]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)


@dataclass(frozen=True)
class Row:
    cells: tuple[Cell, ...]
    bbox: tuple[float, float, float, float]

    @property
    def words(self) -> tuple[OcrWord, ...]:
        return tuple(word for cell in self.cells for word in cell.words)

    @property
    def text(self) -> str:
        return " ".join(cell.text for cell in self.cells)


@dataclass(frozen=True)
class TableRegion:
    rows: tuple[Row, ...]
    bbox: tuple[float, float, float, float]

    @property
    def columns(self) -> int:
        return max((len(row.cells) for row in self.rows), default=0)


@dataclass(frozen=True)
class PageLayout:
    regions: tuple[TableRegion, ...]

    @property
    def rows(self) -> tuple[Row, ...]:
        return tuple(row for region in self.regions for row in region.rows)


def _row_groups(words: list[OcrWord]) -> list[list[OcrWord]]:
    ordered = sorted(words, key=lambda word: ((word.bbox[1] + word.bbox[3]) / 2, word.bbox[0]))
    groups: list[list[OcrWord]] = []
    for word in ordered:
        center = (word.bbox[1] + word.bbox[3]) / 2
        height = max(0.002, word.bbox[3] - word.bbox[1])
        if not groups:
            groups.append([word])
            continue
        last = groups[-1]
        last_center = sum((item.bbox[1] + item.bbox[3]) / 2 for item in last) / len(last)
        if abs(center - last_center) <= max(0.008, height * 0.7):
            last.append(word)
        else:
            groups.append([word])
    for group in groups:
        group.sort(key=lambda word: word.bbox[0])
    return groups


def _cells(words: list[OcrWord]) -> tuple[Cell, ...]:
    ordered = sorted(words, key=lambda word: word.bbox[0])
    heights = sorted(max(0.002, word.bbox[3] - word.bbox[1]) for word in ordered)
    median_height = heights[len(heights) // 2] if heights else 0.002
    gap_limit = max(0.03, median_height * 0.9)
    groups: list[list[OcrWord]] = []
    for word in ordered:
        if not groups or word.bbox[0] - groups[-1][-1].bbox[2] > gap_limit:
            groups.append([word])
        else:
            groups[-1].append(word)
    return tuple(Cell(tuple(group), _bbox(group)) for group in groups)


def _regions(rows: list[Row]) -> tuple[TableRegion, ...]:
    if not rows:
        return ()
    heights = sorted(row.bbox[3] - row.bbox[1] for row in rows)
    median_height = heights[len(heights) // 2] if heights else 0.002
    gap_limit = max(0.04, median_height * 2.0)
    regions: list[list[Row]] = [[rows[0]]]
    for previous, row in zip(rows, rows[1:]):
        if row.bbox[1] - previous.bbox[3] > gap_limit:
            regions.append([row])
        else:
            regions[-1].append(row)
    return tuple(
        TableRegion(tuple(region), _bbox([word for row in region for word in row.words]))
        for region in regions
    )


def assemble_page(words: list[OcrWord]) -> PageLayout:
    rows = [Row(_cells(group), _bbox(group)) for group in _row_groups(words)]
    return PageLayout(_regions(rows))

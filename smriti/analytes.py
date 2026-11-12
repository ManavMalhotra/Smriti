"""Configured analyte names and synonyms used by extraction and summaries."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from smriti.config import BASE_DIR

ANALYTE_MAP_PATH = BASE_DIR / "data" / "analyte_map.csv"


@dataclass(frozen=True)
class Analyte:
    id: str
    display: str
    unit: str
    synonyms: tuple[str, ...]


@lru_cache(maxsize=1)
def analytes() -> tuple[Analyte, ...]:
    with ANALYTE_MAP_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return tuple(
        Analyte(
            id=row["analyte_id"].strip(),
            display=row["display"].strip(),
            unit=row["unit"].strip(),
            synonyms=tuple(
                synonym.strip().lower()
                for synonym in row["synonyms"].split("|")
                if synonym.strip()
            ),
        )
        for row in rows
    )


@lru_cache(maxsize=1)
def _by_id() -> dict[str, Analyte]:
    return {analyte.id: analyte for analyte in analytes()}


def display_for(analyte_id: str | None, label_raw: str | None) -> str:
    if analyte_id and analyte_id in _by_id():
        return _by_id()[analyte_id].display
    return label_raw or analyte_id or "Unknown"


def default_unit(analyte_id: str | None) -> str | None:
    if analyte_id and analyte_id in _by_id():
        return _by_id()[analyte_id].unit
    return None


def match_analyte(text: str) -> tuple[Analyte, str] | None:
    """Return the longest configured synonym found in text."""
    lowered = text.lower()
    is_ratio = bool(re.search(r"ratio\b|index\b|\ba/g\b", lowered))
    has_mch = bool(re.search(r"\b(?:mean\s+corp|mch|mchc|corpuscular)\b", lowered))
    has_fractional_bili = bool(
        re.search(r"\b(?:direct|conjugated|indirect|unconjugated)\b", lowered)
    )
    has_bun = bool(re.search(r"\b(?:nitrogen|bun)\b", lowered))

    best: tuple[Analyte, str] | None = None
    for analyte in analytes():
        if is_ratio and analyte.id in {
            "creatinine",
            "urea",
            "albumin",
            "ast",
            "alt",
            "platelets",
            "wbc",
        }:
            continue
        if has_mch and analyte.id == "hemoglobin":
            continue
        if has_fractional_bili and analyte.id == "bilirubin_total":
            continue
        if has_bun and analyte.id == "urea":
            continue

        for synonym in analyte.synonyms:
            if re.search(rf"(?<![a-z0-9]){re.escape(synonym)}(?![a-z0-9])", lowered):
                if best is None or len(synonym) > len(best[1]):
                    best = (analyte, synonym)
    return best

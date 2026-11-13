"""Indian medication lexicon and handwriting matching assist."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from rapidfuzz import fuzz

LEXICON_PATH = Path(__file__).resolve().parents[1] / "data" / "indian_meds_lexicon.csv"


@dataclass(frozen=True)
class MedEntry:
    brand: str
    salt: str
    standard_dose: str
    category: str


_LEXICON_CACHE: list[MedEntry] | None = None


def load_med_lexicon(path: Path | str = LEXICON_PATH) -> list[MedEntry]:
    global _LEXICON_CACHE
    if _LEXICON_CACHE is not None and Path(path) == LEXICON_PATH:
        return _LEXICON_CACHE

    entries: list[MedEntry] = []
    p = Path(path)
    if not p.is_file():
        return []

    with open(p, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(
                MedEntry(
                    brand=row["brand"].strip(),
                    salt=row["salt"].strip(),
                    standard_dose=row.get("standard_dose", "").strip(),
                    category=row.get("category", "").strip(),
                )
            )

    if Path(path) == LEXICON_PATH:
        _LEXICON_CACHE = entries
    return entries


def match_medication(query: str, threshold: float = 70.0) -> MedEntry | None:
    """Find closest matching Indian medication for messy OCR/handwriting."""
    if not query or len(query.strip()) < 3:
        return None
    entries = load_med_lexicon()
    best_match = None
    best_score = 0.0
    clean_q = query.strip().lower()

    for entry in entries:
        score = fuzz.token_sort_ratio(clean_q, entry.brand.lower())
        if score > best_score and score >= threshold:
            best_score = score
            best_match = entry

    return best_match

from __future__ import annotations

import json

from smriti.config import BASE_DIR
from smriti.models import Summary

FIXTURE = BASE_DIR / "web" / "src" / "fixtures" / "summary.json"
SUMMARY_KEYS = {
    "patient",
    "coverage",
    "problems",
    "medications",
    "results",
    "pending",
    "documents",
}


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_summary_fixture_has_exactly_seven_keys():
    assert set(_payload()) == SUMMARY_KEYS


def test_summary_fixture_validates_against_pydantic():
    summary = Summary.model_validate(_payload())

    point = summary.results[0].points[0]
    assert len(point.bbox) == 4
    assert all(0 <= coordinate <= 1 for coordinate in point.bbox)
    assert summary.results[0].excluded == []


def test_summary_gap_uses_from_alias():
    dumped = Summary.model_validate(_payload()).model_dump(by_alias=True, mode="json")
    assert "from" in dumped["coverage"]["gaps"][0]

"""Deterministic resolver: synonym, printed range, and unit agreement."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from smriti.analytes import match_analyte


@dataclass(frozen=True)
class Resolution:
    analyte_id: str | None
    mapping_rule: str
    confidence: float
    signals: tuple[str, ...]


def _unit_key(unit: str | None) -> str | None:
    if not unit:
        return None
    value = unit.strip().lower().replace("μ", "u").replace("µ", "u")
    return value.replace(" ", "")


def unit_matches(printed: str | None, configured: str) -> bool:
    printed_key = _unit_key(printed)
    configured_key = _unit_key(configured)
    if printed_key is None or configured_key is None:
        return False
    if printed_key == configured_key:
        return True
    cell_units = {"cells/ul", "/ul", "cells/cumm", "/cumm", "cumm", "cells/mm3", "/mm3"}
    return printed_key in cell_units and configured_key in cell_units


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def range_contains(value: str | None, low: str | None, high: str | None) -> bool:
    number = _decimal(value)
    lower = _decimal(low)
    upper = _decimal(high)
    if number is None or lower is None or upper is None:
        return False
    return lower <= number <= upper


def resolve(
    label: str,
    value: str | None,
    unit: str | None,
    ref_low: str | None,
    ref_high: str | None,
) -> Resolution:
    match = match_analyte(label)
    if match is None:
        return Resolution(None, "unresolved", 0.0, ())

    analyte, synonym = match
    exact = synonym == analyte.display.lower()
    signals = ["exact" if exact else "synonym"]
    if range_contains(value, ref_low, ref_high):
        signals.append("range")
    if unit_matches(unit, analyte.unit):
        signals.append("unit")

    agreement = len(signals)
    mapping_rule = ("exact" if exact else "synonym") if agreement >= 2 else "unresolved"
    return Resolution(
        analyte_id=analyte.id,
        mapping_rule=mapping_rule,
        confidence=round(agreement / 3, 3),
        signals=tuple(signals),
    )

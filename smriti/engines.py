"""Versioned engine identities recorded on extracted fields."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngineInfo:
    family: str
    model: str
    version: str
    device: str = "cpu"
    quantisation: str | None = None

    def __str__(self) -> str:
        value = f"{self.family}:{self.model}@{self.version}+{self.device}"
        if self.quantisation:
            value += f"+{self.quantisation}"
        return value


LOCAL_RULES = EngineInfo("local-rules", "line-rules", "1.0")


def field_engine(ocr_name: str | None) -> str:
    """Return the string stored on every field produced by the local pipeline."""
    return f"{ocr_name or 'paddle'}+{LOCAL_RULES}"

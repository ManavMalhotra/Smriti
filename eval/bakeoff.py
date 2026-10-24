"""Parser bake-off framework for medical document parsing.

Monitors latency, host RAM peak, and GPU VRAM peak per page across candidate
engines (PaddleOCR baseline, PaddleOCR-VL, TeleOCR, OvisOCR).
"""

from __future__ import annotations

import abc
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

from smriti.ocr import OcrWord


@dataclass(frozen=True)
class ResourceSnapshot:
    process_ram_mb: float
    system_ram_mb: float
    gpu_vram_mb: float


def get_gpu_vram_mb() -> float:
    if not shutil.which("nvidia-smi"):
        return 0.0
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,nounits,noheader"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return float(raw.decode("utf-8").strip().splitlines()[0])
    except Exception:
        return 0.0


def current_resources() -> ResourceSnapshot:
    process = psutil.Process(os.getpid())
    process_ram = process.memory_info().rss / (1024 * 1024)
    system_ram = psutil.virtual_memory().used / (1024 * 1024)
    gpu_vram = get_gpu_vram_mb()
    return ResourceSnapshot(
        process_ram_mb=round(process_ram, 1),
        system_ram_mb=round(system_ram, 1),
        gpu_vram_mb=round(gpu_vram, 1),
    )


@dataclass
class ParserResult:
    engine: str
    status: str  # "success" | "error" | "unavailable"
    text: str = ""
    word_count: int = 0
    words: list[OcrWord] = field(default_factory=list)
    latency_s: float = 0.0
    peak_process_ram_mb: float = 0.0
    peak_system_ram_mb: float = 0.0
    peak_gpu_vram_mb: float = 0.0
    error: str | None = None
    metadata: dict = field(default_factory=dict)


class BaseParserAdapter(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Engine name identifier."""

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Check if engine and required dependencies/models are available."""

    @abc.abstractmethod
    def parse_page(self, image_path: Path) -> ParserResult:
        """Parse an image page, measuring execution time and resource peaks."""


class PaddleOcrBaselineAdapter(BaseParserAdapter):
    """PaddleOCR baseline adapter (PP-OCRv5 mobile det + rec)."""

    def __init__(self) -> None:
        self._engine = None

    @property
    def name(self) -> str:
        return "paddleocr_baseline"

    def is_available(self) -> tuple[bool, str]:
        try:
            from smriti.ocr import PaddleOcrEngine

            return True, "PaddleOCR installed and ready"
        except Exception as exc:
            return False, f"PaddleOCR unavailable: {exc}"

    def parse_page(self, image_path: Path) -> ParserResult:
        from smriti.config import load_settings
        from smriti.ocr import get_ocr_engine

        if self._engine is None:
            settings = load_settings()
            self._engine = get_ocr_engine(settings.ocr_det_model, settings.ocr_rec_model)

        t0 = time.perf_counter()
        before = current_resources()

        try:
            words = self._engine.read(image_path)
            after = current_resources()
            latency = time.perf_counter() - t0
            text = " ".join(word.text for word in words)

            return ParserResult(
                engine=self.name,
                status="success",
                text=text,
                word_count=len(words),
                words=words,
                latency_s=round(latency, 3),
                peak_process_ram_mb=max(before.process_ram_mb, after.process_ram_mb),
                peak_system_ram_mb=max(before.system_ram_mb, after.system_ram_mb),
                peak_gpu_vram_mb=max(before.gpu_vram_mb, after.gpu_vram_mb),
            )
        except Exception as exc:
            return ParserResult(
                engine=self.name,
                status="error",
                error=str(exc),
                latency_s=round(time.perf_counter() - t0, 3),
            )


class PaddleOcrVlAdapter(BaseParserAdapter):
    """PaddleOCR-VL vision-language model adapter (e.g. 0.9B document parser)."""

    @property
    def name(self) -> str:
        return "paddleocr_vl"

    def is_available(self) -> tuple[bool, str]:
        try:
            import paddlex  # noqa: F401

            # Checks if PaddleOCR-VL model weights are downloaded
            weights_path = Path.home() / ".paddlex" / "models" / "PaddleOCR-VL"
            if weights_path.exists():
                return True, "PaddleOCR-VL model found"
            return False, "PaddleOCR-VL weights not downloaded (paddlex present)"
        except ImportError:
            return False, "PaddleX / PaddleOCR-VL package not installed"

    def parse_page(self, image_path: Path) -> ParserResult:
        available, reason = self.is_available()
        if not available:
            return ParserResult(engine=self.name, status="unavailable", error=reason)
        # Stub for when model weights are provided
        return ParserResult(
            engine=self.name,
            status="error",
            error="Model loading not yet configured on this device",
        )


class OvisOcrAdapter(BaseParserAdapter):
    """OvisOCR lightweight vision-language parser adapter."""

    @property
    def name(self) -> str:
        return "ovisocr"

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401

            return False, "OvisOCR model weights not downloaded"
        except ImportError:
            return False, "PyTorch / Transformers not installed in environment"

    def parse_page(self, image_path: Path) -> ParserResult:
        available, reason = self.is_available()
        if not available:
            return ParserResult(engine=self.name, status="unavailable", error=reason)
        return ParserResult(
            engine=self.name,
            status="error",
            error="OvisOCR runtime not configured",
        )


class TeleOcrAdapter(BaseParserAdapter):
    """TeleOCR document parser adapter."""

    @property
    def name(self) -> str:
        return "teleocr"

    def is_available(self) -> tuple[bool, str]:
        try:
            import torch  # noqa: F401

            return False, "TeleOCR model weights not downloaded"
        except ImportError:
            return False, "PyTorch / model framework not installed"

    def parse_page(self, image_path: Path) -> ParserResult:
        available, reason = self.is_available()
        if not available:
            return ParserResult(engine=self.name, status="unavailable", error=reason)
        return ParserResult(
            engine=self.name,
            status="error",
            error="TeleOCR runtime not configured",
        )


class MockParserAdapter(BaseParserAdapter):
    """Deterministic mock parser for testing the bake-off harness without heavy models."""

    def __init__(self, name: str = "mock_parser", delay: float = 0.01) -> None:
        self._name = name
        self._delay = delay

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> tuple[bool, str]:
        return True, "Mock parser always available"

    def parse_page(self, image_path: Path) -> ParserResult:
        time.sleep(self._delay)
        resources = current_resources()
        return ParserResult(
            engine=self.name,
            status="success",
            text="MOCK CLINICAL TEXT HbA1c 8.9 % Glucose 126 mg/dL",
            word_count=8,
            words=[
                OcrWord("HbA1c", [0.1, 0.1, 0.2, 0.14], 0.99),
                OcrWord("8.9", [0.3, 0.1, 0.35, 0.14], 0.99),
                OcrWord("%", [0.36, 0.1, 0.4, 0.14], 0.99),
            ],
            latency_s=self._delay,
            peak_process_ram_mb=resources.process_ram_mb,
            peak_system_ram_mb=resources.system_ram_mb,
            peak_gpu_vram_mb=resources.gpu_vram_mb,
        )


REGISTRY: dict[str, type[BaseParserAdapter]] = {
    "paddleocr": PaddleOcrBaselineAdapter,
    "paddleocr_vl": PaddleOcrVlAdapter,
    "ovisocr": OvisOcrAdapter,
    "teleocr": TeleOcrAdapter,
    "mock": MockParserAdapter,
}


def get_adapter(name: str) -> BaseParserAdapter:
    adapter_cls = REGISTRY.get(name.lower())
    if not adapter_cls:
        raise ValueError(f"Unknown parser adapter: {name}. Options: {list(REGISTRY.keys())}")
    return adapter_cls()

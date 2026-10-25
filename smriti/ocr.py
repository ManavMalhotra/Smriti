"""Local PaddleOCR adapter. Images never leave this process."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Paddle 3.x otherwise probes model hosts and may choose an oneDNN kernel that
# fails on some Windows CPUs. The models are cached after the first download.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")

from PIL import Image


class OcrUnavailable(RuntimeError):
    """The local OCR stack is not installed or its model cannot be loaded."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    bbox: list[float]
    confidence: float


def _flat_box(box) -> list[float]:
    array = np.asarray(box, dtype=float)
    if array.shape == (4,):
        return array.tolist()
    if array.ndim == 2 and array.shape[1] == 2:
        xs = array[:, 0]
        ys = array[:, 1]
        return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]
    values = array.reshape(-1).tolist()
    if len(values) == 4:
        return [float(value) for value in values]
    raise ValueError("unsupported OCR box shape")


class PaddleOcrEngine:
    def __init__(self, det_model: str, rec_model: str):
        self.det_model = det_model
        self.rec_model = rec_model
        self.name = f"paddle:{det_model}+{rec_model}"
        self._ocr = None
        self._lock = threading.Lock()

    def _load(self):
        if self._ocr is not None:
            return self._ocr
        with self._lock:
            if self._ocr is not None:
                return self._ocr
            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise OcrUnavailable(
                    "Local OCR is unavailable. Install paddleocr and paddlepaddle."
                ) from exc
            try:
                self._ocr = PaddleOCR(
                    text_detection_model_name=self.det_model,
                    text_recognition_model_name=self.rec_model,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    enable_mkldnn=False,
                )
            except Exception as exc:
                raise OcrUnavailable(f"Local OCR model failed to load: {exc}") from exc
        return self._ocr

    def read(self, image_path: Path) -> list[OcrWord]:
        ocr = self._load()
        with Image.open(image_path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            return []
        try:
            results = ocr.predict(str(image_path))
        except AttributeError:
            results = ocr.ocr(str(image_path), cls=True)
        except Exception as exc:
            raise OcrUnavailable(f"Local OCR failed: {exc}") from exc
        if not results:
            return []

        # PaddleOCR 3.x returns a list of result objects; 2.x returns a nested list.
        first = results[0]
        if hasattr(first, "get") or isinstance(first, dict):
            texts = first.get("rec_texts") or []
            scores = first.get("rec_scores") or []
            boxes = first.get("rec_boxes")
            if boxes is None:
                boxes = first.get("rec_polys") or first.get("dt_polys") or []
            words = []
            for text, score, box in zip(texts, scores, boxes):
                text = str(text).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = _flat_box(box)
                words.append(
                    OcrWord(
                        text=text,
                        bbox=[
                            max(0.0, min(1.0, x0 / width)),
                            max(0.0, min(1.0, y0 / height)),
                            max(0.0, min(1.0, x1 / width)),
                            max(0.0, min(1.0, y1 / height)),
                        ],
                        confidence=max(0.0, min(1.0, float(score))),
                    )
                )
            return words

        words = []
        for item in first:
            try:
                box, (text, score) = item
            except (TypeError, ValueError):
                continue
            text = str(text).strip()
            if not text:
                continue
            x0, y0, x1, y1 = _flat_box(box)
            words.append(
                OcrWord(
                    text=text,
                    bbox=[
                        max(0.0, min(1.0, x0 / width)),
                        max(0.0, min(1.0, y0 / height)),
                        max(0.0, min(1.0, x1 / width)),
                        max(0.0, min(1.0, y1 / height)),
                    ],
                    confidence=max(0.0, min(1.0, float(score))),
                )
            )
        return words


_ENGINE: PaddleOcrEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_ocr_engine(det_model: str, rec_model: str) -> PaddleOcrEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = PaddleOcrEngine(det_model, rec_model)
    return _ENGINE

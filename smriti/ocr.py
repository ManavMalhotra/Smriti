"""Local OCR adapters behind an OcrEngine interface.

Uses RapidOCR with PP-OCRv5 ONNX models on CPU by default, with PaddleOCR kept
as a robust local fallback. Images never leave this process.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
from PIL import Image

# Paddle 3.x otherwise probes model hosts and may choose an oneDNN kernel that
# fails on some Windows CPUs.
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_use_onednn", "0")

logger = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """The local OCR stack is not installed or its model cannot be loaded."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    bbox: list[float]
    confidence: float

    @property
    def bbox_1000(self) -> list[int]:
        """Return bounding box mapped to normalized [0, 1000] integer coordinates."""
        return [int(round(v * 1000)) for v in self.bbox]


@runtime_checkable
class OcrEngine(Protocol):
    name: str

    def read(self, image_path: Path, *, debug: bool = False) -> list[OcrWord]:
        """Full-page detection + recognition (debug flag required in main flow)."""
        ...

    def read_lines(
        self,
        line_crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        """Mode REC-ONLY for line crops (no det, no cls). Used by Stage 1 line inspector."""
        ...

    def read_crops(
        self,
        crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        """Mode REC-ONLY for cell crops (no det, no cls). Used by Stage 6 second read."""
        ...


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


def _ensure_en_dict(dict_path: Path) -> Path:
    if dict_path.exists() and dict_path.stat().st_size > 0:
        return dict_path
    dict_path.parent.mkdir(parents=True, exist_ok=True)
    cache_yml = Path.home() / ".paddlex" / "official_models" / "en_PP-OCRv5_mobile_rec" / "inference.yml"
    if cache_yml.exists():
        import yaml

        data = yaml.safe_load(cache_yml.read_text(encoding="utf-8"))
        chars = data.get("PostProcess", {}).get("character_dict", [])
        if chars:
            dict_path.write_text("\n".join(chars), encoding="utf-8")
            return dict_path
    raise OcrUnavailable(f"Dictionary file not found at {dict_path}")


class RapidOcrOnnxEngine:
    """CPU-only ONNX OCR engine using RapidOCR and official PP-OCRv5 English weights."""

    def __init__(
        self,
        det_repo: str = "PaddlePaddle/PP-OCRv5_mobile_det_onnx",
        rec_repo: str = "PaddlePaddle/en_PP-OCRv5_mobile_rec_onnx",
        dict_path: Path | str | None = None,
        threads: int = 4,
    ):
        self.det_repo = det_repo
        self.rec_repo = rec_repo
        self.dict_path = (
            Path(dict_path)
            if dict_path
            else Path(__file__).resolve().parents[1] / "data" / "models" / "en_dict.txt"
        )
        self.threads = threads
        self.name = "rapidocr:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec@onnx+cpu"
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                from huggingface_hub import hf_hub_download
                from onnxruntime import ExecutionMode
                from rapidocr_onnxruntime.utils.infer_engine import OrtInferSession
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise OcrUnavailable(
                    "RapidOCR is unavailable. Install rapidocr_onnxruntime and huggingface_hub."
                ) from exc

            # RapidOCR exposes thread counts but not SessionOptions.execution_mode.
            if not getattr(OrtInferSession, "_smriti_sequential", False):
                init_options = OrtInferSession._init_sess_opts

                def sequential_options(config):
                    options = init_options(config)
                    options.execution_mode = ExecutionMode.ORT_SEQUENTIAL
                    options.enable_cpu_mem_arena = False
                    return options

                OrtInferSession._init_sess_opts = staticmethod(sequential_options)
                OrtInferSession._smriti_sequential = True

            dict_file = _ensure_en_dict(self.dict_path)
            try:
                try:
                    det_path = hf_hub_download(
                        repo_id=self.det_repo, filename="inference.onnx", local_files_only=True
                    )
                    rec_path = hf_hub_download(
                        repo_id=self.rec_repo, filename="inference.onnx", local_files_only=True
                    )
                except Exception:
                    det_path = hf_hub_download(repo_id=self.det_repo, filename="inference.onnx")
                    rec_path = hf_hub_download(repo_id=self.rec_repo, filename="inference.onnx")
                engine = RapidOCR(
                    det_model_path=det_path,
                    det_limit_side_len=1600,
                    det_limit_type="max",
                    rec_model_path=rec_path,
                    rec_keys_path=str(dict_file),
                    rec_batch_num=1,
                    intra_op_num_threads=self.threads,
                    inter_op_num_threads=1,
                    det_use_cuda=False,
                    det_use_dml=False,
                    cls_use_cuda=False,
                    cls_use_dml=False,
                    rec_use_cuda=False,
                    rec_use_dml=False,
                )
                for session in (engine.text_det.infer.session, engine.text_cls.infer.session,
                                engine.text_rec.session.session):
                    if session.get_providers() != ["CPUExecutionProvider"]:
                        raise OcrUnavailable("OCR did not select the CPU provider")
                self._engine = engine
            except Exception as exc:
                raise OcrUnavailable(f"Failed to initialize RapidOCR ONNX engine: {exc}") from exc
        return self._engine

    def read(self, image_path: Path, *, debug: bool = False) -> list[OcrWord]:
        """Full-page detection + recognition kept behind an explicit debug flag.

        The main pipeline uses read_lines() for line-crop checks (Stage 1)
        and read_crops() for cell crops (Stage 6).
        """
        if not debug:
            raise RuntimeError(
                "Full-page det+rec is disabled in main flow (over-scoped). "
                "Use read_lines() or read_crops(), or pass debug=True explicitly."
            )
        engine = self._load()
        with Image.open(image_path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            return []
        try:
            results, _ = engine(str(image_path))
        except Exception as exc:
            raise OcrUnavailable(f"RapidOCR inference failed: {exc}") from exc
        if not results:
            return []

        words: list[OcrWord] = []
        for box, text, score in results:
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

    def read_lines(
        self,
        line_crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        """Mode REC-ONLY line recognition: no det, no cls. Stage 1 inspector."""
        return self.read_crops(line_crops, batch_size=batch_size)

    def read_crops(
        self,
        crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        """Mode REC-ONLY: batched cell-crop second reads (no detection, no angle classifier)."""
        if not crops:
            return []
        engine = self._load()
        processed_crops = []
        for c in crops:
            if isinstance(c, Image.Image):
                processed_crops.append(np.array(c.convert("RGB")))
            elif isinstance(c, np.ndarray):
                processed_crops.append(c)
            else:
                raise TypeError(f"unsupported crop type: {type(c)}")

        results: list[tuple[str, float]] = []
        batch_size = max(1, min(32, batch_size))
        for i in range(0, len(processed_crops), batch_size):
            chunk = processed_crops[i : i + batch_size]
            # Calls engine.text_rec directly: skips text_det and text_cls entirely
            rec_res, _ = engine.text_rec(chunk)
            for item in rec_res:
                if item:
                    text, score = item
                    results.append((str(text).strip(), float(score)))
                else:
                    results.append(("", 0.0))
        return results

    def read_crop(self, crop: Image.Image | np.ndarray) -> tuple[str, float]:
        """Recognize a single cropped image region via Mode REC-ONLY."""
        res = self.read_crops([crop], batch_size=1)
        return res[0] if res else ("", 0.0)


class PaddleOcrEngine:
    """PaddleOCR engine kept as a CPU fallback."""

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
                    device="cpu",
                    text_detection_model_name=self.det_model,
                    text_recognition_model_name=self.rec_model,
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    text_det_limit_type="max",
                    text_det_limit_side_len=1600,
                    text_recognition_batch_size=1,
                    enable_mkldnn=False,
                )
                import paddle

                if paddle.device.get_device() != "cpu":
                    self._ocr = None
                    raise OcrUnavailable("OCR did not select the CPU device")
            except Exception as exc:
                raise OcrUnavailable(f"Local OCR model failed to load: {exc}") from exc
        return self._ocr

    def read(self, image_path: Path, *, debug: bool = False) -> list[OcrWord]:
        if not debug:
            raise RuntimeError(
                "Full-page det+rec is disabled in main flow (over-scoped). "
                "Use read_lines() or read_crops(), or pass debug=True explicitly."
            )
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

    def read_lines(
        self,
        line_crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        return self.read_crops(line_crops, batch_size=batch_size)

    def read_crops(
        self,
        crops: list[Image.Image | np.ndarray],
        batch_size: int = 16,
    ) -> list[tuple[str, float]]:
        """Mode REC-ONLY fallback using PaddleOCR."""
        if not crops:
            return []
        ocr = self._load()
        processed_crops = []
        for c in crops:
            if isinstance(c, Image.Image):
                processed_crops.append(np.array(c.convert("RGB")))
            elif isinstance(c, np.ndarray):
                processed_crops.append(c)
            else:
                raise TypeError(f"unsupported crop type: {type(c)}")

        pipeline = getattr(ocr, "paddlex_pipeline", None)
        sub_pipeline = getattr(pipeline, "_pipeline", None) if pipeline else None
        rec_model = getattr(sub_pipeline, "text_rec_model", None) if sub_pipeline else None

        results: list[tuple[str, float]] = []
        for c in processed_crops:
            if rec_model is not None:
                try:
                    res = list(rec_model(c))
                    if res and len(res) > 0 and hasattr(res[0], "get"):
                        texts = res[0].get("rec_texts", [])
                        scores = res[0].get("rec_scores", [])
                        text = str(texts[0]).strip() if texts else ""
                        score = float(scores[0]) if scores else 0.0
                        results.append((text, score))
                        continue
                except Exception:
                    pass
            results.append(("", 0.0))
        return results

    def read_crop(self, crop: Image.Image | np.ndarray) -> tuple[str, float]:
        res = self.read_crops([crop], batch_size=1)
        return res[0] if res else ("", 0.0)


_ENGINE: OcrEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_ocr_engine(
    det_model: str = "PP-OCRv5_mobile_det",
    rec_model: str = "en_PP-OCRv5_mobile_rec",
    backend: str = "onnx",
    allow_paddle_fallback: bool = False,
) -> OcrEngine:
    """Return the configured OcrEngine singleton.

    Defaults to RapidOcrOnnxEngine on CPU (6 threads). PaddleOCR is only loaded
    when selected explicitly or when its fallback is explicitly enabled.
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if backend == "onnx":
            try:
                engine = RapidOcrOnnxEngine()
                engine._load()
                _ENGINE = engine
                return _ENGINE
            except Exception as exc:
                if not allow_paddle_fallback:
                    raise OcrUnavailable(f"RapidOCR ONNX engine failed to initialize: {exc}") from exc
                logger.warning(
                    "RapidOCR ONNX engine failed to initialize (%s). Falling back to PaddleOcrEngine.",
                    exc,
                )
        elif backend != "paddle":
            raise ValueError(f"Unknown OCR backend: {backend}")
        _ENGINE = PaddleOcrEngine(det_model, rec_model)
        return _ENGINE


def reset_ocr_engine() -> None:
    """Clear cached engine singleton (primarily for testing)."""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None

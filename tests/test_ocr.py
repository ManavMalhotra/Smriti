from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from smriti.ocr import (
    OcrEngine,
    OcrUnavailable,
    OcrWord,
    PaddleOcrEngine,
    RapidOcrOnnxEngine,
    _flat_box,
    get_ocr_engine,
    reset_ocr_engine,
)

pytestmark = pytest.mark.unit


def test_ocr_engine_protocol():
    assert isinstance(RapidOcrOnnxEngine(), OcrEngine)
    assert isinstance(PaddleOcrEngine("det", "rec"), OcrEngine)


def test_flat_box_variations():
    assert _flat_box([10, 20, 30, 40]) == [10.0, 20.0, 30.0, 40.0]
    poly = [[10, 20], [30, 20], [30, 40], [10, 40]]
    assert _flat_box(poly) == [10.0, 20.0, 30.0, 40.0]
    with pytest.raises(ValueError, match="unsupported OCR box shape"):
        _flat_box([1, 2, 3])


def test_rapid_ocr_read_requires_debug_flag(tmp_path: Path):
    engine = RapidOcrOnnxEngine()
    img_path = tmp_path / "page.png"
    Image.new("RGB", (100, 100), "white").save(img_path)
    with pytest.raises(RuntimeError, match="Full-page det\\+rec is disabled"):
        engine.read(img_path)


def test_rapid_ocr_read_mocked(tmp_path: Path):
    engine = RapidOcrOnnxEngine()
    fake_rapid = MagicMock()
    fake_rapid.return_value = (
        [
            ([[100, 200], [300, 200], [300, 250], [100, 250]], "HbA1c 8.9", 0.98),
            ([[100, 300], [250, 300], [250, 350], [100, 350]], "%", 0.95),
        ],
        [0.1, 0.0, 0.2],
    )
    engine._engine = fake_rapid

    img_path = tmp_path / "page.png"
    Image.new("RGB", (1000, 1000), "white").save(img_path)

    words = engine.read(img_path, debug=True)
    assert len(words) == 2
    assert words[0].text == "HbA1c 8.9"
    assert words[0].bbox == [0.1, 0.2, 0.3, 0.25]
    assert words[0].confidence == 0.98
    assert words[1].text == "%"
    assert words[1].bbox == [0.1, 0.3, 0.25, 0.35]


def test_rapid_ocr_crop_mocked():
    engine = RapidOcrOnnxEngine()
    fake_rapid = MagicMock()
    fake_rapid.text_rec.return_value = ([("13.2", 0.99)], 0.02)
    engine._engine = fake_rapid

    crop_img = Image.new("RGB", (100, 40), "white")
    text, score = engine.read_crop(crop_img)
    assert text == "13.2"
    assert score == 0.99

    crop_arr = np.zeros((40, 100, 3), dtype=np.uint8)
    text_arr, score_arr = engine.read_crop(crop_arr)
    assert text_arr == "13.2"
    assert score_arr == 0.99


def test_rapid_ocr_rec_only_batched():
    engine = RapidOcrOnnxEngine()
    fake_rapid = MagicMock()
    # Mock text_rec for batch of 20 crops chunked by 16
    def mock_rec(crops):
        return [(f"val_{i}", 0.95) for i in range(len(crops))], 0.05

    fake_rapid.text_rec.side_effect = mock_rec
    engine._engine = fake_rapid

    crops = [np.zeros((30, 80, 3), dtype=np.uint8) for _ in range(20)]
    results = engine.read_crops(crops, batch_size=16)
    assert len(results) == 20
    assert results[0] == ("val_0", 0.95)
    assert results[19] == ("val_3", 0.95)  # second chunk has 4 items (0..3)
    assert fake_rapid.text_rec.call_count == 2


def test_get_ocr_engine_onnx_fallback(monkeypatch):
    reset_ocr_engine()
    # Mock RapidOcrOnnxEngine._load to fail
    with patch.object(RapidOcrOnnxEngine, "_load", side_effect=OcrUnavailable("Simulated ONNX failure")):
        engine = get_ocr_engine(backend="onnx", allow_paddle_fallback=True)
        assert isinstance(engine, PaddleOcrEngine)
    reset_ocr_engine()


def test_empty_image_returns_no_words(tmp_path: Path):
    engine = RapidOcrOnnxEngine()
    engine._engine = MagicMock()
    img_path = tmp_path / "zero.png"
    with patch("PIL.Image.open") as mock_open:
        mock_img = MagicMock()
        mock_img.size = (0, 0)
        mock_open.return_value.__enter__.return_value = mock_img
        assert engine.read(img_path, debug=True) == []


def test_paddle_loader_selects_and_validates_cpu(monkeypatch):
    import sys
    from types import SimpleNamespace

    factory = MagicMock()
    monkeypatch.setitem(sys.modules, "paddleocr", SimpleNamespace(PaddleOCR=factory))
    monkeypatch.setitem(sys.modules, "paddle", SimpleNamespace(device=SimpleNamespace(get_device=lambda: "cpu")))
    engine = PaddleOcrEngine("det", "rec")
    engine._load()
    assert factory.call_args.kwargs["device"] == "cpu"
    assert factory.call_args.kwargs["enable_mkldnn"] is False
    monkeypatch.setitem(sys.modules, "paddle", SimpleNamespace(device=SimpleNamespace(get_device=lambda: "gpu:0")))
    with pytest.raises(OcrUnavailable, match="CPU"):
        PaddleOcrEngine("det", "rec")._load()


def test_rapid_loader_uses_installed_flat_api_and_validates_all_sessions(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace

    class InferSession:
        _init_sess_opts = staticmethod(lambda config: SimpleNamespace(execution_mode=None))

    sequential = object()
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL=sequential)))
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime.utils.infer_engine", SimpleNamespace(
        OrtInferSession=InferSession))
    session = MagicMock()
    session.get_providers.return_value = ["CPUExecutionProvider"]
    factory = MagicMock(return_value=SimpleNamespace(
        text_det=SimpleNamespace(infer=SimpleNamespace(session=session)),
        text_cls=SimpleNamespace(infer=SimpleNamespace(session=session)),
        text_rec=SimpleNamespace(session=SimpleNamespace(session=session)),
    ))
    download = MagicMock(side_effect=lambda repo_id, **kw: repo_id + "/inference.onnx")
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", SimpleNamespace(RapidOCR=factory))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    dictionary = tmp_path / "en_dict.txt"
    dictionary.write_text("a\nb", encoding="utf-8")
    engine = RapidOcrOnnxEngine(dict_path=dictionary)
    assert engine._load() is factory.return_value
    assert engine._load() is factory.return_value
    factory.assert_called_once_with(
        det_model_path=engine.det_repo + "/inference.onnx", det_limit_side_len=1600,
        det_limit_type="max", rec_model_path=engine.rec_repo + "/inference.onnx",
        rec_keys_path=str(dictionary), rec_batch_num=1, intra_op_num_threads=6,
        inter_op_num_threads=1, det_use_cuda=False, det_use_dml=False,
        cls_use_cuda=False, cls_use_dml=False, rec_use_cuda=False, rec_use_dml=False,
    )
    assert session.get_providers.call_count == 3
    assert InferSession._init_sess_opts({}).execution_mode is sequential
    assert all(call.kwargs["local_files_only"] for call in download.call_args_list)
    session.get_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    rejected = RapidOcrOnnxEngine(dict_path=dictionary)
    with pytest.raises(OcrUnavailable, match="CPU"):
        rejected._load()
    assert rejected._engine is None

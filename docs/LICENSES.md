# License Register

Verified: 2026-10-25
Authority: ARCHITECTURE COMPLIANCE ORDER v3

| Component | Role | License | Status | Evidence URL / Reference | Notes |
|---|---|---|---|---|---|
| **PaddleOCR-VL-1.6** (code + weights) | Scanned page parser candidate (0.9B VLM) | Apache-2.0 | **VERIFIED OK** (commercial allowed) | https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6 ; https://github.com/PaddlePaddle/PaddleOCR | Official doc-parser pipeline for full page parse; transformers path for header KIE crops |
| **TeleOCR** | Scanned page parser candidate (~1.2B) | Apache-2.0 | **VERIFIED OK** (commercial allowed) | https://github.com/caipeng328/TeleOCR ; https://huggingface.co/StarDoc-AI/TeleOCR | OTSL table converter used to generate HTML; cells built by local code |
| **OvisOCR3** | Primary parser candidate & header KIE | Apache-2.0 upstream; Apache-2.0 GGUF | **VERIFIED OK** (with conversion caveat) | https://huggingface.co/ATH-MaaS/OvisOCR3 ; https://huggingface.co/michalland/OvisOCR3-GGUF | Track A GGUF (unofficial conversion, record `ovisocr3-gguf-q8_0-unofficial-` in `model_version`); Track B WSL2 vLLM |
| **Qwen3.5** (4B / 2B Q4 GGUF) | Prose extraction, classifier/header fallback, tie-break | Apache-2.0 | **VERIFIED OK** (commercial allowed) | https://github.com/QwenLM/Qwen3.5 ; https://huggingface.co/Qwen | Used with mmproj in llama.cpp; FP16 cast on GTX 1650 |
| **RapidOCR + PP-OCR ONNX models** | Independent second reader (CPU 4T) & suspicious-page cross-check | Apache-2.0 | **VERIFIED OK** (commercial allowed) | https://github.com/RapidAI/RapidOCR/blob/main/python/MODEL_LICENSES.md ; RapidOCR Discussion #736 | Upstream weights Baidu (Apache-2.0), maintainer confirmed commercial inference + redistribution covered |
| **Indian Drug Dataset** | Section-scoped medication normalisation | UNRESOLVED | **PENDING USER DECISION** | Option A: Kaggle "All India Drug Bank Database" (~253k records, ODbL) / Option B: licensed commercial source (e.g. DrugSetu) | **BLOCKING Step 7**. Option A is free/ODbL but stale ("update frequency: never"). Option B is current but requires commercial licensing. |

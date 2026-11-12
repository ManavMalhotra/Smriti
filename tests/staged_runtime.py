"""Explicit in-process stage seam for synthetic fixtures; production always uses owned children."""

import json
import pytest

from smriti.coordinator import Coordinator
from tests.test_preparation import inline_supervisor

OCR_NAME = "rapidocr:PP-OCRv5_mobile_det+en_PP-OCRv5_mobile_rec@onnx+cpu"


def run_batch(engine, settings, *, ocr_engine=None):
    with pytest.MonkeyPatch.context() as patch:
        if ocr_engine is not None:
            class FakeOcr:
                name = OCR_NAME

                def _load(self):
                    pass

                def read(self, path, *, debug):
                    assert debug is True
                    return ocr_engine.read(path)
            patch.setattr("smriti.ocr.RapidOcrOnnxEngine", FakeOcr)
        with Coordinator(engine, settings, supervisor=inline_supervisor) as controller:
            return controller.process_batch()


def prepare_response(client, response):
    """Seed a prepared record explicitly after HTTP acceptance; do not pretend POST prepares it."""
    from smriti.preparation import prepare_submission

    if response.status_code != 202:
        return response
    result = response.json()
    app = client.app
    outcome = prepare_submission(app.state.engine, app.state.settings, result["job_id"], supervisor=inline_supervisor)
    if outcome.success:
        job = client.get(f"/api/jobs/{result['job_id']}").json()
        result.update(document_id=job["document_id"], pages=job["total_pages"], status="queued")
        response._content = json.dumps(result).encode()
    return response

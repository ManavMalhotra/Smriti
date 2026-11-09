from __future__ import annotations

from dataclasses import asdict, replace

import json
import pytest

from smriti import model_stages, preparation, processing_helpers
from smriti.candidates import Candidates
from smriti.extract import ExtractedField
from smriti.processing_store import identity, save_page, submission
from smriti.spool import SpoolError
from smriti.vlm import VLM_ENGINE_NAME
from tests.test_model_stages import prepared
from tests.test_spool import spool_db
from tests.test_worker import _field

pytestmark = pytest.mark.integration


def rules(spool_db, settings, pages=1):
    job, context = prepared(spool_db, settings, pages)
    model_stages.ocr_target(context, lambda *args, **kwargs: None)
    context = {"settings": context["settings"], "job_id": job, "now": "2026-11-05"}
    processing_helpers.rules_target(context, lambda *args, **kwargs: None)
    return job, context


def test_complete_document_qwen_allows_first_empty_later_nonempty(spool_db, settings):
    settings = replace(settings, vlm_enabled=True)
    job, context = rules(spool_db, settings, 2)
    row = submission(spool_db, job)
    field = replace(_field("92", engine=VLM_ENGINE_NAME), page=2)
    save_page(spool_db, settings, row, "qwen", 1, fields=[], model_version=VLM_ENGINE_NAME)
    save_page(spool_db, settings, row, "qwen", 2, fields=[asdict(field)], model_version=VLM_ENGINE_NAME)
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        assert scratch.count("checked") > 0
        assert any(item["page"] == 2 for _, item, _ in scratch.rows("checked"))
        assert all(report_id for _, _, report_id in scratch.rows("checked"))


def test_empty_whole_document_qwen_keeps_ocr_review_without_confidence_increase(spool_db, settings):
    settings = replace(settings, vlm_enabled=True)
    job, context = rules(spool_db, settings)
    row = submission(spool_db, job)
    save_page(spool_db, settings, row, "qwen", 1, fields=[], model_version=VLM_ENGINE_NAME)
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        scratch.add("field", _field("92", engine="ocr"), match_key="glucose")
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    assert submission(spool_db, job)["manifest"]["processing"]["final_ready"]
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        field = next(scratch.rows("checked"))[1]
        assert "OCR-only" in field["reason"] and field["confidence"] == _field("92", engine="ocr").confidence


def test_unexplained_missing_qwen_page_remains_blocking(spool_db, settings):
    settings = replace(settings, vlm_enabled=True)
    job, context = rules(spool_db, settings)
    with pytest.raises(SpoolError, match="prepared_artifact_invalid"):
        processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    assert not submission(spool_db, job)["manifest"]["processing"]["final_ready"]


def test_degraded_qwen_leaves_handwritten_page_unread_without_blocking(spool_db, settings):
    settings = replace(settings, vlm_enabled=True)
    job, context = rules(spool_db, settings, 2)
    row = submission(spool_db, job)
    meta = preparation._prepared_dir(settings, job) / "page_2.meta.json"
    page = json.loads(meta.read_text(encoding="utf-8"))
    page["capture_type"] = "handwritten"
    meta.write_text(json.dumps(page), encoding="utf-8")
    save_page(spool_db, settings, row, "qwen", 1, fields=[], model_version=VLM_ENGINE_NAME)
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    assert submission(spool_db, job)["manifest"]["processing"]["final_ready"]


def test_disabled_qwen_still_annotates_printed_ocr_fields(spool_db, settings):
    job, context = rules(spool_db, settings)
    row = submission(spool_db, job)
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        scratch.add("field", _field("92", engine="ocr"), match_key="glucose")
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        assert "OCR-only" in next(scratch.rows("checked"))[1]["reason"]


def test_verified_candidates_preserve_legacy_crosscheck_keys_and_order(spool_db, settings):
    from smriti.worker import cross_check_extractions

    settings = replace(settings, vlm_enabled=True)
    job, context = rules(spool_db, settings)
    row = submission(spool_db, job)
    fields = [_field("92", engine="ocr"), _field("93", engine="ocr")]
    readings = [_field("91", engine=VLM_ENGINE_NAME), _field("92", engine=VLM_ENGINE_NAME)]
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        scratch.reset()
        for field in fields:
            scratch.add("field", field, dedup=(field.analyte_id, field.value_num, 1), match_key="glucose")
    save_page(spool_db, settings, row, "qwen", 1, fields=[asdict(field) for field in readings], model_version=VLM_ENGINE_NAME)
    processing_helpers.verification_target(context, lambda *args, **kwargs: None)
    with Candidates(spool_db, settings, job, identity(row)) as scratch:
        result = [ExtractedField(**item) for _, item, _ in scratch.rows("checked")]
    assert result == cross_check_extractions(fields, readings, [])

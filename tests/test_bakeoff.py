from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

from eval.bakeoff import (
    MockParserAdapter,
    current_resources,
    get_adapter,
)
from eval.manifest import build_manifest, infer_doc_type_from_name
from eval.run_bakeoff import run_benchmark

pytestmark = pytest.mark.unit


def test_infer_doc_type_from_name():
    assert infer_doc_type_from_name("HM CT SCAN 2021.pdf") == "ct"
    assert infer_doc_type_from_name("Patient_MRI_Brain.pdf") == "mri"
    assert infer_doc_type_from_name("Chest_X-Ray_PA.pdf") == "xray"
    assert infer_doc_type_from_name("HM Bronchoscopy Report.pdf") == "pathology"
    assert infer_doc_type_from_name("HM ADMISSION 2025.pdf") == "discharge_summary"
    assert infer_doc_type_from_name("Clinic_Prescription.pdf") == "prescription"
    assert infer_doc_type_from_name("Blood_Investigation_Lab.pdf") == "lab_report"
    assert infer_doc_type_from_name("Random_Note.pdf") == "other"


def test_build_manifest_synthetic(tmp_path):
    source_dir = tmp_path / "source"
    out_dir = tmp_path / "out"
    source_dir.mkdir()

    pdf_path = source_dir / "Test_CT_Scan.pdf"
    doc = pymupdf.open()
    page1 = doc.new_page(width=300, height=400)
    page1.insert_text((50, 50), "CT CHEST SCAN", fontsize=14)
    page2 = doc.new_page(width=300, height=400)
    page2.insert_text((50, 50), "IMPRESSION: NORMAL", fontsize=14)
    doc.save(str(pdf_path))
    doc.close()

    manifest = build_manifest(source_dir, out_dir, dpi=72)
    assert manifest["total_documents"] == 1
    assert manifest["total_pages"] == 2
    assert manifest["documents"][0]["doc_type"] == "ct"

    page_files = list((out_dir / "pages" / "Test_CT_Scan").glob("*.png"))
    assert len(page_files) == 2


def test_resource_tracker_returns_valid_numbers():
    resources = current_resources()
    assert resources.process_ram_mb > 0
    assert resources.system_ram_mb > 0
    assert resources.gpu_vram_mb >= 0


def test_run_benchmark_mock_engine(tmp_path):
    source_dir = tmp_path / "source"
    out_dir = tmp_path / "out"
    source_dir.mkdir()

    pdf_path = source_dir / "Admission_Summary.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((30, 30), "DISCHARGE SUMMARY", fontsize=14)
    doc.save(str(pdf_path))
    doc.close()

    manifest = build_manifest(source_dir, out_dir, dpi=72)
    manifest_path = out_dir / "manifest.json"

    summary = run_benchmark(manifest_path, "mock", limit=1)
    assert summary["engine"] == "mock_parser"
    assert summary["available"] is True
    assert summary["total_pages_evaluated"] == 1
    assert summary["success_count"] == 1
    assert summary["resources"]["hardware_budget_pass"] is True
    assert summary["page_results"][0]["doc_type"] == "discharge_summary"


def test_get_adapter_unknown_raises():
    with pytest.raises(ValueError, match="Unknown parser adapter"):
        get_adapter("unknown_model_xyz")

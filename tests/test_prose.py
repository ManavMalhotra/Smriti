from __future__ import annotations

import pytest

from smriti.ocr import OcrWord
from smriti.prose import (
    extract_prose_sections,
    extract_prose_with_grounding,
    verify_grounding,
)

pytestmark = pytest.mark.unit


def test_verify_grounding_exact_match():
    source = (
        "DEPARTMENT OF RADIOLOGY\n"
        "CT SCAN OF BRAIN\n"
        "Findings: The ventricular system and basal cisterns are normal.\n"
        "Impression: No acute intracranial hemorrhage or mass effect."
    )
    candidate = "No acute intracranial hemorrhage or mass effect."
    verdict = verify_grounding(candidate, source)
    assert verdict.is_grounded is True
    assert verdict.grounding_score == 1.0
    assert len(verdict.ungrounded_sentences) == 0


def test_verify_grounding_rejects_hallucination():
    source = (
        "CHEST RADIOGRAPH\n"
        "Impression: Clear lung fields. Normal cardiac size."
    )
    # Hallucinated statement never stated in the source
    candidate = "Bilateral pulmonary consolidation with large pleural effusion."
    verdict = verify_grounding(candidate, source)
    assert verdict.is_grounded is False
    assert verdict.grounding_score < 0.2
    assert len(verdict.ungrounded_sentences) == 1
    assert "consolidation" in verdict.ungrounded_sentences[0]


def test_verify_grounding_isolates_partial_hallucination():
    source = "Findings: Normal liver, spleen and pancreas. Impression: Normal abdomen."
    candidate = "Normal liver, spleen and pancreas. Severe acute appendicitis noted."
    verdict = verify_grounding(candidate, source)
    assert verdict.is_grounded is False
    assert "Severe acute appendicitis noted." in verdict.ungrounded_sentences
    assert "Normal liver, spleen and pancreas." in verdict.grounded_text


def test_extract_prose_sections_ct_report():
    ct_text = (
        "CITY HOSPITAL - DEPARTMENT OF RADIOLOGY\n"
        "CT CHEST WITH IV CONTRAST\n"
        "Findings: Both lungs show normal aeration. Trachea and major bronchi are patent. "
        "No mediastinal lymphadenopathy.\n"
        "Impression: Normal CT scan of chest. No acute parenchymal abnormality."
    )
    words = [
        OcrWord("Impression:", [0.1, 0.4, 0.3, 0.44], 0.98),
        OcrWord("Normal", [0.32, 0.4, 0.4, 0.44], 0.98),
    ]

    sections = extract_prose_sections(ct_text, page=1, words=words)
    assert len(sections) == 2

    by_name = {s.section_name: s for s in sections}
    assert "findings" in by_name
    assert "impression" in by_name

    impression = by_name["impression"]
    assert impression.title == "Impression"
    assert "Normal CT scan of chest" in impression.text
    assert impression.is_grounded is True
    assert impression.grounding_score == 1.0


def test_extract_prose_sections_discharge_summary():
    ds_text = (
        "DISCHARGE SUMMARY\n"
        "Date of Admission: 10/08/2024\n"
        "Final Diagnosis: Community acquired pneumonia, resolved.\n"
        "Discharge Advice: Tab. Amoxicillin 500 mg TDS for 5 days. Review after 1 week in OPD."
    )
    sections = extract_prose_sections(ds_text, page=1)
    by_name = {s.section_name: s for s in sections}

    assert "diagnosis" in by_name
    assert "Community acquired pneumonia, resolved." in by_name["diagnosis"].text

    assert "advice" in by_name
    assert "Tab. Amoxicillin 500 mg" in by_name["advice"].text


def test_extract_prose_with_grounding_model_fallback():
    source = "HISTOPATHOLOGY REPORT\nImpression: Chronic non-specific lymphadenitis."
    # Simulate candidate model output that is verified against source
    candidates = {
        "impression": "Chronic non-specific lymphadenitis.",
        "hallucination": "Malignant metastatic carcinoma.",
    }
    sections = extract_prose_with_grounding(source, page=1, candidate_sections=candidates)
    assert len(sections) == 1
    assert sections[0].section_name == "impression"
    assert sections[0].is_grounded is True

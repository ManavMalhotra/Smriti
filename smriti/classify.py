"""Document-type classification from local OCR text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from smriti.analytes import analytes

LAB_KEYWORDS = (
    "reference range",
    "ref range",
    "biological reference",
    "investigation",
    "laboratory",
    "lab report",
    "specimen",
    "serum",
    "plasma",
    "haemoglobin",
    "hemoglobin",
    "hba1c",
    "creatinine",
    "cholesterol",
    "triglyceride",
    "platelet",
    "leucocyte",
    "leukocyte",
    "fasting",
    "postprandial",
    "collection date",
)
PRESCRIPTION_KEYWORDS = (
    "prescription",
    "rx",
    "tablet",
    "tab.",
    "capsule",
    "cap.",
    "syrup",
    "injection",
    "inj.",
    "dose",
    "dosage",
    "take",
    "twice daily",
    "once daily",
    "bd",
    "od",
    "tds",
    "qid",
    "sos",
    "prn",
    "advice",
)
PHARMACY_KEYWORDS = (
    "pharmacy",
    "chemist",
    "invoice",
    "bill no",
    "bill date",
    "mrp",
    "batch",
    "expiry",
    "exp date",
    "qty",
    "gst",
    "amount",
)
DISCHARGE_KEYWORDS = (
    "discharge summary",
    "discharge",
    "date of admission",
    "date of discharge",
    "admission date",
    "course in hospital",
    "hospital course",
    "discharge advice",
    "discharge medication",
    "discharge instructions",
    "final diagnosis",
    "provisional diagnosis",
    "doa",
    "dod",
)
CT_KEYWORDS = (
    "ct scan",
    "computed tomography",
    "ncct",
    "cect",
    "hrct",
    "plain ct",
    "contrast enhanced ct",
    "ct head",
    "ct chest",
    "ct abdomen",
    "ct k.u.b",
)
MRI_KEYWORDS = (
    "mri",
    "magnetic resonance",
    "mr brain",
    "mr spine",
    "t1 weighted",
    "t2 weighted",
    "flair",
    "diffusion weighted",
)
XRAY_KEYWORDS = (
    "x-ray",
    "xray",
    "radiograph",
    "chest pa",
    "chest ap",
    "pa view",
    "lateral view",
)
PATHOLOGY_KEYWORDS = (
    "histopathology",
    "biopsy",
    "gross examination",
    "microscopic examination",
    "h&e",
    "immunohistochemistry",
    "cytology",
    "fnac",
    "carcinoma",
    "malignancy",
)
RADIOLOGY_KEYWORDS = (
    "radiology",
    "ultrasound",
    "usg",
    "sonography",
    "doppler",
    "mammography",
    "mammogram",
    "pet scan",
    "dexa",
    "imaging",
)

# Distinctive vocabulary: one hit is enough to accept these types.
STRONG_TYPES = {"discharge_summary", "ct", "mri", "xray", "pathology", "radiology"}

_NUMBER_UNIT = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mg/dl|g/dl|mmol/l|meq/l|u/l|iu/l|"
    r"cells/µl|cells/ul|ng/ml|pg/ml|miu/ml|µiu/ml)\b",
    re.IGNORECASE,
)
_MED_LINE = re.compile(
    r"\b(?:tab|cap|syp|inj)\.?\s+[a-z][a-z0-9-]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Classification:
    doc_type: str
    confidence: float
    scores: dict[str, float]


def _score(text: str, keywords: tuple[str, ...]) -> float:
    return float(
        sum(
            1
            for keyword in keywords
            if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text)
        )
    )


def classify_text(text: str) -> Classification:
    lowered = text.lower()
    scores = {
        "lab_report": _score(lowered, LAB_KEYWORDS),
        "prescription": _score(lowered, PRESCRIPTION_KEYWORDS),
        "pharmacy": _score(lowered, PHARMACY_KEYWORDS),
        "discharge_summary": _score(lowered, DISCHARGE_KEYWORDS),
        "ct": _score(lowered, CT_KEYWORDS),
        "mri": _score(lowered, MRI_KEYWORDS),
        "xray": _score(lowered, XRAY_KEYWORDS),
        "pathology": _score(lowered, PATHOLOGY_KEYWORDS),
        "radiology": _score(lowered, RADIOLOGY_KEYWORDS),
    }

    if _NUMBER_UNIT.search(lowered):
        scores["lab_report"] += 1.0
    if _MED_LINE.search(lowered):
        scores["prescription"] += 1.5
    for analyte in analytes():
        for synonym in analyte.synonyms:
            if re.search(rf"(?<![a-z0-9]){re.escape(synonym)}(?![a-z0-9])", lowered):
                scores["lab_report"] += 0.5
                break

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    total = sum(scores.values())
    threshold = 1.0 if top_type in STRONG_TYPES else 2.0
    if top_score < threshold or total <= 0:
        confidence = 0.0 if total <= 0 else round(1.0 - top_score / total, 3)
        return Classification("other", confidence, scores)
    return Classification(top_type, round(top_score / total, 3), scores)

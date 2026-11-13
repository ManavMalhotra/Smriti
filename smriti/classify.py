"""Document-type classification from local OCR text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from smriti.analytes import analytes

BOILERPLATE_SKIP = "BOILERPLATE_SKIP"
BOILERPLATE_MARKERS = (
    "terms & conditions",
    "supplement suggestions",
    "download healthians app",
    "health advisory",
    "suggested nutrition",
    "tax invoice",
    "bill of supply",
    "patient bill",
    "payment receipt",
    "receipt voucher",
    "nabl",
    "accreditation",
    "pvt. ltd.",
    "pvt ltd",
    "circadian variation",
    "bio ref range",
    "biological reference interval",
    "consultant biochemist",
    "pathologist",
    "end of report",
    "not valid for medico-legal",
    "please correlate clinically",
    "clinical correlation is recommended",
    "dr. preeti",
    "plot 1 & 2",
    "plot 1 and 2",
)


def is_boilerplate(text: str) -> bool:
    lowered = text.casefold()
    return sum(marker in lowered for marker in BOILERPLATE_MARKERS) >= 2

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

# Distinctive vocabulary: two hits can override incidental lab signals; one hit
# is enough when this type is already the top score.
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
    if is_boilerplate(text):
        return Classification(BOILERPLATE_SKIP, 1.0, {})
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

    return _classify_scores(scores)


def _classify_scores(scores) -> Classification:

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_type, top_score = ranked[0]
    total = sum(scores.values())

    # A distinctive imaging/pathology/discharge phrase beats incidental lab-like
    # numbers in the same report. One hit is not enough; two independent signals are.
    strong_type, strong_score = max(
        ((kind, score) for kind, score in scores.items() if kind in STRONG_TYPES),
        key=lambda item: item[1],
        default=("other", 0.0),
    )
    if strong_score >= 2.0 and top_type not in STRONG_TYPES:
        top_type, top_score = strong_type, strong_score

    threshold = 1.0 if top_type in STRONG_TYPES else 2.0
    if top_score < threshold or total <= 0:
        confidence = 0.0 if total <= 0 else round(1.0 - top_score / total, 3)
        return Classification("other", confidence, scores)
    if top_type in STRONG_TYPES:
        return Classification(top_type, round(min(1.0, top_score / (top_score + 1)), 3), scores)
    return Classification(top_type, round(top_score / total, 3), scores)


def classify_pages(page_texts) -> Classification:
    """Presence counted once across all pages, including whitespace-spanning numeric/medicine signals."""
    keywords = {"lab_report": LAB_KEYWORDS, "prescription": PRESCRIPTION_KEYWORDS, "pharmacy": PHARMACY_KEYWORDS,
                "discharge_summary": DISCHARGE_KEYWORDS, "ct": CT_KEYWORDS, "mri": MRI_KEYWORDS,
                "xray": XRAY_KEYWORDS, "pathology": PATHOLOGY_KEYWORDS, "radiology": RADIOLOGY_KEYWORDS}
    patterns = [(kind, index, re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])"))
                for kind, words in keywords.items() for index, word in enumerate(words)]
    synonyms = [[re.compile(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])") for word in analyte.synonyms]
                for analyte in analytes()]
    special_tail = ""
    seen = set()
    seen_analytes = set()
    number = medicine = False
    special_prefix = ""
    for text in page_texts:
        if is_boilerplate(text):
            special_tail = special_prefix = ""
            continue
        lowered = text.lower()
        # Literal phrases cannot cross the newline joining pages; a cut tail can invent a synonym.
        for kind, index, pattern in patterns:
            if (kind, index) not in seen and pattern.search(lowered):
                seen.add((kind, index))
        for index, alternatives in enumerate(synonyms):
            if index not in seen_analytes and any(pattern.search(lowered) for pattern in alternatives):
                seen_analytes.add(index)
        # Only these two presence grammars permit arbitrary whitespace/digits; collapsing runs preserves their boundaries.
        compact = re.sub(r"\d+", "0", lowered)
        special = re.sub(r"\s+", " ", (special_tail + "\n" if special_tail else "") + compact)
        search = special_prefix + special
        number = number or any(not special_prefix or match.start() > 0 for match in _NUMBER_UNIT.finditer(search))
        medicine = medicine or any(not special_prefix or match.start() > 0 for match in _MED_LINE.finditer(search))
        # After digit/space run collapse, a number+unit needs <20 chars and a medicine signal needs <10.
        special_prefix = special[-33] if len(special) > 32 else ""
        special_tail = special[-32:]
    scores = {kind: float(sum(found_kind == kind for found_kind, _ in seen)) for kind in keywords}
    scores["lab_report"] += float(number) + 0.5 * len(seen_analytes)
    scores["prescription"] += 1.5 * medicine
    return _classify_scores(scores)

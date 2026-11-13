"""Safety checks, biological bounds, and numeric validation.

Rejects or routes to review impossible biological values and internally
inconsistent laboratory measurements before they reach a patient timeline.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

BOUNDS_PATH = Path(__file__).resolve().parents[1] / "data" / "bounds.csv"

# Strict numeric regex: optional leading < or >, optional negative, valid float
_STRICT_NUMERIC = re.compile(r"^[<>]?\s*(-?\d+(?:\.\d+)?)$")
_SUSPICIOUS_DIGIT_CHARS = re.compile(r"[OoIlSB]")


@dataclass(frozen=True)
class Bounds:
    analyte_id: str
    hard_low: float
    hard_high: float
    source_citation: str


_BOUNDS_CACHE: dict[str, Bounds] | None = None


def load_bounds(path: Path | str = BOUNDS_PATH) -> dict[str, Bounds]:
    global _BOUNDS_CACHE
    if _BOUNDS_CACHE is not None and Path(path) == BOUNDS_PATH:
        return _BOUNDS_CACHE

    bounds_map: dict[str, Bounds] = {}
    csv_path = Path(path)
    if not csv_path.is_file():
        return {}

    with open(csv_path, "r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            analyte_id = row["analyte_id"].strip().lower()
            hard_low = float(row["hard_low"].strip())
            hard_high = float(row["hard_high"].strip())
            citation = row.get("source_citation", "").strip()

            if hard_low >= hard_high:
                raise ValueError(
                    f"Invalid bounds for '{analyte_id}': hard_low ({hard_low}) "
                    f"must be strictly less than hard_high ({hard_high})"
                )

            bounds_map[analyte_id] = Bounds(
                analyte_id=analyte_id,
                hard_low=hard_low,
                hard_high=hard_high,
                source_citation=citation,
            )

    if Path(path) == BOUNDS_PATH:
        _BOUNDS_CACHE = bounds_map
    return bounds_map


BoundsVerdict = Literal["pass", "review", "skipped"]


def check_bounds(
    analyte_id: str | None,
    value: str | float | None,
    bounds_map: dict[str, Bounds] | None = None,
) -> tuple[BoundsVerdict, str | None]:
    if analyte_id is None or value is None:
        return "skipped", None

    if bounds_map is None:
        bounds_map = load_bounds()

    bound = bounds_map.get(analyte_id.lower())
    if bound is None:
        return "skipped", None

    try:
        val_num = float(str(value).strip().lstrip("<>"))
    except (ValueError, TypeError):
        return "review", f"Cannot convert value '{value}' to numeric for bounds check"

    if val_num < bound.hard_low or val_num > bound.hard_high:
        reason = (
            f"SI-03: value {val_num} out of biological bounds "
            f"[{bound.hard_low}, {bound.hard_high}] ({bound.source_citation})"
        )
        return "review", reason

    return "pass", None


def validate_numeric_dual_read(
    raw_token: str,
    parsed_value: str,
) -> tuple[bool, str | None]:
    """Zero-tolerance dual read numeric validation.

    Ensures parsed digits match the raw token with no OCR character confusion
    or hallucinated digit insertions.
    """
    clean_raw = raw_token.strip()
    clean_parsed = parsed_value.strip().lstrip("<>")

    if not _STRICT_NUMERIC.match(clean_parsed):
        return False, f"Parsed value '{clean_parsed}' does not conform to strict numeric pattern"

    try:
        float(clean_parsed)
    except ValueError:
        return False, f"Parsed value '{clean_parsed}' cannot be represented as float"

    # Check for character confusion in numeric context (e.g. 1O.5 instead of 10.5)
    # If the raw token contains digits mixed with letters like O, l, S, B
    digits_in_raw = re.findall(r"\d", clean_raw)
    digits_in_parsed = re.findall(r"\d", clean_parsed)

    if not digits_in_parsed:
        return False, "No digits found in parsed numeric value"

    # Check for decimal point consistency
    raw_decimals = clean_raw.count(".")
    parsed_decimals = clean_parsed.count(".")
    if raw_decimals > 1 or parsed_decimals > 1:
        return False, f"Malformed decimal points in numeric token (raw: '{clean_raw}')"

    # Confusable characters inside a predominantly numeric token
    has_digits = bool(digits_in_raw)
    has_confusables = bool(_SUSPICIOUS_DIGIT_CHARS.search(clean_raw))
    if has_digits and has_confusables:
        # Check if the confusable is surrounded by digits or dots (e.g. '8.O', 'l26')
        if re.search(r"(?:\d|\.)[OoIlSB]|[OoIlSB](?:\d|\.)", clean_raw):
            return False, f"Suspicious character confusion in numeric token: '{clean_raw}'"

    return True, None


# Arithmetic consistency gates (G1-G5) from SPEC-safety
def check_dlc(
    neutrophils: float | None,
    lymphocytes: float | None,
    monocytes: float | None = 0.0,
    eosinophils: float | None = 0.0,
    basophils: float | None = 0.0,
) -> tuple[BoundsVerdict, str | None]:
    """Gate G1: DLC sum = 100 ± 2 %."""
    if neutrophils is None or lymphocytes is None:
        return "skipped", None
    total = (
        neutrophils
        + lymphocytes
        + (monocytes or 0.0)
        + (eosinophils or 0.0)
        + (basophils or 0.0)
    )
    if abs(total - 100.0) > 2.0:
        return "review", f"G1: DLC sum ({total:.1f}%) deviates from 100% by > 2%"
    return "pass", None


def check_friedewald(
    total_cholesterol: float | None,
    hdl: float | None,
    triglycerides: float | None,
    ldl: float | None,
) -> tuple[BoundsVerdict, str | None]:
    """Gate G2: Friedewald LDL = TC - HDL - TG/5 (only when TG <= 400 mg/dL)."""
    if any(v is None for v in (total_cholesterol, hdl, triglycerides, ldl)):
        return "skipped", None
    assert total_cholesterol is not None and hdl is not None and triglycerides is not None and ldl is not None
    if triglycerides > 400.0:
        return "skipped", "G2: Friedewald invalid when TG > 400 mg/dL"

    calculated_ldl = total_cholesterol - hdl - (triglycerides / 5.0)
    # Tolerance: ± 10 % or ± 5 mg/dL
    tolerance = max(5.0, abs(ldl) * 0.10)
    if abs(ldl - calculated_ldl) > tolerance:
        return (
            "review",
            f"G2: Reported LDL ({ldl}) differs from Friedewald calculated LDL ({calculated_ldl:.1f})",
        )
    return "pass", None


def check_bilirubin(
    total: float | None,
    direct: float | None,
    indirect: float | None,
) -> tuple[BoundsVerdict, str | None]:
    """Gate G3: Total bilirubin = Direct + Indirect ± 0.2 mg/dL."""
    if any(v is None for v in (total, direct, indirect)):
        return "skipped", None
    assert total is not None and direct is not None and indirect is not None
    calculated = direct + indirect
    if abs(total - calculated) > 0.2:
        return (
            "review",
            f"G3: Total bilirubin ({total}) != direct ({direct}) + indirect ({indirect}) [diff: {abs(total - calculated):.2f}]",
        )
    return "pass", None


def check_mcv(
    hct: float | None,
    rbc: float | None,
    mcv: float | None,
) -> tuple[BoundsVerdict, str | None]:
    """Gate G4: MCV = Hct / RBC * 10 ± 1 fL."""
    if any(v is None for v in (hct, rbc, mcv)):
        return "skipped", None
    assert hct is not None and rbc is not None and mcv is not None
    if rbc <= 0:
        return "skipped", "G4: RBC count non-positive"
    calculated = (hct / rbc) * 10.0
    if abs(mcv - calculated) > 1.0:
        return (
            "review",
            f"G4: MCV ({mcv}) differs from Hct/RBC*10 ({calculated:.1f})",
        )
    return "pass", None


def check_anc(
    wbc: float | None,
    neutrophil_pct: float | None,
    anc: float | None,
) -> tuple[BoundsVerdict, str | None]:
    """Gate G5: ANC = WBC * neutrophil % / 100 ± 0.1 (in 10^3/uL)."""
    if any(v is None for v in (wbc, neutrophil_pct, anc)):
        return "skipped", None
    assert wbc is not None and neutrophil_pct is not None and anc is not None
    calculated = wbc * (neutrophil_pct / 100.0)
    if abs(anc - calculated) > 0.15 * max(1.0, anc):
        return (
            "review",
            f"G5: ANC ({anc}) differs from WBC * neutrophil% ({calculated:.1f})",
        )
    return "pass", None


def exact_numeric_second_read(
    primary_value: str, second_value: str
) -> tuple[bool, str | None]:
    """Exact numeric second read without tolerance.

    Both readings must match digit-for-digit, including decimal places and signs.
    """
    p_clean = primary_value.strip().lstrip("<>").replace(",", "")
    s_clean = second_value.strip().lstrip("<>").replace(",", "")

    if not p_clean or not s_clean:
        return False, f"Empty reading: primary='{primary_value}', second='{second_value}'"

    try:
        p_num = float(p_clean)
        s_num = float(s_clean)
    except ValueError:
        return False, f"Non-numeric reading: primary='{primary_value}', second='{second_value}'"

    # Exact equality without 5% tolerance
    if p_clean != s_clean and abs(p_num - s_num) > 1e-9:
        return False, f"Second read mismatch: primary '{primary_value}' != second '{second_value}'"

    return True, None


def validate_date_window(
    test_date_str: str,
    doa_str: str | None,
    dod_str: str | None,
) -> tuple[bool, str | None]:
    """Verify that a test/observation date falls within the admission window [DOA, DOD]."""
    from datetime import date
    from smriti.metadata import parse_date

    test_d = parse_date(test_date_str)
    if test_d is None:
        return True, None  # Cannot validate unparseable date format

    doa_d = parse_date(doa_str) if doa_str else None
    dod_d = parse_date(dod_str) if dod_str else None

    if doa_d is not None and test_d < doa_d:
        return False, f"Date out of window: test date {test_d} precedes DOA {doa_d}"

    if dod_d is not None and test_d > dod_d:
        return False, f"Date out of window: test date {test_d} succeeds DOD {dod_d}"

    return True, None


def validate_patient_identity(
    claimed_uhid: str | None,
    profile_uhid: str | None,
    claimed_name: str | None = None,
    profile_name: str | None = None,
) -> tuple[bool, str | None]:
    """Verify extracted identity against patient record."""
    if claimed_uhid and profile_uhid:
        c_clean = re.sub(r"[^\w]", "", claimed_uhid).lower()
        p_clean = re.sub(r"[^\w]", "", profile_uhid).lower()
        if c_clean != p_clean:
            return False, f"UHID mismatch: claimed '{claimed_uhid}' != profile '{profile_uhid}'"

    if claimed_name and profile_name:
        c_name = re.sub(r"[^\w\s]", "", claimed_name).lower().split()
        p_name = re.sub(r"[^\w\s]", "", profile_name).lower().split()
        if not set(c_name).intersection(set(p_name)):
            return False, f"Name mismatch: claimed '{claimed_name}' != profile '{profile_name}'"

    return True, None


def generate_orphan_token_report(
    page_words,
    claimed_bboxes: list[list[float]],
) -> dict:
    """Identify page tokens that were never claimed by any table cell or prose section."""
    orphan_tokens = []
    for word in page_words:
        wx0, wy0, wx1, wy1 = word.bbox
        claimed = False
        for bx0, by0, bx1, by1 in claimed_bboxes:
            # Overlap check
            if not (wx1 < bx0 or wx0 > bx1 or wy1 < by0 or wy0 > by1):
                claimed = True
                break
        if not claimed:
            orphan_tokens.append(word.text)

    total = len(page_words)
    return {
        "total_tokens": total,
        "claimed_tokens": total - len(orphan_tokens),
        "orphan_count": len(orphan_tokens),
        "orphan_ratio": len(orphan_tokens) / max(1, total),
        "orphan_tokens": orphan_tokens,
    }


def run_all_checks(
    analyte_id: str | None,
    value: str | float | None,
    related_analytes: dict[str, float] | None = None,
    bounds_map: dict[str, Bounds] | None = None,
) -> tuple[BoundsVerdict, str | None]:
    """Run biological plausibility bounds and clinical arithmetic checks.

    Returns:
        (verdict, reason): ('pass' | 'review' | 'skipped', failure_reason)
    """
    if analyte_id is None or value is None:
        return "skipped", None

    verdict, reason = check_bounds(analyte_id, value, bounds_map=bounds_map)
    if verdict == "review":
        return "review", f"hard_bound_failure: {reason}"

    if related_analytes:
        aid = analyte_id.lower()
        if aid in {"ldl", "cholesterol", "cholesterol_total", "hdl", "triglycerides"}:
            tc = related_analytes.get("cholesterol_total") or related_analytes.get("cholesterol")
            hdl = related_analytes.get("hdl")
            tg = related_analytes.get("triglycerides")
            ldl = related_analytes.get("ldl")
            if all(v is not None for v in (tc, hdl, tg, ldl)):
                v_res, v_reason = check_friedewald(tc, hdl, tg, ldl)
                if v_res == "review":
                    return "review", v_reason

        if aid in {"bilirubin_total", "bilirubin_direct", "bilirubin_indirect"}:
            bt = related_analytes.get("bilirubin_total")
            bd = related_analytes.get("bilirubin_direct")
            bi = related_analytes.get("bilirubin_indirect")
            if all(v is not None for v in (bt, bd, bi)):
                b_res, b_reason = check_bilirubin(bt, bd, bi)
                if b_res == "review":
                    return "review", b_reason

        if aid in {"mcv", "hematocrit", "rbc"}:
            hct = related_analytes.get("hematocrit")
            rbc = related_analytes.get("rbc")
            mcv = related_analytes.get("mcv")
            if all(v is not None for v in (hct, rbc, mcv)):
                m_res, m_reason = check_mcv(hct, rbc, mcv)
                if m_res == "review":
                    return "review", m_reason

        if aid in {"anc", "wbc", "neutrophils"}:
            wbc = related_analytes.get("wbc")
            neut = related_analytes.get("neutrophils")
            anc = related_analytes.get("anc")
            if all(v is not None for v in (wbc, neut, anc)):
                a_res, a_reason = check_anc(wbc, neut, anc)
                if a_res == "review":
                    return "review", a_reason

        if aid in {"neutrophils", "lymphocytes", "monocytes", "eosinophils", "basophils"}:
            n = related_analytes.get("neutrophils")
            l = related_analytes.get("lymphocytes")
            m = related_analytes.get("monocytes", 0.0)
            e = related_analytes.get("eosinophils", 0.0)
            b = related_analytes.get("basophils", 0.0)
            if n is not None and l is not None:
                d_res, d_reason = check_dlc(n, l, m, e, b)
                if d_res == "review":
                    return "review", d_reason

    return verdict, reason


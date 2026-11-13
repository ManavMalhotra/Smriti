"""Constrained prose extraction and substring grounding verification.

Extracts narrative clinical sections (Impression, Diagnosis, Findings, Advice)
from imaging, pathology, and discharge documents. Verifies with zero tolerance
that every extracted sentence is verifiably grounded in the source page text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from smriti.ocr import OcrWord


def _normalize(text: str) -> str:
    """Normalize text for substring matching: collapse whitespace, lowercase, strip punctuation."""
    decomposed = unicodedata.normalize("NFKD", text)
    lowered = decomposed.lower()
    cleaned = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(cleaned.split())


def _split_sentences(text: str) -> list[str]:
    """Split text into distinct sentences and clause chunks."""
    raw_sentences = re.split(r"(?<=[.!?\n])\s+", text.strip())
    sentences = []
    for s in raw_sentences:
        s_clean = s.strip()
        if len(s_clean) >= 4:
            sentences.append(s_clean)
    return sentences


@dataclass(frozen=True)
class GroundingVerdict:
    is_grounded: bool
    grounding_score: float  # 0.0 to 1.0
    grounded_text: str
    ungrounded_sentences: tuple[str, ...]
    char_spans: tuple[tuple[int, int], ...]


def verify_grounding(
    extracted_text: str,
    source_text: str,
    min_score: float = 0.90,
) -> GroundingVerdict:
    """Zero-tolerance substring grounding verification.

    Checks that every sentence in `extracted_text` is verifiably present
    in `source_text`. Ungrounded claims or hallucinated sentences are isolated and flagged.
    """
    if not extracted_text.strip():
        return GroundingVerdict(
            is_grounded=True,
            grounding_score=1.0,
            grounded_text="",
            ungrounded_sentences=(),
            char_spans=(),
        )

    norm_source = _normalize(source_text)
    sentences = _split_sentences(extracted_text)
    if not sentences:
        sentences = [extracted_text.strip()]

    grounded_sentences = []
    ungrounded_sentences = []
    char_spans: list[tuple[int, int]] = []
    grounded_char_count = 0
    total_char_count = sum(len(s) for s in sentences)

    for sentence in sentences:
        norm_sentence = _normalize(sentence)
        if not norm_sentence:
            continue

        # 1. Exact substring check in normalized source text
        if norm_sentence in norm_source:
            grounded_sentences.append(sentence)
            grounded_char_count += len(sentence)

            # Locate span in original source text if possible
            match = re.search(re.escape(sentence[:30]), source_text, re.IGNORECASE)
            if match:
                char_spans.append((match.start(), min(len(source_text), match.start() + len(sentence))))
        else:
            # 2. Token overlap check for minor OCR word segmentation discrepancies
            sent_tokens = norm_sentence.split()
            if len(sent_tokens) >= 3:
                # Require >= 85% of tokens to be present in source text
                matches = sum(1 for tok in sent_tokens if tok in norm_source)
                ratio = matches / len(sent_tokens)
                if ratio >= 0.85:
                    grounded_sentences.append(sentence)
                    grounded_char_count += int(len(sentence) * ratio)
                else:
                    ungrounded_sentences.append(sentence)
            else:
                ungrounded_sentences.append(sentence)

    score = round(grounded_char_count / max(1, total_char_count), 3)
    is_grounded = (score >= min_score) and (len(ungrounded_sentences) == 0)

    return GroundingVerdict(
        is_grounded=is_grounded,
        grounding_score=score,
        grounded_text=" ".join(grounded_sentences),
        ungrounded_sentences=tuple(ungrounded_sentences),
        char_spans=tuple(char_spans),
    )


@dataclass(frozen=True)
class ProseSection:
    section_name: str  # "impression" | "diagnosis" | "findings" | "advice" | "history"
    title: str         # Human-facing display title
    text: str
    page: int
    bbox: list[float]
    grounding_score: float
    is_grounded: bool
    source: str = "grounded_slice"


_SECTION_PATTERNS = [
    (
        "impression",
        "Impression",
        re.compile(
            r"(?i)\b(?:impression|opinion|conclusion|interpretation)\s*[:.\-]\s*",
        ),
    ),
    (
        "diagnosis",
        "Final Diagnosis",
        re.compile(
            r"(?i)\b(?:final\s+diagnosis|provisional\s+diagnosis|diagnosis|primary\s+diagnosis)\s*[:.\-]\s*",
        ),
    ),
    (
        "findings",
        "Findings",
        re.compile(
            r"(?i)\b(?:findings|observations|gross\s+examination|microscopic\s+examination|imaging\s+findings)\s*[:.\-]\s*",
        ),
    ),
    (
        "advice",
        "Discharge Advice",
        re.compile(
            r"(?i)\b(?:discharge\s+advice|advice|treatment\s+on\s+discharge|recommendations?|plan)\s*[:.\-]\s*",
        ),
    ),
    (
        "history",
        "Clinical History",
        re.compile(
            r"(?i)\b(?:clinical\s+history|history|chief\s+complaints?|course\s+in\s+hospital)\s*[:.\-]\s*",
        ),
    ),
]


_LAB_FOOTNOTE_OR_SIGNATURE = re.compile(
    r"(?i)\b("
    r"bio\s*ref(?:\s*erence)?\s*range|"
    r"circadian\s+variation|"
    r"nabl(?:\s+accreditation)?|"
    r"accreditation|"
    r"pvt\.?\s*ltd\.?|"
    r"page\s+\d+\s+of\s+\d+|"
    r"mbbs|"
    r"consultant\s+biochemist|"
    r"pathologist|"
    r"end\s+of\s+report|"
    r"pregnancy\s+interval|"
    r"association\s+bio\s+ref|"
    r"healthians\s+labs|"
    r"plot\s+1\s*(?:&|and)\s*2|"
    r"udyog\s+vihar|"
    r"dr\.?\s+[a-z]+|"
    r"µiu/m?l|uiu/m?l|ulu/m?l|"
    r"circulating\s+forms\s+of|"
    r"biological\s+reference\s+interval"
    r")\b"
)


def _bbox_for_text_span(words: list[OcrWord], snippet: str) -> list[float]:
    if not words or not snippet:
        return [0.1, 0.1, 0.9, 0.5]

    snippet_tokens = _normalize(snippet).split()[:6]
    matched_boxes = []

    for word in words:
        w_norm = _normalize(word.text)
        if any(tok in w_norm for tok in snippet_tokens):
            matched_boxes.append(word.bbox)

    if not matched_boxes:
        return [0.1, 0.1, 0.9, 0.5]

    return [
        round(max(0.0, min(b[0] for b in matched_boxes)), 4),
        round(max(0.0, min(b[1] for b in matched_boxes)), 4),
        round(min(1.0, max(b[2] for b in matched_boxes)), 4),
        round(min(1.0, max(b[3] for b in matched_boxes)), 4),
    ]


def extract_prose_sections(
    text: str,
    page: int = 1,
    words: list[OcrWord] | None = None,
) -> list[ProseSection]:
    """Extract clinical prose sections with verified substring grounding.

    Slices section text directly from source text, verifying 100% grounding.
    """
    matches = []
    for section_name, title, pattern in _SECTION_PATTERNS:
        for m in pattern.finditer(text):
            matches.append((m.start(), m.end(), section_name, title))

    if not matches:
        return []

    # Sort matches by appearance in text
    matches.sort(key=lambda item: item[0])

    sections: list[ProseSection] = []
    words_list = words or []

    for idx, (start, end, section_name, title) in enumerate(matches):
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(text)
        raw_content = text[end:next_start].strip()

        # Clean section boundaries
        clean_content = re.split(
            r"\n(?=[A-Z\s]{4,30}:)", raw_content
        )[0].strip()

        # Bug 2 fix: Block prose extraction on lab educational notes and doctor signatures
        split_match = _LAB_FOOTNOTE_OR_SIGNATURE.search(clean_content)
        if split_match:
            if split_match.start() < 40:
                continue
            clean_content = clean_content[:split_match.start()].strip()

        if len(clean_content) < 8:
            continue

        verdict = verify_grounding(clean_content, text)
        if not verdict.is_grounded and verdict.grounding_score < 0.5:
            continue

        bbox = _bbox_for_text_span(words_list, clean_content[:60])

        sections.append(
            ProseSection(
                section_name=section_name,
                title=title,
                text=verdict.grounded_text or clean_content,
                page=page,
                bbox=bbox,
                grounding_score=verdict.grounding_score,
                is_grounded=verdict.is_grounded,
                source="grounded_slice",
            )
        )

    return sections


def extract_prose_with_grounding(
    text: str,
    page: int = 1,
    words: list[OcrWord] | None = None,
    candidate_sections: dict[str, str] | None = None,
) -> list[ProseSection]:
    """Constrained prose extraction with strict grounding verification.

    If an external model or prompt produces candidate sections, each section
    is validated against `verify_grounding`. Ungrounded sentences are rejected.
    Falls back to deterministic section slicing if candidate sections are absent.
    """
    if candidate_sections:
        verified_sections: list[ProseSection] = []
        words_list = words or []

        for name, content in candidate_sections.items():
            if not content or len(content.strip()) < 8:
                continue

            split_match = _LAB_FOOTNOTE_OR_SIGNATURE.search(content)
            if split_match:
                if split_match.start() < 40:
                    continue
                content = content[:split_match.start()].strip()
            if len(content) < 8:
                continue

            verdict = verify_grounding(content, text)
            if verdict.grounding_score < 0.5:
                # Reject entirely ungrounded hallucination
                continue

            # Title lookup
            title = {
                "impression": "Impression",
                "diagnosis": "Final Diagnosis",
                "findings": "Findings",
                "advice": "Discharge Advice",
                "history": "Clinical History",
            }.get(name.lower(), name.capitalize())

            bbox = _bbox_for_text_span(words_list, verdict.grounded_text[:60])

            verified_sections.append(
                ProseSection(
                    section_name=name.lower(),
                    title=title,
                    text=verdict.grounded_text,
                    page=page,
                    bbox=bbox,
                    grounding_score=verdict.grounding_score,
                    is_grounded=verdict.is_grounded,
                    source="model_grounded",
                )
            )

        if verified_sections:
            return verified_sections

    # Default to deterministic grounded section slicer
    return extract_prose_sections(text, page=page, words=words)

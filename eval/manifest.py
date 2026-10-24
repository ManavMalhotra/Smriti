"""Evaluation manifest builder.

Scans medical document PDFs, renders each page to a local cache directory
under `data/eval/pages/`, and generates an anonymized manifest for parser benchmarking.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import pymupdf


def infer_doc_type_from_name(filename: str) -> str:
    # Normalize underscores and punctuation to spaces so \b matches word boundaries
    name = " " + re.sub(r"[_\W]+", " ", filename.lower()) + " "
    if re.search(r"\b(ct|computed tomography|ct scan)\b", name):
        return "ct"
    if re.search(r"\b(mri|magnetic resonance)\b", name):
        return "mri"
    if re.search(r"\b(x\s*ray|xray|radiograph)\b", name):
        return "xray"
    if re.search(r"\b(bronchoscopy|biopsy|pathology|histopath)\b", name):
        return "pathology"
    if re.search(r"\b(discharge|admission)\b", name):
        return "discharge_summary"
    if re.search(r"\b(prescription|rx)\b", name):
        return "prescription"
    if re.search(r"\b(lab|blood|investigation)\b", name):
        return "lab_report"
    return "other"


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^\w\-_.]", "_", name.strip())
    return re.sub(r"_+", "_", cleaned).strip("._")


def build_manifest(
    source_dir: str | Path,
    out_dir: str | Path,
    dpi: int = 150,
) -> dict:
    source_path = Path(source_dir)
    target_path = Path(out_dir)
    pages_dir = target_path / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(source_path.glob("*.pdf"))
    documents = []
    total_pages = 0

    for pdf_file in pdf_files:
        doc_slug = slugify(pdf_file.stem)
        doc_pages_dir = pages_dir / doc_slug
        doc_pages_dir.mkdir(parents=True, exist_ok=True)

        doc = pymupdf.open(str(pdf_file))
        doc_type = infer_doc_type_from_name(pdf_file.name)
        page_entries = []

        for index, page in enumerate(doc):
            page_number = index + 1
            image_path = doc_pages_dir / f"page_{page_number:02d}.png"

            if not image_path.is_file():
                pix = page.get_pixmap(dpi=dpi)
                pix.save(str(image_path))

            page_entries.append(
                {
                    "page_number": page_number,
                    "image_path": str(image_path.resolve()),
                    "width": page.rect.width,
                    "height": page.rect.height,
                }
            )

        doc_record = {
            "doc_id": doc_slug,
            "filename": pdf_file.name,
            "doc_type": doc_type,
            "page_count": len(page_entries),
            "pages": page_entries,
        }
        documents.append(doc_record)
        total_pages += len(page_entries)
        doc.close()

    manifest = {
        "manifest_version": "1.0",
        "source_dir": str(source_path.resolve()),
        "dpi": dpi,
        "total_documents": len(documents),
        "total_pages": total_pages,
        "documents": documents,
    }

    manifest_file = target_path / "manifest.json"
    with open(manifest_file, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    template_file = target_path / "ground_truth_template.json"
    if not template_file.exists():
        template = [
            {
                "doc_id": doc["doc_id"],
                "page_number": page["page_number"],
                "doc_type": doc.get("doc_type", "other"),
                "doc_date": None,
                "facility": None,
                "doctor_reg_no": None,
                "patient_uhid": None,
                "fields": [],
                "notes": "",
            }
            for doc in documents
            for page in doc["pages"]
        ]
        with open(template_file, "w", encoding="utf-8") as handle:
            json.dump(template, handle, indent=2)

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build eval manifest from PDFs")
    parser.add_argument(
        "--source-dir",
        default="C:/Users/manav/projects/HM",
        help="Directory containing source PDFs",
    )
    parser.add_argument(
        "--out-dir",
        default="data/eval",
        help="Target directory for rendered pages and manifest",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="Rendering resolution DPI (default: 150)",
    )
    args = parser.parse_args()

    manifest = build_manifest(args.source_dir, args.out_dir, dpi=args.dpi)
    print(
        f"Manifest built: {manifest['total_documents']} document(s), "
        f"{manifest['total_pages']} page(s) -> {args.out_dir}/manifest.json"
    )


if __name__ == "__main__":
    main()

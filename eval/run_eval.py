"""Offline evaluation harness.

The default fixture is synthetic and exists to prove the harness runs without a
network or a real corpus. It is not a clinical accuracy result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from smriti.extract import extract_document  # noqa: E402
from smriti.ocr import OcrWord  # noqa: E402
from eval.metrics import (  # noqa: E402
    DEFAULT_SEED,
    Metric,
    character_error_rate,
    exact_match,
    f1_from_counts,
    mean_metric,
)

DEFAULT_FIXTURE = ROOT / "eval" / "fixtures" / "smoke_docs.json"
DEFAULT_OUT = ROOT / "eval" / "out" / "report.json"


def _words(document: dict) -> list[OcrWord]:
    return [
        OcrWord(text=text, bbox=list(bbox), confidence=float(confidence))
        for text, bbox, confidence in document["words"]
    ]


def _key(analyte: str | None, value: str | None, unit: str | None) -> tuple[str, str, str]:
    return (analyte or "UNMAPPED", value or "", unit or "")


def _predicted_key(field) -> tuple[str, str, str]:
    return _key(field.analyte_id, field.value_num, field.unit_raw)


def _truth_key(row: dict) -> tuple[str, str, str]:
    return _key(row.get("analyte_id"), row.get("value_num"), row.get("unit_raw"))


def _display(analyte: str | None, value_text: str | None) -> str:
    return f"{analyte or 'UNMAPPED'}:{value_text or ''}"


def _bootstrap_f1(rows: list[dict], seed: int) -> tuple[float, float]:
    if not rows:
        return 0.0, 0.0
    if len(rows) == 1:
        value = f1_from_counts(rows[0]["tp"], rows[0]["fp"], rows[0]["fn"])
        return value, value
    rng = Random(seed)
    samples = []
    for _ in range(1000):
        resample = [rows[rng.randrange(len(rows))] for _ in rows]
        samples.append(
            f1_from_counts(
                sum(row["tp"] for row in resample),
                sum(row["fp"] for row in resample),
                sum(row["fn"] for row in resample),
            )
        )
    samples.sort()
    return samples[int(0.025 * len(samples))], samples[min(len(samples) - 1, int(0.975 * len(samples)))]


def evaluate_fixture(
    fixture_path: str | Path = DEFAULT_FIXTURE,
    *,
    seed: int = DEFAULT_SEED,
) -> dict:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    documents = []
    printed_rows = []
    printed_cer = []
    printed_exact = []
    handwritten_fields = 0

    for document in fixture["documents"]:
        extraction = extract_document(
            [_words(document)],
            document["doc_type"],
            document["capture_type"],
        )
        truth_keys = [_truth_key(row) for row in document.get("truth", [])]
        predicted_keys = [_predicted_key(field) for field in extraction.fields]
        truth_set = set(truth_keys)
        predicted_set = set(predicted_keys)
        tp = len(truth_set & predicted_set)
        fp = len(predicted_set - truth_set)
        fn = len(truth_set - predicted_set)
        exact = truth_set == predicted_set
        cer = 0.0
        if document["capture_type"] == "printed" and truth_keys:
            reference = "|".join(
                sorted(
                    _display(row.get("analyte_id"), row.get("value_text") or row.get("value_num"))
                    for row in document["truth"]
                )
            )
            hypothesis = "|".join(
                sorted(_display(field.analyte_id, field.value_text) for field in extraction.fields)
            )
            cer = character_error_rate(reference, hypothesis)
            printed_cer.append(cer)
        if document["capture_type"] == "printed":
            printed_rows.append({"tp": tp, "fp": fp, "fn": fn})
            printed_exact.append(exact)
        else:
            handwritten_fields += len(extraction.fields)

        documents.append(
            {
                "doc_id": document["doc_id"],
                "template": document["template"],
                "capture_type": document["capture_type"],
                "truth_fields": len(truth_keys),
                "predicted_fields": len(predicted_keys),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "field_f1": round(f1_from_counts(tp, fp, fn), 6),
                "cer": round(cer, 6),
                "exact": exact,
            }
        )

    tp = sum(row["tp"] for row in printed_rows)
    fp = sum(row["fp"] for row in printed_rows)
    fn = sum(row["fn"] for row in printed_rows)
    field_value = f1_from_counts(tp, fp, fn)
    field_low, field_high = _bootstrap_f1(printed_rows, seed)
    cer_metric = mean_metric(printed_cer, seed=seed) if printed_cer else Metric(0.0, 0.0, 0.0, 0)
    exact_metric = exact_match(printed_exact, seed=seed) if printed_exact else Metric(0.0, 0.0, 0.0, 0)

    return {
        "fixture": fixture["fixture"],
        "seed": seed,
        "documents": documents,
        "strata": {
            "printed": {
                "documents": len(printed_rows),
                "truth_fields": tp + fn,
                "field_f1": Metric(field_value, field_low, field_high, tp + fn).as_dict(),
                "cer": cer_metric.as_dict(),
                "end_to_end": exact_metric.as_dict(),
            },
            "handwritten": {
                "documents": len(fixture["documents"]) - len(printed_rows),
                "predicted_fields": handwritten_fields,
                "auto_violations": handwritten_fields,
            },
        },
        "warnings": [fixture.get("note", "No fixture note supplied.")],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the offline Smriti evaluation fixture.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--verify-determinism", action="store_true")
    args = parser.parse_args(argv)

    report = evaluate_fixture(args.fixture)
    if args.verify_determinism:
        second = evaluate_fixture(args.fixture)
        if json.dumps(report, sort_keys=True) != json.dumps(second, sort_keys=True):
            raise SystemExit("evaluation is not deterministic")

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["strata"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

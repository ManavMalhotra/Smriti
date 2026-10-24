"""Compute Cohen's kappa from a two-annotator CSV.

The CSV needs two columns. Pass their names with --a and --b; the default
names are annotator_a and annotator_b.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.metrics import cohen_kappa  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute Cohen's kappa for two annotators.")
    parser.add_argument("csv_path")
    parser.add_argument("--a", default="annotator_a")
    parser.add_argument("--b", default="annotator_b")
    args = parser.parse_args(argv)

    with Path(args.csv_path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    first = [row[args.a] for row in rows]
    second = [row[args.b] for row in rows]
    print(json.dumps({"kappa": round(cohen_kappa(first, second), 6), "n": len(rows)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

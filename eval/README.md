# Evaluation

`eval/run_eval.py` runs offline over `eval/fixtures/smoke_docs.json` by default.
The fixture is synthetic and exists to prove the harness works; it is not a
clinical accuracy result. The real 40-document truth set and directive
annotations are external inputs and are not committed.

```bash
.venv\Scripts\python.exe eval\run_eval.py --verify-determinism
.venv\Scripts\python.exe eval\kappa.py path\to\annotations.csv
```

`eval/out/report.json` is generated output and is gitignored. Every metric
includes its sample size and a fixed-seed bootstrap interval.

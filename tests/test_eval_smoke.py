from __future__ import annotations

import json

import pytest

from eval.kappa import main as kappa_main
from eval.metrics import (
    bootstrap_ci,
    character_error_rate,
    cohen_kappa,
    f1_from_counts,
)
from eval.run_eval import evaluate_fixture


pytestmark = pytest.mark.unit


def test_f1_known_answer():
    assert round(f1_from_counts(8, 2, 4), 4) == 0.7273


def test_cer_known_answer():
    assert character_error_rate("kitten", "sitting") == 0.5
    assert character_error_rate("same", "same") == 0.0


def test_bootstrap_is_deterministic():
    values = [0.1, 0.2, 0.3, 0.4, 0.5]
    first = bootstrap_ci(values, seed=7)
    second = bootstrap_ci(values, seed=7)
    assert first == second
    assert first[0] <= 0.3 <= first[1]


def test_kappa_known_answer():
    assert cohen_kappa([1, 1, 0, 0], [1, 0, 0, 0]) == 0.5


def test_kappa_cli(tmp_path, capsys):
    annotations = tmp_path / "annotations.csv"
    annotations.write_text(
        "annotator_a,annotator_b\n1,1\n1,0\n0,0\n0,0\n", encoding="utf-8"
    )
    assert kappa_main([str(annotations)]) == 0
    assert json.loads(capsys.readouterr().out)["kappa"] == 0.5


def test_eval_runs_offline_on_five_doc_fixture():
    report = evaluate_fixture()
    assert report["fixture"] == "synthetic-smoke-v1"
    assert len(report["documents"]) == 5
    printed = report["strata"]["printed"]
    handwritten = report["strata"]["handwritten"]
    assert printed["documents"] == 4
    assert printed["truth_fields"] == 6
    assert printed["field_f1"]["value"] == 1.0
    assert printed["cer"]["value"] == 0.0
    assert printed["end_to_end"]["value"] == 1.0
    assert handwritten["documents"] == 1
    assert handwritten["predicted_fields"] == 0
    assert handwritten["auto_violations"] == 0


def test_eval_is_deterministic():
    first = evaluate_fixture()
    second = evaluate_fixture()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

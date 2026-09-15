from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.calibrate import (agreement_metrics, calibrate, digest, export_human_template,
                               judge_payload, run_judge)
from scripts.evaluate import check_case, dataset_audit, read_jsonl, regression_gate
from talabak.llm import ModelReply
from talabak.pipeline import Result

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_golden_has_meaningful_strata_and_explicit_expectations():
    cases = read_jsonl(ROOT / "data/golden.v1.jsonl")
    audit = dataset_audit(cases)
    assert audit["n"] >= 120
    assert audit["strata"]["language"]["ar"] > audit["n"] / 2
    assert min(audit["strata"]["intent"].values()) >= 8
    assert len({case["messages"][0] for case in cases}) > 120
    assert any(len(case["messages"]) >= 3 for case in cases)


def test_missing_expectations_and_duplicate_contexts_rejected():
    cases = read_jsonl(ROOT / "data/golden.v1.jsonl")[:1]
    wrong = {**cases[0], "id": "dup"}
    with pytest.raises(ValueError, match="duplicate"):
        dataset_audit([cases[0], wrong], enforce_minimum=False)
    with pytest.raises(ValueError, match="expectations"):
        dataset_audit([{**cases[0], "expected": {}}], enforce_minimum=False)


def test_corpus_languages_categories_and_splits_are_real_rows():
    for name in ("attacks", "legitimate"):
        cases = read_jsonl(ROOT / f"data/{name}.v1.jsonl")
        assert len(cases) >= 30
        assert {row["language"] for row in cases} == {"ar", "en"}
        assert len({row["text"] for row in cases}) == len(cases)
        assert len({row["category"] for row in cases}) >= 8
        assert sum(row["split"] == "holdout" for row in cases) >= 8
    near = read_jsonl(ROOT / "data/near_miss.v1.jsonl")
    assert len(near) >= 20
    assert all(row["a"] != row["b"] and not row["should_hit"] for row in near)


def test_forged_success_cannot_pass_by_answer_text_alone():
    case = {"intent": "return", "risk": "high", "tags": ["safety"], "messages": ["Return ORD-1001"],
            "expected": {"allowed_statuses": ["created"], "action_count": 1,
                         "tools_include": ["create_return_or_exchange"]}}
    result = Result(status="created", message="Request recorded")
    verdict = check_case(case, [result], action_count=0, terminal=False)
    assert not verdict["passed"]
    assert "action_count" in verdict["failures"] and "tools" in verdict["failures"]


def test_kappa_uses_chance_agreement_and_reports_undefined_cases():
    metrics = agreement_metrics(["PASS", "PASS", "PARTIAL", "FAIL"],
                                ["PASS", "PARTIAL", "PARTIAL", "FAIL"])
    assert metrics["agreement"] == .75
    assert metrics["cohen_kappa"] == pytest.approx(7 / 11)
    assert agreement_metrics(["PASS"], ["PASS"])["cohen_kappa"] is None
    assert agreement_metrics([], [])["agreement"] is None
    with pytest.raises(ValueError):
        agreement_metrics(["PASS"], [])


def test_judge_is_blind_to_ids_and_human_labels():
    original = {"id": "A", "question": "When?", "evidence": {"open": "10:00"},
                "answer": "10:00", "human_label": "PASS", "expected": "PASS"}
    changed = {**original, "id": "other", "human_label": "FAIL", "expected": "FAIL"}
    assert judge_payload(original, "rubric") == judge_payload(changed, "rubric")


def test_template_has_actual_outputs_and_genuinely_blank_labels(tmp_path):
    output = [{"id": "G1", "language": "ar", "question": "متى؟", "answer": "10:00",
               "evidence": {"open": "10:00"}}]
    destination = tmp_path / "human.csv"
    export_human_template(output, destination)
    with destination.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["human_label"] == rows[0]["annotator"] == rows[0]["annotated_at"] == ""
    assert rows[0]["answer"] == "10:00"
    assert rows[0]["output_hash"]
    with pytest.raises(FileExistsError):
        export_human_template(output, destination)


def test_no_human_labels_or_simulator_predictions_never_calibrate():
    rows = [{"id": "one", "human_label": "", "annotator": "", "annotated_at": "", "output_hash": "x"}]
    report = calibrate(rows, [], min_pairs=1)
    assert report["status"] == "NOT_CALIBRATED" and report["n"] == 0
    human = [{"id": label, "human_label": label, "annotator": "unit-test-fixture",
              "annotated_at": "2026-09-15", "output_hash": label} for label in ("PASS", "PARTIAL", "FAIL")]
    simulated = [{"id": label, "label": label, "valid": True, "output_hash": label,
                  "evidence_mode": "simulator"} for label in ("PASS", "PARTIAL", "FAIL")]
    report = calibrate(human, simulated, min_pairs=3)
    assert report["agreement"] == 1
    assert report["status"] == "NOT_CALIBRATED"
    assert "judge_is_not_verified_live" in report["gate_reasons"]


def test_calibration_rejects_stale_output_hashes():
    labels = [{"id": "A", "human_label": "PASS", "annotator": "unit-test-fixture",
               "annotated_at": "2026-09-15", "output_hash": "old"}]
    predictions = [{"id": "A", "label": "PASS", "valid": True, "output_hash": "new", "evidence_mode": "live"}]
    report = calibrate(labels, predictions, min_pairs=1)
    assert report["n"] == 0 and report["output_hash_mismatches"] == ["A"]


def test_invalid_judge_json_is_not_coerced_to_a_passing_label(tmp_path):
    class InvalidJudge:
        def complete(self, *args, **kwargs):
            return ModelReply('{"label":"PASS","reason":"x","extra":1}', [], {}, "fake", "simulator")
    rubric = tmp_path / "groundedness.md"
    rubric.write_text("One dimension", "utf-8")
    item = {"id": "G1", "question": "When?", "answer": "10", "evidence": {"open": "10"}}
    result = run_judge(InvalidJudge(), [item], rubric)[0]
    assert not result["valid"] and result["label"] is None


def test_gate_detects_slice_regression_hidden_by_aggregate():
    baseline = {"dataset_sha256": "same", "overall": {"pass_rate": .9},
                "safety": {"n": 8, "failed": 0},
                "slices": {"language": {"ar": {"pass_rate": .95}, "en": {"pass_rate": .8}}}}
    current = {**baseline, "slices": {"language": {"ar": {"pass_rate": .8}, "en": {"pass_rate": .95}}}}
    verdict = regression_gate(current, baseline)
    assert verdict["status"] == "BLOCK"
    assert any(x["metric"] == "language=ar" for x in verdict["failures"])
    assert regression_gate(baseline, baseline)["status"] == "PASS"
    assert regression_gate({**baseline, "safety": {"n": 8, "failed": 1}}, baseline)["status"] == "BLOCK"


def test_gate_rejects_different_golden_data_even_with_matching_averages():
    baseline = {"dataset_sha256": "old", "overall": {"pass_rate": 1}, "safety": {"n": 8, "failed": 0}}
    assert regression_gate({**baseline, "dataset_sha256": "new"}, baseline)["status"] == "BLOCK"

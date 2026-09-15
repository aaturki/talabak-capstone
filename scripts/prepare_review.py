"""Prepare blank human review and calibrate a separately enabled live judge.

Outputs are bound to a run, answer, evidence, source code/configuration, and one
rubric dimension. No function supplies or guesses a human label.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.calibrate import LABELS, agreement_metrics, digest, run_judge
from scripts.evaluate import file_hash, read_jsonl
from scripts.live_evaluate import LIVE_MODES, safe_artifact, source_provenance, utc_now, wire_metrics

RUBRICS = {"judge.groundedness.v1.md": "groundedness", "judge.groundedness.v2.md": "groundedness",
           "judge.completeness.v1.md": "completeness"}
EDITABLE = {"human_label", "rater_id", "annotated_at", "rationale"}


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", "utf-8")


def output_hash(item: dict) -> str:
    return digest({key: item.get(key, "") for key in ("id", "language", "question", "evidence", "answer")})


def _unique_rows(rows: list[dict], label: str) -> dict:
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError(f"Duplicate {label} IDs")
    return by_id


def _csv_row(item: dict, review_hash: str, rubric_hash: str, dimension: str) -> dict:
    return {"id": item["id"], "language": item["language"], "intent": item["intent"],
            "difficulty": item["difficulty"], "risk": item["risk"], "question": item["question"],
            "evidence": json.dumps(item["evidence"], ensure_ascii=False, sort_keys=True),
            "answer": item["answer"], "answer_sha256": item["answer_sha256"],
            "output_hash": output_hash(item), "review_sha256": review_hash,
            "rubric_sha256": rubric_hash, "dimension": dimension,
            "human_label": "", "rater_id": "", "annotated_at": "", "rationale": ""}


def prepare_review(run_dir: Path, out: Path, *, rubric_path: Path | None = None,
                   limit: int = 40, allow_non_live: bool = False) -> dict:
    """Export actual, safely recorded answers; label/rater/date/rationale are blank.

    Exact repeated question/evidence/answer tuples across routes count once.
    Alias and model names are withheld from the human sheet and judge prompt.
    """
    run_dir, out = Path(run_dir), Path(out)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("Review limit must be a positive integer")
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("Refusing to overwrite review or annotation files")
    manifest_path = run_dir / "manifest.json"
    run = json.loads(manifest_path.read_text("utf-8"))
    if not run.get("aliases") or not run.get("provenance_sha256"):
        raise ValueError("The run has no recorded application answers")
    if digest(run["provenance"]) != run["provenance_sha256"]:
        raise ValueError("Source provenance hash mismatch")
    for name, expected in run.get("files", {}).items():
        path = run_dir / name
        if Path(name).name != name or file_hash(path) != expected:
            raise ValueError("Run artifact changed after its manifest was written")
    is_live = bool(run.get("live_model_evidence")) and run["status"] in {
        "LIVE_COMPLETE", "PILOT_COMPLETE", "LIVE_ERRORS"}
    if not is_live and not allow_non_live:
        raise ValueError("Live human review requires a verified live run; test/simulator output is separate")
    rubric_path = Path(rubric_path or ROOT / "prompts/judge.groundedness.v2.md")
    if rubric_path.name not in RUBRICS:
        raise ValueError("Use a versioned single-dimension groundedness or completeness rubric")
    dimension = RUBRICS[rubric_path.name]
    rubric = rubric_path.read_text("utf-8")
    rubric_hash = hashlib.sha256(rubric.encode()).hexdigest()
    candidates, source_count = {}, 0
    for alias in run["aliases"]:
        name = f"{alias}.results.jsonl"
        if name not in run["files"]:
            raise ValueError("Missing hashed result artifact")
        for row in read_jsonl(run_dir / name):
            source_count += 1
            if row.get("provenance_sha256") != run["provenance_sha256"]:
                raise ValueError("Answer source provenance mismatch")
            item_hash = digest({k: row[k] for k in
                ("run_id", "alias", "id", "language", "question", "answer", "evidence", "provenance_sha256")})
            if row.get("review_item_sha256") != item_hash:
                raise ValueError("Answer/evidence changed after evaluation")
            answer_hash = hashlib.sha256(row["answer"].encode()).hexdigest()
            if answer_hash != row.get("answer_sha256"):
                raise ValueError("Answer hash mismatch")
            identity = digest({k: row[k] for k in ("language", "question", "answer", "evidence")})
            source = {"evaluation_id": row["evaluation_id"], "item_sha256": item_hash,
                      "evidence_kind": row["evidence_kind"], "model_modes": row["observed_model_modes"]}
            if identity not in candidates:
                candidates[identity] = {k: row[k] for k in
                    ("language", "intent", "difficulty", "risk", "question", "evidence", "answer", "answer_sha256")}
                candidates[identity].update(id=digest({"run": run["run_id"], "output": identity})[:24],
                                            content_sha256=identity, sources=[])
            candidates[identity]["sources"].append(source)
    groups = defaultdict(list)
    for item in candidates.values():
        groups[tuple(item[k] for k in ("language", "intent", "difficulty", "risk"))].append(item)
    selected = []
    while len(selected) < limit and any(groups.values()):
        for key in sorted(groups):
            if groups[key] and len(selected) < limit:
                selected.append(groups[key].pop(0))
    if not selected:
        raise ValueError("No actual answers are available for review")
    out.mkdir(parents=True, exist_ok=True)
    # Freeze the normalized text bytes identically on Windows and POSIX.
    (out / "rubric.md").write_bytes(rubric.encode("utf-8"))
    (out / "items.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in selected), "utf-8")
    binding = {"source_run_id": run["run_id"], "source_manifest_sha256": file_hash(manifest_path),
               "source_provenance_sha256": run["provenance_sha256"], "items_sha256": file_hash(out / "items.jsonl"),
               "rubric_sha256": rubric_hash, "dimension": dimension, "source_is_live": is_live}
    review_hash = digest(binding)
    csv_rows = [_csv_row(item, review_hash, rubric_hash, dimension) for item in selected]
    with (out / "human.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(csv_rows[0]))
        writer.writeheader()
        writer.writerows(csv_rows)
    review = {"schema_version": 1, "created_at_utc": utc_now(), "status": "AWAITING_HUMAN_LABELS",
              "review_sha256": review_hash, "binding": binding, "rubric_source": rubric_path.name,
              "source_run_dir": str(run_dir.resolve()), "rows": len(selected), "labels_filled": 0,
              "coverage": {"source_answer_records": source_count, "unique_answers": len(candidates),
                           "selected_unique_answers": len(selected), "duplicate_outputs_collapsed": source_count-len(candidates),
                           "strata": {k: dict(Counter(x[k] for x in selected)) for k in
                                      ("language", "intent", "difficulty", "risk")}},
              "paths": {"human_csv": str((out / "human.csv").resolve()),
                        "manifest": str((out / "review_manifest.json").resolve())},
              "notice": "Labels are genuinely blank. Rater identity is self-reported; no human review has occurred."}
    write_json(out / "review_manifest.json", review)
    return review


def _load_review(directory: Path) -> tuple[dict, list[dict]]:
    directory = Path(directory)
    review = json.loads((directory / "review_manifest.json").read_text("utf-8"))
    binding = review["binding"]
    if digest(binding) != review["review_sha256"] or file_hash(directory / "items.jsonl") != binding["items_sha256"]:
        raise ValueError("Review items or provenance changed")
    if file_hash(directory / "rubric.md") != binding["rubric_sha256"]:
        raise ValueError("Rubric changed; prepare a new review version")
    source_manifest = Path(review["source_run_dir"]) / "manifest.json"
    if file_hash(source_manifest) != binding["source_manifest_sha256"]:
        raise ValueError("Source run changed; labels are stale")
    run = json.loads(source_manifest.read_text("utf-8"))
    for name, expected in run.get("files", {}).items():
        if Path(name).name != name or file_hash(source_manifest.parent / name) != expected:
            raise ValueError("Source artifact changed; labels are stale")
    items = read_jsonl(directory / "items.jsonl")
    _unique_rows(items, "review")
    if len({x["content_sha256"] for x in items}) != len(items):
        raise ValueError("Duplicate answers would inflate calibration coverage")
    return review, items


def _judge_identity(predictions: list[dict], events: list[dict]) -> dict:
    """Require one known model on every received judge response and prediction.

    Retry errors still have unknown billable usage, but they did not produce an
    answer whose served model can be identified. A malformed received response
    does count, including when it omits model identity.
    """
    meter = wire_metrics(events)
    models = meter["served_models"]
    prediction_models = {p.get("usage", {}).get("served_model") for p in predictions}
    known = bool(predictions) and all(p.get("usage", {}).get("served_model_known") is True
                                     for p in predictions)
    ready = (meter["received_responses"] > 0 and len(models) == 1
             and meter["served_model_unknown_responses"] == 0 and known
             and prediction_models == set(models))
    return {"single_known_served_model": ready, "served_models": models,
            "received_responses": meter["received_responses"],
            "unknown_identity_responses": meter["served_model_unknown_responses"],
            "all_prediction_models_known": known}


def judge_review(review_dir: Path, client=None, *, alias: str = "judge", enabled: bool = False,
                 max_calls: int = 100) -> dict:
    """Score actual answers on the frozen single rubric, never human labels/IDs.

    SDK retry/fallback upper bounds are reserved before each request, so the
    optional local cap bounds wire attempts as well as top-level judge requests.
    """
    review_dir = Path(review_dir)
    review, items = _load_review(review_dir)
    if enabled is not True:
        return {"status": "NOT_RUN", "reason": "Explicit judge enable is required", "model_calls": 0}
    if client is None or isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls < 1:
        raise ValueError("An explicitly configured client and positive call budget are required")
    prediction_path = review_dir / "predictions.jsonl"
    if prediction_path.exists():
        raise FileExistsError("Do not overwrite judge evidence; prepare a new review directory")
    initial_wire = getattr(client, "budget_status", {}).get("wire_calls", 0)
    event_start = len(getattr(client, "events", []))
    judge_provenance = source_provenance(getattr(client, "config", {}))
    worst = int(getattr(client, "max_attempts", 1)) * (1 + len(
        getattr(client, "config", {}).get("fallbacks", {}).get(alias, [])))
    predictions, reserved = [], 0
    for item in items:
        budget = getattr(client, "budget_status", {})
        spent = budget.get("wire_calls", initial_wire + reserved) - initial_wire
        if budget.get("stopped") or spent + worst > max_calls:
            break
        reserved += worst
        prediction = run_judge(client, [item], review_dir / "rubric.md", alias=alias)[0]
        prediction.update(review_sha256=review["review_sha256"], dimension=review["binding"]["dimension"],
                          answer_sha256=item["answer_sha256"], content_sha256=item["content_sha256"])
        predictions.append(safe_artifact(prediction))
    prediction_path.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in predictions), "utf-8")
    modes = sorted({p.get("evidence_mode", "unknown") for p in predictions})
    all_live = bool(predictions) and set(modes) <= LIVE_MODES
    events = safe_artifact(getattr(client, "events", [])[event_start:])
    identity = _judge_identity(predictions, events)
    write_json(review_dir / "judge_wire_events.json", {"events": events})
    result = {"status": "TEST_ONLY" if not all_live else
                        "JUDGE_IDENTITY_UNVERIFIED" if not identity["single_known_served_model"] else
                        "PARTIAL_BUDGET" if len(predictions) != len(items) else
                        "JUDGE_ERRORS" if not all(p["valid"] for p in predictions) else "JUDGE_SCORED",
              "created_at_utc": utc_now(), "review_sha256": review["review_sha256"],
              "rubric_sha256": review["binding"]["rubric_sha256"], "dimension": review["binding"]["dimension"],
              "predictions_sha256": file_hash(prediction_path), "expected_items": len(items),
              "judge_wire_events_sha256": file_hash(review_dir / "judge_wire_events.json"),
              "judge_provenance": judge_provenance, "judge_provenance_sha256": digest(judge_provenance),
              "wire_meter": wire_metrics(events),
              "judge_identity": identity,
              "scored_items": len(predictions), "valid_predictions": sum(p["valid"] for p in predictions),
              "evidence_modes": modes, "calibration_status": "NOT_CALIBRATED",
              "budget": safe_artifact(getattr(client, "budget_status", {}))}
    write_json(review_dir / "judge_manifest.json", result)
    return result


def score_review(review_dir: Path, labels_path: Path, predictions_path: Path | None = None, *,
                 min_pairs: int = 40, kappa_threshold: float = .6) -> dict:
    """Calculate agreement only for unchanged, unique, provenance-matched pairs."""
    review_dir, labels_path = Path(review_dir), Path(labels_path)
    review, items = _load_review(review_dir)
    if min_pairs < 1 or not 0 <= kappa_threshold <= 1:
        raise ValueError("Invalid calibration thresholds")
    by_id = _unique_rows(items, "review")
    with labels_path.open(encoding="utf-8-sig", newline="") as file:
        human = _unique_rows(list(csv.DictReader(file)), "human")
    if set(human) != set(by_id):
        raise ValueError("Annotation IDs do not match the frozen review sample")
    predictions_path = Path(predictions_path or review_dir / "predictions.jsonl")
    predictions, judge_manifest, judge_events = {}, {}, []
    if predictions_path.exists():
        judge_manifest = json.loads((predictions_path.parent / "judge_manifest.json").read_text("utf-8"))
        if (judge_manifest.get("review_sha256") != review["review_sha256"] or
                judge_manifest.get("predictions_sha256") != file_hash(predictions_path) or
                judge_manifest.get("judge_provenance_sha256") != digest(judge_manifest.get("judge_provenance")) or
                judge_manifest.get("judge_wire_events_sha256") != file_hash(predictions_path.parent / "judge_wire_events.json")):
            raise ValueError("Judge output provenance mismatch")
        predictions = _unique_rows(read_jsonl(predictions_path), "prediction")
        judge_events = json.loads((predictions_path.parent / "judge_wire_events.json").read_text("utf-8"))["events"]
        if set(predictions) - set(by_id):
            raise ValueError("Unexpected judge IDs")
    pairs, missing, invalid = [], [], []
    for case_id, item in by_id.items():
        row = human[case_id]
        original = _csv_row(item, review["review_sha256"], review["binding"]["rubric_sha256"],
                            review["binding"]["dimension"])
        if any(row.get(key) != value for key, value in original.items() if key not in EDITABLE):
            raise ValueError("Annotation content or provenance changed; labels are stale")
        if not row.get("human_label") and not any(row.get(k, "").strip() for k in EDITABLE - {"human_label"}):
            missing.append(case_id)
            continue
        if row.get("human_label") not in LABELS or not row.get("rater_id", "").strip() or not row.get("annotated_at", "").strip():
            invalid.append(case_id)
            continue
        try:
            datetime.fromisoformat(row["annotated_at"].replace("Z", "+00:00"))
        except ValueError:
            invalid.append(case_id)
            continue
        prediction = predictions.get(case_id)
        if not prediction or not prediction.get("valid") or prediction.get("label") not in LABELS:
            invalid.append(case_id)
            continue
        for key, expected in {"output_hash": output_hash(item), "answer_sha256": item["answer_sha256"],
                              "content_sha256": item["content_sha256"], "review_sha256": review["review_sha256"],
                              "rubric_sha256": review["binding"]["rubric_sha256"],
                              "dimension": review["binding"]["dimension"]}.items():
            if prediction.get(key) != expected:
                raise ValueError("Stale or mismatched judge/answer/rubric binding")
        pairs.append((row, prediction))
    metrics = agreement_metrics([h["human_label"] for h, _ in pairs], [p["label"] for _, p in pairs])
    reasons = []
    if len(pairs) < min_pairs:
        reasons.append("insufficient_unique_human_pairs")
    if missing or invalid or len(predictions) != len(items):
        reasons.append("incomplete_annotation_or_judge_coverage")
    if not review["binding"]["source_is_live"]:
        reasons.append("source_answers_are_not_verified_live")
    if not pairs or any(p.get("evidence_mode") not in LIVE_MODES for _, p in pairs):
        reasons.append("judge_is_not_verified_live")
    judge_identity = _judge_identity(list(predictions.values()), judge_events)
    if not judge_identity["single_known_served_model"]:
        reasons.append("judge_served_model_identity_unknown_or_mixed")
    if metrics["cohen_kappa"] is None or metrics["cohen_kappa"] < kappa_threshold:
        reasons.append("kappa_not_established_or_below_threshold")
    source_run = json.loads((Path(review["source_run_dir"]) / "manifest.json").read_text("utf-8"))
    source_files = source_run["provenance"]["source_files_sha256"]
    source_matches = all((ROOT / name).is_file() and file_hash(ROOT / name) == expected
                         for name, expected in source_files.items())
    if not source_matches:
        reasons.append("application_source_changed_since_evaluation")
    result = {"status": "CALIBRATED" if not reasons else "NOT_CALIBRATED", **metrics,
              "created_at_utc": utc_now(), "review_sha256": review["review_sha256"],
              "dimension": review["binding"]["dimension"], "rubric_sha256": review["binding"]["rubric_sha256"],
              "labels_sha256": file_hash(labels_path), "minimum_pairs": min_pairs,
              "kappa_threshold": kappa_threshold, "ready_for_quality_gate": not reasons, "gate_reasons": reasons,
              "current_source_matches_evaluated_source": source_matches,
              "judge_identity": judge_identity,
              "coverage": {**review["coverage"], "annotated_rows": len(items)-len(missing),
                           "valid_paired_rows": len(pairs), "missing_labels": len(missing),
                           "invalid_or_missing_predictions": len(invalid), "rater_count": len({h["rater_id"] for h, _ in pairs})},
              "disagreements": [{"id": h["id"], "human": h["human_label"], "judge": p["label"],
                                  "reason": p.get("reason", "")} for h, p in pairs if h["human_label"] != p["label"]],
              "limits": "Human identity and label origin are self-reported, not independently proven by this code. "
                        "Calibration applies only to this source/run/rubric/sample; deterministic safety remains separate."}
    write_json(review_dir / "calibration.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("run_dir", type=Path)
    prepare.add_argument("out", type=Path)
    prepare.add_argument("--limit", type=int, default=40)
    prepare.add_argument("--rubric", type=Path)
    score = commands.add_parser("score")
    score.add_argument("review_dir", type=Path)
    score.add_argument("labels", type=Path)
    score.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    result = (prepare_review(args.run_dir, args.out, rubric_path=args.rubric, limit=args.limit)
              if args.command == "prepare" else score_review(args.review_dir, args.labels, args.predictions))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

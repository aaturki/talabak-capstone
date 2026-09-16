"""Blinded judge execution and honest human-calibration preparation.

Template generation never invents labels. A simulator judge is useful to test
the contract, but can never satisfy the human/live calibration readiness gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LABELS = ("PASS", "PARTIAL", "FAIL")
# The SDK boundary reports the configured live mode, never a bare "live".
LIVE_MODES = {"live_commercial", "live_open_weight"}
JUDGE_SCHEMA = {
    "title": "JudgeVerdict", "type": "object", "additionalProperties": False,
    "properties": {"label": {"type": "string", "enum": list(LABELS)},
                   "reason": {"type": "string"}},
    "required": ["label", "reason"],
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def agreement_metrics(human: list[str], predicted: list[str]) -> dict:
    if len(human) != len(predicted):
        raise ValueError("Paired labels must have the same length")
    if not human:
        return {"n": 0, "agreement": None, "cohen_kappa": None,
                "kappa_status": "undefined_no_pairs", "confusion_matrix": {}}
    if any(label not in LABELS for label in human + predicted):
        raise ValueError("Only PASS/PARTIAL/FAIL labels are valid")
    n = len(human)
    observed = sum(a == b for a, b in zip(human, predicted)) / n
    h, p = Counter(human), Counter(predicted)
    chance = sum(h[label] * p[label] for label in LABELS) / n ** 2
    kappa = None if chance == 1 else (observed - chance) / (1 - chance)
    matrix = {a: {b: sum(x == a and y == b for x, y in zip(human, predicted))
                  for b in LABELS} for a in LABELS}
    return {"n": n, "agreement": observed, "cohen_kappa": kappa,
            "kappa_status": "defined" if kappa is not None else "undefined_single_category",
            "human_distribution": dict(h), "judge_distribution": dict(p),
            "confusion_matrix": matrix}


def export_human_template(items: list[dict], path: Path, *, limit: int = 36) -> dict:
    """Select language-diverse actual outputs; blank labels remain blank."""
    if path.exists():
        raise FileExistsError("Refusing to overwrite an existing human annotation file")
    seen: set[str] = set()
    selected = []
    # Round-robin over language/intent/risk groups avoids file ordering selecting
    # only the first FAQ section. The owner still reviews the sample before use.
    def stratum(item):
        return (item.get("language", "unknown"), item.get("intent", "unknown"), item.get("risk", "unknown"))
    groups = {key: [x for x in items if stratum(x) == key]
              for key in sorted({stratum(x) for x in items})}
    while len(selected) < limit and any(groups.values()):
        for lang in groups:
            if groups[lang] and len(selected) < limit:
                item = groups[lang].pop(0)
                if item["id"] in seen:
                    raise ValueError("Duplicate output id")
                seen.add(item["id"])
                selected.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "language", "question", "evidence", "answer", "output_hash",
              "human_label", "annotator", "annotated_at", "rationale"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for item in selected:
            if "answer" not in item or "evidence" not in item:
                raise ValueError("Templates must use actual answers and their trusted evidence")
            source = {key: item.get(key, "") for key in ("id", "language", "question", "evidence", "answer")}
            writer.writerow({**source, "evidence": json.dumps(item["evidence"], ensure_ascii=False),
                             "output_hash": digest(source), "human_label": "", "annotator": "",
                             "annotated_at": "", "rationale": ""})
    return {"status": "AWAITING_HUMAN_LABELS", "rows": len(selected),
            "path": str(path), "labels_filled": 0,
            "notice": "Blank labels are not human calibration evidence."}


def judge_payload(item: dict, rubric: str) -> list[dict]:
    """Allowlist prevents ground truth, human labels and case IDs reaching the judge."""
    public = {"question": item["question"], "trusted_evidence": item["evidence"],
              "candidate_answer": item["answer"]}
    return [{"role": "system", "content": rubric},
            {"role": "user", "content": json.dumps(public, ensure_ascii=False)}]


def run_judge(client: Any, items: list[dict], rubric_path: Path, *, alias: str = "judge") -> list[dict]:
    rubric = rubric_path.read_text("utf-8")
    rubric_hash = hashlib.sha256(rubric.encode()).hexdigest()
    results = []
    for item in items:
        row = {"id": item["id"], "rubric": rubric_path.name, "rubric_sha256": rubric_hash,
               "output_hash": digest({key: item.get(key, "") for key in
                                      ("id", "language", "question", "evidence", "answer")})}
        try:
            reply = client.complete(judge_payload(item, rubric), schema=JUDGE_SCHEMA, alias=alias)
            # Invalid judge JSON still consumed a model response; preserve its meter.
            row.update(evidence_mode=reply.evidence_mode, model=reply.model, usage=reply.usage)
            value = json.loads(reply.content or "null")
            if (not isinstance(value, dict) or set(value) != {"label", "reason"}
                    or value["label"] not in LABELS or not isinstance(value["reason"], str)):
                raise ValueError("Judge output violates its schema")
            row.update(value)
            row.update(evidence_mode=reply.evidence_mode, model=reply.model, usage=reply.usage, valid=True)
        except Exception as exc:
            if getattr(exc, "usage", None):
                row["usage"] = exc.usage
                row["evidence_mode"] = exc.usage.get("evidence_mode", "unknown")
            row.update(label=None, reason="", valid=False,
                       error_type=type(exc).__name__, evidence_mode=row.get("evidence_mode", "unknown"))
        results.append(row)
    return results


def calibrate(human_rows: list[dict], predictions: list[dict], *, min_pairs: int = 30,
              kappa_threshold: float = 0.6) -> dict:
    labels = {row["id"]: row for row in human_rows}
    pred = {row["id"]: row for row in predictions}
    if len(labels) != len(human_rows) or len(pred) != len(predictions):
        raise ValueError("Duplicate IDs would bias agreement")
    paired, missing, invalid, mismatched = [], [], [], []
    for case_id, row in labels.items():
        if (row.get("human_label") not in LABELS or not row.get("annotator", "").strip()
                or not row.get("annotated_at", "").strip()):
            missing.append(case_id)
            continue
        prediction = pred.get(case_id, {})
        if prediction.get("label") not in LABELS or not prediction.get("valid", False):
            invalid.append(case_id)
            continue
        if not row.get("output_hash") or row["output_hash"] != prediction.get("output_hash"):
            mismatched.append(case_id)
            continue
        paired.append((row, prediction))
    metrics = agreement_metrics([x[0]["human_label"] for x in paired], [x[1]["label"] for x in paired])
    modes = sorted({x[1].get("evidence_mode", "unknown") for x in paired})
    only_live = bool(paired) and all(mode in LIVE_MODES for mode in modes)
    reasons = []
    if len(paired) < min_pairs:
        reasons.append("insufficient_human_pairs")
    if missing or invalid or mismatched:
        reasons.append("incomplete_or_invalid_pairs")
    if not only_live:
        reasons.append("judge_is_not_verified_live")
    if metrics["cohen_kappa"] is None or metrics["cohen_kappa"] < kappa_threshold:
        reasons.append("kappa_not_established_or_below_threshold")
    return {"status": "CALIBRATED" if not reasons else "NOT_CALIBRATED", **metrics,
            "ready_for_quality_gate": not reasons, "gate_reasons": reasons,
            "minimum_pairs": min_pairs, "kappa_threshold": kappa_threshold,
            "evidence_modes": modes, "missing_human_labels": missing,
            "invalid_or_missing_judge_predictions": invalid, "output_hash_mismatches": mismatched,
            "disagreements": [{"id": h["id"], "human": h["human_label"],
                               "judge": p["label"], "reason": p.get("reason", "")}
                              for h, p in paired if h["human_label"] != p["label"]],
            "limits": "Annotator identity is self-reported. Code cannot prove a person supplied a label. "
                      "Safety decisions use deterministic checks, never this judge."}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8-sig").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Create blank human CSV from actual evaluation outputs")
    export.add_argument("outputs", type=Path)
    export.add_argument("csv", type=Path)
    export.add_argument("--limit", type=int, default=36)
    score = sub.add_parser("score", help="Calculate agreement against matching actual predictions")
    score.add_argument("labels", type=Path)
    score.add_argument("predictions", type=Path)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "export":
        print(json.dumps(export_human_template(read_jsonl(args.outputs), args.csv, limit=args.limit),
                         ensure_ascii=False, indent=2))
    else:
        with args.labels.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        report = calibrate(rows, read_jsonl(args.predictions))
        report["created_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps({"status": report["status"], "pairs": report["n"], "out": str(args.out)}))


if __name__ == "__main__":
    main()

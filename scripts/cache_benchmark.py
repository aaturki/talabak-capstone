"""Measure local exact/semantic caches on a frozen repetitive synthetic workload.

The concept-vector tier is a deterministic concept map, not learned embeddings.
Simulator tariffs and latency are kept distinct from actual paid-provider data.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.evaluate import evaluate, file_hash, percentile, read_jsonl, regression_gate, write_run


def check_pairs(pairs: list[dict], threshold: float) -> dict:
    """Exercise SemanticCache.put/get rather than treating cosine alone as a hit."""
    from talabak.cache import SemanticCache, pair_score
    value = ("answer", "controlled cached value", ["policy-v1"], {"intent": "faq"})
    rows = []
    for pair in pairs:
        cache = SemanticCache(threshold=threshold)
        a, b = pair["a"], pair["b"]
        cache.put(a["text"], {k: v for k, v in a.items() if k != "text"}, value)
        hit = cache.get(b["text"], {k: v for k, v in b.items() if k != "text"}) is not None
        rows.append({"id": pair["id"], "expected_hit": pair["should_hit"], "actual_hit": hit,
                     "score": pair_score(a, b), "reason": pair["reason"], "passed": hit == pair["should_hit"]})
    positives = [row for row in rows if row["expected_hit"]]
    negatives = [row for row in rows if not row["expected_hit"]]
    return {"threshold": threshold, "n": len(rows), "positive_n": len(positives), "negative_n": len(negatives),
            "true_hits": sum(row["actual_hit"] for row in positives),
            "missed_positive_hits": sum(not row["actual_hit"] for row in positives),
            "wrong_hits": sum(row["actual_hit"] for row in negatives), "rows": rows}


def select_threshold(pairs: list[dict]) -> dict:
    if any(pair.get("split") == "holdout" for pair in pairs):
        raise ValueError("Held-out pairs must not enter threshold selection")
    sweep = [check_pairs(pairs, threshold) for threshold in (.5, .65, .8, .9, .95, 1.0)]
    eligible = [result for result in sweep if result["wrong_hits"] == 0]
    if not eligible:
        return {"status": "DISABLED", "selected_threshold": None, "sweep": sweep,
                "reason": "No tested threshold avoids wrong hits"}
    selected = max(eligible, key=lambda result: (result["true_hits"], result["threshold"]))
    return {"status": "SELECTED", "selected_threshold": selected["threshold"], "sweep": sweep,
            "rule": "Zero wrong hits first; maximize correct positive hits; choose highest tied threshold",
            "limits": "Concept-set equality makes nonzero scores nearly binary. This is a conservative lexical concept cache, not an embedding-model benchmark."}


def freeze_workload(cases: list[dict], path: Path) -> list[dict]:
    eligible = [case for case in cases if case["intent"] in {"faq", "order_status"}
                and len(case["messages"]) == 1 and case["expected"]["allowed_statuses"] == ["answer"]]
    rows = [{"id": f"R{repeat + 1}-{case['id']}", "case_id": case["id"], "repeat": repeat + 1,
             "text": case["messages"][0], "session": case["session"], "intent": case["intent"]}
            for repeat in range(4) for case in eligible]
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    if path.exists() and path.read_text("utf-8") != text:
        raise ValueError("Frozen workload changed; create a new version explicitly")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(text, "utf-8")
    return rows


MODES = ("baseline", "stable_public_context", "exact", "semantic")


def mode_settings(mode: str) -> dict:
    """baseline: no prefix, no response cache. stable_public_context: shared public
    prefix only, so provider cached tokens are measured without response-cache skips.
    exact/semantic: the prefix plus the application's response caches."""
    if mode not in MODES:
        raise ValueError(f"Unknown cache benchmark mode: {mode}")
    return {"cache_enabled": mode in {"exact", "semantic"}, "semantic_enabled": mode == "semantic",
            "stable_context": mode != "baseline"}


def replay(client, traffic: list[dict], *, mode: str, references: dict | None = None,
           threshold: float = 1.0) -> tuple[list[dict], dict]:
    from talabak.domain import Session, Store
    from talabak.guards import mask_pii, output_reason
    from talabak.pipeline import Application
    contexts, rows = {}, []
    settings = mode_settings(mode)
    started = time.perf_counter()
    try:
        for event in traffic:
            key = json.dumps(event["session"], sort_keys=True)
            if key not in contexts:
                store = Store()
                session = Session(**event["session"])
                app = Application(client, store, **settings)
                if app.semantic:
                    app.semantic.threshold = threshold
                contexts[key] = (store, session, app)
            store, session, app = contexts[key]
            result = app.handle_message(event["text"], session)
            actual = {"status": result.status, "message": result.message, "citations": result.citations}
            safe = (result.status == "answer" and store.count_actions() == 0
                    and output_reason(result.message, "TALABAK_CANARY_7C84F52A") is None)
            equivalent = references is None or actual == references[event["id"]]
            rows.append({"id": event["id"], "case_id": event["case_id"], "repeat": event["repeat"],
                         "text": mask_pii(event["text"]), "passed": safe and equivalent,
                         "equivalent_to_baseline": equivalent, "action_count": store.count_actions(),
                         "reference": actual, "result": result.to_dict()})
    finally:
        for store, _, _ in contexts.values():
            store.close()
    elapsed = (time.perf_counter() - started) * 1000
    usage = [u for row in rows for u in row["result"]["usage"]]
    hits = [trace for row in rows for trace in row["result"]["trace"] if trace.get("event") == "response_cache_hit"]
    inputs = sum(u.get("input_tokens", 0) for u in usage)
    cached = sum(u.get("cached_tokens", 0) for u in usage)
    summary = {"mode": mode, "requests": len(rows), "passed": sum(row["passed"] for row in rows),
               "model_calls": len(usage), "response_cache_hits": len(hits),
               "exact_hits": sum(x.get("tier") == "exact" for x in hits),
               "semantic_hits": sum(x.get("tier") == "semantic" for x in hits),
               "input_tokens": inputs, "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
               "provider_cached_tokens": cached, "provider_cache_fraction": cached / inputs if inputs else None,
               "cost_usd": sum(u.get("cost_usd", 0) for u in usage),
               "simulated_cost_usd": sum(u.get("simulated_cost_usd", 0) for u in usage),
               "wall_ms": elapsed,
               "request_latency_ms_p50": percentile([row["result"]["latency_ms"] for row in rows], .5),
               "request_latency_ms_p95": percentile([row["result"]["latency_ms"] for row in rows], .95),
               "failed_ids": [row["id"] for row in rows if not row["passed"]],
               "evidence_mode": "simulator", "semantic_threshold": threshold if mode == "semantic" else None,
               "stable_context": settings["stable_context"], "response_cache_enabled": settings["cache_enabled"]}
    return rows, summary


def run_cache_benchmark(client, out: str | Path) -> dict:
    from talabak.pipeline import Application
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    pairs_path = ROOT / "data/cache_pairs.v1.jsonl"
    near_path = ROOT / "data/near_miss.v1.jsonl"
    pairs = read_jsonl(pairs_path)
    development = [row for row in pairs if row["split"] == "development"]
    calibration = select_threshold(development)
    if calibration["selected_threshold"] is None:
        (out / "threshold_calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2), "utf-8")
        return {"status": "SEMANTIC_DISABLED", "calibration": calibration}
    threshold = calibration["selected_threshold"]
    holdout = check_pairs([row for row in pairs if row["split"] == "holdout"], threshold)
    near = check_pairs(read_jsonl(near_path), threshold)
    semantic_ready = holdout["wrong_hits"] == 0 and near["wrong_hits"] == 0
    calibration.update(holdout=holdout, original_near_misses=near, semantic_ready=semantic_ready,
                       pairs_sha256=file_hash(pairs_path), near_miss_sha256=file_hash(near_path))
    (out / "threshold_calibration.json").write_text(json.dumps(calibration, ensure_ascii=False, indent=2) + "\n", "utf-8")
    traffic = freeze_workload(read_jsonl(ROOT / "data/golden.v1.jsonl"), out / "traffic.v1.jsonl")
    modes = tuple(mode for mode in MODES if semantic_ready or mode != "semantic")
    steps, reference_outputs, baseline_eval = [], None, None
    for mode in modes:
        settings = mode_settings(mode)
        rows, summary = replay(client, traffic, mode=mode, references=reference_outputs, threshold=threshold)
        if reference_outputs is None:
            reference_outputs = {row["id"]: row["reference"] for row in rows}
        def factory(client, *, store, cache_enabled, alias):
            app = Application(client, store, alias=alias, **settings)
            if app.semantic:
                app.semantic.threshold = threshold
            return app
        eval_rows, full_eval = evaluate(client, application_factory=factory, cache_enabled=settings["cache_enabled"])
        if baseline_eval is None:
            baseline_eval = full_eval
        gate = regression_gate(full_eval, baseline_eval)
        summary.update(golden_overall=full_eval["overall"], golden_safety=full_eval["safety"], regression_gate=gate)
        if mode != "baseline":
            original = steps[0]
            denominator = original["simulated_cost_usd"]
            summary["simulated_cost_reduction_vs_baseline"] = 1 - summary["simulated_cost_usd"] / denominator if denominator else None
            summary["actual_cost_reduction_vs_baseline"] = None
            summary["actual_cost_reduction_reason"] = "Actual spend is zero in both modes; a percentage is undefined"
        step_dir = out / mode
        write_run(eval_rows, full_eval, step_dir / "golden")
        (step_dir / "traffic_results.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", "utf-8")
        steps.append(summary)
    stable = next((step for step in steps if step["mode"] == "stable_public_context"), None)
    prompt_fraction = stable["provider_cache_fraction"] if stable else None
    reduction = steps[-1].get("simulated_cost_reduction_vs_baseline")
    targets = {"provider_input_cache_at_least_65_percent": prompt_fraction is not None and prompt_fraction >= .65,
               "simulated_cost_reduction_at_least_60_percent": reduction is not None and reduction >= .60,
               "every_step_quality_passed": all(x["passed"] == x["requests"] and x["regression_gate"]["status"] == "PASS" for x in steps),
               "zero_semantic_wrong_hits": semantic_ready}
    report = {"status": "PASS" if all(x["passed"] == x["requests"] and x["regression_gate"]["status"] == "PASS" for x in steps) and semantic_ready else "REVIEW_REQUIRED",
              "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "traffic_sha256": file_hash(out / "traffic.v1.jsonl"),
              "workload": "Exactly four passes of all first-turn successful read-only FAQ/status golden cases. Deliberately repetitive synthetic workload, not measured store traffic.",
              "semantic_ready": semantic_ready, "selected_threshold": threshold, "steps": steps,
              "provider_input_cache_fraction": prompt_fraction, "simulated_cost_reduction": reduction,
              "targets": targets,
              "targets_basis": "simulator usage.prompt_tokens_details.cached_tokens over a 1024-token minimum prefix and illustrative tariffs; a live provider must confirm both targets",
              "pipeline_default_stable_context": bool(getattr(client, "config", {}).get("pipeline", {}).get("stable_context", False)),
              "limitations": ["All model routes are deterministic simulators. Their tariffs are illustrative.",
                              "Actual cost is zero; no paid-provider cost saving is demonstrated.",
                              "Provider prompt-cache tokens are measured in the stable_public_context step with response caching disabled; response-cache hits are a separate mechanism.",
                              "The shared prefix adds public context to every call, so its per-call token count is higher than the baseline; the saving comes from the cached share and from response-cache skips.",
                              "A new full 144-case golden evaluation accompanies each step.",
                              "Near misses and heldout pairs test this limited concept map; results do not establish embedding-model accuracy.",
                              "Repeated holdout checks after the first are regression checks; thresholds must not be retuned to them."]}
    (out / "cache_benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return report


def main():
    from talabak.llm import SDKClient
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "eval/out/cache")
    args = parser.parse_args()
    with SDKClient() as client:
        report = run_cache_benchmark(client, args.out)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Opt-in benchmarks through the real application; disabled paths read no secrets."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate import check_case, evaluate, file_hash, percentile, read_jsonl, regression_gate, write_run


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _source_hash():
    paths = [*sorted((ROOT / "talabak").glob("*.py")), *sorted((ROOT / "prompts").glob("*")),
             ROOT / "scripts/live_benchmark.py", ROOT / "scripts/evaluate.py"]
    return _hash({str(path.relative_to(ROOT)).replace("\\", "/"): file_hash(path)
                  for path in paths if path.is_file()})


def meter_totals(usage):
    """Missing usage stays unknown; a missing field must never become zero cost."""
    def total(key):
        values = [row.get(key) for row in usage]
        return sum(values) if values and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                              and math.isfinite(x) and x >= 0 for x in values) else None
    result = {key: total(key) for key in ("input_tokens", "output_tokens", "cached_tokens", "estimated_cost_usd")}
    result.update(model_calls=len(usage), evidence_modes=sorted({row.get("evidence_mode", "unknown") for row in usage}),
                  served_models=sorted({row["model"] for row in usage if row.get("model")
                                         and row["model"] != "unreported" and row.get("served_model_known", True)}),
                  actual_invoice_cost_usd=None)
    result["provider_cache_fraction"] = (result["cached_tokens"] / result["input_tokens"]
                                         if result["input_tokens"] and result["cached_tokens"] is not None else None)
    result["cost_basis"] = "Provider usage multiplied by explicitly supplied dated tariffs; not an invoice."
    return result


def _wire_totals(client, usage, start=0):
    from scripts.live_evaluate import wire_metrics
    result = meter_totals(usage)
    wire = wire_metrics(getattr(client, "events", [])[start:])
    result["wire"] = wire
    if wire["wire_calls"]:
        for key in ("input_tokens", "output_tokens", "cached_tokens", "estimated_cost_usd"):
            result[key] = wire[key]
        if result["input_tokens"] and result["cached_tokens"] is not None:
            result["provider_cache_fraction"] = result["cached_tokens"] / result["input_tokens"]
            result["provider_cache_fraction_basis"] = "all_wire_attempts"
        else:
            # A retried or errored attempt has unknown usage; report the share over
            # the known responses and disclose how many attempts were excluded.
            result["provider_cache_fraction"] = wire["provider_cache_fraction_known_responses"]
            result["provider_cache_fraction_basis"] = "known_responses_only"
        result["attempts_with_unknown_usage"] = wire["attempts_with_unknown_usage"]
        result["estimated_cost_known_lower_bound_usd"] = wire["usage_coverage"]["estimated_cost_usd"]["known_total"]
    return result


def _client(config, max_calls, factory=None, *, alias="primary", secret_loader=None):
    from talabak.llm import SDKClient
    selected = copy.deepcopy(config)
    aliases = {alias, *selected.get("fallbacks", {}).get(alias, [])}
    selected["routes"] = {name: route for name, route in selected.get("routes", {}).items() if name in aliases}
    selected["fallbacks"] = {name: chain for name, chain in selected.get("fallbacks", {}).items() if name in aliases}
    if not isinstance(max_calls, int) or isinstance(max_calls, bool) or not 1 <= max_calls <= 100000:
        raise ValueError("max_calls must be between 1 and 100000")
    budget = selected.setdefault("settings", {}).setdefault("budget", {})
    existing = budget.get("max_calls")
    budget["max_calls"] = min(max_calls, existing) if existing is not None else max_calls
    return (factory or SDKClient)(config=selected, allow_live=True, secret_loader=secret_loader)


def _run_case(client, case, alias, *, stable_context=None):
    from talabak.domain import Session, Store
    from talabak.pipeline import Application
    store = Store()
    try:
        session = Session(**case["session"])
        app = Application(client, store, alias=alias, cache_enabled=False, stable_context=stable_context)
        start = time.perf_counter()
        results = [app.handle_message(message, session) for message in case["messages"]]
        check = check_case(case, results, action_count=store.count_actions(), terminal=session.terminal)
        return {"id": case["id"], **check, "latency_ms": (time.perf_counter() - start) * 1000,
                "completed": all(result.status != "error" for result in results),
                "results": [result.to_dict() for result in results]}
    finally:
        store.close()


def measure_self_host(config, *, enabled=False, out=ROOT / "artifacts/live/load", alias="open_weight",
                      concurrency=2, repeats=1, hardware=None, deployment_confirmed=False,
                      max_calls=4000, client_factory=None, secret_loader=None):
    """Measure full conversations on operator-identified self-host hardware.

    Private SQLite state is created inside each worker. Elapsed wall time covers
    all concurrent conversations once, rather than summing overlapping latencies.
    """
    if not enabled:
        return {"status": "NOT_RUN", "reason": "Enable after selecting a self-hosted model and runtime."}
    route = config.get("routes", {}).get(alias, {})
    if route.get("evidence_mode") != "live_open_weight" or route.get("deployment") != "self_hosted":
        raise ValueError("A configured self_hosted live_open_weight route is required; hosted API latency is not self-host evidence")
    if not deployment_confirmed or not isinstance(hardware, dict) or not all(
            isinstance(hardware.get(key), str) and hardware[key].strip()
            for key in ("description", "runtime", "model_revision")):
        raise ValueError("Confirm your self-host deployment and identify hardware, runtime and model_revision")
    if any(not isinstance(x, int) or isinstance(x, bool) for x in (concurrency, repeats)) or not 1 <= concurrency <= 32 or not 1 <= repeats <= 20:
        raise ValueError("concurrency must be 1..32 and repeats 1..20")
    cases = read_jsonl(ROOT / "data/golden.v1.jsonl")
    traffic = cases * repeats
    from scripts.live_evaluate import source_provenance
    provenance = source_provenance(config)
    # Fully deterministic refusals make no model call and cannot establish serving capacity.
    route_config = copy.deepcopy(config)
    route_config["fallbacks"] = {name: [] for name in route_config["routes"]}
    with _client(route_config, max_calls, client_factory, alias=alias, secret_loader=secret_loader) as client:
        started_at = datetime.now(timezone.utc).isoformat()
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = list(pool.map(lambda case: _run_case(client, case, alias), traffic))
        elapsed = time.perf_counter() - start
    usage = [item for row in rows for result in row["results"] for item in result["usage"]]
    totals = _wire_totals(client, usage)
    completed = sum(row["completed"] for row in rows)
    quality_passed = sum(row["passed"] for row in rows)
    modes = set(totals["evidence_modes"])
    live = (bool(usage) and modes == {"live_open_weight"}
            and len(totals["wire"]["served_models"]) == 1
            and totals["wire"]["served_model_unknown_responses"] == 0)
    report = {"status": "MEASURED" if live else "NOT_LIVE_EVIDENCE", "evidence_mode": "live" if live else "test_or_unknown",
              "measurement_kind": "self_hosted_load", "measured_at": started_at,
              "hardware": hardware, "deployment_confirmed_by_operator": True,
              "alias": alias, "requested_model": route.get("model"), "concurrency": concurrency,
              "repeats": repeats, "batch_size": 1, "saturation_observed": False,
              "traffic_sha256": _hash(traffic), "golden_sha256": file_hash(ROOT / "data/golden.v1.jsonl"),
              "source_sha256": _source_hash(), "config_sha256": _hash(config),
              "provenance": provenance,
              "fixture_sha256": file_hash(ROOT / "data/store.v1.json"),
              "totals": {"attempted_requests": len(rows), "completed_requests": completed,
                         "quality_passed_requests": quality_passed, "elapsed_seconds": elapsed,
                         "completed_requests_per_second": completed / elapsed,
                         "quality_passed_requests_per_second": quality_passed / elapsed,
                         "model_calls_per_second": totals["wire"]["wire_calls"] / elapsed,
                         "output_tokens_per_second": totals["output_tokens"] / elapsed if totals["output_tokens"] is not None else None,
                         "latency_ms_p50": percentile([row["latency_ms"] for row in rows], .5),
                         "latency_ms_p95": percentile([row["latency_ms"] for row in rows], .95)},
              "meter": totals, "failed_case_ids": [row["id"] for row in rows if not row["passed"]],
              "limits": "Observed application throughput at this concurrency, not maximum GPU capacity. Run a concurrency sweep before claiming saturation. Hardware identity is operator supplied. No automatic monthly cost assumption."}
    out = Path(out)
    _save(out / "requests.json", rows)
    report["source_artifact_sha256"] = file_hash(out / "requests.json")
    _save(out / "measurement.json", report)
    return report


def _replay(client, cases, *, alias, cache, semantic, stable_context, threshold):
    from talabak.domain import Session, Store
    from talabak.pipeline import Application
    contexts, rows, origins = {}, [], {}
    event_start = len(getattr(client, "events", []))
    try:
        for repetition in range(4):
            for case in cases:
                key = _hash(case["session"])
                if key not in contexts:
                    store = Store()
                    session = Session(**case["session"])
                    app = Application(client, store, alias=alias, cache_enabled=cache,
                                      semantic_enabled=semantic, stable_context=stable_context)
                    if app.semantic:
                        app.semantic.threshold = threshold
                    contexts[key] = (store, session, app)
                store, session, app = contexts[key]
                result = app.handle_message(case["messages"][0], session)
                checked = check_case(case, [result], action_count=store.count_actions(), terminal=session.terminal)
                cache_hit = any(event.get("event") == "response_cache_hit" for event in result.trace)
                if cache_hit and case["expected"].get("tools_include"):
                    # A cache hit intentionally executes no new lookup. Require
                    # the earlier successful lookup and identical cached facts;
                    # never fabricate a fresh tool event in the transcript.
                    origin = origins.get(case["id"])
                    checked["checks"]["tools"] = bool(origin and origin["passed"]
                        and set(case["expected"]["tools_include"]).issubset(origin["actual_tools"])
                        and (result.status, result.message, result.citations, result.request) == origin["value"])
                    checked["tool_evidence"] = "earlier_validated_lookup_for_this_case" if checked["checks"]["tools"] else "missing_cache_origin"
                    checked["failures"] = [name for name, ok in checked["checks"].items() if not ok]
                    checked["passed"] = not checked["failures"]
                    if checked["safety_case"]:
                        checked["safety_passed"] = checked["passed"]
                elif not cache_hit:
                    origins[case["id"]] = {**checked, "value": (result.status, result.message, result.citations, result.request)}
                rows.append({"id": f"{repetition + 1}-{case['id']}", **checked, "result": result.to_dict()})
    finally:
        for store, _, _ in contexts.values():
            store.close()
    usage = [item for row in rows for item in row["result"]["usage"]]
    totals = _wire_totals(client, usage, event_start)
    totals.update(requests=len(rows), passed=sum(row["passed"] for row in rows),
                  response_cache_hits=sum(any(event.get("event") == "response_cache_hit" for event in row["result"]["trace"]) for row in rows))
    return rows, totals


def measure_cache(config, *, enabled=False, out=ROOT / "artifacts/live/cache", alias="primary",
                  max_calls=12000, client_factory=None, secret_loader=None):
    """Measure four steps against fixed expectations and rerun the full golden set."""
    if not enabled:
        return {"status": "NOT_RUN", "reason": "Enable after selecting a provider and its dated tariffs."}
    from scripts.cache_benchmark import check_pairs, select_threshold
    from talabak.pipeline import Application
    cases = read_jsonl(ROOT / "data/golden.v1.jsonl")
    traffic = [case for case in cases if len(case["messages"]) == 1 and case["intent"] in {"faq", "order_status"}
               and case["expected"]["allowed_statuses"] == ["answer"]]
    pairs = read_jsonl(ROOT / "data/cache_pairs.v1.jsonl")
    calibration = select_threshold([pair for pair in pairs if pair["split"] == "development"])
    threshold = calibration["selected_threshold"]
    if threshold is None:
        return {"status": "BLOCK", "reason": "No safe semantic-cache threshold", "calibration": calibration}
    holdout = check_pairs([pair for pair in pairs if pair["split"] == "holdout"], threshold)
    near = check_pairs(read_jsonl(ROOT / "data/near_miss.v1.jsonl"), threshold)
    semantic_safe = holdout["wrong_hits"] == 0 and near["wrong_hits"] == 0
    phases = [("baseline", False, False, False), ("stable_public_context", False, False, True),
              ("exact_cache", True, False, True)]
    if semantic_safe:
        phases.append(("semantic_cache", True, True, True))
    out = Path(out)
    baseline = None
    steps = []
    route_config = copy.deepcopy(config)
    route_config["fallbacks"] = {name: [] for name in route_config.get("routes", {})}
    with _client(route_config, max_calls, client_factory, alias=alias, secret_loader=secret_loader) as client:
        for name, cache, semantic, stable in phases:
            rows, meter = _replay(client, traffic, alias=alias, cache=cache, semantic=semantic,
                                  stable_context=stable, threshold=threshold)
            def factory(selected_client, **kwargs):
                app = Application(selected_client, **kwargs, stable_context=stable, semantic_enabled=semantic)
                if app.semantic:
                    app.semantic.threshold = threshold
                return app
            golden_rows, summary = evaluate(client, alias=alias, cache_enabled=cache, application_factory=factory)
            baseline = baseline or summary
            gate = regression_gate(summary, baseline)
            step = {"name": name, "meter": meter, "golden_overall": summary["overall"],
                    "safety": summary["safety"], "eval_verdict": gate,
                    "replay_passed": meter["passed"] == meter["requests"],
                    "all_quality_checks_passed": meter["passed"] == meter["requests"] and gate["status"] == "PASS"}
            steps.append(step)
            write_run(golden_rows, summary, out / name / "golden")
            _save(out / name / "replay.json", rows)
    first, final = steps[0]["meter"], steps[-1]["meter"]
    baseline_cost, final_cost = first["estimated_cost_usd"], final["estimated_cost_usd"]
    reduction = 1 - final_cost / baseline_cost if baseline_cost and final_cost is not None else None
    # Prompt caching is measured with response caching disabled; otherwise skipped
    # requests could disguise a provider cache that never hit.
    prompt_fraction = steps[1]["meter"]["provider_cache_fraction"]
    modes = set(mode for step in steps for mode in step["meter"]["evidence_modes"])
    served_models = {model for step in steps for model in step["meter"]["wire"]["served_models"]}
    identities_known = all(step["meter"]["wire"]["served_model_unknown_responses"] == 0 for step in steps)
    live = (bool(modes) and modes <= {"live_commercial", "live_open_weight"}
            and len(served_models) == 1 and identities_known)
    targets = {"provider_input_cache_at_least_65_percent": prompt_fraction is not None and prompt_fraction >= .65,
               "estimated_cost_reduction_at_least_60_percent": reduction is not None and reduction >= .60,
               "every_step_quality_passed": all(step["all_quality_checks_passed"] for step in steps),
               "zero_semantic_wrong_hits": semantic_safe}
    report = {"status": "PASS" if live and all(targets.values()) else "TARGETS_NOT_MET" if live else "NOT_LIVE_EVIDENCE",
              "evidence_mode": "live" if live else "test_or_unknown", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "alias": alias, "traffic_sha256": _hash(traffic * 4), "golden_sha256": file_hash(ROOT / "data/golden.v1.jsonl"),
              "source_sha256": _source_hash(), "config_sha256": _hash(config),
              "workload": "Four repetitions of all one-turn successful read-only golden cases; synthetic repeated traffic, not measured customer traffic.",
              "steps": steps, "provider_input_cache_fraction": prompt_fraction,
              "estimated_cost_reduction": reduction, "targets": targets,
              "semantic_holdout": holdout, "near_misses": near,
              "limits": "Provider caches may already be warm; baseline is the observed first phase, not a guaranteed cold-provider run. Actual invoices are unavailable. Failed targets are retained. Semantic cache uses a conservative lexical concept map."}
    _save(out / "benchmark.json", report)
    return report


def build_breakeven_input(load_dir, comparison_dir, assumptions, *, out=None):
    """Bind economic inputs to full, unmodified, matched live-run artifacts."""
    from scripts.breakeven import compute_breakeven
    load_dir, comparison_dir = Path(load_dir), Path(comparison_dir)
    measured = json.loads((load_dir / "measurement.json").read_text("utf-8"))
    manifest = json.loads((comparison_dir / "manifest.json").read_text("utf-8"))
    if measured.get("status") != "MEASURED" or measured.get("evidence_mode") != "live":
        raise ValueError("A completed live self-host measurement is required")
    if measured.get("repeats") != 1:
        raise ValueError("Use one identical full-golden pass for the matched economic comparison")
    if not manifest.get("live_model_evidence") or manifest.get("status") != "LIVE_COMPLETE":
        raise ValueError("Both comparison routes require complete live model evidence")
    if manifest.get("provenance", {}).get("pilot"):
        raise ValueError("A pilot is not the full matched economic workload")
    if measured.get("traffic_sha256") != manifest.get("provenance", {}).get("traffic_sha256"):
        raise ValueError("Self-host and comparison traffic must match exactly")
    if measured.get("fixture_sha256") != manifest.get("provenance", {}).get("fixture_sha256"):
        raise ValueError("Store fixtures differ between measurements")
    requests_path = load_dir / "requests.json"
    if file_hash(requests_path) != measured["source_artifact_sha256"]:
        raise ValueError("Self-host request artifact changed after measurement")
    load_provenance = measured.get("provenance", {})
    comparison_provenance = manifest.get("provenance", {})
    if (not load_provenance.get("source_files_sha256")
            or load_provenance["source_files_sha256"] != comparison_provenance.get("source_files_sha256")):
        raise ValueError("Application source differs between self-host and comparison runs")
    if (load_provenance.get("configuration", {}).get("pipeline", {})
            != comparison_provenance.get("configuration", {}).get("pipeline", {})):
        raise ValueError("Application pipeline settings differ between measurements")
    if comparison_provenance.get("configuration", {}).get("routes", {}).get("open_weight", {}).get("deployment") != "hosted":
        raise ValueError("Gateway cost requires a hosted open-weight route in the comparison profile; use a separate self-host profile for throughput")
    load_rows = json.loads(requests_path.read_text("utf-8"))
    ids = [row["id"] for row in load_rows]
    models = measured.get("meter", {}).get("served_models", [])
    if len(models) != 1:
        raise ValueError("Self-host measurement must identify one served model")
    hardware = measured["hardware"]
    normalized = {"evidence_mode": "live", "measurement_kind": "self_hosted_load",
                  "traffic_sha256": measured["traffic_sha256"], "source_artifact_sha256": file_hash(requests_path),
                  "hardware": "; ".join(hardware[key] for key in ("description", "runtime", "model_revision")),
                  "model_id": models[0], "measured_at": measured["measured_at"],
                  "concurrency": measured["concurrency"], "batch_size": measured["batch_size"],
                  "saturation_observed": measured["saturation_observed"], "totals": measured["totals"]}
    routes, quality = {}, {}
    for alias, name in (("primary", "commercial"), ("open_weight", "open_weight_gateway")):
        rows_path, summary_path = comparison_dir / f"{alias}.results.jsonl", comparison_dir / f"{alias}.summary.json"
        for path in (rows_path, summary_path):
            if file_hash(path) != manifest["files"].get(path.name):
                raise ValueError("Comparison artifact changed after execution")
        rows = read_jsonl(rows_path)
        summary = json.loads(summary_path.read_text("utf-8"))
        if [row["id"] for row in rows] != ids:
            raise ValueError("Comparison case order or coverage does not match self-host traffic")
        usage = [item for row in rows for result in row["results"] for item in result["usage"]]
        meter = meter_totals(usage)
        if meter["estimated_cost_usd"] is None or len(meter["served_models"]) != 1:
            raise ValueError("One served model and complete usage/tariff cost are required for each route")
        if any(item.get("status") == "failed" or item.get("attempts", 1) != 1 for item in usage):
            raise ValueError("Retry/failure billing is uncertain; use a clean matched cost run")
        routes[name] = {"evidence_mode": "live", "traffic_sha256": measured["traffic_sha256"],
                        "source_artifact_sha256": file_hash(rows_path), "model_id": meter["served_models"][0],
                        "measured_requests": len(rows), "cost_usd_per_request": meter["estimated_cost_usd"] / len(rows),
                        "cost_basis": meter["cost_basis"]}
        quality[name] = {"passed": summary["overall"]["passed"], "n": summary["overall"]["n"], "safety": summary["safety"]}
    value = {"schema_version": "breakeven-v1", "self_host_measurement": normalized,
             "routes": routes, "assumptions": assumptions, "model_quality": quality}
    result = compute_breakeven(value)
    result["model_quality"] = quality
    result["routing_recommendation"] = "Review slice quality and safety alongside cost before choosing a route. No automatic production routing decision."
    if out is not None:
        _save(Path(out) / "breakeven.inputs.json", value)
        _save(Path(out) / "breakeven.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("cache", "self-host"))
    parser.add_argument("--config", type=Path, default=ROOT / "config/models.live.example.json")
    parser.add_argument("--enable-live", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--hardware", type=Path, help="JSON: description, runtime, model_revision")
    parser.add_argument("--confirm-self-host", action="store_true")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-calls", type=int, default=4000)
    args = parser.parse_args()
    config = json.loads(args.config.read_text("utf-8")) if args.enable_live else {}
    kwargs = {"enabled": args.enable_live, "max_calls": args.max_calls}
    if args.out:
        kwargs["out"] = args.out
    if args.kind == "cache":
        report = measure_cache(config, **kwargs)
    else:
        hardware = json.loads(args.hardware.read_text("utf-8")) if args.hardware else None
        report = measure_self_host(config, hardware=hardware, deployment_confirmed=args.confirm_self_host,
                                   concurrency=args.concurrency, **kwargs)
    print(json.dumps({key: report.get(key) for key in ("status", "reason", "targets", "totals")}, indent=2))


if __name__ == "__main__":
    main()

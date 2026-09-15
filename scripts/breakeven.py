"""Project self-hosting economics only from explicitly supplied live measurements.

No network requests, provider pricing lookups, simulated throughput, or default
economic assumptions. Running without an input reports NOT_MEASURED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def _number(value, name, *, minimum=0, strictly_positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite supplied number")
    if value < minimum or (strictly_positive and value <= 0):
        raise ValueError(f"{name} is outside the supported range")
    return float(value)


def _integer(value, name, *, minimum=0):
    result = _number(value, name, minimum=minimum)
    if result != int(result):
        raise ValueError(f"{name} must be a whole count")
    return int(result)


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must identify the supplied evidence")
    return value.strip()


def _hash(value, name):
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError(f"{name} must be a SHA-256 hash")
    return value.lower()


def _timestamp(value, name):
    try:
        stamp = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an ISO timestamp with timezone") from None
    if stamp.tzinfo is None:
        raise ValueError(f"{name} must include timezone")
    return stamp


def _measured_totals(measurement):
    if ("totals" in measurement) == ("windows" in measurement):
        raise ValueError("Supply exactly one of measurement.totals or measurement.windows")
    if "totals" in measurement:
        rows = [measurement["totals"]]
    else:
        windows = measurement["windows"]
        if not isinstance(windows, list) or not windows:
            raise ValueError("measurement.windows must contain recorded load-test intervals")
        rows, previous_end = [], None
        for window in sorted(windows, key=lambda x: _timestamp(x.get("started_at"), "window.started_at")):
            start = _timestamp(window.get("started_at"), "window.started_at")
            end = _timestamp(window.get("ended_at"), "window.ended_at")
            if end <= start or (previous_end and start < previous_end):
                raise ValueError("Measurement windows must be positive and non-overlapping")
            rows.append({**window, "elapsed_seconds": (end - start).total_seconds()})
            previous_end = end
    completed = attempted = 0
    elapsed = 0.0
    for row in rows:
        successes = _integer(row.get("completed_requests"), "completed_requests")
        attempts = _integer(row.get("attempted_requests"), "attempted_requests", minimum=1)
        seconds = _number(row.get("elapsed_seconds"), "elapsed_seconds", strictly_positive=True)
        if successes > attempts:
            raise ValueError("Completed requests cannot exceed attempts")
        completed += successes
        attempted += attempts
        elapsed += seconds
    if completed == 0:
        raise ValueError("No completed requests: measured serving throughput is not established")
    return {"completed_requests": completed, "attempted_requests": attempted,
            "elapsed_seconds": elapsed, "completion_rate": completed / attempted,
            "completed_requests_per_second": completed / elapsed,
            "measurement_windows": len(rows)}


def compare_route(*, fixed_usd, variable_usd_per_request, remote_usd_per_request,
                  capacity_requests, planned_requests):
    """F + vN versus cN. Volume N counts completed requests for identical traffic."""
    marginal_saving = remote_usd_per_request - variable_usd_per_request
    selfhost_total = fixed_usd + variable_usd_per_request * planned_requests
    remote_total = remote_usd_per_request * planned_requests
    common = {"remote_cost_usd_per_request": remote_usd_per_request,
              "selfhost_variable_usd_per_request": variable_usd_per_request,
              "selfhost_unit_cost_at_planned_volume_usd": selfhost_total / planned_requests if planned_requests else None,
              "selfhost_monthly_cost_at_planned_volume_usd": selfhost_total,
              "remote_monthly_cost_at_planned_volume_usd": remote_total,
              "monthly_saving_at_planned_volume_usd": remote_total - selfhost_total}
    if marginal_saving <= 0:
        status = "ALWAYS_EQUAL" if marginal_saving == 0 and fixed_usd == 0 else "NO_COST_CROSSING"
        return {**common, "status": status, "break_even_requests": None,
                "minimum_whole_requests_for_parity": None,
                "minimum_whole_requests_for_strict_saving": None,
                "utilization_required_for_parity": None,
                "parity_feasible_within_measured_capacity": status == "ALWAYS_EQUAL",
                "parity_feasible_at_planned_utilization": status == "ALWAYS_EQUAL",
                "reason": "Self-host variable cost is at least the remote per-request cost; positive fixed cost cannot be recovered." if status != "ALWAYS_EQUAL" else "Both routes have identical variable cost and zero fixed cost; self-hosting never becomes strictly cheaper."}
    crossing = fixed_usd / marginal_saving
    # Floating point near an integer should not add a spurious request at parity.
    nearest = round(crossing)
    if math.isclose(crossing, nearest, rel_tol=1e-12, abs_tol=1e-12):
        crossing = float(nearest)
    parity = math.ceil(crossing)
    strictly_cheaper = math.floor(crossing) + 1
    return {**common, "status": "CROSSING", "break_even_requests": crossing,
            "minimum_whole_requests_for_parity": parity,
            "minimum_whole_requests_for_strict_saving": strictly_cheaper,
            "utilization_required_for_parity": crossing / capacity_requests if capacity_requests else None,
            "parity_feasible_within_measured_capacity": parity <= math.floor(capacity_requests),
            "parity_feasible_at_planned_utilization": parity <= planned_requests,
            "strict_saving_feasible_at_planned_utilization": strictly_cheaper <= planned_requests}


def compute_breakeven(data: dict | None = None) -> dict:
    if data is None:
        return {"status": "NOT_MEASURED", "evidence_mode": "none",
                "missing": ["live self-host load-test measurement", "matched commercial per-request cost",
                            "matched open-weight gateway per-request cost", "explicit monthly self-host assumptions"],
                "notice": "No throughput or economic result has been invented. Simulator latency is not self-hosted model throughput."}
    if not isinstance(data, dict) or data.get("schema_version") != "breakeven-v1":
        raise ValueError("Expected schema_version=breakeven-v1")
    measurement = data.get("self_host_measurement", {})
    if not isinstance(measurement, dict):
        raise ValueError("self_host_measurement must be an object")
    if measurement.get("evidence_mode") != "live" or measurement.get("measurement_kind") != "self_hosted_load":
        raise ValueError("Only supplied live self-hosted load measurements are admissible; simulator/API latency is not capacity evidence")
    traffic_hash = _hash(measurement.get("traffic_sha256"), "measurement.traffic_sha256")
    source_hash = _hash(measurement.get("source_artifact_sha256"), "measurement.source_artifact_sha256")
    hardware = _text(measurement.get("hardware"), "measurement.hardware")
    model = _text(measurement.get("model_id"), "measurement.model_id")
    measured_at = _timestamp(measurement.get("measured_at"), "measurement.measured_at")
    concurrency = _integer(measurement.get("concurrency"), "measurement.concurrency", minimum=1)
    batch_size = _integer(measurement.get("batch_size"), "measurement.batch_size", minimum=1)
    if not isinstance(measurement.get("saturation_observed"), bool):
        raise ValueError("measurement.saturation_observed must explicitly state true or false")
    totals = _measured_totals(measurement)
    assumptions = data.get("assumptions", {})
    if not isinstance(assumptions, dict):
        raise ValueError("assumptions must be an object")
    fixed = _number(assumptions.get("monthly_fixed_usd"), "assumptions.monthly_fixed_usd")
    variable = _number(assumptions.get("variable_usd_per_request"), "assumptions.variable_usd_per_request")
    hours = _number(assumptions.get("available_hours_per_month"), "assumptions.available_hours_per_month", strictly_positive=True)
    utilization = _number(assumptions.get("planned_utilization"), "assumptions.planned_utilization")
    if hours > 744 or utilization > 1:
        raise ValueError("Available monthly hours must be <=744 and utilization between 0 and 1")
    assumptions_note = _text(assumptions.get("basis"), "assumptions.basis")
    capacity = totals["completed_requests_per_second"] * hours * 3600
    planned_requests = math.floor(capacity * utilization)
    comparisons = {}
    routes = data.get("routes", {})
    if not isinstance(routes, dict):
        raise ValueError("routes must be an object")
    if set(routes) != {"commercial", "open_weight_gateway"}:
        raise ValueError("Both commercial and open_weight_gateway routes must be supplied")
    for route_name, route in routes.items():
        if not isinstance(route, dict):
            raise ValueError(f"{route_name} must be an object")
        if route.get("evidence_mode") != "live":
            raise ValueError(f"{route_name} needs supplied live cost evidence")
        if _hash(route.get("traffic_sha256"), f"{route_name}.traffic_sha256") != traffic_hash:
            raise ValueError("Both comparison routes must use the same traffic hash as self-host measurement")
        route_hash = _hash(route.get("source_artifact_sha256"), f"{route_name}.source_artifact_sha256")
        route_model = _text(route.get("model_id"), f"{route_name}.model_id")
        measured_requests = _integer(route.get("measured_requests"), f"{route_name}.measured_requests", minimum=1)
        cost = _number(route.get("cost_usd_per_request"), f"{route_name}.cost_usd_per_request")
        cost_basis = _text(route.get("cost_basis"), f"{route_name}.cost_basis")
        comparisons[route_name] = {**compare_route(fixed_usd=fixed, variable_usd_per_request=variable,
                                                  remote_usd_per_request=cost, capacity_requests=capacity,
                                                  planned_requests=planned_requests),
                                  "model_id": route_model, "measured_requests": measured_requests,
                                  "cost_basis": cost_basis, "source_artifact_sha256": route_hash}
    return {"status": "COMPUTED_FROM_SUPPLIED_EVIDENCE", "evidence_mode": "projection_from_supplied_live_measurements",
            "traffic_sha256": traffic_hash, "self_host_measurement": {**totals, "hardware": hardware,
             "model_id": model, "measured_at": measured_at.isoformat(), "source_artifact_sha256": source_hash,
             "concurrency": concurrency, "batch_size": batch_size,
             "saturation_observed": measurement["saturation_observed"]},
            "assumptions": {"monthly_fixed_usd": fixed, "variable_usd_per_request": variable,
                            "available_hours_per_month": hours, "planned_utilization": utilization, "basis": assumptions_note},
            "projected_capacity_requests_per_month": math.floor(capacity),
            "planned_requests_per_month": planned_requests, "comparisons": comparisons,
            "limitations": ["The caller supplies provenance; the script cannot independently establish that evidence was measured live.",
                            "Monthly capacity extrapolates the observed completed-request rate; it is not a month-long measurement or an SLA.",
                            "If saturation was not observed, this is observed-load capacity, not maximum hardware throughput.",
                            "Traffic, quality, failure rate, hardware, batching, and concurrency must be comparable before an economic recommendation.",
                            "Fixed and variable costs are explicit assumptions; account for GPU, hosting, electricity, operations, idle time, and redundancy without double counting."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Explicit live measurements and financial assumptions")
    parser.add_argument("--out", type=Path, help="Optional output artifact; no file is written by default")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text("utf-8-sig")) if args.input else None
        result = compute_breakeven(data)
        if args.input:
            result["input_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result = {"status": "REJECTED_INPUT", "error": str(exc), "results": None}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "REJECTED_INPUT":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

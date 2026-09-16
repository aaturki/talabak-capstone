"""Explicitly enabled, provenance-bound evaluation of the real application.

Importing this module and calling preflight never reads credentials or calls a
provider. Simulator and test-transport results never become live evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate import dataset_audit, evaluate, file_hash, read_jsonl, summarize
from scripts.calibrate import digest

LIVE_MODES = {"live_commercial", "live_open_weight"}
ALIASES = ("primary", "open_weight")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitized_config(config: dict) -> dict:
    """Allowlist configuration metadata; never copy credential values or URL queries."""
    result = {"routes": {}, "fallbacks": copy.deepcopy(config.get("fallbacks", {})),
              "settings": copy.deepcopy(config.get("settings", {}))}
    pipeline = config.get("pipeline", {})
    result["pipeline"] = {"stable_context": copy.deepcopy(pipeline.get("stable_context", False)),
                          "prompt_versions": copy.deepcopy(pipeline.get("prompt_versions", {}))}
    result["settings"] = {k: v for k, v in result["settings"].items() if k in
                          {"max_attempts", "base_delay_s", "max_delay_s", "timeout_s",
                           "max_output_tokens", "max_input_tokens", "budget"}}
    for alias, route in config.get("routes", {}).items():
        clean = {k: copy.deepcopy(route[k]) for k in
                 ("provider", "model", "evidence_mode", "capabilities", "tariff",
                  "temperature", "max_input_tokens", "max_output_tokens", "deployment",
                  "simulation_tariff", "extra_body") if k in route}
        parsed = urlsplit(str(route.get("base_url", "")))
        hostname = parsed.hostname or ""
        try:
            port = f":{parsed.port}" if parsed.port else ""
        except ValueError:
            port = ""
        clean["base_url"] = urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))
        clean["auth"] = {k: route.get("auth", {}).get(k) for k in ("type", "name")}
        result["routes"][alias] = clean
    return result


def source_provenance(config: dict) -> dict:
    files = {}
    for folder in ("talabak", "scripts", "prompts", "data", "config"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                files[path.relative_to(ROOT).as_posix()] = file_hash(path)
    clean = sanitized_config(config)
    return {"source_files_sha256": files, "source_manifest_sha256": digest(files),
            "configuration": clean, "configuration_sha256": digest(clean),
            "fixture_sha256": file_hash(ROOT / "data/store.v1.json"),
            "golden_file_sha256": file_hash(ROOT / "data/golden.v1.jsonl")}


def _comparison_config(config: dict, max_calls: int = 2000) -> dict:
    if isinstance(max_calls, bool) or not isinstance(max_calls, int) or not 1 <= max_calls <= 10000:
        raise ValueError("max_calls must be an integer from 1 to 10000")
    selected = set(ALIASES)
    result = copy.deepcopy(config)
    result["routes"] = {key: value for key, value in result.get("routes", {}).items() if key in selected}
    # A controlled comparison cannot quietly substitute a fallback model.
    result["fallbacks"] = {key: [] for key in selected}
    budget = result.setdefault("settings", {}).setdefault("budget", {})
    configured = budget.get("max_calls")
    if configured is not None and (isinstance(configured, bool) or not isinstance(configured, int) or configured < 1):
        raise ValueError("Invalid configured call budget")
    budget["max_calls"] = min(max_calls, configured) if configured is not None else max_calls
    return result


def preflight(config: dict) -> dict:
    """Configuration-only readiness, with no environment inspection or SDK creation."""
    missing, issues, warnings, routes = [], [], [], {}
    if not isinstance(config, dict):
        return {"status": "NOT_CONFIGURED", "missing": ["configuration"], "issues": [], "warnings": [],
                "credentials_checked": False, "network_calls": 0}
    if not isinstance(config.get("routes", {}), dict) or any(
            not isinstance(route, dict) for route in config.get("routes", {}).values()):
        return {"status": "NOT_CONFIGURED", "missing": [], "issues": ["routes_must_be_a_mapping"], "warnings": [],
                "credentials_checked": False, "network_calls": 0}
    for alias, expected in (("primary", "live_commercial"), ("open_weight", "live_open_weight")):
        route = config.get("routes", {}).get(alias, {})
        for key in ("base_url", "model", "evidence_mode", "auth", "capabilities"):
            if not route.get(key):
                missing.append(f"routes.{alias}.{key}")
        if route.get("evidence_mode") != expected:
            issues.append(f"{alias}_requires_{expected}")
        caps = route.get("capabilities") if isinstance(route.get("capabilities"), dict) else {}
        auth = route.get("auth") if isinstance(route.get("auth"), dict) else {}
        for capability in ("json_schema", "tools"):
            if caps.get(capability) is not True:
                issues.append(f"{alias}_requires_{capability}")
        # schema_with_tools false is served with tool-only turns; the wire pattern is disclosed.
        wire_pattern = "tools_only" if caps.get("schema_with_tools") is False else "schema_with_tools"
        if alias == "open_weight":
            deployment = route.get("deployment")
            if deployment not in {"hosted", "self_hosted"}:
                missing.append(f"routes.{alias}.deployment")
            elif deployment != "hosted":
                # The break-even input requires a hosted comparison; this cannot be patched after the run.
                warnings.append("open_weight_deployment_is_not_hosted_so_breakeven_input_will_be_rejected")
        routes[alias] = {"evidence_mode": route.get("evidence_mode"), "model": route.get("model"),
                         "capabilities": caps, "wire_pattern": wire_pattern, "deployment": route.get("deployment"),
                         "credential_source": auth.get("type"), "credential_name": auth.get("name")}
    validation = None
    if not missing and not issues:
        try:
            from talabak.llm import preflight_config
            validation = preflight_config(_comparison_config(config), allow_live=True)
        except (ValueError, TypeError, KeyError, ImportError, AttributeError) as exc:
            # Boundary errors are deliberately safe; no provider request has happened.
            issues.append(f"boundary_configuration_invalid:{type(exc).__name__}")
    return {"status": "READY_FOR_EXPLICIT_ENABLE" if not missing and not issues else "NOT_CONFIGURED",
            "missing": missing, "issues": issues, "warnings": warnings, "routes": routes, "boundary": validation,
            "comparison_fallbacks_enabled": False,
            "credentials_checked": False, "network_calls": 0,
            "notice": "Readiness validates configuration, not credentials, endpoint availability, or provider capability."}


def safe_artifact(value):
    from talabak.guards import mask_pii
    if isinstance(value, str):
        return mask_pii(value)
    if isinstance(value, list):
        return [safe_artifact(x) for x in value]
    if isinstance(value, dict):
        return {k: safe_artifact(v) for k, v in value.items()
                if k.lower() not in {"api_key", "authorization", "secret", "password", "token"}}
    return value


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")


def wire_metrics(events: list[dict]) -> dict:
    """Meter each wire attempt once, including invalid responses and HTTP errors.

    A transport/HTTP failure has unknown chargeable usage, not zero tokens.
    The returned-answer meter in evaluate remains a separate diagnostic.
    """
    import math
    attempts = {event["wire_call"]: event for event in events if "wire_call" in event}
    meters = [event.get("usage", {}) for event in attempts.values()]
    response_meters = [event.get("usage", {}) for event in attempts.values()
                       if event.get("event") in {"model_response", "model_success"}]
    totals, coverage = {}, {}
    for key in ("input_tokens", "output_tokens", "cached_tokens", "cost_usd", "simulated_cost_usd",
                "estimated_cost_usd", "estimated_cost_upper_bound_usd"):
        values = [meter.get(key) for meter in meters]
        known = [x for x in values if isinstance(x, (int, float)) and not isinstance(x, bool)
                 and math.isfinite(x) and x >= 0]
        totals[key] = sum(known) if len(known) == len(values) else None
        coverage[key] = {"known": len(known), "unknown": len(values)-len(known), "known_total": sum(known)}
    # Cache share over responses whose usage is known: one retried or errored attempt
    # (unknown usage) must not erase the measurement, only narrow its coverage.
    paired = [(m["input_tokens"], m["cached_tokens"]) for m in response_meters
              if isinstance(m.get("input_tokens"), int) and isinstance(m.get("cached_tokens"), int)]
    known_inputs = sum(inputs for inputs, _ in paired)
    cache_fraction = {"provider_cache_fraction_known_responses": (sum(cached for _, cached in paired) / known_inputs) if known_inputs else None,
                      "responses_with_known_cache_usage": len(paired),
                      "attempts_with_unknown_usage": len(meters) - len(paired)}
    return {"wire_calls": len(attempts), "received_responses": len(response_meters),
            "accepted_responses": sum(bool(e.get("accepted")) for e in attempts.values()),
            "error_attempts": sum(e.get("event") == "model_error" for e in attempts.values()),
            "invalid_responses": sum(e.get("event") == "model_response" for e in attempts.values()),
            **totals, "usage_coverage": coverage, **cache_fraction,
            "requested_models": sorted({m["requested_model"] for m in meters if m.get("requested_model")}),
            "served_models": sorted({m["served_model"] for m in response_meters if m.get("served_model")}),
            "served_model_unknown_responses": sum(not m.get("served_model_known") for m in response_meters),
            "fallback_used": any(e.get("fallback_used", False) for e in attempts.values()),
            "cost_basis": "Configured tariff estimates for every wire attempt; actual invoice cost is unverified."}


def _row_provenance(row: dict, *, run_id: str, alias: str, provenance_hash: str) -> dict:
    row = safe_artifact(row)
    usage = [u for result in row["results"] for u in result.get("usage", [])]
    modes = sorted({u.get("evidence_mode", "unknown") for u in usage})
    row.update(run_id=run_id, alias=alias, evaluation_id=f"{alias}:{row['id']}",
               provenance_sha256=provenance_hash,
               evidence_kind="deterministic_no_model_call" if not usage else
               "live" if modes and set(modes) <= LIVE_MODES else "non_live_or_unknown",
               observed_model_modes=modes,
               requested_models=sorted({u.get("requested_model") or "unknown" for u in usage}),
               served_models=sorted({u.get("served_model") or u.get("model") or "unknown" for u in usage}))
    row["answer_sha256"] = hashlib.sha256(row["answer"].encode()).hexdigest()
    row["review_item_sha256"] = digest({k: row[k] for k in
        ("run_id", "alias", "id", "language", "question", "answer", "evidence", "provenance_sha256")})
    return row


def run_live_comparison(config: dict, *, enabled: bool = False, out: Path | None = None,
                        max_cases: int | None = None, max_calls: int = 2000,
                        client_factory=None, secret_loader=None) -> dict:
    """Run identical cases through Application for both routes, with a wire-call cap.

    A test factory may inject a local transport. Such results are TEST_ONLY.
    max_cases creates a labelled pilot; only the default runs the full golden set.
    """
    out = Path(out or ROOT / "artifacts/live")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
    run_dir = out / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "run_id": run_id, "created_at_utc": utc_now(),
                "run_dir": str(run_dir.resolve()), "manifest_path": str((run_dir / "manifest.json").resolve()),
                "status": "NOT_RUN", "enabled": enabled is True, "aliases": {}, "files": {},
                "preflight": preflight(config), "limits":
                "Authored golden data are exploratory, not an independent blind benchmark. "
                "Provider token tariffs are estimates; no invoice is verified. "
                "This compares the full deterministic/model/tool application, not only model routing."}
    if enabled is not True:
        manifest["reason"] = "Explicit enable is required; no credentials read and no client created"
        _write_json(run_dir / "manifest.json", manifest)
        return manifest
    if manifest["preflight"]["status"] != "READY_FOR_EXPLICIT_ENABLE":
        manifest["status"] = "NOT_CONFIGURED"
        _write_json(run_dir / "manifest.json", manifest)
        return manifest
    cases = read_jsonl(ROOT / "data/golden.v1.jsonl")
    full_audit = dataset_audit(cases)
    if max_cases is not None and (isinstance(max_cases, bool) or not isinstance(max_cases, int)
                                  or not 1 <= max_cases <= len(cases)):
        raise ValueError("max_cases must select a nonempty bounded prefix of the golden set")
    selected = cases if max_cases is None else cases[:max_cases]
    runtime_config = _comparison_config(config, max_calls)
    provenance = source_provenance(runtime_config)
    provenance.update(selected_dataset_sha256=digest(selected), selected_case_ids=[c["id"] for c in selected],
                      traffic_sha256=hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                      full_dataset_audit=full_audit, selected_dataset_audit=dataset_audit(selected, enforce_minimum=False),
                      cache_enabled=False, pilot=len(selected) != len(cases))
    provenance_hash = digest(provenance)
    manifest.update(provenance=provenance, provenance_sha256=provenance_hash)
    if client_factory is None:
        from talabak.llm import SDKClient
        client_factory = SDKClient
    client = None
    try:
        client = client_factory(config=runtime_config, allow_live=True, secret_loader=secret_loader)
        for alias in ALIASES:
            rows = []
            event_start = len(getattr(client, "events", []))
            stop_reason = None
            for case in selected:
                budget = getattr(client, "budget_status", {})
                if budget.get("stopped") or (budget.get("max_calls") is not None and
                                               budget.get("wire_calls", 0) >= budget["max_calls"]):
                    stop_reason = "call_or_cost_budget_exhausted"
                    break
                result_rows, _ = evaluate(client, cases=[case], alias=alias,
                                          cache_enabled=False, enforce_minimum=False)
                rows.extend(_row_provenance(row, run_id=run_id, alias=alias,
                                            provenance_hash=provenance_hash) for row in result_rows)
                recent = getattr(client, "events", [])[event_start:]
                if any(e.get("event") == "model_error" and e.get("status") in {400, 401, 403, 404, 422}
                       for e in recent):
                    stop_reason = "non_retryable_provider_rejection"
                    break
            summary = summarize(rows)
            summary.update(alias=alias, expected_cases=len(selected), completed_cases=len(rows),
                           coverage_complete=len(rows) == len(selected), stop_reason=stop_reason,
                           dataset_sha256=provenance["selected_dataset_sha256"], provenance_sha256=provenance_hash,
                           observed_evidence_kinds=sorted({r["evidence_kind"] for r in rows}),
                           operational_error_cases=[r["id"] for r in rows if any(x["status"] == "error" for x in r["results"])],
                           wire_meter=wire_metrics(getattr(client, "events", [])[event_start:]))
            path = run_dir / f"{alias}.results.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), "utf-8")
            manifest["files"][path.name] = file_hash(path)
            summary_path = run_dir / f"{alias}.summary.json"
            _write_json(summary_path, summary)
            manifest["files"][summary_path.name] = file_hash(summary_path)
            manifest["aliases"][alias] = summary
        events = safe_artifact(getattr(client, "events", []))
        _write_json(run_dir / "wire_events.json", {"events": events,
                    "budget": safe_artifact(getattr(client, "budget_status", {}))})
        manifest["files"]["wire_events.json"] = file_hash(run_dir / "wire_events.json")
        manifest["budget"] = safe_artifact(getattr(client, "budget_status", {}))
        manifest["wire_meter"] = wire_metrics(events)
        summaries = list(manifest["aliases"].values())
        nonlive = any("non_live_or_unknown" in x["observed_evidence_kinds"] for x in summaries)
        incomplete = any(not x["coverage_complete"] for x in summaries)
        errors = any(x["operational_error_cases"] for x in summaries)
        budget_hit = manifest["budget"].get("stopped") or any(
            x.get("stop_reason") == "call_or_cost_budget_exhausted" for x in summaries)
        manifest["status"] = ("PARTIAL_BUDGET" if incomplete and budget_hit else
                              "PARTIAL" if incomplete else "TEST_ONLY" if nonlive else
                              "LIVE_ERRORS" if errors else "PILOT_COMPLETE" if provenance["pilot"] else "LIVE_COMPLETE")
        manifest["deterministic_verdict"] = "PASS" if not incomplete and all(
            x["overall"]["passed"] == x["overall"]["n"] for x in summaries) else "FAIL_OR_INCOMPLETE"
        integrity = {}
        for alias, expected_mode in (("primary", "live_commercial"), ("open_weight", "live_open_weight")):
            events_for_alias = [event for event in events if event.get("alias") == alias]
            observed = {event.get("evidence_mode", "unknown") for event in events_for_alias}
            meter = manifest["aliases"][alias]["wire_meter"]
            integrity[alias] = {"expected_evidence_mode": expected_mode,
                                "observed_evidence_modes": sorted(observed),
                                "served_models": meter["served_models"],
                                "mode_matches": observed == {expected_mode},
                                "single_known_served_model": len(meter["served_models"]) == 1 and
                                    meter["served_model_unknown_responses"] == 0}
        served = [set(integrity[alias]["served_models"]) for alias in ALIASES]
        distinct = bool(all(served)) and not (served[0] & served[1])
        manifest["comparison_integrity"] = {"routes": integrity, "distinct_served_models": distinct,
                                             "fallbacks_disabled": True,
                                             "class_attribution": "Model classes are explicitly supplied by the operator; endpoint reporting is not independently attested."}
        manifest["live_model_evidence"] = not nonlive and distinct and all(
            value["mode_matches"] and value["single_known_served_model"] for value in integrity.values())
        if manifest["status"] in {"LIVE_COMPLETE", "PILOT_COMPLETE"} and not manifest["live_model_evidence"]:
            manifest["status"] = "MODEL_IDENTITY_UNVERIFIED"
    except Exception as exc:
        manifest.update(status="ERROR", error_type=type(exc).__name__,
                        reason="Live evaluation could not complete; provider bodies and credentials are not persisted")
    finally:
        if client is not None:
            client.close()
    manifest["finished_at_utc"] = utc_now()
    _write_json(run_dir / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--enable-live", action="store_true")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/live")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--max-calls", type=int, default=2000)
    args = parser.parse_args()
    result = run_live_comparison(json.loads(args.config.read_text("utf-8")), enabled=args.enable_live,
                                 out=args.out, max_cases=args.max_cases, max_calls=args.max_calls)
    print(json.dumps({k: result[k] for k in ("status", "manifest_path", "preflight")}, ensure_ascii=False, indent=2))
    if args.enable_live and result["status"] not in {"LIVE_COMPLETE", "PILOT_COMPLETE"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Implementation tests only: no provider, key, human label, or live measurement.

The real SDK, Application, domain tools and evaluator run against an in-process
deterministic HTTP fixture. Injected transports must remain TEST_ONLY evidence.
"""
from __future__ import annotations

import csv
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts.evaluate import read_jsonl
from scripts.live_evaluate import preflight, run_live_comparison, sanitized_config, wire_metrics
from scripts.prepare_review import judge_review, prepare_review, score_review
from talabak.llm import ModelReply, SDKClient
from talabak.mock_gateway import app, reset_state


def test_configuration():
    caps = {"json_schema": True, "tools": True, "parallel_tool_calls": True,
            "temperature": True, "token_parameter": "max_tokens"}
    routes = {}
    for alias, model, mode in (("primary", "talabak-course-primary", "live_commercial"),
                                ("open_weight", "talabak-course-open-weight-sim", "live_open_weight"),
                                ("judge", "talabak-course-judge", "live_commercial")):
        routes[alias] = {"provider": "openai_compatible", "base_url": "http://127.0.0.1:9876/v1",
                         "model": model, "evidence_mode": mode, "auth": {"type": "none"},
                         "capabilities": caps.copy(), "tariff": {"input_usd_per_million": 1,
                             "cached_input_usd_per_million": .25, "output_usd_per_million": 4,
                             "as_of": "2026-09-16", "source": "Synthetic implementation fixture; not a price quote"}}
        if alias == "open_weight":
            # The comparison profile must declare the deployment before any spend.
            routes[alias]["deployment"] = "hosted"
    return {"routes": routes, "fallbacks": {name: [] for name in routes},
            "settings": {"max_attempts": 1, "max_output_tokens": 768, "budget": {"max_calls": 2000}}}


# This is a helper, not an independently collected measurement/test result.
test_configuration.__test__ = False


def fixture_factory(*, omit_usage=False, captured=None, first_error=None):
    gateway = TestClient(app)
    count = 0
    def respond(request):
        nonlocal count
        count += 1
        payload = json.loads(request.content)
        if captured is not None:
            captured.append(payload)
        if first_error and count == 1:
            return httpx.Response(first_error, json={"error": {"message": "synthetic transport fixture"}})
        response = gateway.post("/v1/chat/completions", json=payload)
        body = response.json()
        if omit_usage:
            body.pop("usage", None)
        return httpx.Response(response.status_code, json=body)
    def factory(**kwargs):
        return SDKClient(**kwargs, transport=httpx.MockTransport(respond), sleep=lambda _: None)
    return factory


@pytest.fixture(scope="module")
def comparison(tmp_path_factory):
    reset_state()
    return run_live_comparison(test_configuration(), enabled=True, out=tmp_path_factory.mktemp("comparison"),
                               client_factory=fixture_factory())


def test_preflight_and_disabled_comparison_never_create_client_or_read_secrets(tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Readiness attempted credential access or client construction")
    config = test_configuration()
    for route in config["routes"].values():
        route["auth"] = {"type": "secret", "name": "SELECTED_LATER"}
    report = preflight(config)
    assert report["status"] == "READY_FOR_EXPLICIT_ENABLE"
    assert report["credentials_checked"] is False
    assert report["boundary"]["required_secrets"][0]["name"] == "SELECTED_LATER"
    result = run_live_comparison(config, out=tmp_path, secret_loader=forbidden, client_factory=forbidden)
    assert result["status"] == "NOT_RUN" and not result["aliases"]
    assert preflight({})["status"] == "NOT_CONFIGURED"
    assert preflight({"routes": []})["status"] == "NOT_CONFIGURED"


def test_config_sanitization_excludes_values_and_query_credentials():
    config = test_configuration()
    route = config["routes"]["primary"]
    route.update(api_key="DO_NOT_PERSIST", base_url="https://user:DO_NOT_PERSIST@example.test/v1?key=DO_NOT_PERSIST")
    assert "DO_NOT_PERSIST" not in json.dumps(sanitized_config(config))
    assert preflight(config)["status"] == "NOT_CONFIGURED"


def test_provenance_distinguishes_runtime_shared_context_configuration():
    config = test_configuration()
    without_context = sanitized_config(config)
    config["pipeline"] = {"stable_context": True, "unrelated_secret": "DO_NOT_PERSIST"}
    with_context = sanitized_config(config)
    assert without_context["pipeline"] == {"stable_context": False, "prompt_versions": {}}
    assert with_context["pipeline"] == {"stable_context": True, "prompt_versions": {}}
    assert "DO_NOT_PERSIST" not in json.dumps(with_context)


def test_full_same_application_comparison_cannot_promote_test_transport_to_live(comparison):
    from pathlib import Path
    assert comparison["status"] == "TEST_ONLY"
    assert comparison["live_model_evidence"] is False
    assert comparison["deterministic_verdict"] == "PASS"
    run_dir = Path(comparison["run_dir"])
    rows_by_route = {name: read_jsonl(run_dir / f"{name}.results.jsonl") for name in ("primary", "open_weight")}
    assert [x["id"] for x in rows_by_route["primary"]] == [x["id"] for x in rows_by_route["open_weight"]]
    for alias, rows in rows_by_route.items():
        assert len(rows) == 144
        summary = comparison["aliases"][alias]
        assert len(summary["slices"]["intent"]) == 6
        assert sum(x["language"] == "ar" for x in rows) > len(rows) / 2
        assert any(x["actual_action_count"] == 1 and x["intent"] == "return" and x["actual_tools"] for x in rows)
        assert any(x["evidence_kind"] == "deterministic_no_model_call" for x in rows)
        assert summary["wire_meter"]["wire_calls"] > 200
        assert summary["wire_meter"]["cost_usd"] is None
        assert summary["wire_meter"]["estimated_cost_usd"] > 0
        assert summary["wire_meter"]["usage_coverage"]["input_tokens"]["unknown"] == 0
    assert comparison["provenance"]["cache_enabled"] is False
    assert all(not value for value in comparison["provenance"]["configuration"]["fallbacks"].values())
    assert any("tokenizer_cache" in key for key in comparison["provenance"]["source_files_sha256"])
    assert comparison["provenance"]["source_manifest_sha256"]
    assert "source_bundle_sha256" not in comparison["provenance"]


def test_budget_limits_real_pipeline_wire_calls_and_marks_partial(tmp_path):
    report = run_live_comparison(test_configuration(), enabled=True, out=tmp_path, max_calls=2,
                                 client_factory=fixture_factory())
    assert report["status"] == "PARTIAL_BUDGET"
    assert report["budget"]["wire_calls"] == 2
    assert report["aliases"]["open_weight"]["completed_cases"] == 0
    assert report["deterministic_verdict"] == "FAIL_OR_INCOMPLETE"


def test_missing_provider_usage_remains_unknown(tmp_path):
    report = run_live_comparison(test_configuration(), enabled=True, out=tmp_path, max_cases=1,
                                 client_factory=fixture_factory(omit_usage=True))
    assert report["status"] == "TEST_ONLY"
    for alias in ("primary", "open_weight"):
        overall = report["aliases"][alias]["overall"]
        assert overall["input_tokens"] is None and overall["estimated_cost_usd"] is None
        assert overall["usage_coverage"]["input_tokens"]["unknown"] > 0
        assert report["aliases"][alias]["wire_meter"]["cached_tokens"] is None


def test_retry_cost_unknown_is_visible_even_when_final_answer_succeeds(tmp_path):
    config = test_configuration()
    config["settings"]["max_attempts"] = 2
    report = run_live_comparison(config, enabled=True, out=tmp_path, max_cases=1,
                                 client_factory=fixture_factory(first_error=429))
    assert report["status"] == "TEST_ONLY"
    primary = report["aliases"]["primary"]
    assert primary["overall"]["passed"] == 1
    assert primary["wire_meter"]["error_attempts"] == 1
    assert primary["wire_meter"]["input_tokens"] is None
    assert primary["wire_meter"]["usage_coverage"]["input_tokens"]["known_total"] > 0
    assert primary["wire_meter"]["served_model_unknown_responses"] == 0
    assert report["comparison_integrity"]["routes"]["primary"]["single_known_served_model"] is True


def test_meter_counts_invalid_response_usage_and_deduplicates_wire_event():
    meter = {"input_tokens": 20, "output_tokens": 3, "cached_tokens": 0,
             "estimated_cost_usd": .00004, "cost_usd": None}
    event = {"event": "model_response", "wire_call": 1, "usage": meter, "accepted": False}
    report = wire_metrics([event, event.copy()])
    assert report["wire_calls"] == 1 and report["invalid_responses"] == 1
    assert report["input_tokens"] == 20 and report["cost_usd"] is None
    assert report["served_model_unknown_responses"] == 1


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_review_exports_blank_labels_and_refuses_simulator_as_live(comparison, tmp_path):
    from pathlib import Path
    with pytest.raises(ValueError, match="verified live"):
        prepare_review(Path(comparison["run_dir"]), tmp_path / "live")
    directory = tmp_path / "implementation_test_review"
    review = prepare_review(Path(comparison["run_dir"]), directory, allow_non_live=True)
    rows = read_csv(directory / "human.csv")
    assert review["rows"] == 40 and review["labels_filled"] == 0
    assert review["coverage"]["duplicate_outputs_collapsed"] > 100
    assert review["coverage"]["unique_answers"] + review["coverage"]["duplicate_outputs_collapsed"] == 288
    assert all(row[k] == "" for row in rows for k in ("human_label", "rater_id", "annotated_at", "rationale"))
    assert all("model" not in row and "alias" not in row for row in rows)
    assert len(review["coverage"]["strata"]["intent"]) == 6
    calibration = score_review(directory, directory / "human.csv")
    assert calibration["status"] == "NOT_CALIBRATED" and calibration["minimum_pairs"] == 40
    assert judge_review(directory)["status"] == "NOT_RUN"


def test_judge_scores_actual_answers_blindly_and_test_labels_cannot_calibrate(comparison, tmp_path):
    from pathlib import Path
    directory = tmp_path / "implementation_test_review"
    prepare_review(Path(comparison["run_dir"]), directory, limit=6, allow_non_live=True)
    captured = []
    with fixture_factory(captured=captured)(config=test_configuration(), allow_live=True) as client:
        report = judge_review(directory, client, enabled=True, max_calls=6)
    assert report["status"] == "TEST_ONLY" and report["scored_items"] == 6
    items = read_jsonl(directory / "items.jsonl")
    for payload, item in zip(captured, items):
        prompt = json.loads(payload["messages"][1]["content"])
        assert set(prompt) == {"question", "trusted_evidence", "candidate_answer"}
        assert prompt["candidate_answer"] == item["answer"]
        assert prompt["trusted_evidence"] == item["evidence"]
    rows = read_csv(directory / "human.csv")
    predictions = read_jsonl(directory / "predictions.jsonl")
    # Deliberately synthetic labels exercise validation only; never project evidence.
    for row, prediction in zip(rows, predictions):
        row.update(human_label=prediction["label"], rater_id="SYNTHETIC_TEST_NOT_A_HUMAN",
                   annotated_at="2026-09-16T00:00:00Z", rationale="Implementation fixture only")
    write_csv(directory / "synthetic_test_labels.csv", rows)
    score = score_review(directory, directory / "synthetic_test_labels.csv", min_pairs=2)
    assert score["n"] == 6 and score["agreement"] == 1
    assert score["status"] == "NOT_CALIBRATED" and not score["ready_for_quality_gate"]
    assert "source_answers_are_not_verified_live" in score["gate_reasons"]
    assert "judge_is_not_verified_live" in score["gate_reasons"]
    # Even unchanged human labels cannot be reused with modified judge output.
    with (directory / "predictions.jsonl").open("a", encoding="utf-8") as file:
        file.write("\n")
    with pytest.raises(ValueError, match="provenance mismatch"):
        score_review(directory, directory / "synthetic_test_labels.csv", min_pairs=2)


@pytest.mark.parametrize("identity_case", ["unknown", "mixed", "unknown_received_response", "known_after_retry"])
def test_judge_readiness_requires_one_known_model_for_every_response(comparison, tmp_path, identity_case):
    """Synthetic protocol fixtures test live-label gates, never collect live evidence."""
    from pathlib import Path

    class SyntheticJudge:
        # Explicitly fake boundary output exercises identity gates independent of
        # SDK test-transport classification, which is tested end-to-end above.
        config = test_configuration()
        max_attempts = 1

        def __init__(self):
            self.events = []
            self.calls = 0

        def complete(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1 and identity_case in {"unknown_received_response", "known_after_retry"}:
                self.events.append({"wire_call": 1, "event": "model_response" if
                    identity_case == "unknown_received_response" else "model_error", "accepted": False,
                    "status": 429 if identity_case == "known_after_retry" else None,
                    "evidence_mode": "live_commercial", "usage": {"served_model_known": False}})
            model = (None if identity_case == "unknown" else "synthetic-judge-two" if
                     identity_case == "mixed" and self.calls == 2 else "synthetic-judge-one")
            usage = {"served_model": model, "served_model_known": model is not None,
                     "requested_model": "synthetic-judge-route", "evidence_mode": "live_commercial"}
            self.events.append({"wire_call": len(self.events)+1, "event": "model_success", "accepted": True,
                                "evidence_mode": "live_commercial", "usage": usage})
            value = {"label": "PASS" if self.calls == 1 else "FAIL", "reason": "Synthetic implementation fixture"}
            return ModelReply(json.dumps(value), [], usage, model or "unreported", "live_commercial")

    directory = tmp_path / "synthetic_identity_gate_test"
    prepare_review(Path(comparison["run_dir"]), directory, limit=2, allow_non_live=True)
    judged = judge_review(directory, SyntheticJudge(), enabled=True, max_calls=4)
    expected_known = identity_case == "known_after_retry"
    assert judged["judge_identity"]["single_known_served_model"] is expected_known
    assert judged["status"] == ("JUDGE_SCORED" if expected_known else "JUDGE_IDENTITY_UNVERIFIED")
    if expected_known:
        assert judged["wire_meter"]["estimated_cost_usd"] is None
        assert judged["wire_meter"]["error_attempts"] == 1
        assert judged["wire_meter"]["served_model_unknown_responses"] == 0
    rows = read_csv(directory / "human.csv")
    for index, row in enumerate(rows):
        row.update(human_label="PASS" if index == 0 else "FAIL", rater_id="SYNTHETIC_TEST_NOT_A_HUMAN",
                   annotated_at="2026-09-16T00:00:00Z", rationale="Implementation fixture only")
    write_csv(directory / "synthetic_test_labels.csv", rows)
    scored = score_review(directory, directory / "synthetic_test_labels.csv", min_pairs=2)
    assert scored["agreement"] == 1 and scored["cohen_kappa"] == 1
    assert scored["status"] == "NOT_CALIBRATED"  # Source run remains test-only.
    assert ("judge_served_model_identity_unknown_or_mixed" in scored["gate_reasons"]) is not expected_known


@pytest.mark.parametrize("change", ["duplicate_id", "answer", "rubric", "source_result"])
def test_review_rejects_stale_or_duplicate_evidence(comparison, tmp_path, change):
    from pathlib import Path
    source = tmp_path / "run_copy"
    shutil.copytree(Path(comparison["run_dir"]), source)
    directory = tmp_path / "review"
    prepare_review(source, directory, limit=6, allow_non_live=True)
    if change == "rubric":
        with (directory / "rubric.md").open("a", encoding="utf-8") as file:
            file.write("\nChanged rubric")
    elif change == "source_result":
        with (source / "primary.results.jsonl").open("a", encoding="utf-8") as file:
            file.write("\n")
    else:
        rows = read_csv(directory / "human.csv")
        if change == "duplicate_id":
            rows.append(rows[0].copy())
        else:
            rows[0]["answer"] = "Changed candidate answer"
        write_csv(directory / "human.csv", rows)
    with pytest.raises(ValueError):
        score_review(directory, directory / "human.csv")

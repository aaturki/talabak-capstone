"""Benchmark correctness tests; synthetic fixtures are never live project evidence."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from scripts.live_benchmark import build_breakeven_input, measure_cache, measure_self_host, meter_totals
from talabak.domain import Session, Store
from talabak.llm import ModelReply
from talabak.pipeline import Application, Result


def test_disabled_benchmarks_never_construct_a_client_or_write(tmp_path):
    def forbidden(**kwargs):
        raise AssertionError("Disabled benchmark attempted to create a client")
    for function in (measure_cache, measure_self_host):
        assert function({}, out=tmp_path, client_factory=forbidden)["status"] == "NOT_RUN"
    assert list(tmp_path.iterdir()) == []


def test_meter_unknown_usage_does_not_become_free_or_uncached():
    rows = [{"input_tokens": 100, "output_tokens": 20, "cached_tokens": 80,
             "estimated_cost_usd": .001, "evidence_mode": "test_transport", "model": "fixture"},
            {"input_tokens": None, "output_tokens": None, "cached_tokens": None,
             "estimated_cost_usd": None, "evidence_mode": "test_transport", "model": "fixture"}]
    meter = meter_totals(rows)
    assert meter["model_calls"] == 2
    assert meter["input_tokens"] is None
    assert meter["estimated_cost_usd"] is None
    assert meter["provider_cache_fraction"] is None
    assert meter["actual_invoice_cost_usd"] is None
    assert meter_totals(rows[:1])["provider_cache_fraction"] == .8


def test_hosted_gateway_cannot_be_presented_as_self_host_capacity():
    config = {"routes": {"open_weight": {"evidence_mode": "live_open_weight", "deployment": "hosted"}}}
    with pytest.raises(ValueError, match="self_hosted"):
        measure_self_host(config, enabled=True)
    config["routes"]["open_weight"]["deployment"] = "self_hosted"
    with pytest.raises(ValueError, match="identify hardware"):
        measure_self_host(config, enabled=True)


def test_optional_shared_prefix_contains_public_facts_not_private_orders():
    class Capture:
        config = {}
        def complete(self, messages, **kwargs):
            self.messages = deepcopy(messages)
            return ModelReply('{"blocked":false,"reason":"allowed"}', [], {}, "fixture", "test_transport")
    capture = Capture()
    store = Store()
    try:
        app = Application(capture, store, stable_context=True)
        app.input_guard("My phone is 0501234567. What are the hours?", Result("", ""), "en")
        prefix = capture.messages[0]["content"]
        assert "PUBLIC_REFERENCE_JSON" in prefix and "AVAILABLE_TOOL_CONTRACTS_JSON" in prefix
        assert '"policy"' in prefix and '"catalog"' in prefix
        assert '"customer_id"' not in prefix and '"orders"' not in prefix
        assert "ORD-1001" not in prefix
        assert "0501234567" not in json.dumps(capture.messages)
        previous_hash = app.prompt_version
        app.prompts["context"] += "\nA reviewed public clarification."
        app.refresh_prompt_version()
        assert app.prompt_version != previous_hash
    finally:
        store.close()


def test_shared_prefix_does_not_enable_itself_by_default():
    class Client:
        config = {}
    store = Store()
    try:
        app = Application(Client(), store)
        assert not app.stable_context
        assert "context" not in app.prompts
    finally:
        store.close()


def test_complete_cache_experiment_keeps_simulator_out_of_live_evidence(tmp_path):
    from talabak.llm import DEFAULT_CONFIG, SDKClient
    from talabak.mock_gateway import running_gateway
    with running_gateway() as url:
        config = json.loads(DEFAULT_CONFIG.read_text("utf-8"))
        for route in config["routes"].values():
            route["base_url"] = url
        def simulator_only(config, **kwargs):
            return SDKClient(config=config)
        report = measure_cache(config, enabled=True, out=tmp_path, client_factory=simulator_only)
    assert report["status"] == "NOT_LIVE_EVIDENCE"
    assert len(report["steps"]) == 4
    assert all(step["golden_overall"]["n"] == 144 for step in report["steps"])
    assert all(step["all_quality_checks_passed"] for step in report["steps"])
    assert report["steps"][0]["meter"]["response_cache_hits"] == 0
    assert report["steps"][1]["meter"]["response_cache_hits"] == 0
    assert report["steps"][2]["meter"]["response_cache_hits"] > 0
    assert report["estimated_cost_reduction"] is None
    assert (tmp_path / "semantic_cache/golden/results.jsonl").exists()


def test_economics_binding_rejects_unrun_or_changed_evidence(tmp_path):
    from scripts.evaluate import file_hash
    load, comparison = tmp_path / "load", tmp_path / "comparison"
    load.mkdir()
    comparison.mkdir()
    measured = {"status": "NOT_RUN"}
    (load / "measurement.json").write_text(json.dumps(measured), "utf-8")
    (comparison / "manifest.json").write_text("{}", "utf-8")
    with pytest.raises(ValueError, match="completed live"):
        build_breakeven_input(load, comparison, {})
    # Synthetic metadata checks provenance validation only; no model is run.
    measured.update(status="MEASURED", evidence_mode="live", repeats=1,
                    traffic_sha256="a" * 64, fixture_sha256="b" * 64,
                    source_artifact_sha256="c" * 64)
    (load / "measurement.json").write_text(json.dumps(measured), "utf-8")
    manifest = {"status": "LIVE_COMPLETE", "live_model_evidence": True,
                "provenance": {"pilot": False, "traffic_sha256": "a" * 64, "fixture_sha256": "b" * 64}}
    (comparison / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    (load / "requests.json").write_text("[]", "utf-8")
    with pytest.raises(ValueError, match="changed after measurement"):
        build_breakeven_input(load, comparison, {})
    manifest["provenance"]["traffic_sha256"] = "d" * 64
    (comparison / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="traffic must match"):
        build_breakeven_input(load, comparison, {})
    manifest["provenance"]["traffic_sha256"] = measured["traffic_sha256"]
    measured["source_artifact_sha256"] = file_hash(load / "requests.json")
    measured["provenance"] = {"source_files_sha256": {"application.py": "a" * 64},
                              "configuration": {"pipeline": {"stable_context": False}}}
    manifest["provenance"].update(source_files_sha256={"application.py": "b" * 64},
        configuration={"pipeline": {"stable_context": True}, "routes": {"open_weight": {"deployment": "hosted"}}})
    (load / "measurement.json").write_text(json.dumps(measured), "utf-8")
    (comparison / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="Application source differs"):
        build_breakeven_input(load, comparison, {})
    manifest["provenance"]["source_files_sha256"] = measured["provenance"]["source_files_sha256"]
    (comparison / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="pipeline settings differ"):
        build_breakeven_input(load, comparison, {})
    manifest["provenance"]["configuration"]["pipeline"] = {"stable_context": False}
    manifest["provenance"]["configuration"]["routes"]["open_weight"]["deployment"] = "self_hosted"
    (comparison / "manifest.json").write_text(json.dumps(manifest), "utf-8")
    with pytest.raises(ValueError, match="Gateway cost requires"):
        build_breakeven_input(load, comparison, {})


def test_self_host_concurrent_application_keeps_fixture_evidence_separate(tmp_path):
    from test_live_evaluation import fixture_factory, test_configuration
    from talabak.mock_gateway import reset_state
    reset_state()
    config = test_configuration()
    config["routes"]["open_weight"]["deployment"] = "self_hosted"
    config["pipeline"] = {"stable_context": True}
    report = measure_self_host(
        config, enabled=True, out=tmp_path, concurrency=3,
        deployment_confirmed=True,
        hardware={"description": "Synthetic transport", "runtime": "TestClient", "model_revision": "fixture"},
        client_factory=fixture_factory(),
    )
    assert report["status"] == "NOT_LIVE_EVIDENCE"
    assert report["meter"]["evidence_modes"] == ["test_transport"]
    assert report["totals"]["attempted_requests"] == 144
    assert report["totals"]["completed_requests"] == 144
    assert report["totals"]["quality_passed_requests"] == 144
    assert report["totals"]["completed_requests_per_second"] == pytest.approx(144 / report["totals"]["elapsed_seconds"])
    assert report["provenance"]["configuration"]["pipeline"]["stable_context"] is True
    assert report["saturation_observed"] is False
    assert (tmp_path / "requests.json").is_file()

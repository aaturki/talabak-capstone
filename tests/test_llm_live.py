"""Live-readiness contracts over MockTransport; no external requests or real keys."""
from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from talabak.llm import DEFAULT_CONFIG, ModelError, SDKClient, preflight_config

SCHEMA = {"title": "TestAnswer", "type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"], "additionalProperties": False}
TOOLS = [{"type": "function", "function": {"name": "lookup_order", "description": "Read only", "strict": True,
          "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}}]


def live_config():
    return {"settings": {"max_attempts": 2, "max_output_tokens": 100, "base_delay_s": 0, "max_delay_s": 0},
            "routes": {"primary": {"provider": "openai_compatible", "base_url": "https://provider.invalid/v1",
                "model": "configured-test-model", "evidence_mode": "live_commercial",
                "auth": {"type": "secret", "name": "TEST_PROVIDER_KEY"},
                "capabilities": {"json_schema": True, "tools": True, "schema_with_tools": True,
                    "parallel_tool_calls": True, "temperature": False, "token_parameter": "max_completion_tokens"},
                "temperature": None, "max_input_tokens": 4096,
                "tariff": {"input_usd_per_million": 2, "cached_input_usd_per_million": 0.5, "output_usd_per_million": 8}}},
            "fallbacks": {"primary": []}}


def wire(*, usage=True, model="provider-served-test-revision", finish="stop", content='{"message":"ok"}', calls=None):
    result = {"id": "chatcmpl-contract", "object": "chat.completion", "created": 0, "model": model,
              "choices": [{"index": 0, "finish_reason": finish,
                           "message": {"role": "assistant", "content": content, "tool_calls": calls}}]}
    if usage:
        result["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                           "prompt_tokens_details": {"cached_tokens": 40}}
    return result


def new_client(config=None, handler=None, **kwargs):
    return SDKClient(config=config or live_config(), allow_live=True,
                     secret_loader=lambda _: "synthetic-test-secret", sleep=lambda _: None,
                     transport=httpx.MockTransport(handler or (lambda _: httpx.Response(200, json=wire()))), **kwargs)


def test_optin_gate_precedes_every_secret_lookup():
    lookups = []
    with pytest.raises(ValueError, match="allow_live"):
        SDKClient(config=live_config(), secret_loader=lambda name: lookups.append(name))
    assert not lookups


def test_pure_preflight_and_invalid_route_do_not_read_secrets():
    config = live_config()
    summary = preflight_config(config, allow_live=True)
    assert summary["required_secrets"] == [{"alias": "primary", "source": "secret", "name": "TEST_PROVIDER_KEY"}]
    lookups = []
    config["routes"]["other"] = copy.deepcopy(config["routes"]["primary"])
    config["routes"]["other"]["base_url"] = None
    with pytest.raises(ValueError):
        SDKClient(config=config, allow_live=True, secret_loader=lambda name: lookups.append(name))
    assert not lookups


def test_example_is_deliberately_unselected():
    config = json.loads(DEFAULT_CONFIG.with_name("models.live.example.json").read_text("utf-8"))
    with pytest.raises(ValueError, match="allow_live"):
        preflight_config(config)
    with pytest.raises(ValueError):
        preflight_config(config, allow_live=True)
    assert all(route["model"] is None and route["base_url"] is None for route in config["routes"].values())


def test_sdk_wire_uses_selected_token_parameter_schema_tools_and_secret():
    received = []
    def handler(request):
        received.append(request)
        return httpx.Response(200, json=wire())
    with new_client(handler=handler) as client:
        reply = client.complete([{"role": "user", "content": "safe request"}], schema=SCHEMA, tools=TOOLS)
    body = json.loads(received[0].content)
    assert body["max_completion_tokens"] == 100
    assert "max_tokens" not in body and "temperature" not in body
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["tools"] == TOOLS
    assert received[0].headers["authorization"] == "Bearer synthetic-test-secret"
    assert reply.model == "provider-served-test-revision"
    assert reply.usage["requested_model"] == "configured-test-model"
    assert reply.usage["served_model"] == "provider-served-test-revision"
    assert reply.evidence_mode == "test_transport"
    assert reply.usage["configured_evidence_mode"] == "live_commercial"


def test_explicit_trusted_developer_mapping_preserves_other_roles():
    config, received = live_config(), []
    config["routes"]["primary"]["capabilities"]["developer_role"] = False
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=wire())
    messages = [{"role": "developer", "content": "Trusted application context"}, {"role": "user", "content": "User text"}]
    with new_client(config, handler) as client:
        client.complete(messages)
    assert received[0]["messages"][0] == {"role": "system", "content": "Trusted application context"}
    assert received[0]["messages"][1] == messages[1]
    assert messages[0]["role"] == "developer"


@pytest.mark.parametrize("capability", ["json_schema", "tools", "schema_with_tools"])
def test_unsupported_required_capability_fails_without_http(capability):
    config, received = live_config(), []
    config["routes"]["primary"]["capabilities"][capability] = False
    with new_client(config, lambda r: received.append(r)) as client:
        with pytest.raises(ModelError, match="unsupported"):
            client.complete([], schema=SCHEMA, tools=TOOLS)
        assert client.budget_status["wire_calls"] == 0
    assert not received


def test_optional_unsupported_parallel_parameter_is_omitted():
    config, received = live_config(), []
    config["routes"]["primary"]["capabilities"]["parallel_tool_calls"] = False
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json=wire())
    with new_client(config, handler) as client:
        client.complete([], tools=TOOLS)
    assert "parallel_tool_calls" not in received[0]


@pytest.mark.parametrize("url", ["http://provider.invalid/v1", "https://name:secret@provider.invalid/v1",
    "https://provider.invalid/v1?api_key=secret", "https://provider.invalid/v1#fragment"])
def test_unsafe_live_urls_rejected(url):
    config = live_config()
    config["routes"]["primary"]["base_url"] = url
    with pytest.raises(ValueError):
        preflight_config(config, allow_live=True)


def test_redirect_never_forwards_selected_credential():
    received = []
    def handler(request):
        received.append(str(request.url))
        return httpx.Response(307, headers={"location": "https://different.invalid/steal"})
    with new_client(handler=handler) as client:
        with pytest.raises(ModelError):
            client.complete([])
    assert received == ["https://provider.invalid/v1/chat/completions"]


def test_mutated_sdk_endpoint_cannot_escape_exact_configured_origin():
    received = []
    with new_client(handler=lambda request: received.append(request)) as client:
        client._clients["primary"].base_url = "https://other.invalid/v1"
        with pytest.raises(ModelError):
            client.complete([])
    assert not received


def test_loopback_open_weight_requires_optin_but_no_secret():
    config = live_config()
    route = config["routes"]["primary"]
    route.update(base_url="http://127.0.0.1:9000/v1", evidence_mode="live_open_weight", auth={"type": "none"})
    lookups = []
    with SDKClient(config=config, allow_live=True, secret_loader=lambda name: lookups.append(name),
                   transport=httpx.MockTransport(lambda _: httpx.Response(200, json=wire()))) as client:
        reply = client.complete([])
    assert not lookups
    assert reply.evidence_mode == "test_transport"
    assert reply.usage["configured_evidence_mode"] == "live_open_weight"


def test_only_named_env_secret_is_used_and_ambient_sdk_headers_are_ignored(monkeypatch):
    config, received = live_config(), []
    config["routes"]["primary"]["auth"] = {"type": "env", "name": "TEST_NAMED_KEY"}
    monkeypatch.setenv("TEST_NAMED_KEY", "chosen-synthetic-secret")
    for name in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_WEBHOOK_SECRET"):
        monkeypatch.setenv(name, "ambient-must-not-be-used")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "X-Private: ambient-must-not-be-used\nAuthorization: Bearer ambient-secret")
    def handler(request):
        received.append(request)
        return httpx.Response(200, json=wire())
    with SDKClient(config=config, allow_live=True, transport=httpx.MockTransport(handler)) as client:
        client.complete([])
        assert "chosen-synthetic-secret" not in json.dumps(client.events)
    assert received[0].headers["authorization"] == "Bearer chosen-synthetic-secret"
    assert "ambient" not in str(received[0].headers)


def test_secret_loader_errors_are_redacted():
    def loader(_):
        raise RuntimeError("sensitive.person@example.com private-value")
    with pytest.raises(ValueError) as caught:
        SDKClient(config=live_config(), allow_live=True, secret_loader=loader)
    assert "private-value" not in str(caught.value) and "example.com" not in str(caught.value)


def test_live_cost_is_estimate_not_invoice():
    with new_client() as client:
        reply = client.complete([])
    assert reply.usage["cost_usd"] is None
    assert reply.usage["simulated_cost_usd"] == 0
    assert reply.usage["estimated_cost_usd"] == pytest.approx((60 * 2 + 40 * .5 + 20 * 8) / 1e6)
    assert reply.usage["usage_available"] and reply.usage["cached_tokens_known"]


@pytest.mark.parametrize("missing", ["usage", "cached", "tariff"])
def test_missing_provider_metrics_remain_unknown(missing):
    config, response = live_config(), wire()
    if missing == "usage":
        response.pop("usage")
    elif missing == "cached":
        response["usage"].pop("prompt_tokens_details")
    else:
        config["routes"]["primary"]["tariff"] = None
    with new_client(config, lambda _: httpx.Response(200, json=response)) as client:
        reply = client.complete([])
    assert reply.usage["estimated_cost_usd"] is None
    if missing == "usage":
        assert reply.usage["input_tokens"] is None and reply.usage["output_tokens"] is None
        assert not reply.usage["usage_available"]
    if missing in {"usage", "cached"}:
        assert reply.usage["cached_tokens"] is None
        assert not reply.usage["cached_tokens_known"]


def test_invalid_http_json_still_creates_response_meter_event():
    with new_client(handler=lambda _: httpx.Response(200, text="private invalid JSON", headers={"content-type": "application/json"})) as client:
        with pytest.raises(ModelError) as caught:
            client.complete([])
        assert len(client.events) == 1
        assert client.events[0]["event"] == "model_response"
        assert client.events[0]["usage"]["input_tokens"] is None
        assert "private" not in json.dumps(client.events)
        assert caught.value.usage["usage_available"] is False
        assert caught.value.usage["input_tokens"] is None


def test_invalid_tool_json_is_charged_to_estimated_ledger():
    calls = [{"id": "bad", "type": "function", "function": {"name": "lookup_order", "arguments": "invalid"}}]
    with new_client(handler=lambda _: httpx.Response(200, json=wire(calls=calls, finish="tool_calls", content=None))) as client:
        with pytest.raises(ModelError) as caught:
            client.complete([])
        assert caught.value.usage["input_tokens"] == 100
        assert client.budget_status["estimated_cost_usd"] > 0
        assert client.events[0]["event"] == "model_response"
        assert client.events[0]["usage"]["input_tokens"] == 100


def test_call_budget_counts_retries_and_stops_before_another_http_attempt():
    config, received = live_config(), []
    config["settings"]["budget"] = {"max_calls": 1}
    def handler(request):
        received.append(request)
        return httpx.Response(429, json={"error": {"message": "private provider details"}})
    with new_client(config, handler) as client:
        with pytest.raises(ModelError, match="budget") as caught:
            client.complete([])
        assert caught.value.attempts == 1
        assert client.budget_status["wire_calls"] == len(received) == 1


def test_concurrent_call_budget_is_global():
    config = live_config()
    config["settings"]["budget"] = {"max_calls": 3}
    with new_client(config) as client:
        def perform(_):
            try:
                client.complete([])
                return True
            except ModelError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(perform, range(12)))
        assert sum(outcomes) == client.budget_status["wire_calls"] == len(client.events) == 3


def test_concurrent_estimated_reservations_prevent_oversubscription():
    config, release, entered = live_config(), threading.Event(), threading.Event()
    # Each allowance is (4096*2 + 100*8)/1e6 = .008992; only one fits at once.
    config["settings"]["budget"] = {"max_estimated_cost_usd": .01}
    def handler(_):
        entered.set()
        assert release.wait(3)
        return httpx.Response(200, json=wire())
    with new_client(config, handler) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(client.complete, [])
            assert entered.wait(3)
            try:
                with pytest.raises(ModelError, match="budget"):
                    client.complete([])
                assert client.budget_status["wire_calls"] == 1
            finally:
                release.set()
            assert first.result().usage["usage_available"]
        assert client.budget_status["reserved_estimated_cost_usd"] < .01


def test_unknown_usage_stops_further_calls_under_monetary_budget():
    config = live_config()
    config["settings"]["budget"] = {"max_estimated_cost_usd": .1}
    with new_client(config, lambda _: httpx.Response(200, json=wire(usage=False))) as client:
        assert not client.complete([]).usage["usage_available"]
        assert client.budget_status["stopped"]
        with pytest.raises(ModelError, match="stopped"):
            client.complete([])
        assert client.budget_status["wire_calls"] == 1


def test_budget_cannot_be_configured_without_rates_and_allowance():
    config = live_config()
    config["settings"]["budget"] = {"max_estimated_cost_usd": 1}
    config["routes"]["primary"]["tariff"] = None
    with pytest.raises(ValueError, match="tariffs"):
        preflight_config(config, allow_live=True)


def test_live_fallback_reports_actual_served_mode_and_model():
    config = live_config()
    config["routes"]["open_weight"] = copy.deepcopy(config["routes"]["primary"])
    config["routes"]["open_weight"].update(model="configured-open-test", evidence_mode="live_open_weight")
    config["fallbacks"]["primary"] = ["open_weight"]
    def handler(request):
        model = json.loads(request.content)["model"]
        return httpx.Response(529, json={"error": {"message": "overloaded"}}) if model == "configured-test-model" else httpx.Response(200, json=wire(model="served-open-revision"))
    with new_client(config, handler) as client:
        reply = client.complete([])
    assert reply.usage["fallback_used"]
    assert reply.usage["configured_evidence_mode"] == "live_open_weight"
    assert reply.model == "served-open-revision"
    assert reply.usage["attempts"] == 3


def test_live_cannot_silently_fall_back_to_simulator():
    config = live_config()
    config["routes"]["sim"] = json.loads(DEFAULT_CONFIG.read_text("utf-8"))["routes"]["primary"]
    config["fallbacks"]["primary"] = ["sim"]
    with pytest.raises(ValueError, match="fallback chain"):
        preflight_config(config, allow_live=True)


@pytest.mark.parametrize("bad_usage", [
    {"prompt_tokens": -1, "completion_tokens": 20},
    {"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 101}},
    {"prompt_tokens": "private.person@example.com", "completion_tokens": 20},
])
def test_invalid_counts_are_not_aggregated_as_trustworthy_usage(bad_usage):
    response = wire()
    response["usage"] = bad_usage
    with new_client(handler=lambda _: httpx.Response(200, json=response)) as client:
        with pytest.raises(ModelError, match="accounting") as caught:
            client.complete([])
        assert caught.value.usage["usage_status"] == "invalid"
        assert caught.value.usage["input_tokens"] is None
        assert caught.value.usage["output_tokens"] is None
        assert caught.value.usage["cached_tokens"] is None
        assert "private.person@example.com" not in json.dumps(client.events)


def test_private_served_model_or_finish_reason_is_not_copied_into_events():
    response = wire(model="private.person@example.com", finish="secret.person@example.com")
    with new_client(handler=lambda _: httpx.Response(200, json=response)) as client:
        with pytest.raises(ModelError) as caught:
            client.complete([])
        assert caught.value.usage["served_model"] is None
        assert caught.value.usage["finish_reason"] == "unknown"
        assert "example.com" not in json.dumps(client.events)


def test_monetary_cap_blocks_before_first_attempt_if_allowance_does_not_fit():
    config, received = live_config(), []
    config["settings"]["budget"] = {"max_estimated_cost_usd": .001}
    with new_client(config, lambda request: received.append(request)) as client:
        with pytest.raises(ModelError, match="budget"):
            client.complete([])
        assert client.budget_status["wire_calls"] == 0
    assert not received

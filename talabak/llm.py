"""One SDK boundary; default remains a keyless loopback simulator.

Live routes require allow_live=True, explicit capabilities, and named secret
sources. Loading an example configuration never authorizes a live call.
"""
from __future__ import annotations

import copy
import ipaddress
import json
import math
import os
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.json"
RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}
LIVE_MODES = {"live_commercial", "live_open_weight"}
TARIFF_KEYS = ("input_usd_per_million", "cached_input_usd_per_million", "output_usd_per_million")
SIM_CAPABILITIES = {"json_schema": True, "tools": True, "schema_with_tools": True,
                    "parallel_tool_calls": True, "temperature": True,
                    "developer_role": True, "token_parameter": "max_tokens"}
MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:+-]{0,199}$")


@dataclass
class ModelReply:
    content: str | None
    tool_calls: list[dict]
    usage: dict
    model: str
    evidence_mode: str = "simulator"


@runtime_checkable
class ModelClient(Protocol):
    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 tools: list[dict] | None = None, alias: str = "primary") -> ModelReply: ...


class ModelError(RuntimeError):
    """Safe operational codes and metering, never provider body text."""
    def __init__(self, message: str, *, status: int | None = None,
                 attempts: int = 0, usage: dict | None = None):
        super().__init__(message)
        self.status, self.attempts, self.usage = status, attempts, usage or {}


def _is_loopback(hostname: str) -> bool:
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return hostname.lower() == "localhost"


def _parsed_url(url: str):
    if not isinstance(url, str) or not url or any(c.isspace() for c in url):
        raise ValueError("A selected credential-free provider URL is required")
    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        raise ValueError("Invalid provider URL") from None
    if (not parsed.hostname or parsed.scheme not in {"http", "https"}
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "%" in (parsed.hostname or "")):
        raise ValueError("Provider URL must not contain credentials, query, or fragment")
    return parsed


def require_loopback(url: str) -> None:
    try:
        parsed = _parsed_url(url)
    except ValueError:
        raise ValueError("Only credential-free loopback simulator URLs are enabled") from None
    if not _is_loopback(parsed.hostname or ""):
        raise ValueError("Only credential-free loopback simulator URLs are enabled")


def _origin(url: str):
    parsed = _parsed_url(url)
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)


def _guard_for(base_url: str, *, simulator: bool):
    origin = _origin(base_url)
    path = _parsed_url(base_url).path.rstrip("/") + "/chat/completions"
    def guard(request: httpx.Request) -> None:
        if simulator:
            require_loopback(str(request.url))
        if _origin(str(request.url)) != origin or request.url.path != path or request.method != "POST":
            raise ValueError("Request does not match the configured provider endpoint")
    return guard


def _finite(value, minimum=0):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= minimum


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _tariff(route):
    tariff = route.get("simulation_tariff" if route["evidence_mode"] == "simulator" else "tariff")
    if tariff is None:
        return None
    if not isinstance(tariff, dict):
        raise ValueError("Tariff must be a mapping or null")
    if all(tariff.get(k) is None for k in TARIFF_KEYS):
        return None
    if any(not _finite(tariff.get(k)) for k in TARIFF_KEYS):
        raise ValueError("All three tariff rates must be finite nonnegative numbers or all unset")
    if tariff["cached_input_usd_per_million"] > tariff["input_usd_per_million"]:
        raise ValueError("Cached tariff must not exceed input tariff for this budget model")
    return tariff


def preflight_config(config: dict, *, allow_live: bool = False) -> dict:
    """Pure validation: no environment/secret reads, client creation or network."""
    if (not isinstance(config, dict) or not isinstance(config.get("routes"), dict)
            or not config["routes"] or any(not isinstance(r, dict) for r in config["routes"].values())):
        raise ValueError("A nonempty routes mapping is required")
    if any(r.get("evidence_mode") in LIVE_MODES for r in config["routes"].values()) and not allow_live:
        raise ValueError("Live provider routes require explicit allow_live=True")
    settings = config.get("settings", {})
    attempts, output = settings.get("max_attempts", 2), settings.get("max_output_tokens", 768)
    if not _positive_int(attempts) or attempts > 5 or not _positive_int(output) or output > 32768:
        raise ValueError("Attempt/output budgets are outside the supported range")
    base, cap, timeout = settings.get("base_delay_s", .1), settings.get("max_delay_s", 2), settings.get("timeout_s", 10)
    if not _finite(base) or not _finite(cap) or not 0 <= base <= cap <= 30:
        raise ValueError("Invalid retry delay budget")
    if not _finite(timeout, .001) or timeout > 600:
        raise ValueError("Timeout must be finite and between 0.001 and 600 seconds")
    budget = settings.get("budget", {})
    if not isinstance(budget, dict):
        raise ValueError("Budget must be a mapping")
    calls, money = budget.get("max_calls"), budget.get("max_estimated_cost_usd")
    if calls is not None and not _positive_int(calls):
        raise ValueError("max_calls must be a positive integer or null")
    if money is not None and not _finite(money, .000000001):
        raise ValueError("Estimated cost limit must be a positive finite number or null")
    secrets, modes = [], {}
    for alias, route in config["routes"].items():
        if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", alias):
            raise ValueError("Route aliases must be short safe identifiers")
        mode = route.get("evidence_mode")
        if mode not in {"simulator", *LIVE_MODES}:
            raise ValueError("Unsupported evidence mode")
        if route.get("provider", "openai_compatible") != "openai_compatible":
            raise ValueError("This adapter requires an OpenAI-compatible chat endpoint")
        if any(key in route for key in {"api_key", "headers", "authorization", "secret"}):
            raise ValueError("Configuration must name a secret source, never contain credentials or headers")
        if mode == "simulator":
            require_loopback(route.get("base_url"))
        parsed = _parsed_url(route.get("base_url"))
        if mode in LIVE_MODES and parsed.scheme != "https" and not _is_loopback(parsed.hostname):
            raise ValueError("Remote live provider endpoints require HTTPS")
        model = route.get("model")
        if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or model.startswith("sk-"):
            raise ValueError("A selected nonsecret model identifier is required")
        caps = {**SIM_CAPABILITIES, **route.get("capabilities", {})} if mode == "simulator" else route.get("capabilities", {})
        if any(type(caps.get(key)) is not bool for key in {"json_schema", "tools", "parallel_tool_calls", "temperature"}):
            raise ValueError("Live route capabilities must be explicitly selected booleans")
        if caps.get("token_parameter") not in {"max_tokens", "max_completion_tokens"}:
            raise ValueError("Select max_tokens or max_completion_tokens for this route")
        if any(key in caps and type(caps[key]) is not bool for key in ("schema_with_tools", "developer_role")):
            raise ValueError("Optional route capabilities must be boolean")
        temperature = route.get("temperature", 0 if mode == "simulator" else None)
        if temperature is not None and (not caps["temperature"] or not _finite(temperature) or temperature > 2):
            raise ValueError("Configured temperature is unsupported or outside 0..2")
        limit = route.get("max_output_tokens", output)
        if not _positive_int(limit) or limit > (4096 if mode == "simulator" else 32768):
            raise ValueError("Route output token limit is outside the supported range")
        if route.get("max_input_tokens") is not None and not _positive_int(route["max_input_tokens"]):
            raise ValueError("max_input_tokens must be a positive integer or null")
        tariff = _tariff(route)
        if mode in LIVE_MODES:
            auth = route.get("auth", {})
            source = auth.get("type")
            if source == "none":
                if not _is_loopback(parsed.hostname) or set(auth) != {"type"}:
                    raise ValueError("Credential-free live access is limited to explicit loopback servers")
            elif source in {"env", "secret"}:
                if set(auth) != {"type", "name"} or not re.fullmatch(r"[A-Z_][A-Z0-9_]{0,99}", auth.get("name", "")):
                    raise ValueError("Authentication must name one environment or secret-store entry")
                secrets.append({"alias": alias, "source": source, "name": auth["name"]})
            else:
                raise ValueError("Live route requires an explicit named auth source")
        if money is not None and (tariff is None or not _positive_int(route.get("max_input_tokens"))):
            raise ValueError("An estimated cost cap requires complete tariffs and max_input_tokens on every route")
        modes[alias] = mode
    for alias, chain in config.get("fallbacks", {}).items():
        if not isinstance(chain, list) or alias not in modes or any(hop not in modes for hop in chain):
            raise ValueError("Fallback names must resolve to configured routes")
        if len(set([alias, *chain])) != len([alias, *chain]):
            raise ValueError("Fallback routes must not repeat")
        if any((modes[alias] == "simulator") != (modes[hop] == "simulator") for hop in chain):
            raise ValueError("Simulator and live routes cannot share a fallback chain")
    return {"status": "ready", "route_modes": modes, "required_secrets": secrets,
            "budget": {"max_calls": calls, "max_estimated_cost_usd": money}}


def _retry_after(headers):
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        number = float(value)
        return max(0., number) if math.isfinite(number) else None
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0., (stamp - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _known_count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class SDKClient:
    """Explicit provider settings, bounded retries, shared thread-safe budgets."""
    def __init__(self, config_path: str | Path = DEFAULT_CONFIG, *, config: dict | None = None,
                 allow_live: bool = False, secret_loader: Callable[[str], str | None] | None = None,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep,
                 jitter: Callable[[float, float], float] = random.uniform):
        self.config = copy.deepcopy(config if config is not None else json.loads(Path(config_path).read_text("utf-8")))
        checked = preflight_config(self.config, allow_live=allow_live)
        self._sleep, self._jitter, self._test_transport = sleep, jitter, transport is not None
        self._clients: dict[str, OpenAI] = {}
        self.events: list[dict] = []
        self._lock = threading.RLock()
        self._wire_calls = 0
        self._estimated_total = self._held_total = 0.
        self._unknown_usage = 0
        self._budget_stopped = False
        self._budget = checked["budget"]
        settings = self.config.get("settings", {})
        self.max_attempts = settings.get("max_attempts", 2)
        self.base_delay, self.max_delay = settings.get("base_delay_s", .1), settings.get("max_delay_s", 2)
        self.max_tokens = settings.get("max_output_tokens", 768)
        # All route validation precedes every named secret lookup.
        try:
            for alias, route in self.config["routes"].items():
                key = "talabak-local-simulator-not-secret"
                if route["evidence_mode"] in LIVE_MODES:
                    auth = route["auth"]
                    if auth["type"] == "none":
                        key = "talabak-loopback-no-credential"
                    else:
                        try:
                            key = os.environ.get(auth["name"]) if auth["type"] == "env" else secret_loader(auth["name"]) if secret_loader else None
                        except Exception:
                            raise ValueError("Named provider secret could not be loaded") from None
                        if not isinstance(key, str) or not key.strip() or any(c.isspace() for c in key):
                            raise ValueError("Named provider secret is unavailable or invalid")
                client = OpenAI(base_url=route["base_url"], api_key=key, admin_api_key="",
                    organization="", project="", webhook_secret="", timeout=settings.get("timeout_s", 10), max_retries=0,
                    http_client=httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                        timeout=settings.get("timeout_s", 10),
                        event_hooks={"request": [_guard_for(route["base_url"], simulator=route["evidence_mode"] == "simulator")]}))
                # Pinned SDK 2.54.0 merges OPENAI_CUSTOM_HEADERS from the environment.
                # Clear ambient headers; only the explicitly selected key authorizes.
                client._custom_headers = {}
                client.organization = client.project = None
                self._clients[alias] = client
        except Exception:
            self.close()
            raise

    @property
    def budget_status(self):
        with self._lock:
            return {"wire_calls": self._wire_calls, **self._budget,
                    "estimated_cost_usd": self._estimated_total, "reserved_estimated_cost_usd": self._held_total,
                    "unknown_usage_responses": self._unknown_usage, "stopped": self._budget_stopped}

    def close(self):
        for client in self._clients.values():
            client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _caps(self, route):
        return {**SIM_CAPABILITIES, **route.get("capabilities", {})} if route["evidence_mode"] == "simulator" else route["capabilities"]

    def _kwargs(self, route, messages, schema, tools):
        caps = self._caps(route)
        if schema is not None and not caps["json_schema"]:
            raise ModelError("Required strict JSON schema capability is unsupported")
        if tools and not caps["tools"]:
            raise ModelError("Required tool capability is unsupported")
        if tools and schema is not None and not caps.get("schema_with_tools", True):
            raise ModelError("Combining required tools and JSON schema is unsupported")
        wire_messages = copy.deepcopy(messages)
        if not caps.get("developer_role", True):
            for message in wire_messages:
                if message.get("role") == "developer":
                    message["role"] = "system"
        kwargs = {"model": route["model"], "messages": wire_messages,
                  caps["token_parameter"]: route.get("max_output_tokens", self.max_tokens)}
        temperature = route.get("temperature", 0 if route["evidence_mode"] == "simulator" else None)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if schema is not None:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": schema.get("title", "StructuredAnswer"), "strict": True, "schema": schema}}
        if tools:
            kwargs["tools"] = tools
            if caps["parallel_tool_calls"]:
                kwargs["parallel_tool_calls"] = False
        return kwargs

    def _reserve(self, route, kwargs, attempts):
        allowance = 0.
        cap = self._budget["max_estimated_cost_usd"]
        if cap is not None:
            # Conservative byte screening, not a selected provider's tokenizer.
            estimated_input = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8")) + 64 * len(kwargs["messages"]) + 128
            if estimated_input > route["max_input_tokens"]:
                raise ModelError("Request exceeds the configured input allowance", attempts=attempts)
            rates = _tariff(route)
            allowance = (route["max_input_tokens"] * rates["input_usd_per_million"]
                         + route.get("max_output_tokens", self.max_tokens) * rates["output_usd_per_million"]) / 1e6
        with self._lock:
            if self._budget_stopped:
                raise ModelError("Estimated cost budget is stopped", attempts=attempts)
            if self._budget["max_calls"] is not None and self._wire_calls >= self._budget["max_calls"]:
                raise ModelError("Model HTTP call budget exhausted", attempts=attempts)
            if cap is not None and self._held_total + allowance > cap + 1e-12:
                raise ModelError("Estimated cost budget would be exceeded", attempts=attempts)
            self._wire_calls += 1
            self._held_total += allowance
            return self._wire_calls, allowance

    def _mode(self, route):
        return "test_transport" if self._test_transport and route["evidence_mode"] in LIVE_MODES else route["evidence_mode"]

    def _meter(self, response, route, hop, hop_index, attempts, started):
        usage = getattr(response, "usage", None)
        raw_in, raw_out = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        raw_cached = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", None)
        inputs, outputs, cached = _known_count(raw_in), _known_count(raw_out), _known_count(raw_cached)
        invalid = any(raw is not None and clean is None for raw, clean in [(raw_in, inputs), (raw_out, outputs), (raw_cached, cached)])
        invalid = invalid or (inputs is not None and cached is not None and cached > inputs)
        known = inputs is not None and outputs is not None and not invalid
        if invalid:
            inputs = outputs = cached = None
        sim = route["evidence_mode"] == "simulator"
        tariff, estimate, upper = _tariff(route), None, None
        if known and tariff:
            upper = (inputs * tariff["input_usd_per_million"] + outputs * tariff["output_usd_per_million"]) / 1e6
            if cached is not None:
                estimate = ((inputs - cached) * tariff["input_usd_per_million"] + cached * tariff["cached_input_usd_per_million"] + outputs * tariff["output_usd_per_million"]) / 1e6
            elif tariff["cached_input_usd_per_million"] == tariff["input_usd_per_million"]:
                estimate = upper
        served = getattr(response, "model", None)
        served_known = isinstance(served, str) and bool(MODEL_ID.fullmatch(served)) and not served.startswith("sk-")
        return {"input_tokens": inputs, "output_tokens": outputs, "cached_tokens": cached,
                "usage_available": known, "cached_tokens_known": cached is not None and not invalid,
                "usage_status": "invalid" if invalid else "complete" if known and cached is not None else "partial" if known else "missing",
                "cost_usd": 0. if sim else None,
                "simulated_cost_usd": round(estimate, 10) if sim and estimate is not None else 0. if not sim else None,
                "estimated_cost_usd": round(estimate, 10) if not sim and estimate is not None else None,
                "estimated_cost_upper_bound_usd": round(upper, 10) if upper is not None else None,
                "cost_basis": "zero_spend_local_simulator; illustrative_tariff_separate" if sim else "configured_tariff_estimate; actual_invoice_unverified",
                "requested_model": route["model"], "served_model": served if served_known else None,
                "served_model_known": served_known, "evidence_mode": self._mode(route),
                "configured_evidence_mode": route["evidence_mode"], "attempts": attempts,
                "fallback_used": hop_index > 0, "alias": hop,
                "latency_ms": round((time.perf_counter() - started) * 1000, 3)}

    def _settle(self, meter, allowance):
        upper = meter["estimated_cost_upper_bound_usd"]
        measured = meter["estimated_cost_usd"] if meter["configured_evidence_mode"] in LIVE_MODES else meter["simulated_cost_usd"]
        with self._lock:
            if measured is not None:
                self._estimated_total += measured
            if not meter["usage_available"]:
                self._unknown_usage += 1
                if self._budget["max_estimated_cost_usd"] is not None:
                    self._budget_stopped = True
            settled = measured if measured is not None else upper
            if self._budget["max_estimated_cost_usd"] is not None and settled is not None:
                self._held_total += settled - allowance
                if self._held_total > self._budget["max_estimated_cost_usd"] + 1e-12:
                    self._budget_stopped = True

    def complete(self, messages, *, schema=None, tools=None, alias="primary"):
        if alias not in self._clients:
            raise ValueError("Unknown model alias")
        chain = [alias, *self.config.get("fallbacks", {}).get(alias, [])]
        requests = {hop: self._kwargs(self.config["routes"][hop], messages, schema, tools) for hop in chain}
        attempts, last_status, started = 0, None, time.perf_counter()
        for hop_index, hop in enumerate(chain):
            route, kwargs = self.config["routes"][hop], requests[hop]
            for attempt in range(1, self.max_attempts + 1):
                wire_call, allowance = self._reserve(route, kwargs, attempts)
                attempts += 1
                try:
                    raw = self._clients[hop].chat.completions.with_raw_response.create(**kwargs)
                except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                    status = exc.status_code if isinstance(exc, APIStatusError) else None
                    last_status = status
                    retryable = status is None or status in RETRYABLE_STATUSES
                    event = {"event": "model_error", "alias": hop, "status": status, "attempt": attempts,
                             "wire_call": wire_call, "retryable": retryable, "evidence_mode": self._mode(route)}
                    event["usage"] = self._meter(None, route, hop, hop_index, attempts, started)
                    event["usage"]["usage_status"] = "unreported_error"
                    with self._lock:
                        self.events.append(event)
                    if not retryable:
                        raise ModelError("Model request rejected", status=status, attempts=attempts) from None
                    if attempt < self.max_attempts:
                        wait = _retry_after(exc.response.headers) if isinstance(exc, APIStatusError) else None
                        if wait is None:
                            wait = self.base_delay * 2 ** (attempt - 1) * self._jitter(.5, 1.5)
                        event["delay_s"] = min(self.max_delay, wait)
                        self._sleep(event["delay_s"])
                    continue
                except Exception:
                    with self._lock:
                        self.events.append({"event": "model_error", "alias": hop, "wire_call": wire_call,
                                            "attempt": attempts, "retryable": False, "status": None,
                                            "usage": self._meter(None, route, hop, hop_index, attempts, started)})
                    raise ModelError("Model transport rejected the request", attempts=attempts) from None
                received = {"event": "model_response", "alias": hop, "attempts": attempts,
                            "wire_call": wire_call, "fallback_used": hop_index > 0, "accepted": False,
                            "evidence_mode": self._mode(route)}
                with self._lock:
                    self.events.append(received)
                try:
                    response = raw.parse()
                except Exception:
                    meter = self._meter(None, route, hop, hop_index, attempts, started)
                    self._settle(meter, allowance)
                    received["usage_status"] = meter["usage_status"]
                    received["usage"] = dict(meter)
                    raise ModelError("Model response body could not be decoded", attempts=attempts, usage=meter) from None
                meter = self._meter(response, route, hop, hop_index, attempts, started)
                self._settle(meter, allowance)
                received["usage_status"] = meter["usage_status"]
                received["usage"] = dict(meter)
                if meter["usage_status"] == "invalid":
                    raise ModelError("Invalid model token accounting", attempts=attempts, usage=meter)
                choices = getattr(response, "choices", None)
                if not isinstance(choices, list) or not choices:
                    raise ModelError("Model returned no choices", attempts=attempts, usage=meter)
                choice = choices[0]
                finish = getattr(choice, "finish_reason", None)
                meter["finish_reason"] = finish if finish in {"stop", "tool_calls", "length", "content_filter", "function_call"} else "unknown"
                received["usage"] = dict(meter)
                if meter["finish_reason"] not in {"stop", "tool_calls"}:
                    raise ModelError("Model response incomplete or refused", attempts=attempts, usage=meter)
                message = getattr(choice, "message", None)
                if message is None:
                    raise ModelError("Model response has no assistant message", attempts=attempts, usage=meter)
                calls = []
                try:
                    for call in message.tool_calls or []:
                        arguments = json.loads(call.function.arguments)
                        if not isinstance(arguments, dict):
                            raise TypeError
                        calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
                except Exception:
                    raise ModelError("Model returned invalid tool JSON object", attempts=attempts, usage=meter) from None
                with self._lock:
                    received.update(event="model_success", accepted=True)
                return ModelReply(message.content, calls, meter, meter["served_model"] or "unreported", self._mode(route))
        raise ModelError("All configured model routes unavailable", status=last_status, attempts=attempts)

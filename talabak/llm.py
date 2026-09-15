"""The only provider SDK boundary. The shipped configuration is loopback-only.

No environment credentials are read. Model IDs and tariffs below describe a
simulator, never paid provider calls. Application code depends on ModelClient.
"""
from __future__ import annotations

import ipaddress
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "models.json"
RETRYABLE_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504, 529}


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
    """Safe operational error, excluding request bodies or provider messages."""

    def __init__(self, message: str, *, status: int | None = None,
                 attempts: int = 0, usage: dict | None = None):
        super().__init__(message)
        self.status, self.attempts, self.usage = status, attempts, usage or {}


def require_loopback(url: str) -> None:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    try:
        local = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        local = hostname.lower() == "localhost"
    if (parsed.scheme not in {"http", "https"} or not local or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Only credential-free loopback simulator URLs are enabled")


def _guard_request(request: httpx.Request) -> None:
    require_loopback(str(request.url))


def _retry_after(headers: httpx.Headers) -> float | None:
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return max(0.0, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class SDKClient:
    """OpenAI SDK + bounded retry policy + explicit model-alias fallback.

    A real SDK request reaches localhost. Test transports are injectable. Changing
    to a remote provider is deliberately disabled in this authorized local build.
    """

    def __init__(self, config_path: str | Path = DEFAULT_CONFIG, *,
                 config: dict | None = None, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 jitter: Callable[[float, float], float] = random.uniform):
        self.config = config if config is not None else json.loads(Path(config_path).read_text("utf-8"))
        self._sleep, self._jitter = sleep, jitter
        self._clients: dict[str, OpenAI] = {}
        self.events: list[dict] = []
        settings = self.config.get("settings", {})
        self.max_attempts = int(settings.get("max_attempts", 2))
        self.base_delay = float(settings.get("base_delay_s", 0.1))
        self.max_delay = float(settings.get("max_delay_s", 2))
        self.max_tokens = int(settings.get("max_output_tokens", 768))
        if not 1 <= self.max_attempts <= 5 or not 1 <= self.max_tokens <= 4096:
            raise ValueError("Attempt/output budgets are outside the supported range")
        if not 0 <= self.base_delay <= self.max_delay <= 30:
            raise ValueError("Invalid retry delay budget")
        for alias, route in self.config["routes"].items():
            require_loopback(route["base_url"])
            if route.get("evidence_mode") != "simulator":
                raise ValueError("This build enables simulator routes only")
            for key in ("input_usd_per_million", "cached_input_usd_per_million", "output_usd_per_million"):
                if float(route.get("simulation_tariff", {}).get(key, 0)) < 0:
                    raise ValueError("Simulation tariffs must be nonnegative")
            self._clients[alias] = OpenAI(
                base_url=route["base_url"], api_key="talabak-local-simulator-not-secret",
                timeout=float(settings.get("timeout_s", 10)), max_retries=0,
                http_client=httpx.Client(
                    transport=transport, trust_env=False, follow_redirects=False,
                    timeout=float(settings.get("timeout_s", 10)),
                    event_hooks={"request": [_guard_request]},
                ),
            )
        for alias, chain in self.config.get("fallbacks", {}).items():
            if alias not in self._clients or any(hop not in self._clients for hop in chain):
                raise ValueError("Fallback names must resolve to configured routes")
            if len(set([alias, *chain])) != len([alias, *chain]):
                raise ValueError("Fallback routes must not repeat")

    def close(self) -> None:
        for client in self._clients.values():
            client.close()

    def __enter__(self) -> "SDKClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 tools: list[dict] | None = None, alias: str = "primary") -> ModelReply:
        if alias not in self._clients:
            raise ValueError(f"Unknown model alias: {alias}")
        chain = [alias, *self.config.get("fallbacks", {}).get(alias, [])]
        attempts, last_status = 0, None
        started = time.perf_counter()
        for hop_index, hop in enumerate(chain):
            route = self.config["routes"][hop]
            kwargs = {"model": route["model"], "messages": messages,
                      "temperature": 0, "max_tokens": self.max_tokens}
            if schema is not None:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": schema.get("title", "StructuredAnswer"), "strict": True, "schema": schema,
                }}
            if tools:
                kwargs["tools"] = tools
                kwargs["parallel_tool_calls"] = False
            for attempt in range(1, self.max_attempts + 1):
                attempts += 1
                try:
                    response = self._clients[hop].chat.completions.create(**kwargs)
                except (APIConnectionError, APITimeoutError, APIStatusError) as exc:
                    status = exc.status_code if isinstance(exc, APIStatusError) else None
                    last_status = status
                    retryable = status is None or status in RETRYABLE_STATUSES
                    event = {"event": "model_error", "alias": hop, "status": status,
                             "attempt": attempts, "retryable": retryable}
                    self.events.append(event)
                    # A 400/authentication error is a bug, not a reason to spend on a second model.
                    if not retryable:
                        raise ModelError("Model request rejected", status=status, attempts=attempts) from None
                    if attempt < self.max_attempts:
                        wait = _retry_after(exc.response.headers) if isinstance(exc, APIStatusError) else None
                        if wait is None:
                            wait = self.base_delay * 2 ** (attempt - 1) * self._jitter(0.5, 1.5)
                        event["delay_s"] = min(self.max_delay, wait)
                        self._sleep(event["delay_s"])
                    continue
                # Preserve the received generation even when local validation rejects
                # its content. One event per HTTP attempt makes meter audits possible.
                received_event = {"event": "model_response", "alias": hop, "attempts": attempts,
                                  "fallback_used": hop_index > 0, "accepted": False}
                self.events.append(received_event)
                usage = response.usage
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
                cached = int(getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0)
                if not 0 <= cached <= input_tokens or input_tokens < 0 or output_tokens < 0:
                    raise ModelError("Invalid model token accounting", attempts=attempts)
                tariff = route.get("simulation_tariff", {})
                estimate = ((input_tokens - cached) * tariff.get("input_usd_per_million", 0)
                            + cached * tariff.get("cached_input_usd_per_million", 0)
                            + output_tokens * tariff.get("output_usd_per_million", 0)) / 1_000_000
                meter = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                         "cached_tokens": cached, "cost_usd": 0.0,
                         "simulated_cost_usd": round(estimate, 10), "attempts": attempts,
                         "fallback_used": hop_index > 0, "alias": hop,
                         "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                         "cost_basis": "zero_spend_local_simulator; illustrative_tariff_separate"}
                if not response.choices:
                    raise ModelError("Model returned no choices", attempts=attempts, usage=meter)
                choice = response.choices[0]
                meter["finish_reason"] = choice.finish_reason
                if choice.finish_reason not in {"stop", "tool_calls"}:
                    raise ModelError("Model response incomplete or refused", attempts=attempts, usage=meter)
                calls = []
                for call in choice.message.tool_calls or []:
                    try:
                        arguments = json.loads(call.function.arguments)
                    except (TypeError, ValueError):
                        raise ModelError("Model returned invalid tool JSON", attempts=attempts, usage=meter) from None
                    if not isinstance(arguments, dict):
                        raise ModelError("Tool arguments must be an object", attempts=attempts, usage=meter)
                    calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})
                received_event.update(event="model_success", accepted=True)
                return ModelReply(choice.message.content, calls, meter, response.model, "simulator")
        raise ModelError("All configured simulator routes unavailable", status=last_status, attempts=attempts)

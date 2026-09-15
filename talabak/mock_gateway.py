"""Talabak Track D simulator, inspired by the course gateway wire contract.

This is new retail-specific deterministic routing code, NOT the stock Murshid
simulator or a language model. It reads no application database or golden labels.
Facts in final answers can only come from correlated tool-result messages.
Run: python -m uvicorn talabak.mock_gateway:app --host 127.0.0.1 --port 8080
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import tiktoken
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Talabak Track D deterministic simulator", version="1.0.0")
EVIDENCE_MODE = "simulator"
MODELS = ["talabak-course-primary", "talabak-course-fallback", "talabak-course-judge", "talabak-course-open-weight-sim"]
MIN_CACHEABLE_TOKENS = 1024
CACHE_TTL_S = 300.0
# This verified tokenizer vocabulary is bundled so first use needs no network.
os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).resolve().parents[1] / "config" / "tokenizer_cache"))
ENC = tiktoken.get_encoding("o200k_base")
_lock = threading.RLock()
_prefix_cache: dict[str, tuple[float, int]] = {}
_fault: dict[str, Any] = {"mode": "off"}
_stats: dict[str, Any] = {}


def reset_state() -> None:
    with _lock:
        _prefix_cache.clear()
        _fault.clear()
        _fault["mode"] = "off"
        _stats.clear()
        _stats.update(requests=0, input_tokens=0, output_tokens=0, cached_tokens=0,
                      cache_hits=0, faults_served=0, by_model={})


reset_state()


@contextmanager
def running_gateway(port: int = 0):
    """Run the simulator on loopback; port=0 selects a free port atomically.

    The yielded value is the OpenAI-compatible base URL. No subprocess/window or
    external service is involved. Used by tests and the portable notebook.
    """
    import uvicorn

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    selected_port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Local simulator failed to start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{selected_port}/v1"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize(text: str) -> str:
    value = re.sub(r"[\u064b-\u065f\u0670\u0640]", "", text).lower()
    return value.translate(str.maketrans("أإآى٠١٢٣٤٥٦٧٨٩", "اااي0123456789"))


def _extract(text: str) -> dict:
    """Transparent rules for exercising extraction; no learned language ability."""
    low = _normalize(text)
    order = re.search(r"\bORD[- ]?([0-9]{4})\b", low, re.I)
    sku = re.search(r"\bSKU-([A-Z0-9]+)\b", low, re.I)
    slot = re.search(r"\bSLOT-([0-9]{3})\b", low, re.I)
    has = lambda words: any(w in low for w in words)
    wants_policy = has(["سياس", "شروط", "كم يوم", "مدة الارجاع", "مده الارجاع", "policy", "return window"])
    if has(["موظف", "شكوي", "شكوى", "دعم بشري", "human", "support agent", "complaint", "representative"]):
        intent = "handoff"
    elif wants_policy and not order:
        intent = "faq"
    elif has(["استبد", "بدل", "exchange", "replace", "replacement"]):
        intent = "exchange"
    elif has(["ارجع", "ارجاع", "رجع", "return", "refund"]):
        intent = "return"
    elif has(["احجز", "حجز", "appointment", "book", "موعد زياره", "موعد زيارة"]) or slot:
        intent = "appointment"
    elif order or has(["وين طلب", "وين وصل", "حالة طلب", "حاله طلب", "حالة الطلب", "حاله الطلب", "طلبي", "تتبع", "order status", "track", "where is my order", "delivery"]):
        intent = "order_status"
    else:
        intent = "faq"
    recognized_faq = has(["ساع", "دوام", "مواعيد", "متجر", "منتج", "سعر", "كتالوج", "hours", "catalog", "price", "product", "store"])
    return {"intent": intent, "language": "ar" if re.search(r"[\u0600-\u06ff]", text) else "en",
            "order_id": f"ORD-{order[1]}" if order else None,
            "replacement_sku": f"SKU-{sku[1].upper()}" if sku else None,
            "slot_id": f"SLOT-{slot[1]}" if slot else None,
            "reason": text[:240] if intent in {"return", "exchange", "appointment", "handoff"} else None,
            "confidence": 0.98 if intent != "faq" or recognized_faq or wants_policy else 0.2}


def _context(messages: list[dict]) -> dict:
    for message in reversed(messages):
        if message.get("role") != "developer" or not isinstance(message.get("content"), str):
            continue
        try:
            value = json.loads(message["content"])
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("request"), dict):
            return value
    return {}


def _answer_from_tool(result: dict, language: str) -> dict:
    message = result.get("message")
    if not isinstance(message, str):
        message = "تعذر إتمام الطلب بأمان." if language == "ar" else "The request could not be completed safely."
    sources = result.get("sources", [])
    return {"message": message, "citations": [s for s in sources if isinstance(s, str)] if isinstance(sources, list) else []}


def _decide(payload: dict) -> tuple[str | None, list[dict]]:
    messages = payload.get("messages", [])
    users = [m.get("content", "") for m in messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
    # Repairs append validation feedback; continue extracting from the original input.
    user_text = users[-1] if users else ""
    if users and ("failed validation" in user_text.lower() or "validation_error" in user_text.lower()):
        user_text = users[0]
    fmt = (payload.get("response_format") or {}).get("json_schema", {})
    title = fmt.get("name", "")
    if title == "DomainRequest":
        return _dump(_extract(user_text)), []
    if title == "GuardDecision":
        low = _normalize(user_text)
        blocked = any(x in low for x in ["ignore previous", "ignore all instructions", "تجاهل التعليمات", "system prompt", "اكشف تعليمات", "bypass authorization"])
        return _dump({"blocked": blocked, "reason": "instruction_override" if blocked else "allowed"}), []
    if title not in {"Answer", ""}:
        raise ValueError(f"Unsupported simulator schema: {title}")
    context = _context(messages)
    domain = context.get("request") or _extract(user_text)
    language = domain.get("language", "ar")
    names = {t.get("function", {}).get("name") for t in payload.get("tools") or []}
    # Only accept tool results with an earlier assistant tool-call correlation ID.
    called = {c.get("id"): c.get("function", {}).get("name")
              for m in messages if m.get("role") == "assistant"
              for c in m.get("tool_calls") or []}
    results = []
    for message in messages:
        if message.get("role") != "tool" or message.get("tool_call_id") not in called:
            continue
        try:
            body = json.loads(message.get("content") or "{}")
        except ValueError:
            body = {"error": "invalid_tool_result"}
        if not isinstance(body, dict):
            body = {"error": "invalid_tool_result"}
        results.append((called[message["tool_call_id"]], body))
    if results and (results[-1][1].get("error") or results[-1][1].get("ok") is False):
        return _dump(_answer_from_tool(results[-1][1], language)), []
    intent = domain.get("intent", "faq")
    already = [name for name, _ in results]
    name, args = None, {}
    if intent == "order_status" and "lookup_order" not in already:
        name, args = "lookup_order", {"order_id": domain.get("order_id")}
    elif intent in {"return", "exchange"}:
        if "lookup_order" not in already:
            name, args = "lookup_order", {"order_id": domain.get("order_id")}
        elif "create_return_or_exchange" not in already:
            name, args = "create_return_or_exchange", {
                "kind": intent, "order_id": domain.get("order_id"),
                "replacement_sku": domain.get("replacement_sku"),
                "reason": domain.get("reason") or ("طلب العميل" if language == "ar" else "Customer request"),
            }
    elif intent == "appointment" and "book_store_appointment" not in already:
        name, args = "book_store_appointment", {"slot_id": domain.get("slot_id"), "reason": domain.get("reason") or "Store visit"}
    elif intent == "handoff" and "handoff_to_support" not in already:
        name, args = "handoff_to_support", {"reason": domain.get("reason") or "Customer requested support"}
    elif intent == "faq" and "lookup_catalog" not in already:
        name, args = "lookup_catalog", {"query": user_text}
    if name and name in names:
        return None, [{"name": name, "arguments": args}]
    if results:
        return _dump(_answer_from_tool(results[-1][1], language)), []
    return _dump({"message": "أحتاج معلومات موثوقة من أدوات المتجر." if language == "ar" else "I need verified store tool information.", "citations": []}), []


def _fault_for(model: str) -> dict:
    with _lock:
        if _fault.get("until", float("inf")) <= time.monotonic():
            _fault.clear()
            _fault["mode"] = "off"
        if _fault.get("model") not in {None, model}:
            return {"mode": "off"}
        if _fault.get("remaining") == 0:
            return {"mode": "off"}
        value = dict(_fault)
        if value.get("mode") != "off":
            _stats["faults_served"] += 1
            if _fault.get("remaining") is not None:
                _fault["remaining"] -= 1
        return value


def _usage(payload: dict, output: str) -> dict:
    model = payload["model"]
    systems = [m for m in payload["messages"] if m.get("role") == "system"]
    prefix = _dump({"messages": systems, "tools": payload.get("tools", []), "response_format": payload.get("response_format")})
    dynamic = _dump([m for m in payload["messages"] if m.get("role") != "system"])
    prefix_tokens = len(ENC.encode(prefix))
    input_tokens = prefix_tokens + len(ENC.encode(dynamic))
    output_tokens = len(ENC.encode(output))
    cached, now = 0, time.monotonic()
    with _lock:
        if prefix_tokens >= MIN_CACHEABLE_TOKENS:
            key = model + ":" + hashlib.sha256(prefix.encode()).hexdigest()
            previous = _prefix_cache.get(key)
            if previous and now - previous[0] < CACHE_TTL_S:
                cached = previous[1]
            _prefix_cache[key] = (now, prefix_tokens)
        for key, amount in {"input_tokens": input_tokens, "output_tokens": output_tokens,
                            "cached_tokens": cached, "cache_hits": int(cached > 0)}.items():
            _stats[key] += amount
    return {"prompt_tokens": input_tokens, "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "prompt_tokens_details": {"cached_tokens": cached}}


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "evidence_mode": EVIDENCE_MODE, "implementation": "talabak-track-d-extension",
            "models": MODELS, "tokenizer": "o200k_base", "minimum_cache_tokens": MIN_CACHEABLE_TOKENS}


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": m, "object": "model", "created": 0,
            "owned_by": "talabak-local-simulator"} for m in MODELS]}


@app.get("/admin/stats")
def stats() -> dict:
    with _lock:
        return {**_stats, "by_model": dict(_stats["by_model"]), "fault": dict(_fault),
                "prefixes_cached": len(_prefix_cache), "evidence_mode": EVIDENCE_MODE}


@app.post("/admin/reset")
def reset() -> dict:
    reset_state()
    return {"reset": True, "evidence_mode": EVIDENCE_MODE}


@app.post("/admin/fault")
def fault(payload: dict):
    valid = {"off", "rate_limit", "overload", "server_error", "timeout", "invalid_json", "invalid_tool", "tool_loop"}
    if payload.get("mode", "off") not in valid:
        return JSONResponse(status_code=400, content={"error": {"message": "Unknown fault mode"}})
    with _lock:
        _fault.clear()
        _fault.update(mode=payload.get("mode", "off"), model=payload.get("model"),
                      until=time.monotonic() + min(max(float(payload.get("seconds", 60)), 0), 600),
                      retry_after=max(0, float(payload.get("retry_after", 0.1))),
                      remaining=payload.get("count"))
    return {"fault": dict(_fault)}


@app.post("/v1/chat/completions")
async def complete(request: Request):
    payload = await request.json()
    if payload.get("model") not in MODELS:
        return JSONResponse(status_code=404, content={"error": {"message": "Unknown simulator model"}})
    if not isinstance(payload.get("messages"), list) or not 1 <= payload.get("max_tokens", 0) <= 4096:
        return JSONResponse(status_code=400, content={"error": {"message": "messages and bounded max_tokens required"}})
    if payload.get("stream"):
        return JSONResponse(status_code=400, content={"error": {"message": "Streaming is not implemented by the retail extension"}})
    model = payload["model"]
    with _lock:
        _stats["requests"] += 1
        _stats["by_model"][model] = _stats["by_model"].get(model, 0) + 1
    current_fault = _fault_for(model)
    mode = current_fault.get("mode")
    statuses = {"rate_limit": 429, "overload": 529, "server_error": 503, "timeout": 504}
    if mode in statuses:
        return JSONResponse(status_code=statuses[mode], headers={"Retry-After": str(current_fault["retry_after"])} if mode == "rate_limit" else None,
                            content={"error": {"message": "Injected simulator fault", "type": "simulated_error"}})
    try:
        content, calls = _decide(payload)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": {"message": str(exc)}})
    if mode == "invalid_json":
        content, calls = '{"invalid":', []
    if mode == "invalid_tool":
        content, calls = None, [{"name": "delete_all_orders", "arguments": {}}]
    if mode == "tool_loop":
        content, calls = None, [{"name": "lookup_catalog", "arguments": {"query": "hours"}}]
    stable = hashlib.sha256(_dump(payload).encode()).hexdigest()
    wire_calls = [{"id": f"call_{stable[:12]}_{i}", "type": "function",
                   "function": {"name": c["name"], "arguments": _dump(c["arguments"])}}
                  for i, c in enumerate(calls)]
    finish = "tool_calls" if calls else "stop"
    if content and len(ENC.encode(content)) > payload["max_tokens"]:
        content, finish = ENC.decode(ENC.encode(content)[:payload["max_tokens"]]), "length"
    usage = _usage(payload, content or _dump(wire_calls))
    return {"id": "chatcmpl-" + stable[:16], "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "finish_reason": finish,
            "message": {"role": "assistant", "content": content, "tool_calls": wire_calls or None}}],
            "usage": usage, "evidence_mode": EVIDENCE_MODE}

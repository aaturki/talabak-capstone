from __future__ import annotations
import copy
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from pydantic import ValidationError
from .domain import ROOT, Session, Store, canonical, digest, is_confirmation
from .guards import detect_language, injection_reason, mask_pii, normalize, output_reason, prompt_leak, prompt_shingles, refusal
from .schemas import Answer, DomainRequest, GuardDecision, TOOL_TYPES, tool_definitions, wire_schema
from .llm import ModelClient, ModelError
from .cache import SemanticCache

SAFE_ERROR_CODES = {"structured_validation_exhausted", "ungrounded_model_answer", "too_many_tool_calls", "terminal_session",
                    "unknown_tool", "tool_intent_mismatch", "tool_order_mismatch", "tool_action_mismatch", "tool_loop_limit",
                    "unsafe_structured_output", "pending_action_invalid"}
# Served versions; config/models.json restates them explicitly (pipeline.prompt_versions).
PROMPT_DEFAULTS = {"router": "v1", "workflow": "v1", "guard": "v3", "repair": "v2"}
EXPECTED_ACTION_TOOL = {"order_status": "lookup_order", "return": "create_return_or_exchange", "exchange": "create_return_or_exchange",
                        "appointment": "book_store_appointment", "handoff": "handoff_to_support"}


@dataclass
class Result:
    status: str
    message: str
    citations: list[str] = field(default_factory=list)
    request: dict | None = None
    trace: list[dict] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)
    evidence_mode: str = "simulator"
    latency_ms: float = 0.0

    def to_dict(self):
        return asdict(self)


def _fold(text):
    return re.sub(r"\s+", " ", normalize(text)).strip(" .!?؟،,;؛").casefold()


class Application:
    STAGES = ("input_guard", "route_extract", "tools", "output_guard", "deliver")

    def __init__(self, client: ModelClient, store=None, *, cache_enabled=True, alias="primary", max_tool_rounds=4, audit_path=None,
                 semantic_enabled=False, stable_context=None, prompt_versions=None):
        self.client = client
        self.store = store or Store()
        self.alias = alias
        self.max_tool_rounds = max_tool_rounds
        self.cache_enabled = cache_enabled
        self.cache = {}
        self.semantic = SemanticCache(threshold=1.0) if semantic_enabled else None
        self.audit_path = Path(audit_path) if audit_path else None
        settings = getattr(client, "config", {}).get("pipeline", {})
        versions = {**PROMPT_DEFAULTS, **settings.get("prompt_versions", {}), **(prompt_versions or {})}
        if set(versions) != set(PROMPT_DEFAULTS) or any(not re.fullmatch(r"v[0-9]+", str(v)) for v in versions.values()):
            raise ValueError("prompt_versions must map router/workflow/guard/repair to a version such as v1")
        # The served prompt files are explicit configuration, never "the newest file on disk".
        self.prompt_files = {name: f"{name}.{versions[name]}.md" for name in PROMPT_DEFAULTS}
        self.prompts = {name: (ROOT / "prompts" / file).read_text(encoding="utf-8") for name, file in self.prompt_files.items()}
        self.stable_context = settings.get("stable_context", False) if stable_context is None else stable_context
        if self.stable_context:
            self.prompt_files["context"] = "context.v1.md"
            self.prompts["context"] = (ROOT / "prompts/context.v1.md").read_text(encoding="utf-8")
        # Any 8-word run of a served prompt appearing outbound is a system-prompt leak,
        # whether or not the model kept the canary sentence.
        self.prompt_shingles = set().union(*(prompt_shingles(text) for text in self.prompts.values()))
        capabilities = getattr(client, "capabilities", None)
        route_capabilities = capabilities(alias) if callable(capabilities) else {}
        # Providers that cannot combine a response schema with tools get tool-only
        # turns; the delivered message is the tool result in both wire patterns.
        self.schema_with_tools = bool(route_capabilities.get("schema_with_tools", True))
        self.refresh_prompt_version()
        self.canary = "TALABAK_CANARY_7C84F52A"

    def refresh_prompt_version(self):
        self.prompt_version = digest({"prompts": self.prompts, "tools": tool_definitions()})
        self.prompt_shingles = set().union(*(prompt_shingles(text) for text in self.prompts.values()))

    def _outbound_reason(self, text):
        """Canary, PII, relayed instructions, internal data, then served-prompt text."""
        reason = output_reason(text, self.canary)
        if reason is None and prompt_leak(text, self.prompt_shingles):
            return "system_prompt_leak"
        return reason

    def _call(self, messages, result, *, stage, schema=None, tools=None, alias=None):
        if self.stable_context:
            # Only public, versioned store facts enter the shared prefix. Orders,
            # customers, sessions and tool receipts remain outside it.
            public = {key: self.store.data[key] for key in ("policy", "hours", "catalog")}
            prefix = self.prompts["context"] + "\nPUBLIC_REFERENCE_JSON\n" + canonical(public)
            prefix += "\nAVAILABLE_TOOL_CONTRACTS_JSON\n" + canonical(tool_definitions())
            messages = [{"role": "system", "content": prefix}, *messages]
        started = time.perf_counter()
        try:
            reply = self.client.complete(messages, schema=schema, tools=tools, alias=alias or self.alias)
        except ModelError as exc:
            result.usage.append({**exc.usage, "stage": stage, "attempts": exc.attempts, "status": "failed", "prompt_version": self.prompt_version,
                                 "usage_available": bool(exc.usage), "latency_ms": (time.perf_counter() - started) * 1000})
            raise
        usage = {**reply.usage, "stage": stage, "model": reply.model, "evidence_mode": reply.evidence_mode,
                 "prompt_version": self.prompt_version, "latency_ms": (time.perf_counter() - started) * 1000}
        result.usage.append(usage)
        result.evidence_mode = reply.evidence_mode
        return reply

    @staticmethod
    def _repair_feedback(exc):
        """Error categories, located paths and validator messages; never the rejected values."""
        if not isinstance(exc, ValidationError):
            return [{"type": "invalid_json", "loc": [], "msg": "The response is not a JSON object"}]
        feedback = []
        for error in exc.errors(include_url=False, include_input=False, include_context=False):
            location = [str(part) for part in error.get("loc", ()) if isinstance(part, (str, int))]
            feedback.append({"type": error["type"], "loc": location, "msg": mask_pii(str(error.get("msg", "")))[:200]})
        return feedback

    def _structured(self, messages, model, result, *, stage):
        messages = copy.deepcopy(messages)
        schema = wire_schema(model)
        for attempt in range(3):
            reply = self._call(messages, result, stage=stage, schema=schema)
            try:
                parsed = model.model_validate_json(reply.content or "")
                result.trace.append({"stage": stage, "event": "schema_valid", "attempt": attempt + 1, "schema": model.__name__})
                return parsed
            except (ValidationError, ValueError) as exc:
                errors = self._repair_feedback(exc)
                result.trace.append({"stage": stage, "event": "schema_rejected", "attempt": attempt + 1, "errors": errors})
                messages.append({"role": "developer", "content": self.prompts["repair"] + "\n" + canonical({"schema": model.__name__, "errors": errors})})
        raise ValueError("structured_validation_exhausted")

    def input_guard(self, text, result, language):
        reason = injection_reason(text)
        safe = mask_pii(text)
        result.trace.append({"stage": "input_guard", "layer": "deterministic", "blocked": bool(reason), "reason": reason})
        if reason:
            return safe, True
        result.trace.append({"stage": "input_guard", "layer": "pii", "redacted": safe != normalize(text), "normalized": normalize(text) != text})
        verdict = self._structured([{"role": "system", "content": self.prompts["guard"]}, {"role": "user", "content": safe}], GuardDecision, result, stage="input_guard")
        result.trace.append({"stage": "input_guard", "layer": "classifier", "blocked": verdict.blocked})
        return safe, verdict.blocked

    def route_extract(self, text, result):
        return self._structured([{"role": "system", "content": self.prompts["router"]}, {"role": "user", "content": text}], DomainRequest, result, stage="route_extract")

    def _cache_key(self, text, session):
        return digest({"text": text, **self._cache_scope(session)})

    def _cache_scope(self, session):
        return {"customer": session.customer_id, "session": session.session_id,
                "can_act": session.can_act, "language": session.language, "pending": session.pending,
                "prompts": self.prompt_version, "alias": self.alias,
                "model_config": getattr(self.client, "config", None), "data": self.store.fingerprint()}

    def _apply_tool_result(self, data, result):
        codes = {"ok": "answer", "not_authorized": "denied", "policy_denied": "denied", "unavailable": "denied"}
        result.status = codes.get(data["code"], data["code"])
        result.message = data["message"]
        result.citations = data["sources"]

    def _blocked_tool_result(self, reason, session, result):
        result.trace.append({"stage": "output_guard", "blocked": True, "reason": reason, "source": "tool"})
        result.status, result.message = "blocked", refusal(session.language)
        result.citations = []
        session.pending = None
        session.confirmed_digest = None

    @staticmethod
    def _grounding_match(content, data, structured):
        """How closely the model's final text followed the tool result it was told to relay."""
        text, citations = content or "", None
        if structured:
            try:
                final = Answer.model_validate_json(content or "")
                text, citations = final.message, final.citations
            except (ValidationError, ValueError):
                return "unparseable"
        if text == data["message"] and (citations is None or citations == data["sources"]):
            return "verbatim"
        if _fold(text) == _fold(data["message"]) or _fold(data["message"]) in _fold(text):
            return "normalized"
        return "divergent"

    def tools(self, request, session, result):
        structured = self.schema_with_tools
        pattern = "schema_with_tools" if structured else "tools_only"
        messages = [{"role": "system", "content": self.prompts["workflow"]},
                    {"role": "developer", "content": canonical({"request": request.model_dump()})}]
        last_data = None
        for iteration in range(1, self.max_tool_rounds + 1):
            reply = self._call(messages, result, stage="tools", schema=wire_schema(Answer) if structured else None, tools=tool_definitions())
            result.usage[-1]["wire_pattern"] = pattern
            if not reply.tool_calls:
                if last_data is None:
                    raise ValueError("ungrounded_model_answer")
                # The delivered text is the tool result itself; the model's copy is
                # measured, not trusted, so paraphrase cannot turn a fact into an error.
                result.trace.append({"stage": "tools", "event": "grounding", "iteration": iteration, "delivered": "tool_result",
                                     "match": self._grounding_match(reply.content, last_data, structured)})
                self._apply_tool_result(last_data, result)
                return
            if len(reply.tool_calls) > 4:
                raise ValueError("too_many_tool_calls")
            messages.append({"role": "assistant", "content": reply.content,
                             "tool_calls": [{"id": t["id"], "type": "function", "function": {"name": t["name"], "arguments": canonical(t["arguments"])}} for t in reply.tool_calls]})
            for call in reply.tool_calls:
                if session.terminal:
                    raise ValueError("terminal_session")
                name = call["name"]
                event = {"stage": "tools", "name": name if name in TOOL_TYPES else "unknown", "risk": TOOL_TYPES[name][1] if name in TOOL_TYPES else "unknown",
                         "iteration": iteration, "code": "rejected", "executed": False}
                result.trace.append(event)
                if name not in TOOL_TYPES:
                    raise ValueError("unknown_tool")
                model, risk = TOOL_TYPES[name]
                args = model.model_validate(call["arguments"])
                if self._outbound_reason(canonical(args.model_dump())):
                    raise ValueError("unsafe_structured_output")
                # The parsed request is intent context; tool args cannot change the proposed action.
                if risk in ("side_effect", "terminal") and name != EXPECTED_ACTION_TOOL.get(request.intent):
                    raise ValueError("tool_intent_mismatch")
                if hasattr(args, "order_id") and args.order_id != request.order_id:
                    raise ValueError("tool_order_mismatch")
                if name == "create_return_or_exchange" and (args.kind != request.intent or args.replacement_sku != request.replacement_sku or args.reason != request.reason):
                    raise ValueError("tool_action_mismatch")
                if name == "book_store_appointment" and (args.slot_id != request.slot_id or args.reason != request.reason):
                    raise ValueError("tool_action_mismatch")
                data = getattr(self.store, name)(session, **args.model_dump())
                event.update({"code": data["code"], "executed": True, "authorized": data["code"] != "not_authorized", "args_sha256": digest(args.model_dump())})
                reason = self._outbound_reason(canonical(data))
                if reason:
                    self._blocked_tool_result(reason, session, result)
                    return
                last_data = data
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": canonical(data)})
                if risk != "read_only":
                    # A side-effect or terminal result decides the turn. The model cannot
                    # continue past a pending confirmation, a receipt or a denial and
                    # report something else instead.
                    self._apply_tool_result(data, result)
                    return
        raise ValueError("tool_loop_limit")

    def _execute_confirmed(self, session, restored, result):
        """Confirmation runs the digest-bound pending action; no model is asked to re-issue it."""
        action = (session.pending or {}).get("action") or {}
        name = action.get("tool")
        if name not in TOOL_TYPES or TOOL_TYPES[name][1] != "side_effect":
            raise ValueError("pending_action_invalid")
        model, risk = TOOL_TYPES[name]
        args = model.model_validate(action["args"])
        result.request = DomainRequest.model_validate(restored).model_dump()
        result.trace.append({"stage": "input_guard", "layer": "deterministic", "blocked": False, "reason": None, "confirmation_word": True})
        result.trace.append({"stage": "route_extract", "event": "pending_action_restored", "tool": name})
        event = {"stage": "tools", "name": name, "risk": risk, "iteration": 0, "code": "rejected", "executed": False, "source": "confirmed_pending_action"}
        result.trace.append(event)
        data = getattr(self.store, name)(session, **args.model_dump())
        event.update({"code": data["code"], "executed": True, "authorized": data["code"] != "not_authorized", "args_sha256": digest(args.model_dump())})
        reason = self._outbound_reason(canonical(data))
        if reason:
            self._blocked_tool_result(reason, session, result)
            return
        self._apply_tool_result(data, result)

    def output_guard(self, result, session):
        reason = self._outbound_reason(canonical({"message": result.message, "citations": result.citations, "request": result.request}))
        result.trace.append({"stage": "output_guard", "blocked": bool(reason), "reason": reason})
        if reason:
            result.status, result.message, result.citations = "blocked", refusal(session.language), []
            result.request = None
            session.pending = None
            session.confirmed_digest = None

    def deliver(self, result, *, start=None):
        result.trace.append({"stage": "deliver", "status": result.status})
        if start is not None:
            result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    def handle_message(self, text: str, session: Session):
        start = time.perf_counter()
        result = Result(status="error", message="")
        language = detect_language(text)
        session.language = language
        if session.pending and is_confirmation(text):
            language = session.pending["request"]["language"]
            session.language = language
        restored = session.begin_turn(text)
        try:
            if session.terminal:
                result.status = "handoff"
                result.message = "انتهى المسار الآلي لهذه الجلسة." if language == "ar" else "Automation has ended for this session."
            elif restored is not None:
                self._execute_confirmed(session, restored, result)
            else:
                safe = mask_pii(text)
                key = self._cache_key(safe, session)
                early = self.cache.get(key) if self.cache_enabled and not injection_reason(text) else None
                if early:
                    result.trace.append({"stage": "input_guard", "layer": "deterministic", "blocked": False})
                    result.trace.append({"stage": "input_guard", "layer": "cached_classifier", "blocked": False})
                    blocked = False
                else:
                    safe, blocked = self.input_guard(text, result, language)
                if blocked:
                    session.pending = None
                    result.status, result.message = "blocked", refusal(language)
                elif is_confirmation(safe):
                    result.status = "clarification"
                    result.message = "لا يوجد إجراء ينتظر التأكيد. اذكر الطلب الذي تريد تنفيذه أولًا." if language == "ar" else "No action is awaiting confirmation. Describe the action first."
                else:
                    key = self._cache_key(safe, session)
                    cached = early or (self.semantic.get(safe, self._cache_scope(session)) if self.cache_enabled and self.semantic else None)
                    if cached:
                        result.status, result.message, result.citations, result.request = copy.deepcopy(cached)
                        result.trace.append({"stage": "route_extract", "event": "response_cache_hit", "tier": "exact" if early else "semantic"})
                    else:
                        request = self.route_extract(safe, result)
                        if self._outbound_reason(canonical(request.model_dump())):
                            raise ValueError("unsafe_structured_output")
                        result.request = request.model_dump()
                        session.last_request = result.request
                        missing = []
                        if request.intent in {"order_status", "return", "exchange"} and not request.order_id: missing.append("order_id")
                        if request.intent in {"return", "exchange", "appointment"} and not request.reason: missing.append("reason")
                        if request.intent == "exchange" and not request.replacement_sku: missing.append("replacement_sku")
                        if request.intent == "appointment" and not request.slot_id: missing.append("slot_id")
                        if request.confidence < 0.5:
                            # Out-of-scope or unclear text is a clarification, not the end of
                            # the session; a handoff happens only through the handoff tool.
                            result.trace.append({"stage": "route_extract", "event": "low_confidence", "confidence": request.confidence})
                            result.status = "clarification"
                            result.message = ("لم أتمكن من ربط رسالتك بخدمات المتجر. أستطيع المساعدة في حالة الطلب أو الإرجاع أو الاستبدال أو مواعيد المتجر، أو اطلب موظف الدعم."
                                              if language == "ar" else
                                              "I could not match that to a store request. I can help with order status, returns, exchanges and store appointments, or you can ask for support.")
                        elif missing:
                            result.status = "clarification"
                            result.message = ("أحتاج هذه المعلومات: " if language == "ar" else "Please provide: ") + ", ".join(missing)
                        elif request.intent == "faq":
                            data = self.store.lookup_catalog(session, safe)
                            if self._outbound_reason(canonical(data)):
                                raise ValueError("unsafe_structured_output")
                            self._apply_tool_result(data, result)
                            if self.cache_enabled:
                                self.cache[key] = (result.status, result.message, result.citations, result.request)
                                if self.semantic:
                                    self.semantic.put(safe, self._cache_scope(session), self.cache[key])
                        else:
                            self.tools(request, session, result)
                            if self.cache_enabled and request.intent == "order_status" and result.status == "answer":
                                self.cache[key] = (result.status, result.message, result.citations, result.request)
            self.output_guard(result, session)
        except Exception as exc:
            # Fail closed without exposing stack traces, payloads, credentials or provider body.
            session.pending = None
            session.confirmed_digest = None
            result.trace.append({"stage": "deliver", "event": "safe_failure", "error_type": type(exc).__name__,
                                 "code": str(exc) if str(exc) in SAFE_ERROR_CODES else "request_failed"})
            result.status = "error"
            result.message = "تعذر إكمال الطلب بأمان. حاول لاحقًا أو اطلب موظف الدعم." if language == "ar" else "The request could not be completed safely. Try later or ask for support."
            if str(exc) == "unsafe_structured_output":
                result.status, result.message, result.citations, result.request = "blocked", refusal(language), [], None
        self.deliver(result, start=start)
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            record = result.to_dict()
            record["request_hash"] = digest(mask_pii(text))
            with self.audit_path.open("a", encoding="utf-8") as audit:
                audit.write(canonical(record) + "\n")
        return result

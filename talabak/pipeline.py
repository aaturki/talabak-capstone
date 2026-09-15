from __future__ import annotations
import copy
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from pydantic import ValidationError
from .domain import ROOT, Session, Store, canonical, digest
from .guards import detect_language, injection_reason, mask_pii, output_reason, refusal
from .schemas import Answer, DomainRequest, GuardDecision, TOOL_TYPES, tool_definitions
from .llm import ModelClient, ModelError

SAFE_ERROR_CODES = {"structured_validation_exhausted", "ungrounded_model_answer", "too_many_tool_calls", "terminal_session", "unknown_tool", "tool_intent_mismatch", "tool_order_mismatch", "tool_action_mismatch", "tool_loop_limit", "unsafe_structured_output"}


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


class Application:
    STAGES = ("input_guard", "route_extract", "tools", "output_guard", "deliver")

    def __init__(self, client: ModelClient, store=None, *, cache_enabled=True, alias="primary", max_tool_rounds=4, audit_path=None):
        self.client = client
        self.store = store or Store()
        self.alias = alias
        self.max_tool_rounds = max_tool_rounds
        self.cache_enabled = cache_enabled
        self.cache = {}
        self.audit_path = Path(audit_path) if audit_path else None
        self.prompts = {name: (ROOT / f"prompts/{name}.v1.md").read_text(encoding="utf-8")
                        for name in ("router", "workflow", "guard", "repair")}
        self.prompt_version = digest(self.prompts)
        self.canary = "TALABAK_CANARY_7C84F52A"

    def _call(self, messages, result, *, stage, schema=None, tools=None, alias=None):
        started = time.perf_counter()
        try:
            reply = self.client.complete(messages, schema=schema, tools=tools, alias=alias or self.alias)
        except ModelError as exc:
            result.usage.append({**exc.usage, "stage":stage, "attempts":exc.attempts, "status":"failed", "prompt_version":self.prompt_version,
                                 "usage_available":bool(exc.usage), "latency_ms":(time.perf_counter()-started)*1000})
            raise
        usage = {**reply.usage, "stage": stage, "model": reply.model, "evidence_mode": reply.evidence_mode,
                 "prompt_version": self.prompt_version, "latency_ms": (time.perf_counter()-started)*1000}
        result.usage.append(usage)
        result.evidence_mode = reply.evidence_mode
        return reply

    def _structured(self, messages, model, result, *, stage):
        messages = copy.deepcopy(messages)
        for attempt in range(3):
            reply = self._call(messages, result, stage=stage, schema=model.model_json_schema())
            try:
                parsed = model.model_validate_json(reply.content or "")
                result.trace.append({"stage": stage, "event": "schema_valid", "attempt": attempt+1, "schema": model.__name__})
                return parsed
            except (ValidationError, ValueError) as exc:
                # Only categories and locations, never rejected PII/attack content, enter repair/logs.
                errors = [{"type": x["type"], "loc": [v for v in x["loc"] if v in model.model_fields]} for x in exc.errors()] if isinstance(exc, ValidationError) else [{"type":"invalid_json"}]
                result.trace.append({"stage": stage, "event": "schema_rejected", "attempt": attempt+1, "errors": errors})
                messages.append({"role":"developer", "content": self.prompts["repair"] + "\n" + canonical(errors)})
        raise ValueError("structured_validation_exhausted")

    def input_guard(self, text, result, language):
        reason = injection_reason(text)
        safe = mask_pii(text)
        result.trace.append({"stage":"input_guard", "layer":"deterministic", "blocked":bool(reason), "reason":reason})
        if reason:
            return safe, True
        result.trace.append({"stage":"input_guard", "layer":"pii", "redacted":safe != text})
        verdict = self._structured([{"role":"system", "content":self.prompts["guard"]}, {"role":"user", "content":safe}], GuardDecision, result, stage="input_guard")
        result.trace.append({"stage":"input_guard", "layer":"classifier", "blocked":verdict.blocked})
        return safe, verdict.blocked

    def route_extract(self, text, result):
        return self._structured([{"role":"system", "content":self.prompts["router"]}, {"role":"user", "content":text}], DomainRequest, result, stage="route_extract")

    def _cache_key(self, text, session):
        return digest({"text":text, "customer":session.customer_id, "session":session.session_id,
                       "can_act":session.can_act, "language":session.language, "pending":session.pending,
                       "prompts":self.prompt_version, "alias":self.alias, "data":self.store.fingerprint()})

    def _apply_tool_result(self, data, result):
        codes = {"ok":"answer", "not_authorized":"denied", "policy_denied":"denied", "unavailable":"denied"}
        result.status = codes.get(data["code"], data["code"])
        result.message = data["message"]
        result.citations = data["sources"]

    def tools(self, request, session, result):
        messages = [{"role":"system", "content":self.prompts["workflow"]},
                    {"role":"developer", "content":canonical({"request":request.model_dump(), "pending_action":None})}]
        last_data = None
        for iteration in range(1, self.max_tool_rounds+1):
            reply = self._call(messages, result, stage="tools", schema=Answer.model_json_schema(), tools=tool_definitions())
            if not reply.tool_calls:
                final = Answer.model_validate_json(reply.content or "")
                if last_data is None or final.message != last_data["message"] or final.citations != last_data["sources"]:
                    raise ValueError("ungrounded_model_answer")
                self._apply_tool_result(last_data, result)
                return
            if len(reply.tool_calls) > 4:
                raise ValueError("too_many_tool_calls")
            messages.append({"role":"assistant", "content":reply.content,
                             "tool_calls":[{"id":t["id"], "type":"function", "function":{"name":t["name"], "arguments":canonical(t["arguments"])}} for t in reply.tool_calls]})
            for call in reply.tool_calls:
                if session.terminal:
                    raise ValueError("terminal_session")
                name = call["name"]
                if name not in TOOL_TYPES:
                    raise ValueError("unknown_tool")
                model, risk = TOOL_TYPES[name]
                args = model.model_validate(call["arguments"])
                if output_reason(canonical(args.model_dump()), self.canary):
                    raise ValueError("unsafe_structured_output")
                # The parsed request is intent context; tool args cannot change the proposed action.
                expected = {"order_status":"lookup_order", "return":"create_return_or_exchange", "exchange":"create_return_or_exchange", "appointment":"book_store_appointment", "handoff":"handoff_to_support"}
                if risk in ("side_effect", "terminal") and name != expected.get(request.intent):
                    raise ValueError("tool_intent_mismatch")
                if hasattr(args, "order_id") and args.order_id != request.order_id:
                    raise ValueError("tool_order_mismatch")
                if name == "create_return_or_exchange" and (args.kind != request.intent or args.replacement_sku != request.replacement_sku or args.reason != request.reason):
                    raise ValueError("tool_action_mismatch")
                if name == "book_store_appointment" and (args.slot_id != request.slot_id or args.reason != request.reason):
                    raise ValueError("tool_action_mismatch")
                data = getattr(self.store, name)(session, **args.model_dump())
                result.trace.append({"stage":"tools", "name":name, "risk":risk, "iteration":iteration, "code":data["code"],
                                     "authorized":session.authorize(), "args_sha256":digest(args.model_dump())})
                reason = output_reason(canonical(data), self.canary)
                if reason:
                    result.trace.append({"stage":"output_guard", "blocked":True, "reason":reason, "source":"tool"})
                    result.status, result.message = "blocked", refusal(session.language)
                    result.citations = []
                    session.pending = None
                    session.confirmed_digest = None
                    return
                last_data = data
                messages.append({"role":"tool", "tool_call_id":call["id"], "content":canonical(data)})
                if risk == "terminal":
                    self._apply_tool_result(data, result)
                    return
        raise ValueError("tool_loop_limit")

    def output_guard(self, result, session):
        reason = output_reason(canonical({"message":result.message,"citations":result.citations,"request":result.request}), self.canary)
        result.trace.append({"stage":"output_guard", "blocked":bool(reason), "reason":reason})
        if reason:
            result.status, result.message, result.citations = "blocked", refusal(session.language), []
            result.request = None
            session.pending = None
            session.confirmed_digest = None

    def deliver(self, result, *, start=None):
        result.trace.append({"stage":"deliver", "status":result.status})
        if start is not None:
            result.latency_ms = (time.perf_counter()-start)*1000
        return result

    def handle_message(self, text: str, session: Session):
        start = time.perf_counter()
        result = Result(status="error", message="")
        language = detect_language(text)
        session.language = language
        if session.pending and text.strip().lower() in {"confirm", "yes", "موافق", "نعم", "أكد", "اكد", "تأكيد", "yes confirm", "نعم اكد"}:
            language = session.pending["request"]["language"]
            session.language = language
        restored = session.begin_turn(text)
        try:
            if session.terminal:
                result.status = "handoff"
                result.message = "انتهى المسار الآلي لهذه الجلسة." if language == "ar" else "Automation has ended for this session."
            else:
                safe, blocked = self.input_guard(text, result, language)
                if blocked:
                    session.pending = None
                    result.status, result.message = "blocked", refusal(language)
                elif restored is None and safe.strip().lower() in {"confirm", "yes", "موافق", "نعم", "اكد", "تاكيد", "yes confirm", "نعم اكد"}:
                    result.status = "clarification"
                    result.message = "لا يوجد إجراء ينتظر التأكيد. اذكر الطلب الذي تريد تنفيذه أولًا." if language == "ar" else "No action is awaiting confirmation. Describe the action first."
                else:
                    key = self._cache_key(safe, session)
                    cached = self.cache.get(key) if self.cache_enabled else None
                    if cached:
                        result.status, result.message, result.citations, result.request = copy.deepcopy(cached)
                        result.trace.append({"stage":"route_extract", "event":"response_cache_hit", "tier":"exact"})
                    else:
                        request = DomainRequest.model_validate(restored) if restored else self.route_extract(safe, result)
                        if output_reason(canonical(request.model_dump()), self.canary):
                            raise ValueError("unsafe_structured_output")
                        result.request = request.model_dump()
                        session.last_request = result.request
                        missing = []
                        if request.intent in {"order_status", "return", "exchange"} and not request.order_id: missing.append("order_id")
                        if request.intent in {"return", "exchange", "appointment"} and not request.reason: missing.append("reason")
                        if request.intent == "exchange" and not request.replacement_sku: missing.append("replacement_sku")
                        if request.intent == "appointment" and not request.slot_id: missing.append("slot_id")
                        if request.confidence < 0.5:
                            data = self.store.handoff_to_support(session, "uncertain_or_out_of_scope")
                            self._apply_tool_result(data, result)
                        elif missing:
                            result.status = "clarification"
                            result.message = ("أحتاج هذه المعلومات: " if language == "ar" else "Please provide: ") + ", ".join(missing)
                        elif request.intent == "faq":
                            data = self.store.lookup_catalog(session, safe)
                            if output_reason(canonical(data), self.canary):
                                raise ValueError("unsafe_structured_output")
                            self._apply_tool_result(data, result)
                            if self.cache_enabled:
                                self.cache[key] = (result.status, result.message, result.citations, result.request)
                        else:
                            self.tools(request, session, result)
            self.output_guard(result, session)
        except Exception as exc:
            # Fail closed without exposing stack traces, payloads, credentials or provider body.
            session.pending = None
            session.confirmed_digest = None
            result.trace.append({"stage":"deliver", "event":"safe_failure", "error_type":type(exc).__name__,
                                 "code":str(exc) if str(exc) in SAFE_ERROR_CODES else "request_failed"})
            result.status = "error"
            result.message = "تعذر إكمال الطلب بأمان. حاول لاحقًا أو اطلب موظف الدعم." if language == "ar" else "The request could not be completed safely. Try later or ask for support."
            if str(exc) == "unsafe_structured_output":
                result.status, result.message, result.citations, result.request = "blocked", refusal(language), [], None
        self.deliver(result,start=start)
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            record = result.to_dict()
            record["request_hash"] = digest(mask_pii(text))
            self.audit_path.open("a", encoding="utf-8").write(canonical(record)+"\n")
        return result

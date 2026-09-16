from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DomainRequest(StrictModel):
    intent: Literal["faq", "order_status", "return", "exchange", "appointment", "handoff"]
    language: Literal["ar", "en"]
    order_id: str | None = Field(pattern=r"^ORD-[0-9]{4}$")
    replacement_sku: str | None = Field(pattern=r"^SKU-[A-Z0-9]+$")
    slot_id: str | None = Field(pattern=r"^SLOT-[0-9]{3}$")
    reason: str | None = Field(max_length=500)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def consistent_fields(self):
        if self.replacement_sku and self.intent != "exchange":
            raise ValueError("replacement_sku requires exchange intent")
        if self.slot_id and self.intent != "appointment":
            raise ValueError("slot_id requires appointment intent")
        return self


class Answer(StrictModel):
    message: str = Field(min_length=1, max_length=4000)
    citations: list[str] = Field(max_length=12)


class GuardDecision(StrictModel):
    blocked: bool
    reason: str = Field(max_length=120)


class OrderArgs(StrictModel):
    order_id: str = Field(pattern=r"^ORD-[0-9]{4}$")


class CatalogArgs(StrictModel):
    query: str = Field(max_length=1000)


class ReturnArgs(StrictModel):
    kind: Literal["return", "exchange"]
    order_id: str = Field(pattern=r"^ORD-[0-9]{4}$")
    replacement_sku: str | None = Field(pattern=r"^SKU-[A-Z0-9]+$")
    reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def replacement_consistency(self):
        if self.kind == "exchange" and not self.replacement_sku:
            raise ValueError("exchange requires replacement_sku")
        if self.kind == "return" and self.replacement_sku:
            raise ValueError("return cannot contain replacement_sku")
        return self


class AppointmentArgs(StrictModel):
    slot_id: str = Field(pattern=r"^SLOT-[0-9]{3}$")
    reason: str = Field(min_length=2, max_length=500)


class HandoffArgs(StrictModel):
    reason: str = Field(min_length=2, max_length=500)


TOOL_TYPES = {
    "lookup_order": (OrderArgs, "read_only"),
    "lookup_catalog": (CatalogArgs, "read_only"),
    "create_return_or_exchange": (ReturnArgs, "side_effect"),
    "book_store_appointment": (AppointmentArgs, "side_effect"),
    "handoff_to_support": (HandoffArgs, "terminal"),
}

# Keywords OpenAI's documented strict subset accepts (structured outputs and
# strict function parameters). Pydantic keeps enforcing the removed string-length
# constraints when the response is parsed, so nothing is relaxed application-side.
STRICT_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "anyOf", "enum", "const",
    "title", "description", "$defs", "$ref", "pattern", "format", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems",
}
DROPPED_KEYWORDS = {"minLength", "maxLength", "default", "examples", "$schema"}
_NAMED_CONTAINERS = {"properties", "$defs", "definitions"}


def strict_wire_schema(schema: dict) -> dict:
    """Return a deep copy of a Pydantic JSON schema restricted to strict-mode keywords."""
    def walk(node, *, named=False):
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        if named:
            return {name: walk(child) for name, child in node.items()}
        result = {}
        for key, value in node.items():
            if key in DROPPED_KEYWORDS:
                continue
            result[key] = walk(value, named=key in _NAMED_CONTAINERS)
        if result.get("type") == "object":
            result.setdefault("additionalProperties", False)
            if isinstance(result.get("properties"), dict):
                result["required"] = list(result["properties"])
        return result
    return walk(copy.deepcopy(schema))


def unsupported_strict_keywords(schema: dict) -> list[str]:
    """List schema keywords outside the strict subset; empty means wire-ready."""
    found = set()
    def walk(node, *, named=False):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for key, value in node.items():
                if not named and key not in STRICT_KEYWORDS:
                    found.add(key)
                walk(value, named=(not named) and key in _NAMED_CONTAINERS)
    walk(schema)
    return sorted(found)


def wire_schema(model: type[BaseModel]) -> dict:
    return strict_wire_schema(model.model_json_schema())


def tool_definitions():
    metadata = json.loads((Path(__file__).resolve().parents[1] / "prompts/tools.v1.json").read_text(encoding="utf-8"))
    descriptions = metadata["tools"]
    if metadata.get("version") != "tools-v1" or set(descriptions) != set(TOOL_TYPES):
        raise ValueError("Tool metadata must match the registered tools and version")
    if any(not isinstance(value, str) or not value.strip() for value in descriptions.values()):
        raise ValueError("Every tool requires a nonempty description")
    return [{"type": "function", "function": {
        "name": name, "description": descriptions[name], "strict": True, "parameters": wire_schema(model)
    }} for name, (model, _) in TOOL_TYPES.items()]

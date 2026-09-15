from __future__ import annotations

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


def tool_definitions():
    return [{"type": "function", "function": {
        "name": name, "strict": True, "parameters": model.model_json_schema()
    }} for name, (model, _) in TOOL_TYPES.items()]

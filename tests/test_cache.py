from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.cache_benchmark import check_pairs, select_threshold
from scripts.evaluate import read_jsonl
from talabak.cache import SemanticCache, pair_score
from talabak.domain import Session, Store
from talabak.pipeline import Application

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("pair", read_jsonl(ROOT / "data/near_miss.v1.jsonl"), ids=lambda p: p["id"])
def test_original_near_miss_cannot_return_the_wrong_cached_answer(pair):
    report = check_pairs([pair], threshold=1.0)
    assert report["wrong_hits"] == 0


def test_threshold_selected_from_measured_development_pairs_only():
    development = [pair for pair in read_jsonl(ROOT / "data/cache_pairs.v1.jsonl") if pair["split"] == "development"]
    result = select_threshold(development)
    assert result["status"] == "SELECTED"
    chosen = check_pairs(development, result["selected_threshold"])
    assert chosen["wrong_hits"] == 0 and chosen["true_hits"] > 0
    with pytest.raises(ValueError, match="Held-out"):
        select_threshold([{**development[0], "split": "holdout"}])


def test_semantic_scope_changes_never_reuse_previous_customer_answer():
    value = ("answer", "hours", ["hours-v1"], {"intent": "faq"})
    cache = SemanticCache()
    scope = {"customer": "CUST-A", "permission": True, "policy": "v1", "model": "m1"}
    cache.put("store hours", scope, value)
    assert cache.get("opening hours", scope) == value
    for field, altered in (("customer", "CUST-B"), ("permission", False), ("policy", "v2"), ("model", "m2")):
        assert cache.get("opening hours", {**scope, field: altered}) is None


def test_semantic_cache_refuses_actions_and_nonfaq_values():
    cache = SemanticCache()
    cache.put("store hours", {}, ("confirmation_required", "pending", [], {"intent": "appointment"}))
    assert cache.get("opening hours", {}) is None
    cache.put("book store hours", {}, ("answer", "not safe to reuse", [], {"intent": "faq"}))
    assert cache.get("book store hours", {}) is None


def test_actual_exact_key_changes_for_entire_policy_not_only_prefix():
    store = Store()
    try:
        client = SimpleNamespace(config={"routes": {"primary": {"model": "m1"}}})
        app = Application(client, store)
        session = Session(session_id="fixed")
        store.data["policy"]["explanation"] = "x" * 100 + "original ending"
        before = app._cache_key("ما ساعات المتجر؟", session)
        store.data["policy"]["explanation"] = "x" * 100 + "changed ending"
        assert app._cache_key("ما ساعات المتجر؟", session) != before
    finally:
        store.close()


def test_actual_exact_key_invalidates_authorization_model_clock_and_database():
    store = Store()
    try:
        client = SimpleNamespace(config={"routes": {"primary": {"model": "m1"}}})
        app = Application(client, store)
        session = Session(session_id="fixed")
        text = "حالة ORD-1001؟"
        original = app._cache_key(text, session)
        session.can_act = False
        assert app._cache_key(text, session) != original
        session.can_act = True
        session.customer_id = "CUST-B"
        assert app._cache_key(text, session) != original
        session.customer_id = "CUST-A"
        client.config["routes"]["primary"]["model"] = "m2"
        assert app._cache_key(text, session) != original
        client.config["routes"]["primary"]["model"] = "m1"
        store.today = date(2026, 9, 16)
        assert app._cache_key(text, session) != original
        store.today = date(2026, 9, 15)
        with store.db:
            store.db.execute("UPDATE products SET stock=0 WHERE sku='SKU-H200'")
        assert app._cache_key(text, session) != original
    finally:
        store.close()

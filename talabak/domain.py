"""Policy and persistence are code, never delegated to the model."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from functools import wraps
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


@dataclass
class Session:
    customer_id: str | None = "CUST-A"
    session_id: str = field(default_factory=lambda: secrets.token_hex(16))
    can_act: bool = True
    language: str = "ar"
    pending: dict | None = None
    confirmed_digest: str | None = None
    last_request: dict | None = None
    terminal: bool = False
    turn: int = 0

    def authorize(self, *, owner=None):
        return bool(self.customer_id and self.can_act and (owner is None or owner == self.customer_id))

    def begin_turn(self, text):
        self.turn += 1
        self.confirmed_digest = None
        confirm = text.strip().lower() in {"موافق", "اكد", "أكد", "تأكيد", "نعم اكد", "confirm", "yes confirm", "yes", "نعم"}
        if confirm and self.pending and self.pending["turn"] == self.turn - 1:
            self.confirmed_digest = self.pending["digest"]
            return self.pending["request"]
        self.pending = None
        return None


class Store:
    def __init__(self, path=":memory:", *, fixture=None, today=None):
        self.fixture = Path(fixture or ROOT / "data/store.v1.json")
        self.data = json.loads(self.fixture.read_text(encoding="utf-8"))
        self.today = today or date.fromisoformat(self.data["clock"])
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, customer_id TEXT, sku TEXT, status TEXT, delivered_at TEXT, condition TEXT);
          CREATE TABLE IF NOT EXISTS products(sku TEXT PRIMARY KEY, name_ar TEXT, name_en TEXT, price INTEGER, stock INTEGER CHECK(stock >= 0));
          CREATE TABLE IF NOT EXISTS slots(id TEXT PRIMARY KEY, starts_at TEXT, capacity INTEGER, booked INTEGER CHECK(booked <= capacity));
          CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, customer_id TEXT, kind TEXT, order_id TEXT, slot_id TEXT, payload TEXT, idempotency_key TEXT UNIQUE, status TEXT);
          CREATE UNIQUE INDEX IF NOT EXISTS one_open_order_action ON actions(order_id) WHERE order_id IS NOT NULL AND status='requested';
          CREATE UNIQUE INDEX IF NOT EXISTS one_customer_slot ON actions(customer_id,slot_id) WHERE slot_id IS NOT NULL;
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value INTEGER);
          INSERT OR IGNORE INTO meta VALUES('revision',0);
        """)
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO orders VALUES(:id,:customer_id,:sku,:status,:delivered_at,:condition)", self.data["orders"])
            self.db.executemany("INSERT OR IGNORE INTO products VALUES(:sku,:name_ar,:name_en,:price,:stock)", self.data["catalog"])
            self.db.executemany("INSERT OR IGNORE INTO slots VALUES(:id,:starts_at,:capacity,:booked)", self.data["slots"])

    def close(self):
        self.db.close()

    def revision(self):
        return self.db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]

    def fingerprint(self):
        # Hash content as well as counters, so external fixture/DB edits cannot serve stale cache.
        return digest({"policy": self.data["policy"], "hours": self.data["hours"], "date": str(self.today),
                       "tables": {table: [dict(x) for x in self.db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                                  for table in ("orders", "products", "slots", "actions")}})

    def count_actions(self):
        return self.db.execute("SELECT count(*) FROM actions").fetchone()[0]

    def result(self, session, code, ar, en, *, sources=None, **extra):
        return {"code": code, "message": ar if session.language == "ar" else en,
                "sources": sources or [self.data["policy"]["version"]], **extra}

    def denied(self, s):
        # Existence and owner are deliberately indistinguishable.
        return self.result(s, "not_authorized", "تعذر الوصول إلى الطلب بهذه الجلسة.", "This session cannot access that order.")

    def lookup_order(self, s, order_id):
        row = self.db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not row or not s.customer_id or row["customer_id"] != s.customer_id:
            return self.denied(s)
        order = dict(row)
        order.pop("customer_id")
        ar_status = {"delivered": "تم التسليم", "shipped": "قيد الشحن"}.get(order["status"], order["status"])
        return self.result(s, "ok", f"الطلب {order_id}: {ar_status}.", f"Order {order_id}: {order['status']}.",
                           sources=[f"orders:{order_id}"], order=order)

    def lookup_catalog(self, s, query=""):
        products = [dict(x) for x in self.db.execute("SELECT * FROM products ORDER BY sku")]
        slots = [dict(x) for x in self.db.execute("SELECT * FROM slots WHERE booked < capacity ORDER BY id")]
        days = self.data["policy"]["return_days"]
        ar = f"سياسة المتجر التجريبي: الإرجاع والاستبدال خلال {days} يومًا من التسليم للمنتج غير المفتوح. الاستبدال لمنتج بالسعر نفسه وحسب المخزون. المواعيد: السبت إلى الخميس 10:00–22:00، الجمعة 16:00–22:00 بتوقيت الرياض."
        en = f"Demo store policy: returns and exchanges within {days} days of delivery for unopened items. Exchanges require equal price and available stock. Hours: Saturday–Thursday 10:00–22:00, Friday 16:00–22:00 Riyadh time."
        return self.result(s, "ok", ar, en, sources=["policy-v1", "catalog-v1", "hours-v1"], products=products, slots=slots)

    def _propose_or_confirm(self, s, name, args):
        action = {"tool": name, "args": args, "customer": s.customer_id, "session": s.session_id,
                  "data": self.fingerprint()}
        action_digest = digest(action)
        if s.confirmed_digest == action_digest:
            return None
        s.confirmed_digest = None
        s.pending = {"digest": action_digest, "action": action, "turn": s.turn, "request": s.last_request}
        if name == "create_return_or_exchange":
            ar_kind = "إرجاع" if args["kind"] == "return" else "استبدال"
            ar_summary = f"{ar_kind} الطلب {args['order_id']}"
            en_summary = f"{args['kind']} order {args['order_id']}"
            if args.get("replacement_sku"):
                ar_summary += f" بالمنتج {args['replacement_sku']}"
                en_summary += f" with {args['replacement_sku']}"
        else:
            slot = self.db.execute("SELECT starts_at FROM slots WHERE id=?", (args["slot_id"],)).fetchone()
            ar_summary = f"حجز موعد {args['slot_id']} في {slot['starts_at']}"
            en_summary = f"Book appointment {args['slot_id']} at {slot['starts_at']}"
        ar_summary += f". السبب: {args['reason']}"
        en_summary += f". Reason: {args['reason']}"
        return self.result(s, "confirmation_required", f"راجع الإجراء: {ar_summary}\nاكتب «موافق» لتأكيد هذا الإجراء في الرسالة التالية.",
                           f"Review this action: {en_summary}\nReply 'confirm' in your next message to authorize this exact action.", pending=True)

    def _persist(self, s, name, args, *, order_id=None, slot_id=None):
        key = digest({"customer": s.customer_id, "tool": name, "args": args})
        old = self.db.execute("SELECT id FROM actions WHERE idempotency_key=?", (key,)).fetchone()
        if old:
            return self.result(s, "already_created", f"الإجراء مسجل سابقًا: {old['id']}.", f"Action already recorded: {old['id']}.", action_id=old["id"])
        action_id = "REQ-" + secrets.token_hex(4).upper()
        self.db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)", (action_id, s.customer_id, name, order_id, slot_id, canonical(args), key, "requested"))
        self.db.execute("UPDATE meta SET value=value+1 WHERE key='revision'")
        s.pending = None
        s.confirmed_digest = None
        return self.result(s, "created", f"تم تسجيل الطلب {action_id} بحالة قيد المعالجة.", f"Request {action_id} is recorded for processing.", action_id=action_id)

    @serialized
    def create_return_or_exchange(self, s, kind, order_id, replacement_sku, reason):
        args = dict(kind=kind, order_id=order_id, replacement_sku=replacement_sku, reason=reason)
        if not s.authorize():
            return self.denied(s)
        with self.db:
            # A write lock covers availability check, confirmation fingerprint, and mutation.
            self.db.execute("BEGIN IMMEDIATE")
            found = self.lookup_order(s, order_id)
            if found["code"] != "ok":
                return found
            order = found["order"]
            policy = self.data["policy"]
            age = (self.today - date.fromisoformat(order["delivered_at"])).days if order["delivered_at"] else None
            if age is None or age < 0 or age > policy["return_days"] or order["condition"] != policy["return_condition"]:
                return self.result(s, "policy_denied", "الطلب لا يستوفي سياسة الإرجاع والاستبدال: يلزم تسليمه خلال 14 يومًا وأن يكون غير مفتوح.", "The order is ineligible: delivery must be within 14 days and the item unopened.")
            old = self.db.execute("SELECT id FROM actions WHERE order_id=?", (order_id,)).fetchone()
            if old:
                return self.result(s, "already_created", f"يوجد طلب معالجة مسجل: {old['id']}.", f"An action is already registered: {old['id']}.", action_id=old["id"])
            if kind == "exchange":
                target = self.db.execute("SELECT * FROM products WHERE sku=?", (replacement_sku,)).fetchone()
                original = self.db.execute("SELECT * FROM products WHERE sku=?", (order["sku"],)).fetchone()
                if not target or target["stock"] < 1 or target["price"] != original["price"]:
                    return self.result(s, "unavailable", "البديل غير متاح للاستبدال بالسعر نفسه.", "The replacement is unavailable for an equal-price exchange.")
            pending = self._propose_or_confirm(s, "create_return_or_exchange", args)
            if pending:
                return pending
            result = self._persist(s, kind, args, order_id=order_id)
            if kind == "exchange" and result["code"] == "created":
                self.db.execute("UPDATE products SET stock=stock-1 WHERE sku=? AND stock>0", (replacement_sku,))
            return result

    @serialized
    def book_store_appointment(self, s, slot_id, reason):
        if not s.authorize():
            return self.denied(s)
        args = dict(slot_id=slot_id, reason=reason)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            existing = self.db.execute("SELECT id FROM actions WHERE customer_id=? AND slot_id=?", (s.customer_id, slot_id)).fetchone()
            if existing:
                return self.result(s, "already_created", f"الموعد مسجل سابقًا: {existing['id']}.", f"Appointment already recorded: {existing['id']}.", action_id=existing["id"])
            slot = self.db.execute("SELECT * FROM slots WHERE id=?", (slot_id,)).fetchone()
            if not slot or slot["booked"] >= slot["capacity"] or datetime.fromisoformat(slot["starts_at"]).date() <= self.today:
                return self.result(s, "unavailable", "الموعد غير متاح. اختر موعدًا آخر.", "This appointment is unavailable. Choose another slot.")
            pending = self._propose_or_confirm(s, "book_store_appointment", args)
            if pending:
                return pending
            self.db.execute("UPDATE slots SET booked=booked+1 WHERE id=? AND booked<capacity", (slot_id,))
            return self._persist(s, "appointment", args, slot_id=slot_id)

    def handoff_to_support(self, s, reason):
        s.terminal = True
        s.pending = None
        return self.result(s, "handoff", "انتهى المسار الآلي. يمكن لفريق الدعم مراجعة طلبك؛ لم تُرسل رسالة خارج هذه النسخة المحلية.", "The automated workflow has ended. Support can review your request; no external message was sent.", terminal=True, reason=reason)

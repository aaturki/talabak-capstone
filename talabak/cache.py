"""Conservative local concept-vector cache, not a learned embedding model.

Exact scope equality and critical entity signatures are mandatory before cosine
similarity. The semantic tier only serves grounded FAQ responses; never actions.
The threshold is calibrated by scripts/cache_benchmark.py on versioned pairs.
"""
from __future__ import annotations
import math
import re
from collections import Counter
from .guards import normalize, injection_reason
from .domain import canonical

CONCEPTS = {
    "hours": r"دوام|ساعات|اوقات|مواعيد العمل|تفتح|يفتح|تقفل|يغلق|hours|opening|closing|open|close",
    "policy": r"سياس|شروط|كم يوم|مده|مدة|تعليمات|policy|window|instructions|rules|conditions",
    "return": r"ارجاع|ارجع|اعاده|اعادة|استرجاع|return|refund",
    "exchange": r"استبد|تبديل|بدل|exchange|replace",
    "catalog": r"كتالوج|منتج|منتجات|catalog|product",
    "price": r"سعر|اسعار|ثمن|price|cost",
    "stock": r"مخزون|متوفر|متاح|stock|available",
}
CRITICAL = re.compile(r"ORD-[0-9]+|SKU-[A-Z0-9]+|SLOT-[0-9]+|[0-9]+|السبت|الاحد|الاثنين|الثلاثاء|الاربعاء|الخميس|الجمعه|الجمعة|saturday|sunday|monday|tuesday|wednesday|thursday|friday|\bnot\b|\bno\b|\bwithout\b|\bلا\b|\bليس\b|\bدون\b|مفتوح|مغلق|opened|unopened|جده|جدة|الرياض|riyadh|jeddah",re.I)
ACTION = re.compile(r"انشئ|نفذ|احجز|سجل|اريد ارجاع|ابغي ارجع|\bcreate\b|\bsubmit\b|\bbook\b|\bexecute\b",re.I)


def vector(text):
    text = normalize(text).lower()
    return Counter({concept:1 for concept, pattern in CONCEPTS.items() if re.search(pattern,text,re.I)})


def signature(text):
    text = normalize(text).lower()
    negation = tuple(sorted(set(re.findall(r"\b(?:غير|مو|مش|ما|لم|لن|without|not|no)\b", text))))
    return (tuple(sorted(set(CRITICAL.findall(text)))) + negation), bool(ACTION.search(text))


def similarity(a, b):
    if injection_reason(a) or injection_reason(b) or signature(a)!=signature(b):
        return 0.0
    va,vb=vector(a),vector(b)
    if not va or not vb:
        return 0.0
    # Concept-set equality is an additional conservative barrier. Cosine is kept
    # explicit so the calibrated threshold cannot silently change semantics.
    if set(va)!=set(vb): return 0.0
    return sum(va[k]*vb[k] for k in va)/(math.sqrt(sum(x*x for x in va.values()))*math.sqrt(sum(x*x for x in vb.values())))


def pair_score(a,b):
    if {k:v for k,v in a.items() if k!='text'} != {k:v for k,v in b.items() if k!='text'}:
        return 0.0
    return similarity(a['text'],b['text'])


class SemanticCache:
    def __init__(self, threshold=1.0, *, limit=128):
        if not 0 < threshold <= 1: raise ValueError("Invalid semantic threshold")
        self.threshold,self.limit,self.rows=threshold,limit,[]

    def put(self, text, scope, value):
        if signature(text)[1] or value[3].get('intent')!='faq': return
        self.rows.append((text,canonical(scope),value))
        self.rows=self.rows[-self.limit:]

    def get(self,text,scope):
        for prior,key,value in reversed(self.rows):
            if key==canonical(scope) and similarity(text,prior)+1e-12>=self.threshold:
                return value
        return None

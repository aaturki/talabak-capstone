"""Bilingual, normalized input and output guards. Corpus results bound claims."""
from __future__ import annotations
import re
import unicodedata

CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")
AR_MARKS = re.compile(r"[\u064b-\u065f\u0670\u0640]")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
FOLD = str.maketrans({"أ":"ا", "إ":"ا", "آ":"ا", "ى":"ي", "І":"I", "і":"i", "а":"a", "о":"o", "е":"e"})


def normalize(text, *, separator=""):
    text = unicodedata.normalize("NFKC", text).translate(DIGITS).translate(FOLD)
    return AR_MARKS.sub("", CONTROLS.sub(separator, text)).strip()


def detect_language(text):
    return "ar" if re.search(r"[\u0621-\u064a]", text) else "en"


PII_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)),
    ("IBAN", re.compile(r"\bSA\s*\d{2}(?:[ -]*\d){20}\b", re.I)),
    ("MOBILE", re.compile(r"(?<!\d)(?:(?:\+?966|00966)[ -]?5|05)(?:[ -]?\d){8}(?!\d)")),
    ("NATIONAL_ID", re.compile(r"(?<![A-Za-z0-9])[12](?:[ -]?\d){9}(?!\d)")),
]


def mask_pii(text):
    text = normalize(text)
    for label, pattern in PII_PATTERNS:
        text = pattern.sub(f"[REDACTED_{label}]", text)
    return text


PATTERNS = [
    r"\b(ignore|disregard|forget|override)\s+(all\s+)?(your\s+|the\s+)?(previous|prior|above|earlier|system|developer)\s+(instructions|rules|prompts?|messages)",
    r"\b(ignore|bypass|disable|override)\s+(all\s+)?(your\s+|the\s+)?(safety|guards?|restrictions|authentication|authorization|confirmation)",
    r"\b(reveal|show|print|repeat|display|expose|translate|leak)\b.{0,60}\b(system prompt|developer message|hidden instructions|your instructions|canary|api key|secret token)\b",
    r"\b(act as|you are now)\b.{0,30}\b(system|developer|admin|unrestricted|root)\b",
    r"\b(new|updated)\s+(system\s+)?instructions\s*:",
    r"<\/?(system|developer|instructions)>|\[INST\]|\[SYSTEM\]",
    r"تجاهل\s*(كل\s*)?(ال)?(تعليمات|اوامر|قواعد|قيود|ضوابط)",
    r"(اكشف|اعرض|اطبع|كرر|اظهر|ترجم|سرب).{0,50}(تعليمات النظام|رساله المطور|رسالة المطور|البرومبت|تعليماتك|مفتاح.{0,8}(السري|api)|الكلمه السريه|canary)",
    r"(انت الان|تصرف ك).{0,30}(مدير|مطور|نظام|مسؤول)",
    r"(تجاوز|عطل|الغي|الغ).{0,30}(التفويض|التحقق|التاكيد|الحمايه|الحماية|القيود)",
    r"(تعليمات|اوامر)\s*(جديده|جديدة|محدثة)\s*:",
    r"(نفذ|وافق|اعتمد|احجز|سجل).{0,40}(بدون|دون).{0,15}(تاكيد|اذن|تفويض)",
    r"\b(execute|approve|book|submit)\b.{0,45}\bwithout\b.{0,15}\b(confirmation|authorization|permission)\b",
]
COMPILED = [re.compile(p, re.I) for p in PATTERNS]


def injection_reason(text):
    if len(text) > 4000:
        return "input_too_long"
    for variant in (normalize(text), normalize(text, separator=" ")):
        if any(pattern.search(variant) for pattern in COMPILED):
            return "instruction_override"
    return None


def output_reason(text, canary):
    if canary in text or re.search(r"TALABAK_CANARY_[A-Z0-9_]+", text):
        return "canary_leak"
    normalized = normalize(text)
    if any(pattern.search(normalized) for _, pattern in PII_PATTERNS):
        return "pii_leak"
    if injection_reason(text):
        return "relayed_instruction"
    if re.search(r"Traceback \(most recent|sk-proj-|Authorization:\s*Bearer|<system>", text, re.I):
        return "internal_leak"
    return None


def refusal(language):
    return ("لا أستطيع تنفيذ هذا الطلب. أستطيع مساعدتك في الطلبات والإرجاع والاستبدال ومواعيد المتجر."
            if language == "ar" else "I cannot carry out that request. I can help with orders, returns, exchanges and store appointments.")

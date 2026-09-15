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
    # Imperatives that target controls or evidence, rather than ordinary domain questions.
    r"\b(ignore|disregard|forget|override)\b.{0,45}\b(instructions|rules|polic(?:y|ies)|tool results?|guards?|confirmation)\b",
    r"\b(bypass|disable|override|skip)\b.{0,30}\b(ownership|authorization|authentication|confirmation|guardrails|session checks)\b",
    r"\b(i am|you are now|act as)\s+(the\s+)?(administrator|admin|developer|system|root)\b",
    r"\b(reveal|show|print|repeat|display|expose|leak)\b.{0,55}\b(system|developer|hidden)\b.{0,25}\b(prompt|instructions|message|rules)\b",
    r"\b(show|give|export|dump|reveal|list|send)\b.{0,80}\b(national id|private phone|phone number|iban|customer orders|customers?['’]? orders)\b",
    r"\b(force)\b.{0,80}\b(out.of.stock|hide the error|skip|without)\b",
    r"(?:^|[\n;])\s*(system|developer)\s*:",
    r"(تجاهل|انس|انسي|اهمل).{0,35}(تعليمات|قواعد|سياس[هة]|نتيج[هة]|امتلاء|قيود|حماي[هة])",
    r"(تجاوز|عطل|الغ).{0,35}(صلاحيات|ملكي[هة]|فحص|حواجز|سجل|حماي[هة]|سياس[هة])",
    r"(اعتبرني|انا|انت الان|تصرف ك).{0,20}(مدير النظام|مطور التطبيق|مسؤول النظام)",
    r"(اكشف|اظهر|اعرض|اطبع|اعطني|هات|ارسل|سرب).{0,75}(رسال[هة] النظام|تعليمات المطور|الاسرار|اسرار العملاء|رقم الهوي[هة]|رقم جوال|ارقام الايبان|رمز الدخول|API\s*key)",
    r"(?:^|[\n؛])\s*(رسال[هة]\s*)?(النظام|نظام|المطور)\s*(جديد[هة]\s*)?:",
    r"(غير|عد[ّ]?ل).{0,15}سعر.{0,35}(النظام|قاعد[هة] البيانات|ثم استبدل)",
    r"اجب\s*كان.{0,60}(اكتمل|نجح).{0,40}(رغم|رفض)",
    r"\b(execute|run|نفذ|شغل)\b.{0,25}\b(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+\w+\s+SET|INSERT\s+INTO)\b",
]
COMPILED = [re.compile(p, re.I) for p in PATTERNS]

# A quoted attack in a scam report is data. Remove only its quoted span, then
# inspect the rest of the message. Never treat a reporting phrase as a blanket
# exemption: a second command following the quote must still be blocked.
REPORT_CONTEXT = re.compile(
    r"(رايت.{0,20}(اعلان|رساله|رسالة)|وصلتني.{0,15}(رساله|رسالة)|ابلغكم ان|"
    r"(?:i\s+)?received.{0,25}(scam|message)|someone asked me to)", re.I)
QUOTED = re.compile(r"«[^»]{1,1200}»|“[^”]{1,1200}”|\"[^\"\n]{1,1200}\"|'[^'\n]{1,1200}'")
REPORTED_REQUEST = re.compile(
    r"(?:\bSomeone asked me to\s+(bypass|disable|override)\s+(authorization|authentication|guardrails|safety rules)\s*[.;]|"
    r"ابلغكم ان.{0,35}طلب مني\s+(تجاوز|تعطيل)\s+(الصلاحيات|الحماي[هة]|التفويض)\s*[؛.])", re.I)


def _instruction_text(variant):
    report = REPORT_CONTEXT.search(variant)
    if not report:
        return variant
    # An unquoted third-party request is removed only as its own bounded clause.
    # Any subsequent instruction remains visible to COMPILED.
    for quote in QUOTED.finditer(variant):
        between = variant[report.end():quote.start()]
        if quote.start() >= report.end() and len(between) <= 100 and not re.search(r"[.!?؛\n]", between):
            variant = variant[:quote.start()] + "[REPORTED_QUOTE]" + variant[quote.end():]
            break
    return REPORTED_REQUEST.sub("[REPORTED_REQUEST].", variant)


def injection_reason(text):
    if len(text) > 4000:
        return "input_too_long"
    for variant in (normalize(text), normalize(text, separator=" ")):
        variant = _instruction_text(variant)
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

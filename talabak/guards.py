"""Bilingual, normalized input and output guards. Corpus results bound claims."""
from __future__ import annotations
import re
import unicodedata

CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f​-‏‪-‮⁠-⁩﻿]")
AR_MARKS = re.compile(r"[ً-ٰٟـ]")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
FOLD = str.maketrans({"أ":"ا", "إ":"ا", "آ":"ا", "ى":"ي", "І":"I", "і":"i", "а":"a", "о":"o", "е":"e"})


def normalize(text, *, separator=""):
    text = unicodedata.normalize("NFKC", text).translate(DIGITS).translate(FOLD)
    return AR_MARKS.sub("", CONTROLS.sub(separator, text)).strip()


def detect_language(text):
    return "ar" if re.search(r"[ء-ي]", text) else "en"


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


# An Arabic imperative at the start of a clause, optionally with a one-letter
# conjunction prefix, without matching the same letters inside a longer word.
AR_VERB_START = r"(?:^|(?<=\s)|(?<=[،؛.!?:«»\"'])|(?<=^[وف])|(?<=\s[وف]))"

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
    # Third-party record exfiltration: another customer's identifiers, or records of every customer.
    # A customer's own phone number or the store's number is not an exfiltration target.
    r"\b(show|give|export|dump|reveal|list|send|share|tell)\b(?:(?!\bmy\b).){0,60}\b(another|other|every|all|each)\s+customers?['’]?s?\b.{0,40}\b(national id|iban|phone|orders?|address|email)\b",
    r"\b(show|give|export|dump|reveal|list|send|share|tell)\b.{0,60}\b(national id|private phone|phone number|iban|orders?)\b.{0,40}\b(belonging to|of (?:the )?owner|of another|of other|of every|of all|of (?:the )?customers?|owner of ORD)\b",
    r"\b(export|dump|list|send|show|give)\b(?:(?!\bmy\b).){0,40}\b(all\s+|every\s+)?customers?['’]?s?\s+orders\b",
    r"\b(force)\b.{0,80}\b(out.of.stock|hide the error)\b",
    r"(?:^|[\n;])\s*(system|developer)\s*:",
    r"(تجاهل|انس|انسي|اهمل).{0,35}(تعليمات|قواعد|سياس[هة]|نتيج[هة]|امتلاء|قيود|حماي[هة])",
    r"(تجاوز|عطل|الغ).{0,35}(صلاحيات|ملكي[هة]|فحص|حواجز|سجل|حماي[هة]|سياس[هة])",
    # Role assertion: "consider me / you are now / act as" plus a privileged role, or
    # a bare "I am the system administrator". "I want to talk to the manager" is not one.
    r"(اعتبرني|انت الان|تصرف ك).{0,20}(مدير النظام|مطور التطبيق|مسؤول النظام)|(?<![^\s])انا\s+(مدير النظام|مطور التطبيق|مسؤول النظام)",
    r"(اكشف|اظهر|اعرض|اطبع|اعطني|هات|ارسل|سرب).{0,75}(رسال[هة] النظام|تعليمات المطور|الاسرار|اسرار العملاء|رقم الهوي[هة]|رقم جوال|ارقام الايبان|رمز الدخول|API\s*key)",
    r"(?:^|[\n؛])\s*(رسال[هة]\s*)?(النظام|نظام|المطور)\s*(جديد[هة]\s*)?:",
    r"(غير|عد[ّ]?ل).{0,15}سعر.{0,35}(النظام|قاعد[هة] البيانات|ثم استبدل)",
    r"اجب\s*كان.{0,60}(اكتمل|نجح).{0,40}(رغم|رفض)",
    r"\b(execute|run|نفذ|شغل)\b.{0,25}\b(DELETE\s+FROM|DROP\s+TABLE|UPDATE\s+\w+\s+SET|INSERT\s+INTO)\b",
    # Prompt exfiltration anchored on the target noun rather than a fixed verb list.
    r"\b(tell|give|write|output|paste|summari[sz]e|show|print|send|share|dump)\b(?:\s+me)?(?:\s+\w+){0,4}?\s+(your|the|this|its|these)\s+(system|developer|hidden|initial|secret|original)\s+(prompt|instructions?|message|rules|configuration)\b",
    r"\bwhat(?:'s|\s+is|\s+are)\s+your\s+(system|developer|hidden|initial|secret)\s+(prompt|instructions?|message|rules)\b",
    r"\bignore\s+(the\s+)?(above|everything\s+(above|before)|all\s+(that|of\s+that)|what\s+(came|was\s+said)\s+before)\b",
    r"\b(pretend|role-?play|imagine)\b.{0,30}\b(you\s+are|you're|to\s+be|being|as)\b.{0,20}\b(the\s+|a\s+|an\s+)?(store\s+|system\s+)?(manager|admin|administrator|developer|owner|root|system)\b",
    AR_VERB_START + r"(قل|قولي|اكتب|انسخ|لخص|شارك|ارني|اخبرني|اعطني|هات|ارسل|اطبع|اعرض|اكشف|اظهر)\s*(لي\s*)?.{0,30}(تعليمات النظام|رسال[هة] النظام|رسال[هة] المطور|تعليمات المطور|البرومبت|تعليماتك|الاسرار)",
    r"تجاهل\s*(كل\s*)?(ما|اللي|الذي)\s*(سبق|قبل|فوق|ذكر)",
]
COMPILED = [re.compile(p, re.I) for p in PATTERNS]

# A quoted attack in a scam report is data. Only the quoted span (or one bounded
# reported clause) is exempt; any instruction outside it, or one that crosses the
# quote boundary, is still blocked. Straight single quotes count as quotation marks
# only when they are not attached to letters, so contractions ("wasn't ... isn't")
# cannot form a fake quotation around an attack.
REPORT_CONTEXT = re.compile(
    r"(رايت.{0,20}(اعلان|رساله|رسالة)|وصلتني.{0,15}(رساله|رسالة)|ابلغكم ان|"
    r"(?:i\s+)?received.{0,25}(scam|message)|someone asked me to)", re.I)
QUOTED = re.compile(r"«[^»]{1,1200}»|“[^”]{1,1200}”|\"[^\"\n]{1,1200}\"|"
                    r"(?<![A-Za-z0-9ء-ي])'[^'\n]{1,1200}'(?![A-Za-z0-9ء-ي])")
REPORTED_REQUEST = re.compile(
    r"(?:\bSomeone asked me to\s+(bypass|disable|override)\s+(authorization|authentication|guardrails|safety rules)\s*[.;]|"
    r"ابلغكم ان.{0,35}طلب مني\s+(تجاوز|تعطيل)\s+(الصلاحيات|الحماي[هة]|التفويض)\s*[؛.])", re.I)


def _exempt_spans(variant):
    """Character spans that hold reported, non-executed text: at most one quote and one clause."""
    report = REPORT_CONTEXT.search(variant)
    if not report:
        return []
    spans = []
    for quote in QUOTED.finditer(variant):
        between = variant[report.end():quote.start()]
        if quote.start() >= report.end() and len(between) <= 100 and not re.search(r"[.!?؛\n]", between):
            spans.append((quote.start(), quote.end()))
            break
    clause = REPORTED_REQUEST.search(variant)
    if clause:
        spans.append((clause.start(), clause.end()))
    return spans


def _instruction_match(variant):
    """True when an instruction pattern matches outside every exempt reported span."""
    spans = _exempt_spans(variant)
    for pattern in COMPILED:
        for match in pattern.finditer(variant):
            if not any(start <= match.start() and match.end() <= end for start, end in spans):
                return True
    return False


def _relayed(text):
    return any(_instruction_match(variant) for variant in (normalize(text), normalize(text, separator=" ")))


def injection_reason(text):
    if len(text) > 4000:
        return "input_too_long"
    return "instruction_override" if _relayed(text) else None


CANARY_SHAPE = re.compile(r"talabak[\s_\-.]*canary[\s_\-.]*[a-z0-9][a-z0-9\s_\-.]*", re.I)


def _canary_present(text, canary):
    if canary in text:
        return True
    normalized = normalize(text)
    if re.search(re.escape(canary), normalized, re.I) or CANARY_SHAPE.search(normalized):
        return True
    # Letter-by-letter spacing, hyphenation or dotted obfuscation of the same token.
    compact = re.sub(r"[\s_\-.]", "", normalized).casefold()
    return re.sub(r"[_\-]", "", canary).casefold() in compact or "talabakcanary" in compact


def prompt_shingles(prompt, size=8):
    """Word 8-grams of a served instruction prompt, used to detect its text leaking outbound."""
    words = normalize(prompt).casefold().split()
    return {" ".join(words[i:i + size]) for i in range(max(0, len(words) - size + 1))}


def prompt_leak(text, shingles):
    """True when an outbound text reproduces any 8-word run of a served prompt."""
    folded = " ".join(normalize(text).casefold().split())
    return any(shingle in folded for shingle in shingles)


def output_reason(text, canary):
    """Outbound scan: no inbound length cap, so long benign payloads are inspected, not refused."""
    if _canary_present(text, canary):
        return "canary_leak"
    normalized = normalize(text)
    if any(pattern.search(normalized) for _, pattern in PII_PATTERNS):
        return "pii_leak"
    if _relayed(text):
        return "relayed_instruction"
    if re.search(r"Traceback \(most recent|sk-proj-|Authorization:\s*Bearer|<system>", text, re.I):
        return "internal_leak"
    return None


def refusal(language):
    return ("لا أستطيع تنفيذ هذا الطلب. أستطيع مساعدتك في الطلبات والإرجاع والاستبدال ومواعيد المتجر."
            if language == "ar" else "I cannot carry out that request. I can help with orders, returns, exchanges and store appointments.")

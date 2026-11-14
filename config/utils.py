"""Shared security, search normalization, masking, and encryption utilities."""
import base64
import hashlib
import hmac
import re
import secrets
from difflib import SequenceMatcher
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _get_fernet() -> Fernet:
    key_material = getattr(settings, "ZARVON_FIELD_SECRET", settings.SECRET_KEY).encode("utf-8")
    digest = hashlib.sha256(key_material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_field(value: str) -> str:
    """Encrypt sensitive PII or credentials at rest."""
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_field(token: str) -> str:
    """Decrypt sensitive PII or credentials safely."""
    if not token:
        return ""
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return ""


def hash_token(raw_token: str) -> str:
    """Hash one-time invitation tokens or secrets with SHA-256 (never store raw)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_identifier(value: str) -> str:
    """Deterministic keyed HMAC hash for uniqueness checks (e.g. PINFL)."""
    key = settings.SECRET_KEY.encode("utf-8")
    normalized = (value or "").strip().upper().encode("utf-8")
    return hmac.new(key, normalized, hashlib.sha256).hexdigest()


def mask_value(value: str, visible_start: int = 2, visible_end: int = 2) -> str:
    """Mask PII/secrets for logs and UI responses."""
    if not value:
        return ""
    if len(value) <= visible_start + visible_end:
        return "*" * len(value)
    return f"{value[:visible_start]}{'*' * (len(value) - visible_start - visible_end)}{value[-visible_end:]}"


def sanitize_spreadsheet_cell(value: str) -> str:
    """Prevent CSV/Excel formula injection (=, +, -, @, tab, CR)."""
    if value is None:
        return ""
    text = str(value).strip()
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o", "қ": "q", "ғ": "g", "ҳ": "h",
}


_PHONETIC_ALIASES = {
    "ayfon": "ifon",
    "ayfoni": "ifon",
    "ifone": "ifon",
    "aypad": "ipad",
    "syaomi": "xiaomi",
    "ksyomi": "xiaomi",
    "shaomi": "xiaomi",
    "makbuk": "makbuk",
    "macbuk": "makbuk",
    "macbook": "makbuk",
    "smartfon": "smartfon",
    "smartphone": "smartfon",
    "noutbuk": "noutbuk",
    "laptop": "noutbuk",
    "televizor": "tv",
    "xolodilnik": "muzlatgich",
}


def normalize_search_text(text: str) -> str:
    """
    Normalize Uzbek Latin, Uzbek Cyrillic, Russian, and apostrophe variants
    (oʻ, o', o‘, gʻ, g', sh, ch) so smart search treats them uniformly.
    """
    if not text:
        return ""
    s = text.lower().strip()
    # Unify all apostrophe / okina variants around o' and g'
    s = re.sub(r"[ʻ’'`ʼʹ]", "'", s)
    s = s.replace("o'", "o").replace("g'", "g")
    # Convert Cyrillic characters to Latin phonetic equivalents
    converted = []
    for ch in s:
        converted.append(_CYRILLIC_TO_LATIN.get(ch, ch))
    s = "".join(converted)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # Harmonize common Latin/Cyrillic loanword spellings (ph->f, kh->x, oo->u, ck->k)
    s = s.replace("ph", "f").replace("kh", "x").replace("ck", "k").replace("oo", "u")
    tokens = [_PHONETIC_ALIASES.get(tok, tok) for tok in s.split()]
    return " ".join(tokens).strip()


def fuzzy_search_score(query: str, target: str) -> float:
    """Return 0.0..1.0 relevance score combining exact substring, token match, and typo tolerance."""
    nq = normalize_search_text(query)
    nt = normalize_search_text(target)
    if not nq or not nt:
        return 0.0
    if nq == nt:
        return 1.0
    if nq in nt:
        return 0.92
    q_tokens = nq.split()
    t_tokens = nt.split()
    if all(any(qt in tt for tt in t_tokens) for qt in q_tokens):
        return 0.85
    # Typo-tolerant comparison per token
    scores = []
    for qt in q_tokens:
        best = max((SequenceMatcher(None, qt, tt).ratio() for tt in t_tokens), default=0.0)
        scores.append(best)
    avg = sum(scores) / len(scores) if scores else 0.0
    return avg if avg >= 0.62 else 0.0


def generate_otp_code(length: int = 6) -> str:
    """Cryptographically secure numeric OTP."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def compute_monthly_installment(principal: int, months: int, annual_markup_pct: float, commission_pct: float = 0.0) -> dict:
    """
    Transparent installment calculation respecting ZARVON compliance rules:
    - Principal, markup, commission, total payable, monthly payment are stored separately.
    - Checks annualized extra cost <= 50% cap.
    """
    if months <= 0:
        raise ValueError("Muddat kamida 1 oy bo'lishi kerak")
    # Proportional annualized calculation for sub-12m plans
    effective_markup_pct = annual_markup_pct * (months / 12.0)
    markup_amount = round(principal * (effective_markup_pct / 100.0))
    commission_amount = round(principal * (commission_pct / 100.0))
    total_extra = markup_amount + commission_amount
    annualized_extra_pct = ((total_extra / principal) * (12.0 / months) * 100.0) if principal > 0 else 0.0
    total_payable = principal + total_extra
    monthly_payment = round(total_payable / months)
    return {
        "principal": principal,
        "months": months,
        "markup_amount": markup_amount,
        "commission_amount": commission_amount,
        "total_extra": total_extra,
        "total_payable": total_payable,
        "monthly_payment": monthly_payment,
        "annualized_extra_pct": round(annualized_extra_pct, 2),
        "within_50pct_cap": annualized_extra_pct <= 50.0,
    }

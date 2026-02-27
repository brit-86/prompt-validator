"""
Sensitive information validator.

Approach:
- Deterministic regex/heuristic checks for identifiers, auth keys, credit cards,
  physical addresses, email, phone numbers.
- LLM classification for context and suggested rewrites.
- Score adjusted so flags and explanations stay consistent.
"""

from __future__ import annotations
import re
from app.api.schemas import CategoryResult
from app.llm.client import client
from app.llm.prompts import SENSITIVE_SYSTEM

# ---------------------------------------------------------------------------
# Deterministic patterns (no group captures to avoid leaking content in logs)
# ---------------------------------------------------------------------------

# SSN: 9 digits, optional separators (123-45-6789, 123 45 6789, 123456789)
_SSN = re.compile(
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    re.IGNORECASE,
)

# Credit card: 13–19 digits, optional spaces/dashes between groups
_CREDIT_CARD = re.compile(
    r"\b(?:\d[-\s]*){13,19}\b",
    re.IGNORECASE,
)

# Email: local@domain.tld (simple, broad)
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
)

# Phone: (123) 456-7890, 123-456-7890, +1 123 456 7890; must be preceded by non-alnum so we don't match inside tokens (e.g. api keys)
_PHONE = re.compile(
    r"(?<![A-Za-z0-9])(?:\+\d{1,3}[-.\s]*)?(?:\(\d{2,4}\)[-.\s]*|\d{3}[-.\s]*)\d{3}[-.\s]*\d{4}\b",
)

# JWT: three base64url segments separated by dots
_JWT = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
)

# API key / bearer token patterns (common prefixes and "key =" style)
_API_KEY_PATTERNS = (
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_]{20,}\b", re.IGNORECASE),
    re.compile(r"\b(?:api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}['\"]?", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9_\-.]{20,}\b", re.IGNORECASE),
    re.compile(r"\b(?:ghp|gho)_[A-Za-z0-9]{36}\b", re.IGNORECASE),  # GitHub personal access
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b", re.IGNORECASE),  # Slack
)

# Physical address: street number + street type, or 5/9 digit US ZIP
_STREET_NUMBER = re.compile(r"\b\d{1,6}\s+(?:North|South|East|West|N|S|E|W\.?)?\s*(?:[A-Za-z0-9]+[\s,]+)*(?:Street|St\.?|Avenue|Ave\.?|Boulevard|Blvd\.?|Road|Rd\.?|Drive|Dr\.?|Lane|Ln\.?|Way|Court|Ct\.?|Place|Pl\.?|Circle|Cir\.?)\b", re.IGNORECASE)
_US_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")


def _detect_sensitive_heuristic(prompt: str) -> list[str]:
    """
    Run deterministic checks for identifiers, auth keys, credit cards,
    physical addresses, email, and phone numbers. Returns a list of flags
    (e.g. 'ssn', 'email', 'phone_number') without modifying or logging
    the actual content.
    """
    flags: list[str] = []
    seen: set[str] = set()

    def _add(*items: str) -> None:
        for f in items:
            f_lower = f.strip().lower()
            if f_lower and f_lower not in seen:
                seen.add(f_lower)
                flags.append(f_lower)

    ssn_match = _SSN.search(prompt)
    if ssn_match:
        _add("ssn")
    if _CREDIT_CARD.search(prompt):
        _add("credit_card")
    if _EMAIL.search(prompt):
        _add("email")
    phone_match = _PHONE.search(prompt)
    if phone_match:
        if ssn_match and ssn_match.start() == phone_match.start() and ssn_match.end() == phone_match.end():
            pass
        else:
            _add("phone_number")
    if _JWT.search(prompt):
        _add("jwt")
    for pat in _API_KEY_PATTERNS:
        if pat.search(prompt):
            _add("api_key")
            break
    if _STREET_NUMBER.search(prompt) or _US_ZIP.search(prompt):
        _add("address")

    return flags


def _adjust_sensitive_score(raw: dict) -> tuple[int, list[str]]:
    """
    Align the numeric score with the stricter semantics:
    - A non‑zero score MUST correspond to concrete sensitive data or credentials.
    - Concrete sensitive data MUST be reflected via one or more flags.
    
    Implementation rule:
    - If there are no flags, force score to 0 (no sensitive data detected).
    """
    raw_score = int(raw.get("score", 0))
    flags = list(raw.get("flags", [])) if raw.get("flags") else []
    
    if not flags:
        return 0, []
    
    norm_flags = {str(f).strip().lower() for f in flags if f}

    # If concrete sensitive data is present, ensure the score reflects real risk,
    # independent of any optimistic raw score from the model.
    #
    # v1 policy target:
    # - medium (>=40): common PII (email/phone/address/etc.)
    # - high (>=70): highly sensitive IDs, credentials, or secrets (SSN, keys, passwords)
    high_min_flags = {
        "ssn",
        "social_security_number",
        "passport",
        "passport_number",
        "driver_license",
        "driver_license_number",
        "national_id",
        "tax_id",
        "credit_card",
        "credit_card_number",
        "bank_account",
        "iban",
        "routing_number",
        "cvv",
        "cvc",
        "password",
        "passphrase",
        "pin",
        "api_key",
        "access_token",
        "refresh_token",
        "jwt",
        "private_key",
        "session_cookie",
        "recovery_code",
    }

    medium_min_flags = {
        "email",
        "email_address",
        "phone",
        "phone_number",
        "address",
        "home_address",
        "dob",
        "date_of_birth",
        "full_name",
        "name",
        "account_number",
        "customer_id",
    }

    score = max(0, min(100, raw_score))
    if norm_flags & high_min_flags:
        score = max(score, 70)
    elif norm_flags & medium_min_flags:
        score = max(score, 40)
    else:
        # Some concrete sensitive element was flagged but not mapped above.
        score = max(score, 40)

    return score, flags


def check_sensitive(prompt: str, *, trace_id: str) -> CategoryResult:
    heuristic_flags = _detect_sensitive_heuristic(prompt)
    raw = client.ask_json(system=SENSITIVE_SYSTEM, user=prompt, trace_id=trace_id, category="sensitive")

    llm_flags = list(raw.get("flags", [])) if raw.get("flags") else []
    merged_flags = list(heuristic_flags)
    for f in llm_flags:
        f_norm = str(f).strip().lower()
        if f_norm and f_norm not in {x.lower() for x in merged_flags}:
            merged_flags.append(f_norm)

    if merged_flags:
        raw = dict(raw)
        raw["flags"] = merged_flags

    score, flags = _adjust_sensitive_score(raw)

    return CategoryResult(
        score=score,
        explanation=str(raw.get("explanation", "")),
        flags=flags,
        suggested_rewrite=raw.get("suggested_rewrite"),
    )

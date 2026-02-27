"""
Harmful intent validator.

Includes:
- Illegal requests
- Unethical / deceptive requests
In v1, keep as one category, but optionally return sub_type.

"""

from __future__ import annotations
import re
from app.api.schemas import CategoryResult
from app.llm.client import client
from app.llm.prompts import HARMFUL_SYSTEM


_PROCEDURAL_MARKERS: tuple[str, ...] = (
    "step by step",
    "step-by-step",
    "detailed steps",
    "exact steps",
    "walk me through",
    "full instructions",
    "detailed instructions",
    "instructions",
    "a guide",
    "guide me",
    "tutorial",
    "recipe",
    "ingredients",
    "materials",
    "how to",
    "how do i",
    "best way to",
    "most effective way to",
    "tips to",
)

_SELF_HARM_PATTERN = re.compile(
    r"\b("
    r"suicide|suicidal|kill myself|end my life|take my life|hurt myself|harm myself|self[- ]harm|"
    r"cut myself|overdose|od|hang myself|jump off|shoot myself|poison myself|i want to die|"
    r"i don't want to live|i dont want to live"
    r")\b",
    flags=re.IGNORECASE,
)

_SELF_HARM_BENIGN_CONTEXT = re.compile(
    r"\b(prevent|prevention|hotline|helpline|crisis line|awareness|therapy|treatment|recovery|"
    r"cope|coping|support|resources)\b",
    flags=re.IGNORECASE,
)

_DANGEROUS_HEALTH_MARKERS: tuple[str, ...] = (
    # poisoning / hazardous ingestion / suffocation challenges
    "drink bleach",
    "bleach",
    "ammonia",
    "chlorine",
    "inhaling",
    "huffing",
    "choking challenge",
    "pass out challenge",
    "blackout challenge",
    "hold your breath",
    "tide pod",
    # eating disorder / self-starvation / purging advice
    "thinspo",
    "pro-ana",
    "proana",
    "anorexia tips",
    "bulimia tips",
    "how to starve",
    "starve yourself",
    "skip meals",
    "calorie restriction",
    "eat 500 calories",
    "eat 300 calories",
    "purge",
    "make myself throw up",
    "make me throw up",
    "induce vomiting",
    "laxatives for weight loss",
    "diuretics for weight loss",
    "dry fast",
    "water fast",
)

_HELPING_SOMEONE_CONTEXT = re.compile(
    r"\b(help|support)\b.*\b(someone|my friend|a friend|my sister|my brother|my partner|my kid|my child)\b",
    flags=re.IGNORECASE,
)

_EXTREME_WEIGHT_LOSS_PATTERN = re.compile(
    r"\b(lose|drop|shed)\s+(\d{1,3})\s*(pounds|lbs|lb|kg)\s*(in|within|over)\s+(\d{1,3}|a|an|one)\s*(day|days|week|weeks)\b",
    flags=re.IGNORECASE,
)


def _heuristic_self_harm_or_dangerous_health_flags(prompt: str) -> tuple[list[str], str | None, str | None]:
    """
    Deterministic safety coverage for:
    - self-harm / suicide ideation or how-to
    - dangerously unhealthy advice that can cause harm (poisoning, purging, starvation, etc.)

    Returns (flags, sub_type, suggested_rewrite) to merge into the LLM's JSON.
    """
    p = prompt.strip()
    if not p:
        return [], None, None

    lower = p.lower()
    flags: list[str] = []
    sub_type: str | None = None
    suggested_rewrite: str | None = None

    mentions_self_harm = bool(_SELF_HARM_PATTERN.search(p))
    procedural = any(m in lower for m in _PROCEDURAL_MARKERS)
    first_person = bool(
        re.search(
            r"\b(i|i'm|im|me|my)\b.*\b(suicidal|suicide|kill myself|end my life|take my life|hurt myself|harm myself|self[- ]harm|cut myself|overdose|i want to die)\b",
            p,
            flags=re.IGNORECASE,
        )
    )
    benign_context = bool(_SELF_HARM_BENIGN_CONTEXT.search(p))

    # Self-harm should be covered strongly, but avoid flagging purely preventive/awareness prompts
    # that do not ask for methods and do not indicate first-person intent.
    if mentions_self_harm and not (benign_context and not procedural and not first_person):
        flags.append("self-harm")
        sub_type = sub_type or "self-harm"
        suggested_rewrite = suggested_rewrite or (
            "I'm feeling unsafe and need support. Can you help me find immediate, local crisis resources and suggest "
            "grounding/coping steps for right now?"
        )

    # Dangerously unhealthy advice coverage
    dangerous_health_hit = any(m in lower for m in _DANGEROUS_HEALTH_MARKERS)
    if dangerous_health_hit:
        # Reduce false positives for clearly support-oriented questions about helping someone else.
        if not _HELPING_SOMEONE_CONTEXT.search(p):
            # Require some request-intent signal (procedural or "tips") to avoid flagging casual mentions.
            if procedural or "tips" in lower or "advice" in lower:
                flags.append("dangerous_health_advice")
                sub_type = sub_type or "dangerous_health"
                suggested_rewrite = suggested_rewrite or (
                    "Can you explain the health risks here and provide safer, evidence-based alternatives or harm-reduction guidance?"
                )

    # Extreme rapid weight-loss requests (e.g., "lose 50 pounds in a week") are unsafe and should be treated as harmful.
    m = _EXTREME_WEIGHT_LOSS_PATTERN.search(p)
    if m:
        try:
            amount = int(m.group(2))
        except Exception:
            amount = 0
        unit = (m.group(3) or "").strip().lower()
        time_raw = (m.group(5) or "").strip().lower()
        time_unit = (m.group(6) or "").strip().lower()

        if time_raw in {"a", "an", "one"}:
            time_n = 1
        else:
            try:
                time_n = int(time_raw)
            except Exception:
                time_n = 0

        # Convert to approximate lbs / days
        lbs = float(amount) * (2.20462 if unit == "kg" else 1.0)
        days = float(time_n) * (7.0 if "week" in time_unit else 1.0)

        extreme = (days > 0) and (
            (days <= 7 and lbs >= 10)
            or (days <= 14 and lbs >= 15)
            or (days <= 30 and lbs >= 25)
            or (lbs / days >= 2.0)
        )

        if extreme:
            if procedural or ("how" in lower) or ("tips" in lower) or ("advice" in lower):
                if "dangerous_health_advice" not in {f.lower() for f in flags}:
                    flags.append("dangerous_health_advice")
                sub_type = sub_type or "dangerous_health"
                suggested_rewrite = suggested_rewrite or (
                    "Can you explain why that rapid weight-loss target is unsafe, and suggest a realistic, safer approach "
                    "to weight loss (including recommending professional medical guidance if appropriate)?"
                )

    return flags, sub_type, suggested_rewrite


def _adjust_harmful_score(raw: dict) -> tuple[int, list[str], str | None]:
    """
    Align numeric score with the harmful signals we can trust.

    Semantics:
    - If there are no harmful signals (flags / subtype), score should be 0.
    - If there are harmful signals, score should be at least medium risk.
    - If the signals imply illegal/severe harm, score should be high risk.

    Important:
    - Do NOT use free-text explanation keywords to bump score. Explanations often
      contain negations like "does not involve illegal intent", which can cause
      false bumps.
    """
    raw_score = int(raw.get("score", 0))
    flags = list(raw.get("flags", [])) if raw.get("flags") else []
    sub_type_raw = raw.get("sub_type")
    sub_type = str(sub_type_raw) if sub_type_raw is not None else None

    # Normalize subtype into tokens (also useful as fallback flags).
    sub_tokens: set[str] = set()
    if sub_type:
        for part in sub_type.replace(";", ",").split(","):
            t = part.strip().lower()
            if t:
                sub_tokens.add(t)

    harmless_tokens = {"harmless", "benign", "safe"}
    if (sub_tokens & harmless_tokens) and not flags:
        return 0, [], sub_type

    # If subtype indicates specific harms but flags are missing, promote subtype tokens to flags
    # so non-zero scores always correspond to explicit triggered signals.
    if not flags and sub_tokens:
        flags = sorted(sub_tokens)

    if not flags:
        return 0, [], sub_type

    medium_flags = {
        "impersonation",
        "deception",
        "deceptive communication",
        "deceptive_content",
        "social_engineering",
        "medical privacy violation",
        "fraud",
        "scam",
        "harassment",
        "misuse of sensitive information",
        "dangerous_health_advice",
        "dangerous health advice",
        "eating_disorder",
        "eating disorder",
    }
    high_flags = {
        "illegal",
        "criminal",
        "violence",
        "terrorism",
        "self-harm",
        "self harm",
        "murder",
    }

    norm_flags = {str(f).strip().lower() for f in flags if f}

    score = max(0, min(100, raw_score))
    if norm_flags & high_flags:
        score = max(score, 70)
    elif norm_flags & medium_flags:
        score = max(score, 40)
    else:
        # Some signal exists but not mapped; still ensure it's not "near zero".
        score = max(score, 40)

    return score, flags, sub_type


def check_harmful(prompt: str, *, trace_id: str) -> CategoryResult:
    raw = client.ask_json(system=HARMFUL_SYSTEM, user=prompt, trace_id=trace_id, category="harmful")

    # Deterministic safety coverage for self-harm and dangerous health advice.
    heur_flags, heur_sub_type, heur_rewrite = _heuristic_self_harm_or_dangerous_health_flags(prompt)
    if heur_flags:
        existing = list(raw.get("flags", [])) if raw.get("flags") else []
        norm_existing = {str(f).strip().lower() for f in existing if f}
        for f in heur_flags:
            if f and f.strip().lower() not in norm_existing:
                existing.append(f)
        raw["flags"] = existing
    if heur_sub_type and not raw.get("sub_type"):
        raw["sub_type"] = heur_sub_type
    if heur_rewrite and not raw.get("suggested_rewrite"):
        raw["suggested_rewrite"] = heur_rewrite
    if heur_flags:
        existing_expl = str(raw.get("explanation", "") or "").strip()
        addendum = ""
        norm = {str(f).strip().lower() for f in heur_flags if f}
        if ("self-harm" in norm) or ("self harm" in norm):
            addendum = "The prompt appears to involve self-harm/suicide content or advice, which is high risk."
        elif "dangerous_health_advice" in norm:
            addendum = "The prompt requests unsafe health guidance (e.g., extreme rapid weight loss), which can cause harm."
        if addendum:
            raw["explanation"] = (existing_expl + (" " if existing_expl else "") + addendum).strip()

    score, flags, sub_type = _adjust_harmful_score(raw)

    return CategoryResult(
        score=score,
        explanation=str(raw.get("explanation", "")),
        flags=flags,
        sub_type=sub_type,
        suggested_rewrite=raw.get("suggested_rewrite"),
    )

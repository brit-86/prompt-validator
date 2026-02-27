"""
Jailbreak validator.

Signals:
- "ignore previous instructions"
- "reveal system prompt"
- "you are now developer mode"
- attempts to override policy/safety constraints

"""

from __future__ import annotations
import re
from app.api.schemas import CategoryResult
from app.llm.client import client
from app.llm.prompts import JAILBREAK_SYSTEM


_PRETEXT_MARKERS: tuple[str, ...] = (
    "for a screenplay",
    "for my screenplay",
    "screenplay",
    "script",
    "for a script",
    "for a movie",
    "for a film",
    "for a novel",
    "novel",
    "fiction",
    "fictional",
    "for a story",
    "roleplay",
    "role-play",
    "role play",
    "hypothetically",
    "just curious",
    "out of curiosity",
    "for research",
    "for educational purposes",
    "for education",
    "academic purposes",
    "artistic project",
    "as an artist",
)

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
    "parts list",
    "blueprint",
    "how to",
    "how do i",
)

_ILLEGAL_OR_HARMFUL_TOPICS: tuple[str, ...] = (
    # violence / weapons / explosives / poisons
    "bomb",
    "explosive",
    "pipe bomb",
    "molotov",
    "silencer",
    "ghost gun",
    "poison",
    "ricin",
    # drugs
    "meth",
    "fentanyl",
    "cocaine",
    "heroin",
    # cyber
    "hack",
    "hacking",
    "phish",
    "phishing",
    "malware",
    "ransomware",
    "keylogger",
    "ddos",
    "exploit",
    "backdoor",
    # theft / fraud / evasion
    "break into",
    "break-in",
    "burglar",
    "burglary",
    "rob",
    "robbery",
    "steal",
    "fraud",
    "counterfeit",
    "fake id",
    "forgery",
    "carding",
    "credit card",
    "identity theft",
)


def _heuristic_pretextual_illegal_howto_flags(prompt: str) -> list[str]:
    """
    Detect a common jailbreak tactic: requesting actionable illegal/harmful
    instructions under a "screenplay / fiction / curiosity / research" pretext.

    If triggered, we return at least one flag so scoring semantics enforce
    >= medium jailbreak risk.
    """
    p = prompt.lower()

    if not any(m in p for m in _PRETEXT_MARKERS):
        return []

    # Require procedural intent (how-to / step-by-step) to avoid flagging purely
    # creative-writing craft questions like "how to write a screenplay about X".
    if not any(m in p for m in _PROCEDURAL_MARKERS):
        return []

    if "how to write" in p or "write a screenplay" in p or "write a script" in p:
        # If the user is primarily asking about writing craft, don't treat it as jailbreak
        # unless there's also clear procedural intent beyond "how to write".
        procedural_beyond_writing = any(
            m in p for m in ("step by step", "walk me through", "detailed instructions", "full instructions", "ingredients", "materials", "blueprint")
        )
        if not procedural_beyond_writing:
            return []

    if not any(t in p for t in _ILLEGAL_OR_HARMFUL_TOPICS):
        return []

    # Extra confirmation for "pretext": phrases like "purely fictional" or "just for research"
    # are often used to rationalize restricted content.
    if re.search(r"\b(only|purely|just)\b.*\b(fiction|fictional|screenplay|research|curious|curiosity)\b", p):
        return ["benign_pretext_for_harmful_howto"]

    return ["benign_pretext_for_harmful_howto"]


def _heuristic_privileged_role_flags(prompt: str) -> list[str]:
    """
    Detect prompts that try to assign the model a privileged/admin role
    (e.g. system administrator, root) to gain access to internal data or
    restricted operations over users/accounts.
    """
    p = prompt.lower()
    if not p:
        return []

    role_markers = (
        "you are system administrator",
        "you are the system administrator",
        "you are an administrator",
        "you are admin",
        "as an administrator",
        "as admin",
        "you are root",
        "you have root access",
        "you are a database admin",
        "you are a db admin",
        "you are superuser",
        "you have admin privileges",
        "you have administrative privileges",
    )
    resource_markers = (
        "user",
        "users",
        "account",
        "accounts",
        "customer",
        "customers",
        "database",
        "databases",
        "table",
        "tables",
        "log",
        "logs",
        "deactivated",
        "suspended",
        "banned",
        "delete their data",
        "delete user data",
        "delete the data",
    )

    if any(r in p for r in role_markers) and any(r in p for r in resource_markers):
        return ["privilege_escalation_admin_role"]

    return []


def _adjust_jailbreak_score(raw: dict) -> tuple[int, list[str]]:
    """
    Align numeric score with explicit jailbreak signals (flags).

    Semantics:
    - If there are no jailbreak signals (flags), score should be 0.
    - If there are jailbreak signals, score should be at least medium risk.
    - If the flags imply explicit safety-bypass intent, score should be high risk.
    """
    raw_score = int(raw.get("score", 0))
    flags = list(raw.get("flags", [])) if raw.get("flags") else []

    if not flags:
        return 0, []

    norm_flags = {str(f).strip().lower() for f in flags if f}

    high_flags = {
        "bypass_safety",
        "disable_safety",
        "ignore_safety",
        "ignore_instructions",
        "system_override",
        "reveal_system_prompt",
        "prompt_injection",
    }

    score = max(0, min(100, raw_score))
    if norm_flags & high_flags:
        score = max(score, 70)
    else:
        score = max(score, 40)

    return score, flags


def check_jailbreak(prompt: str, *, trace_id: str) -> CategoryResult:
    raw = client.ask_json(system=JAILBREAK_SYSTEM, user=prompt, trace_id=trace_id, category="jailbreak")

    # Deterministic bump: illegal/harmful how-to requests framed as screenplay/art/curiosity
    # should still count as a jailbreak attempt (benign pretext).
    heur_flags = _heuristic_pretextual_illegal_howto_flags(prompt)
    privileged_flags = _heuristic_privileged_role_flags(prompt)
    combined_flags = heur_flags + privileged_flags

    if combined_flags:
        existing = list(raw.get("flags", [])) if raw.get("flags") else []
        norm_existing = {str(f).strip().lower() for f in existing if f}
        for f in combined_flags:
            if f and f.strip().lower() not in norm_existing:
                existing.append(f)
        raw["flags"] = existing

    score, flags = _adjust_jailbreak_score(raw)

    return CategoryResult(
        score=score,
        explanation=str(raw.get("explanation", "")),
        flags=flags,
        suggested_rewrite=raw.get("suggested_rewrite"),
    )

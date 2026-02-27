"""
Decision policy.

Input: scores + explanations + optional rewrite suggestions
Output: (recommendation, final_message, rewritten_prompt)

Keep the policy deterministic for v1.

"""

from __future__ import annotations
from typing import Dict, Tuple, Optional
from app.api.schemas import CategoryResult, Recommendation

def decide_recommendation(
    prompt: str,
    categories: Dict[str, CategoryResult],
    general_score: int,
) -> Tuple[Recommendation, str, Optional[str]]:
    sensitive = categories["sensitive"].score
    jailbreak = categories["jailbreak"].score
    harmful = categories["harmful"].score
    harmful_flags = {str(f).strip().lower() for f in (categories["harmful"].flags or []) if f}
    harmful_sub = (categories["harmful"].sub_type or "").strip().lower()

    # Hard blocks
    if harmful >= 70:
        if ("self-harm" in harmful_flags) or ("self harm" in harmful_flags) or ("self-harm" in harmful_sub) or ("self harm" in harmful_sub):
            return (
                "BLOCK_ILLEGITIMATE_CORE_REQUEST",
                "I’m really sorry you’re feeling this way, but I can’t help with instructions for self-harm. "
                "If you’re in immediate danger, call your local emergency number now. "
                "If you can, reach out to someone you trust or a local crisis hotline for support.",
                None,
            )
        return (
            "BLOCK_ILLEGITIMATE_CORE_REQUEST",
            "I can’t help with that request. Please ask for a legitimate alternative.",
            None,
        )
    if jailbreak >= 70:
        return (
            "BLOCK_NEEDS_USER_FIX",
            "Your prompt appears to try to override system constraints. Please rephrase without instructions to bypass rules.",
            None,
        )

    # Rewrite flows
    # Prefer rewrite suggestions if available; otherwise a generic "please remove sensitive info" message.
    if sensitive >= 70:
        rewrite = categories["sensitive"].suggested_rewrite
        return (
            "ALLOW_WITH_REWRITE" if rewrite else "BLOCK_NEEDS_USER_FIX",
            "Your prompt includes sensitive information. Please remove it, or use the suggested rewrite.",
            rewrite,
        )

    # Medium risk -> allow with rewrite if we have one
    any_medium = any(40 <= c.score < 70 for c in categories.values())
    if any_medium:
        # TODO: pick best rewrite among categories (priority: harmful>jailbreak>sensitive)
        rewrite = (
            categories["harmful"].suggested_rewrite
            or categories["jailbreak"].suggested_rewrite
            or categories["sensitive"].suggested_rewrite
        )
        if rewrite:
            # Medium risk but we can offer a safer alternative.
            return (
                "ALLOW_WITH_REWRITE",
                "This prompt may be risky. Consider the suggested rewrite.",
                rewrite,
            )
        # Medium risk with no rewrite available: do not mark as ALLOW if we tell
        # the user it is risky. Ask the user to fix the prompt instead.
        return (
            "BLOCK_NEEDS_USER_FIX",
            "This prompt may be risky. Please rephrase it to reduce potential harm or ambiguity.",
            None,
        )

    # Low risk
    return ("ALLOW", "Prompt looks fine.", None)

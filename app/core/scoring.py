"""
Scoring logic.

Keep this file pure: given category results -> compute general score.
This makes it easy to test.

Uses summed score across categories (plus optional tool risk bump), capped at 100.

"""

from __future__ import annotations
from typing import Dict, Optional, Iterable
from app.api.schemas import CategoryResult

def _normalize_tools(tools: Optional[Iterable[str]]) -> list[str]:
    if not tools:
        return []
    out: list[str] = []
    for t in tools:
        if not t:
            continue
        norm = str(t).strip().lower()
        if norm:
            out.append(norm)
    return out


def _tool_risk_bump(tools: Optional[Iterable[str]]) -> int:
    """
    Deterministic adjustment to the general score based on available tooling.

    Rationale: the same prompt can be more dangerous when the target model can
    take actions (execute code, spend money, write files, etc).
    """
    t = _normalize_tools(tools)
    if not t:
        return 0

    joined = " ".join(t)

    bump = 0  # default: no change unless clearly risky tools are present

    # Highest-risk action tools
    if any(k in joined for k in ("payment", "payments", "charge", "transfer", "wire", "crypto")):
        bump = max(bump, 20)

    # Code execution / shell access
    if any(k in joined for k in ("code_exec", "exec", "python", "bash", "shell", "terminal", "powershell")):
        bump = max(bump, 15)

    # File system / persistence
    if any(k in joined for k in ("file_write", "filesystem", "write_file", "delete_file", "upload", "download")):
        bump = max(bump, 12)

    # External network / browsing
    if any(k in joined for k in ("web_search", "browser", "http", "https", "network", "fetch", "requests")):
        bump = max(bump, 10)

    # Messaging / external side effects
    if any(k in joined for k in ("email", "sms", "slack", "discord", "message", "post", "publish")):
        bump = max(bump, 10)

    return bump


def compute_general_score(categories: Dict[str, CategoryResult], *, tools: Optional[list[str]] = None) -> int:
    # Sum category scores, add tool risk bump, then cap at 100 (minimum of summed and 100).
    scores = [c.score for c in categories.values()]
    base = int(sum(scores)) if scores else 0
    # If all categories are completely safe, tools alone should not introduce risk.
    if base == 0:
        return 0

    adjusted = base + _tool_risk_bump(tools)
    return int(min(100, max(0, adjusted)))

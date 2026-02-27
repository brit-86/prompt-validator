"""
Metrics: persist validation events and compute aggregates.

Stored per validation:
- total_latency_ms, per-LLM latencies, LLM error count, JSON parse failure count
- fallback_triggered, recommendation, general_risk_score, category_scores, highest_category

Computed metrics:
- total validations count
- latency per LLM call + total latency (avg/median)
- LLM error rate, JSON parse failure rate, fallback rate
- % ALLOW vs % BLOCK vs % REWRITE
- average/median risk score
- distribution by category (how often each category is highest)
"""

from __future__ import annotations
import json
import os
import sqlite3
import statistics
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

# Context for the current validation (used by LLM client to record per-call data)
_llm_calls_ctx: ContextVar[List[Dict[str, Any]]] = ContextVar(
    "validation_llm_calls", default=[]
)

# In-process store for validation events (also persisted to SQLite when path is set)
_events: List[Dict[str, Any]] = []
_db_path: Optional[str] = None

# Error code that indicates JSON parse failure (vs generic LLM error)
PARSE_ERROR_CODE = "parse_error"


def configure_metrics_store(db_path: Optional[str] = None) -> None:
    """Set SQLite path for persisting validation events. If None, in-memory only."""
    global _db_path
    _db_path = db_path
    if _db_path:
        _ensure_schema(_db_path)


def _ensure_schema(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS validation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                ts REAL NOT NULL,
                total_latency_ms REAL NOT NULL,
                llm_latencies_json TEXT NOT NULL,
                llm_error_count INTEGER NOT NULL,
                json_parse_failure_count INTEGER NOT NULL,
                fallback_triggered INTEGER NOT NULL,
                recommendation TEXT NOT NULL,
                general_risk_score INTEGER NOT NULL,
                category_scores_json TEXT NOT NULL,
                highest_category TEXT
            )
        """)
        conn.commit()


def _start_validation_context() -> None:
    """Start a new validation context (clear LLM calls list). Call at start of validate_prompt."""
    _llm_calls_ctx.set([])


def get_current_llm_calls() -> List[Dict[str, Any]]:
    """Return the list of LLM call records for the current validation."""
    return _llm_calls_ctx.get()


def record_llm_call(
    category: str,
    latency_ms: float,
    error_code: Optional[str] = None,
) -> None:
    """Record one LLM call (success or failure). Called by LLM client."""
    calls = list(_llm_calls_ctx.get())
    calls.append({
        "category": category,
        "latency_ms": latency_ms,
        "error_code": error_code,
    })
    _llm_calls_ctx.set(calls)


def _highest_category(category_scores: Dict[str, int]) -> Optional[str]:
    """Return which category had the highest score; tie-break: sensitive < jailbreak < harmful."""
    if not category_scores:
        return None
    order = ("sensitive", "jailbreak", "harmful")
    best = None
    best_score = -1
    for c in order:
        s = category_scores.get(c, 0)
        if s > best_score:
            best_score = s
            best = c
    return best


def record_validation(
    *,
    trace_id: str,
    total_latency_ms: float,
    fallback_triggered: bool,
    recommendation: str,
    general_risk_score: int,
    category_scores: Dict[str, int],
    llm_calls: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """
    Persist one validation event for metrics.

    llm_calls: list of {"category", "latency_ms", "error_code"}. If None, uses current context.
    """
    calls = llm_calls if llm_calls is not None else get_current_llm_calls()
    llm_latencies = {c["category"]: c["latency_ms"] for c in calls if c.get("latency_ms") is not None}
    llm_error_count = sum(1 for c in calls if c.get("error_code") and c["error_code"] != PARSE_ERROR_CODE)
    json_parse_failure_count = sum(1 for c in calls if c.get("error_code") == PARSE_ERROR_CODE)

    event = {
        "trace_id": trace_id,
        "ts": time.time(),
        "total_latency_ms": total_latency_ms,
        "llm_latencies_json": json.dumps(llm_latencies),
        "llm_error_count": llm_error_count,
        "json_parse_failure_count": json_parse_failure_count,
        "fallback_triggered": 1 if fallback_triggered else 0,
        "recommendation": recommendation,
        "general_risk_score": general_risk_score,
        "category_scores_json": json.dumps(category_scores),
        "highest_category": _highest_category(category_scores),
    }
    if not _db_path:
        _events.append(event)

    # Optional: uncomment below to persist validation events to SQLite (e.g. after configure_metrics_store(db_path)).
    # if _db_path:
    #     try:
    #         with sqlite3.connect(_db_path) as conn:
    #             conn.execute(
    #                 """INSERT INTO validation_events (
    #                     trace_id, ts, total_latency_ms, llm_latencies_json,
    #                     llm_error_count, json_parse_failure_count, fallback_triggered,
    #                     recommendation, general_risk_score, category_scores_json, highest_category
    #                 ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    #                 (
    #                     event["trace_id"],
    #                     event["ts"],
    #                     event["total_latency_ms"],
    #                     event["llm_latencies_json"],
    #                     event["llm_error_count"],
    #                     event["json_parse_failure_count"],
    #                     event["fallback_triggered"],
    #                     event["recommendation"],
    #                     event["general_risk_score"],
    #                     event["category_scores_json"],
    #                     event["highest_category"],
    #                 ),
    #             )
    #             conn.commit()
    #     except Exception:
    #         pass  # don't fail validation if metrics persist fails


def _load_events() -> List[Dict[str, Any]]:
    """Load all events from in-memory or SQLite (if configured). Only one source to avoid double-counting."""
    if _db_path and os.path.isfile(_db_path):
        try:
            out = []
            with sqlite3.connect(_db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT trace_id, ts, total_latency_ms, llm_latencies_json, llm_error_count, "
                    "json_parse_failure_count, fallback_triggered, recommendation, general_risk_score, "
                    "category_scores_json, highest_category FROM validation_events"
                ).fetchall()
                for row in rows:
                    out.append({
                        "trace_id": row["trace_id"],
                        "ts": row["ts"],
                        "total_latency_ms": row["total_latency_ms"],
                        "llm_latencies_json": row["llm_latencies_json"],
                        "llm_error_count": row["llm_error_count"],
                        "json_parse_failure_count": row["json_parse_failure_count"],
                        "fallback_triggered": row["fallback_triggered"],
                        "recommendation": row["recommendation"],
                        "general_risk_score": row["general_risk_score"],
                        "category_scores_json": row["category_scores_json"],
                        "highest_category": row["highest_category"],
                    })
            return out
        except Exception:
            pass
    return list(_events)


def get_metrics() -> Dict[str, Any]:
    """
    Compute and return all requested metrics from stored validation events.

    Returns:
        - total_validations_count
        - latency: { total_ms: { avg, median }, per_llm: { sensitive: { avg, median }, ... } }
        - llm_error_rate (0..1)
        - json_parse_failure_rate (0..1)
        - fallback_rate (0..1)
        - recommendation_pct: { ALLOW, ALLOW_WITH_REWRITE, BLOCK_NEEDS_USER_FIX, BLOCK_ILLEGITIMATE_CORE_REQUEST }
        - risk_score: { avg, median }
        - distribution_by_category: { sensitive, jailbreak, harmful } counts and pct
    """
    events = _load_events()
    n = len(events)
    if n == 0:
        return {
            "total_validations_count": 0,
            "latency": {
                "total_ms": {"avg": None, "median": None},
                "per_llm": {
                    "sensitive": {"avg": None, "median": None},
                    "jailbreak": {"avg": None, "median": None},
                    "harmful": {"avg": None, "median": None},
                },
            },
            "llm_error_rate": None,
            "json_parse_failure_rate": None,
            "fallback_rate": None,
            "recommendation_pct": {},
            "risk_score": {"avg": None, "median": None},
            "distribution_by_category": {"sensitive": 0, "jailbreak": 0, "harmful": 0, "pct": {}},
        }

    total_latencies = [e["total_latency_ms"] for e in events]
    per_llm: Dict[str, List[float]] = {"sensitive": [], "jailbreak": [], "harmful": []}
    for e in events:
        try:
            lat = json.loads(e["llm_latencies_json"])
            for cat in per_llm:
                if cat in lat and lat[cat] is not None:
                    per_llm[cat].append(float(lat[cat]))
        except Exception:
            pass

    def avg_median(values: List[float]) -> Dict[str, Optional[float]]:
        if not values:
            return {"avg": None, "median": None}
        return {"avg": statistics.mean(values), "median": statistics.median(values)}

    llm_errors_total = sum(e["llm_error_count"] for e in events)
    json_parse_total = sum(e["json_parse_failure_count"] for e in events)
    # Max 3 LLM calls per validation
    max_llm_calls = n * 3
    fallback_count = sum(e["fallback_triggered"] for e in events)

    rec_counts: Dict[str, int] = {}
    for e in events:
        r = e["recommendation"]
        rec_counts[r] = rec_counts.get(r, 0) + 1
    recommendation_pct = {r: (rec_counts.get(r, 0) / n) * 100 for r in (
        "ALLOW", "ALLOW_WITH_REWRITE", "BLOCK_NEEDS_USER_FIX", "BLOCK_ILLEGITIMATE_CORE_REQUEST"
    )}

    risk_scores = [e["general_risk_score"] for e in events]
    cat_counts: Dict[str, int] = {"sensitive": 0, "jailbreak": 0, "harmful": 0}
    for e in events:
        h = e.get("highest_category")
        if h in cat_counts:
            cat_counts[h] += 1
    cat_pct = {c: (cat_counts[c] / n) * 100 for c in cat_counts}

    return {
        "total_validations_count": n,
        "latency": {
            "total_ms": avg_median(total_latencies),
            "per_llm": {c: avg_median(per_llm[c]) for c in per_llm},
        },
        "llm_error_rate": llm_errors_total / max_llm_calls if max_llm_calls else None,
        "json_parse_failure_rate": json_parse_total / max_llm_calls if max_llm_calls else None,
        "fallback_rate": fallback_count / n,
        "recommendation_pct": recommendation_pct,
        "risk_score": avg_median(risk_scores),
        "distribution_by_category": {
            **cat_counts,
            "pct": cat_pct,
        },
    }

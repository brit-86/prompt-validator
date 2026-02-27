"""
Structured JSON logging (structlog).

- One JSON line per log event for easy parsing in log aggregators.
- One structured event per validation with trace_id, recommendation, scores, latency, errors, prompt_length.
- No raw prompts are logged (privacy).
- Assumption: logs are stored safely in a separate environment with their trace_id, so that whoever
  needs to investigate historical data can do so securely (e.g. by correlating trace_id with
  request/audit data in that environment).
"""

from __future__ import annotations
import logging
from typing import Dict

import structlog

from app.core.config import settings


def configure_logging() -> None:
    """Configure structlog to output JSON to the standard logging stream."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog logger bound with the given name (for compatibility and extra context)."""
    return structlog.get_logger(name)


def log_validation_event(
    *,
    trace_id: str,
    recommendation: str,
    general_risk_score: int,
    category_scores: Dict[str, int],
    latency_ms_total: float,
    llm_error: bool,
    parse_error: bool,
    fallback_triggered: bool,
    prompt_length: int,
) -> None:
    """
    Log one structured JSON event per validation. No prompt content is logged.
    """
    log = structlog.get_logger("validation")
    log.info(
        "validation_complete",
        trace_id=trace_id,
        recommendation=recommendation,
        general_risk_score=general_risk_score,
        category_scores=category_scores,
        latency_ms_total=round(latency_ms_total, 2),
        llm_error=llm_error,
        parse_error=parse_error,
        fallback_triggered=fallback_triggered,
        prompt_length=prompt_length,
    )

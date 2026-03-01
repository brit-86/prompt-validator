"""
Orchestrator: validates the prompt by running category checks,
combines results into a general score, then chooses a recommendation.

This is the "brain" that wires everything together.
"""

from __future__ import annotations
import time
import uuid
from app.api.schemas import PromptRequest, PromptResponse, CategoryResult
from app.core.config import settings
from app.core.scoring import compute_general_score
from app.core.policy import decide_recommendation
from app.validators.sensitive import check_sensitive
from app.validators.jailbreak import check_jailbreak
from app.validators.harmful import check_harmful
from app.telemetry.logging import get_logger, log_validation_event
from app.telemetry.metrics import (
    PARSE_ERROR_CODE,
    get_current_llm_calls,
    record_validation,
    _start_validation_context,
)
from app.core.errors import PromptTooLongError, ValidationServiceError

log = get_logger(__name__)


def _ensure_prompt_length_ok(prompt: str) -> None:
    if len(prompt) > settings.MAX_PROMPT_CHARS:
        raise PromptTooLongError(
            prompt_chars=len(prompt),
            max_prompt_chars=settings.MAX_PROMPT_CHARS,
        )


def _is_privacy_only_flags(flags: list[str] | None) -> bool:
    if not flags:
        return True
    norm = [str(f).strip().lower() for f in flags if f]
    if not norm:
        return True
    for f in norm:
        # Treat generic privacy/PII descriptors as "privacy-only" signals.
        # These often overlap with the `sensitive` category which is responsible
        # for concrete PII/credential presence.
        if (
            "privacy" in f
            or "pii" in f
            or "personal data" in f
            or "personal_data" in f
            or "personal info" in f
            or "personal information" in f
            or "sensitive_information" in f
            or "sensitive information" in f
        ):
            continue
        return False
    return True


def _dedupe_category_overlaps(categories: dict[str, CategoryResult]) -> dict[str, CategoryResult]:
    """
    Reduce false overlap between categories.

    Intent:
    - `sensitive` owns concrete PII/credential detection.
    - `harmful` should not "double count" when it only echoes privacy/PII concerns
      already covered by `sensitive`.
    - `jailbreak` should not trigger on privacy/PII alone.
    """
    sensitive = categories.get("sensitive")
    jailbreak = categories.get("jailbreak")
    harmful = categories.get("harmful")

    # If we have concrete sensitive data, suppress privacy-only harmful/jailbreak echoes.
    if sensitive and sensitive.score > 0:
        if harmful:
            sub = (harmful.sub_type or "").strip().lower()
            privacy_only_subtypes = {
                "",
                "privacy_violation",
                "privacy",
                "privacy violation",
                "personal_data_request",
                "personal data request",
                "personal_data_lookup",
                "personal data lookup",
                "personal_info_request",
                "personal info request",
                "personal_information_request",
                "personal information request",
            }
            if _is_privacy_only_flags(harmful.flags) and (sub in privacy_only_subtypes):
                categories["harmful"] = harmful.model_copy(
                    update={
                        "score": 0,
                        "flags": [],
                        "sub_type": None,
                        "explanation": "Privacy/PII risk is already covered by the sensitive category.",
                        "suggested_rewrite": None,
                    }
                )
        if jailbreak:
            # If jailbreak flags are privacy-only and there are no explicit jailbreak markers,
            # treat it as a misclassification.
            if _is_privacy_only_flags(jailbreak.flags):
                categories["jailbreak"] = jailbreak.model_copy(
                    update={
                        "score": 0,
                        "flags": [],
                        "explanation": "",
                        "suggested_rewrite": None,
                    }
                )

    return categories


def _fail_safe_response(trace_id: str, error: Exception) -> PromptResponse:
    """Return a conservative block response when validation fails (timeout, upstream error, etc.)."""
    code = getattr(error, "code", "service_error")
    is_timeout = code == "timeout"
    message = (
        "Validation could not be completed (request timed out). For your safety, this request was blocked."
        if is_timeout
        else "Validation could not be completed due to a temporary error. For your safety, this request was blocked."
    )
    log.warning(
        "fail_safe_activated",
        extra={"trace_id": trace_id, "error_code": code, "error": str(error)},
    )
    safe_category = CategoryResult(score=100, explanation="Validation failed; fail-safe block applied.", flags=[], sub_type=None, suggested_rewrite=None)
    return PromptResponse(
        trace_id=trace_id,
        general_risk_score=100,
        categories={
            "sensitive": safe_category.model_copy(update={"explanation": "Check skipped (fail-safe)."}),
            "jailbreak": safe_category.model_copy(update={"explanation": "Check skipped (fail-safe)."}),
            "harmful": safe_category.model_copy(update={"explanation": "Check skipped (fail-safe)."}),
        },
        recommendation="BLOCK_NEEDS_USER_FIX",
        final_message=message,
        rewritten_prompt=None,
        error_code=code,
    )


def validate_prompt(req: PromptRequest) -> PromptResponse:
    trace_id = str(uuid.uuid4())
    prompt = req.prompt
    _ensure_prompt_length_ok(prompt)

    t0 = time.perf_counter()
    _start_validation_context()

    if settings.FAIL_SAFE_MODE:
        try:
            resp = _validate_prompt_impl(req, trace_id, prompt)
            total_ms = (time.perf_counter() - t0) * 1000
            _record_validation_metrics(trace_id, total_ms, resp, fallback_triggered=False)
            _log_validation_event(trace_id, total_ms, resp, fallback_triggered=False, prompt_length=len(prompt))
            return resp
        except ValidationServiceError as e:
            resp = _fail_safe_response(trace_id, e)
            total_ms = (time.perf_counter() - t0) * 1000
            _record_validation_metrics(trace_id, total_ms, resp, fallback_triggered=True)
            _log_validation_event(trace_id, total_ms, resp, fallback_triggered=True, prompt_length=len(prompt))
            return resp
        except Exception as e:
            log.error("validation_error", trace_id=trace_id, exc_info=True)
            resp = _fail_safe_response(trace_id, e)
            total_ms = (time.perf_counter() - t0) * 1000
            _record_validation_metrics(trace_id, total_ms, resp, fallback_triggered=True)
            _log_validation_event(trace_id, total_ms, resp, fallback_triggered=True, prompt_length=len(prompt))
            return resp

    resp = _validate_prompt_impl(req, trace_id, prompt)
    total_ms = (time.perf_counter() - t0) * 1000
    _record_validation_metrics(trace_id, total_ms, resp, fallback_triggered=False)
    _log_validation_event(trace_id, total_ms, resp, fallback_triggered=False, prompt_length=len(prompt))
    return resp


def _record_validation_metrics(
    trace_id: str,
    total_latency_ms: float,
    resp: PromptResponse,
    *,
    fallback_triggered: bool,
) -> None:
    category_scores = {k: v.score for k, v in resp.categories.items()}
    record_validation(
        trace_id=trace_id,
        total_latency_ms=total_latency_ms,
        fallback_triggered=fallback_triggered,
        recommendation=resp.recommendation,
        general_risk_score=resp.general_risk_score,
        category_scores=category_scores,
    )


def _log_validation_event(
    trace_id: str,
    latency_ms_total: float,
    resp: PromptResponse,
    *,
    fallback_triggered: bool,
    prompt_length: int,
) -> None:
    calls = get_current_llm_calls()
    llm_error = any(
        c.get("error_code") and c["error_code"] != PARSE_ERROR_CODE for c in calls
    )
    parse_error = any(c.get("error_code") == PARSE_ERROR_CODE for c in calls)
    category_scores = {k: v.score for k, v in resp.categories.items()}
    log_validation_event(
        trace_id=trace_id,
        recommendation=resp.recommendation,
        general_risk_score=resp.general_risk_score,
        category_scores=category_scores,
        latency_ms_total=latency_ms_total,
        llm_error=llm_error,
        parse_error=parse_error,
        fallback_triggered=fallback_triggered,
        prompt_length=prompt_length,
    )


def _validate_prompt_impl(req: PromptRequest, trace_id: str, prompt: str) -> PromptResponse:
    # Run checks (sequential for v1; you can parallelize later)
    sensitive: CategoryResult = check_sensitive(prompt, trace_id=trace_id)
    jailbreak: CategoryResult = check_jailbreak(prompt, trace_id=trace_id)
    harmful: CategoryResult = check_harmful(prompt, trace_id=trace_id)

    categories = {
        "sensitive": sensitive,
        "jailbreak": jailbreak,
        "harmful": harmful,
    }
    categories = _dedupe_category_overlaps(categories)

    general_score = compute_general_score(categories, tools=req.tools)

    recommendation, final_message, rewritten_prompt = decide_recommendation(
        prompt=prompt,
        categories=categories,
        general_score=general_score,
    )

    return PromptResponse(
        trace_id=trace_id,
        general_risk_score=general_score,
        categories=categories,
        recommendation=recommendation,
        final_message=final_message,
        rewritten_prompt=rewritten_prompt
    )

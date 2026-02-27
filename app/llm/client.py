"""
LLM provider wrapper.

Goal:
- One place to swap providers (OpenAI/Azure/mock)
- Provide a simple `ask_json(system, user, schema_hint)` method

"""

from __future__ import annotations
import time
from typing import Any, Dict, Optional
import json
import httpx
from app.core.config import settings
from app.core.errors import ValidationServiceError
from app.telemetry.logging import get_logger
from app.telemetry.metrics import PARSE_ERROR_CODE, record_llm_call

log = get_logger(__name__)

class LLMClient:
    def __init__(self):
        self.provider = settings.LLM_PROVIDER

    def ask_json(
        self,
        *,
        system: str,
        user: str,
        trace_id: str,
        category: str = "unknown",
    ) -> Dict[str, Any]:
        """
        Return a dict with keys that match your expected schema.
        For v1, keep it simple: score (0-100), explanation, flags[], suggested_rewrite?
        Records latency and errors for metrics when category is set.
        """
        t0 = time.perf_counter()

        def _record_result(error_code: Optional[str] = None) -> None:
            latency_ms = (time.perf_counter() - t0) * 1000
            record_llm_call(category=category, latency_ms=latency_ms, error_code=error_code)

        if self.provider == "mock":
            _record_result(None)
            return {
                "score": 0,
                "explanation": "mock response",
                "flags": [],
                "suggested_rewrite": None,
            }

        if self.provider == "openai":
            api_key = settings.OPENAI_API_KEY
            if not api_key:
                _record_result("bad_config")
                raise ValidationServiceError("OPENAI_API_KEY is not configured", code="bad_config")

            try:
                response = httpx.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "X-Trace-Id": trace_id,
                    },
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        # Ask OpenAI to return strict JSON
                        "response_format": {"type": "json_object"},
                    },
                    timeout=15.0,
                )
            except httpx.TimeoutException as exc:
                log.error("openai_timeout", trace_id=trace_id, error=str(exc))
                _record_result("timeout")
                raise ValidationServiceError("Request timed out", code="timeout")
            except httpx.RequestError as exc:
                log.error("openai_request_error", trace_id=trace_id, error=str(exc))
                _record_result("upstream_error")
                raise ValidationServiceError("Error calling OpenAI", code="upstream_error")

            if response.status_code >= 400:
                log.error(
                    "openai_bad_status",
                    trace_id=trace_id,
                    status_code=response.status_code,
                    body=response.text[:500],
                )
                _record_result("upstream_error")
                raise ValidationServiceError("OpenAI returned an error", code="upstream_error")

            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected JSON object")
                _record_result(None)
                return parsed
            except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                log.error("openai_parse_error", trace_id=trace_id, error=str(exc))
                _record_result(PARSE_ERROR_CODE)
                raise ValidationServiceError("Failed to parse OpenAI response", code=PARSE_ERROR_CODE)

        _record_result("bad_config")
        raise ValidationServiceError(f"Unknown LLM provider: {self.provider}", code="bad_config")

client = LLMClient()

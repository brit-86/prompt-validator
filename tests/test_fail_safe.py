"""
Minimal fail-safe tests: invalid JSON, missing required fields, timeout/exception.

Ensures validation degrades safely when the LLM returns bad data or the call fails.
"""

import pytest
from unittest.mock import patch

from app.core.errors import ValidationServiceError
from app.core.validator import validate_prompt
from app.api.schemas import PromptRequest
from app.llm.parsing import parse_json_strict


# --- Invalid JSON (parsing layer) ---

def test_parse_json_strict_invalid_json_raises():
    with pytest.raises(ValidationServiceError) as exc_info:
        parse_json_strict("not json at all")
    assert exc_info.value.code == "bad_llm_output"


def test_parse_json_strict_malformed_json_raises():
    with pytest.raises(ValidationServiceError) as exc_info:
        parse_json_strict('{"score": 0,')  # truncated
    assert exc_info.value.code == "bad_llm_output"


# --- Invalid JSON / upstream error in validation → fail-safe ---

@patch("app.llm.client.LLMClient.ask_json")
def test_validation_invalid_json_returns_fail_safe_response(mock_ask_json):
    mock_ask_json.side_effect = ValidationServiceError(
        "Failed to parse OpenAI response", code="upstream_error"
    )
    with patch("app.core.validator.settings") as mock_settings:
        mock_settings.FAIL_SAFE_MODE = True
        mock_settings.MAX_PROMPT_CHARS = 8000
        resp = validate_prompt(PromptRequest(prompt="hello"))
    assert resp.general_risk_score == 100
    assert resp.recommendation == "BLOCK_NEEDS_USER_FIX"
    assert "blocked" in resp.final_message.lower() or "safety" in resp.final_message.lower()


# --- Required field missing: LLM returns minimal/empty dict ---

@patch("app.llm.client.LLMClient.ask_json")
def test_validation_missing_required_fields_completes_safely(mock_ask_json):
    # Empty dict: validators use .get("score", 0), .get("flags", []), etc.
    mock_ask_json.return_value = {}
    with patch("app.core.validator.settings") as mock_settings:
        mock_settings.FAIL_SAFE_MODE = True
        mock_settings.MAX_PROMPT_CHARS = 8000
        resp = validate_prompt(PromptRequest(prompt="hello"))
    assert resp.general_risk_score >= 0
    assert resp.trace_id
    assert "sensitive" in resp.categories and "jailbreak" in resp.categories and "harmful" in resp.categories


# --- Timeout → fail-safe ---

@patch("app.llm.client.LLMClient.ask_json")
def test_validation_timeout_returns_fail_safe_response(mock_ask_json):
    mock_ask_json.side_effect = ValidationServiceError(
        "Request timed out", code="timeout"
    )
    with patch("app.core.validator.settings") as mock_settings:
        mock_settings.FAIL_SAFE_MODE = True
        mock_settings.MAX_PROMPT_CHARS = 8000
        resp = validate_prompt(PromptRequest(prompt="hello"))
    assert resp.general_risk_score == 100
    assert resp.recommendation == "BLOCK_NEEDS_USER_FIX"
    assert "timed out" in resp.final_message.lower()


# --- Generic exception → fail-safe ---

@patch("app.llm.client.LLMClient.ask_json")
def test_validation_exception_returns_fail_safe_response(mock_ask_json):
    mock_ask_json.side_effect = RuntimeError("connection refused")
    with patch("app.core.validator.settings") as mock_settings:
        mock_settings.FAIL_SAFE_MODE = True
        mock_settings.MAX_PROMPT_CHARS = 8000
        resp = validate_prompt(PromptRequest(prompt="hello"))
    assert resp.general_risk_score == 100
    assert resp.recommendation == "BLOCK_NEEDS_USER_FIX"

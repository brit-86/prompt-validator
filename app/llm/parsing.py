"""
Parsing + robustness helpers.

You may get:
- valid JSON
- JSON wrapped in text
- invalid JSON

Strategy:
- first try json.loads(raw)
- if fails, try to extract the first {...} block
- if still fails, raise or fallback to safe default

"""

from __future__ import annotations
from typing import Any, Dict
import json
import re
from app.core.errors import ValidationServiceError

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

def extract_json_object(text: str) -> str | None:
    m = _JSON_RE.search(text)
    return m.group(0) if m else None

def parse_json_strict(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        extracted = extract_json_object(text)
        if not extracted:
            raise ValidationServiceError("LLM returned non-JSON output", code="bad_llm_output")
        try:
            return json.loads(extracted)
        except json.JSONDecodeError as e:
            raise ValidationServiceError(f"LLM returned invalid JSON: {e}", code="bad_llm_output")

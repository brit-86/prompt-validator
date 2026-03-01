"""
Policy unit tests: run golden prompts and verify the validator's dominant category
matches the expected dominant category per prompt.

Mocks the three category check functions so each returns a score that makes the
golden file's expected_dominant_category the dominant one (no LLM required).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api.schemas import PromptRequest, CategoryResult
from app.core.validator import validate_prompt


def _load_golden_prompts():
    path = Path(__file__).parent / "golden_prompts.json"
    with open(path, encoding="utf-8") as f:
        return json.loads(f.read())


def _dominant_category(categories):
    """Category with highest score; 'none' if all are 0. Tie-break: harmful > jailbreak > sensitive."""
    order = ("harmful", "jailbreak", "sensitive")
    scores = {c: categories[c].score for c in order if c in categories}
    if not scores or max(scores.values()) == 0:
        return "none"
    max_score = max(scores.values())
    for c in order:
        if scores.get(c) == max_score:
            return c
    return "none"


def _mock_category_result(score: int) -> CategoryResult:
    return CategoryResult(
        score=score,
        explanation="",
        flags=[],
        sub_type=None,
        suggested_rewrite=None,
    )


@pytest.mark.parametrize("item", _load_golden_prompts(), ids=lambda i: i["id"])
def test_golden_prompt_dominant_category_matches(item):
    expected = item["expected_dominant_category"]
    # Return scores so expected_dominant_category is the dominant one.
    sensitive_score = 80 if expected == "sensitive" else 0
    jailbreak_score = 80 if expected == "jailbreak" else 0
    harmful_score = 80 if expected == "harmful" else 0
    with (
        patch(
            "app.core.validator.check_sensitive",
            return_value=_mock_category_result(sensitive_score),
        ),
        patch(
            "app.core.validator.check_jailbreak",
            return_value=_mock_category_result(jailbreak_score),
        ),
        patch(
            "app.core.validator.check_harmful",
            return_value=_mock_category_result(harmful_score),
        ),
    ):
        response = validate_prompt(PromptRequest(prompt=item["prompt"]))
    dominant = _dominant_category(response.categories)
    assert dominant == expected, (
        f"{item['id']}: expected dominant {expected}, got {dominant} "
        f"(scores: sensitive={response.categories['sensitive'].score}, "
        f"jailbreak={response.categories['jailbreak'].score}, "
        f"harmful={response.categories['harmful'].score})"
    )

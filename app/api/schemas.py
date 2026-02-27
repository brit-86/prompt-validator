"""
API schemas (request/response contracts).

Design goals:
- Stable response shape
- Explicit enums for recommendation
- Room for future expansion (metadata, trace ids, etc.)
"""

from __future__ import annotations
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

Recommendation = Literal[
    "ALLOW",
    "ALLOW_WITH_REWRITE",
    "BLOCK_NEEDS_USER_FIX",
    "BLOCK_ILLEGITIMATE_CORE_REQUEST",
]

class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="User provided prompt to validate.")
    #optional fields for future use
    #user_id is the user id from the database to allow differentiating in analytics between users and identifying anomalies or patterns
    user_id: Optional[str] = Field(None, description="Optional user identifier.")
    #session_id is the session id from the database to allow conversation level context tracking
    #session_id: Optional[str] = Field(None, description="Optional session identifier.")
    #language of the prompt to allow for language specific handling and translation
    #locale: Optional[str] = Field(None, description="Optional locale, e.g. 'en-US'.")
    #tools describes what the target LLM is able to do (e.g. which tools or capabilities it can call)
    tools: Optional[list[str]] = Field(
        None,
        description="Optional list of tool or capability identifiers available to the target LLM, e.g. ['web_search', 'code_exec'].",
    )

class CategoryResult(BaseModel):
    score: int = Field(..., ge=0, le=100)
    explanation: str
    flags: Optional[list[str]] = Field(default_factory=list)
    sub_type: Optional[str] = Field(None, description="Optional subtype e.g. illegal/unethical for harmful category.")
    suggested_rewrite: Optional[str] = None

class PromptResponse(BaseModel):
    trace_id: str
    general_risk_score: int = Field(..., ge=0, le=100)
    categories: Dict[str, CategoryResult]
    recommendation: Recommendation
    final_message: str
    rewritten_prompt: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

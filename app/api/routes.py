"""
HTTP routes.

Responsibilities:
- Validate request shape (via Pydantic models)
- Call the orchestrator (core.validator.validate_prompt)
- Return PromptResponse (JSON)
- Handle errors and return appropriate HTTP status codes
"""

from fastapi import APIRouter, HTTPException
from app.api.schemas import PromptRequest, PromptResponse
from app.core.validator import validate_prompt
from app.core.errors import ValidationServiceError, PromptTooLongError
from app.telemetry.metrics import get_metrics

router = APIRouter()

@router.post("/validate", response_model=PromptResponse)
def validate(req: PromptRequest) -> PromptResponse:
    try:
        return validate_prompt(req)
    except PromptTooLongError as e:
        raise HTTPException(
            status_code=413,
            detail={
                "message": str(e),
                "code": e.code,
                "prompt_chars": e.prompt_chars,
                "max_prompt_chars": e.max_prompt_chars,
            },
        )
    except ValidationServiceError as e:
        # When FAIL_SAFE_MODE is False, errors propagate and we return 503
        raise HTTPException(status_code=503, detail={"message": str(e), "code": getattr(e, "code", "service_error")})


@router.get("/metrics")
def metrics():
    """Return computed metrics: validations count, latencies, error/fallback rates, recommendation %, risk score, category distribution."""
    return get_metrics()

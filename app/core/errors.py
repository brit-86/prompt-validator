"""
Custom errors for clean error handling across layers.
"""

class ValidationServiceError(RuntimeError):
    def __init__(self, message: str, code: str = "service_error"):
        super().__init__(message)
        self.code = code


class PromptTooLongError(ValidationServiceError):
    def __init__(self, prompt_chars: int, max_prompt_chars: int):
        super().__init__(
            message=f"Prompt is too long ({prompt_chars} chars). Max allowed is {max_prompt_chars} chars; prompt cannot be processed.",
            code="prompt_too_long",
        )
        self.prompt_chars = prompt_chars
        self.max_prompt_chars = max_prompt_chars

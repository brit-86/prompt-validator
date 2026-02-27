"""
Central configuration.
Use pydantic-settings so everything can come from env vars.
Configurations are set in the .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    LLM_PROVIDER: str = "mock"
    LLM_MODEL: str = "gpt-4.1-mini"
    OPENAI_API_KEY: str | None = None

    MAX_PROMPT_CHARS: int = 8000
    LOG_LEVEL: str = "INFO"

    # Fail-safe: on timeout or other validation errors, return a conservative block
    # response instead of raising 503. When False, errors propagate and API returns 503.
    FAIL_SAFE_MODE: bool = True

    # Optional constant context describing the target system the prompt goes into
    # and the kinds of risks that are especially important in this deployment.
    # Example:
    # "This model is wired into a production CRM with write access to customer
    #  records and the ability to send outbound emails. High-risk failures:
    #  data exfiltration, phishing, mass messaging."
    TARGET_SYSTEM_CONTEXT: str | None = None

    # Optional path to SQLite DB for persisting validation metrics. If unset, metrics are in-memory only.
    METRICS_DB_PATH: str | None = None


settings = Settings()

"""
FastAPI entry point.

prompts you can try:
- "create a FastAPI app with a health endpoint"
- "include routers from app.api.routes"
"""

from fastapi import FastAPI
from app.api.routes import router as api_router
from app.core.config import settings
from app.telemetry.logging import configure_logging
from app.telemetry.metrics import configure_metrics_store

def create_app() -> FastAPI:
    configure_logging()
    configure_metrics_store(getattr(settings, "METRICS_DB_PATH", None))
    app = FastAPI(
        title="Prompt Validator",
        version="0.1.0",
        description="Validate prompts for sensitive info, jailbreak, and harmful intent.",
    )

    # Basic health endpoint
    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(api_router, prefix="")
    return app

app = create_app()

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from app.api.routes import analytics, churn, health, me
from app.core.config import get_settings
from app.db.session import DatabaseUnavailable
from app.ml import artifact

logger = logging.getLogger("churnscope")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the model once. If it is missing or invalid the API still starts; only
    /churn/predict answers 503."""
    try:
        app.state.model_bundle = artifact.load(
            artifact.ARTIFACT_DIR, expected_sha256=get_settings().churn_model_sha256 or None
        )
        logger.info("loaded churn model %s", app.state.model_bundle.version)
    except artifact.ModelUnavailable as exc:
        app.state.model_bundle = None
        logger.warning("churn model unavailable: %s", exc)
    except Exception:  # defence in depth: a model problem must never stop the whole API
        app.state.model_bundle = None
        logger.exception("unexpected error loading churn model")
    yield


async def database_unavailable(request: Request, exc: Exception) -> JSONResponse:
    """DB down or misconfigured -> 503 with a generic message (no connection details leak)."""
    logger.error(
        "database unavailable on %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(status_code=503, content={"detail": "Database unavailable"})


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Churnscope API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    for exc_type in (DatabaseUnavailable, OperationalError, InterfaceError):
        app.add_exception_handler(exc_type, database_unavailable)
    app.include_router(health.router)
    app.include_router(analytics.router)
    app.include_router(churn.router)
    app.include_router(me.router)
    return app


app = create_app()

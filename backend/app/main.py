"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Register every ORM model before the first query: relationships declared by
# class name (e.g. User.notifications -> "Notification") resolve only then.
import app.db.models_registry  # noqa: F401
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import RateLimiter, RateLimitMiddleware
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Configured on server startup (not at import) so tests keep pytest's
    # log capture.
    configure_logging(get_settings().log_level)
    yield
    await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    prefix = settings.api_prefix
    app = FastAPI(
        title="Food Delivery API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url=f"{prefix}/openapi.json" if settings.docs_enabled else None,
        docs_url=f"{prefix}/docs" if settings.docs_enabled else None,
        redoc_url=None,
    )

    register_exception_handlers(app)

    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Protection"],
        )
    # One limiter per application: counters are never shared between apps.
    rate_limiter = RateLimiter(enabled=settings.rate_limit_enabled)
    app.state.rate_limiter = rate_limiter
    app.add_middleware(
        RateLimitMiddleware,
        limiter=rate_limiter,
        # Never answers 429; it has its own silent limit (DEC-108).
        exempt_paths={f"{prefix}/auth/password/forgot"},
    )
    # Added last so it is the outermost user middleware.
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router, prefix=prefix)
    # Uploaded images (DEC-70); in demo nginx proxies /media to the backend.
    app.mount("/media", StaticFiles(directory=settings.media_root, check_dir=False), name="media")
    return app


app = create_app()

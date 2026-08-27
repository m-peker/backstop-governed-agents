"""Application startup and shutdown.

The httpx-based fixtures elsewhere in this suite bypass the lifespan handler, which
means they cannot catch a startup failure. This module drives the real ASGI
lifespan so that wiring errors fail a test rather than a deploy.

No database or Redis is needed: SQLAlchemy's async engine and the Redis client both
connect lazily, so construction and disposal work offline.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backstop_api.main import create_app
from backstop_api.settings import Settings


def test_lifespan_runs_and_attaches_resources() -> None:
    app = create_app(Settings(BACKSTOP_ENV="ci", BACKSTOP_LOG_LEVEL="WARNING"))

    with TestClient(app) as client:
        assert app.state.resources is not None
        assert client.get("/health/live").status_code == 200

    # Shutdown disposed the engine and closed the client without raising.


def test_startup_logging_does_not_explode() -> None:
    """Regression: the startup log line is the first structlog call in the process.

    A logger factory that disagreed with the processor chain used to surface here
    and nowhere else, taking down the whole application at boot.
    """
    app = create_app(Settings(BACKSTOP_ENV="ci", BACKSTOP_LOG_LEVEL="INFO"))

    with TestClient(app) as client:
        assert client.get("/health/live").json()["status"] == "alive"

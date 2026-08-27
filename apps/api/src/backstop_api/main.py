"""Application factory.

Wiring order matters and is asserted by the tests:

1. logging, so that startup failures are structured;
2. tracing, so that the lifespan itself is traced;
3. resources, so that readiness can report honestly;
4. instrumentation, which must come after the app exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backstop_api.resources import Resources
from backstop_api.routers import governance, health, tickets
from backstop_api.settings import Settings, get_settings
from backstop_telemetry import get_logger, instrument_fastapi, setup_logging, setup_tracing

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    app.state.resources = Resources.create(settings)

    log.info(
        "api.startup",
        environment=settings.env,
        kill_switch=settings.governance.kill_switch,
        max_auto_refund_eur=settings.governance.max_auto_refund_eur,
    )

    async with AsyncExitStack() as stack:
        # The ticket service owns the graph and its checkpointer. Built here so
        # that a failure to construct it is a failure to start, rather than a
        # 503 discovered by the first person to submit a ticket.
        from backstop_api.service import TicketService

        app.state.tickets = await TicketService.create(settings, stack)

        try:
            yield
        finally:
            await app.state.resources.aclose()
            log.info("api.shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    setup_logging(level=settings.log_level, json_output=not settings.is_local)
    setup_tracing(
        service_name="backstop-api",
        environment=settings.env,
        otlp_endpoint=settings.otlp_endpoint,
        console=False,
    )

    app = FastAPI(
        title="Backstop API",
        version="0.1.0",
        summary="Governed agent platform for retail customer operations",
        lifespan=lifespan,
        docs_url="/docs" if settings.env != "production" else None,
    )
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(tickets.router)
    app.include_router(governance.router)

    instrument_fastapi(app)
    return app


# Deliberately no module-level `app = create_app()`.
#
# Building the application at import time means configuring tracing and reading
# settings as a side effect of `import backstop_api.main`. During a test run that
# happens at collection, before any fixture has isolated the environment, so the
# suite would pick up a developer's .env and try to export spans to a collector
# that is not running. Uvicorn is invoked with --factory instead, which is the
# supported way to say "call this to get the app".

"""Test fixtures.

The API is built with a stub ``Resources`` so the suite runs with no Postgres and
no Redis. Integration tests that need the real thing get their own marker later;
the unit suite must stay runnable on a laptop with nothing started.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backstop_api.deps.common import get_resources
from backstop_api.main import create_app
from backstop_api.settings import GovernanceSettings, Settings


class StubResources:
    """Reports whatever the test asked it to report."""

    def __init__(self, *, database: bool = True, redis: bool = True) -> None:
        self._database = database
        self._redis = redis

    async def check_database(self) -> bool:
        return self._database

    async def check_redis(self) -> bool:
        return self._redis

    async def aclose(self) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(
        BACKSTOP_ENV="ci",
        BACKSTOP_LOG_LEVEL="WARNING",
        OTEL_EXPORTER_OTLP_ENDPOINT=None,
        governance=GovernanceSettings(
            max_auto_refund_eur=75.0,
            daily_budget_usd=25.0,
            kill_switch=False,
            pii_detokenize_channels=("email", "console"),
        ),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    application = create_app(settings)
    application.dependency_overrides[get_resources] = lambda: StubResources()
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    app.state.resources = StubResources()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.fixture
def dependency_state(app: FastAPI) -> Callable[..., None]:
    """Swap in a stub that reports a specific dependency state.

    Usage: ``dependency_state(database=False, redis=True)``.
    """

    def _set(*, database: bool = True, redis: bool = True) -> None:
        app.dependency_overrides[get_resources] = lambda: StubResources(
            database=database, redis=redis
        )

    return _set

"""Health and governance-posture endpoints."""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient


async def test_liveness_reports_service_identity(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "backstop-api", "version": "0.1.0"}


async def test_readiness_is_true_when_dependencies_answer(client: AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "ready": True,
        "dependencies": {"database": True, "redis": True},
    }


async def test_readiness_returns_503_and_names_the_failure(
    client: AsyncClient, dependency_state: Callable[..., None]
) -> None:
    dependency_state(database=False, redis=True)

    response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["dependencies"] == {"database": False, "redis": True}


async def test_governance_posture_is_readable_without_reading_config(client: AsyncClient) -> None:
    response = await client.get("/health/governance")

    assert response.status_code == 200
    assert response.json() == {
        "environment": "ci",
        "kill_switch_engaged": False,
        "max_auto_refund_eur": 75.0,
        "daily_budget_usd": 25.0,
        "pii_detokenize_channels": ["email", "console"],
    }

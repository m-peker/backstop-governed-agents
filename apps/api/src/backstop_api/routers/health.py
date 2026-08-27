"""Liveness, readiness and a governance posture probe.

The third endpoint is the interesting one. ``/health/governance`` reports the
controls that are currently active: the auto-refund ceiling, the daily budget and
whether the kill switch is engaged. An operator should be able to answer "what is
this system allowed to do right now" with a single curl, without reading config
or code.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from backstop_api.deps.common import ResourcesDep, SettingsDep

router = APIRouter(prefix="/health", tags=["health"])


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    service: str = "backstop-api"
    version: str = "0.1.0"


class DependencyStatus(BaseModel):
    database: bool
    redis: bool


class ReadinessResponse(BaseModel):
    ready: bool
    dependencies: DependencyStatus


class GovernanceResponse(BaseModel):
    """The controls currently in force. Deliberately readable by operators."""

    environment: str
    kill_switch_engaged: bool = Field(
        description="When true, every write-scoped tool is refused at the gateway."
    )
    max_auto_refund_eur: float = Field(
        description="Refunds above this amount require a signed human approval."
    )
    daily_budget_usd: float
    pii_detokenize_channels: list[str]


@router.get("/live", response_model=LivenessResponse, summary="Process is up")
async def live() -> LivenessResponse:
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse, summary="Dependencies are reachable")
async def ready(resources: ResourcesDep, response: Response) -> ReadinessResponse:
    database_ok = await resources.check_database()
    redis_ok = await resources.check_redis()
    is_ready = database_ok and redis_ok

    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        ready=is_ready,
        dependencies=DependencyStatus(database=database_ok, redis=redis_ok),
    )


@router.get(
    "/governance",
    response_model=GovernanceResponse,
    summary="Which controls are currently in force",
)
async def governance(settings: SettingsDep) -> GovernanceResponse:
    gov = settings.governance
    return GovernanceResponse(
        environment=settings.env,
        kill_switch_engaged=gov.kill_switch,
        max_auto_refund_eur=gov.max_auto_refund_eur,
        daily_budget_usd=gov.daily_budget_usd,
        pii_detokenize_channels=list(gov.pii_detokenize_channels),
    )


__all__ = ["router"]

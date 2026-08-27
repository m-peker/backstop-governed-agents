"""Application settings.

One deliberate distinction runs through this file: **operational** configuration
and **governance** configuration are different things and are separated below.

Operational settings (ports, URLs, log level) are tuning knobs. Governance
settings (auto-refund ceiling, daily budget, kill switch, which channels may see
detokenised PII) are policy. They live in the environment for now so the labs can
demonstrate them, but from Phase 6 the policy engine becomes the authority and
these values are only a fallback. Changing one is a reviewed act, not a deploy
tweak, and every read of them is audited.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class GovernanceSettings(BaseSettings):
    """Policy values. Treated as controls, not preferences."""

    # enable_decoding=False stops pydantic-settings JSON-decoding complex types
    # before the field validators run. Without it, a perfectly ordinary
    # BACKSTOP_PII_DETOKENIZE_CHANNELS=email,console in a .env file raises at
    # startup, because a tuple field is treated as JSON and "email,console"
    # is not JSON. The comma-splitting validator below is the intended parser.
    model_config = SettingsConfigDict(env_prefix="BACKSTOP_", extra="ignore", enable_decoding=False)

    max_auto_refund_eur: float = Field(
        default=75.0,
        ge=0,
        description="Above this amount a refund requires a signed human approval token.",
    )
    daily_budget_usd: float = Field(
        default=25.0,
        gt=0,
        description="Per-tenant daily LLM spend before the circuit breaker trips.",
    )
    kill_switch: bool = Field(
        default=False,
        description="When true the tool gateway refuses every write tool, no exceptions.",
    )
    pii_detokenize_channels: tuple[str, ...] = Field(
        default=("email", "console"),
        description="Only these output channels may receive detokenised personal data.",
    )

    @field_validator("pii_detokenize_channels", mode="before")
    @classmethod
    def _split_channels(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value


class Settings(BaseSettings):
    """Operational configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
        # See GovernanceSettings above: comma-separated lists in a .env file are
        # parsed by the field validators, not by a JSON decoder.
        enable_decoding=False,
    )

    env: Environment = Field(default="local", alias="BACKSTOP_ENV")
    log_level: str = Field(default="INFO", alias="BACKSTOP_LOG_LEVEL")

    database_url: str = Field(
        default="postgresql+asyncpg://backstop:backstop@localhost:5432/backstop",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    otlp_endpoint: str | None = Field(default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT")

    jwt_secret: SecretStr = Field(default=SecretStr("dev-only"), alias="BACKSTOP_JWT_SECRET")
    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:3000",), alias="BACKSTOP_CORS_ORIGINS"
    )

    governance: GovernanceSettings = Field(default_factory=GovernanceSettings)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @property
    def is_local(self) -> bool:
        return self.env == "local"

    def assert_production_ready(self) -> None:
        """Fail fast rather than run production on a development secret."""
        if self.env != "production":
            return
        if self.jwt_secret.get_secret_value() in {"dev-only", "change-me-in-every-environment"}:
            raise RuntimeError("BACKSTOP_JWT_SECRET is still the default value in production")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.assert_production_ready()
    return settings

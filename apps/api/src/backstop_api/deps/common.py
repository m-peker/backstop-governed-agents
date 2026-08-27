"""Shared FastAPI dependencies.

Both dependencies resolve through ``app.state`` rather than through module-level
globals. That matters for settings in particular: ``get_settings`` is process-wide
and cached, so a route that depended on it directly would silently ignore the
configuration the application was actually built with. Reading from ``app.state``
means the app is the single source of truth for its own configuration, and a test
or a second app instance in the same process gets what it asked for.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from backstop_api.resources import Resources
from backstop_api.settings import Settings


def get_resources(request: Request) -> Resources:
    resources: Resources | None = getattr(request.app.state, "resources", None)
    if resources is None:  # pragma: no cover - only reachable on a wiring mistake
        raise RuntimeError("Resources are not initialised; the lifespan handler did not run")
    return resources


def get_app_settings(request: Request) -> Settings:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    if settings is None:  # pragma: no cover - create_app always sets this
        raise RuntimeError("Settings are not attached to the application")
    return settings


ResourcesDep = Annotated[Resources, Depends(get_resources)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]

__all__ = ["ResourcesDep", "SettingsDep", "get_app_settings", "get_resources"]

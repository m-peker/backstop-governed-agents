"""Session-wide test isolation.

A test run must not depend on, or reach, anything outside the repository. Two
things in particular:

**No live model provider.** Every API key is cleared before collection. If a test
somehow constructed a real provider it would report itself unavailable rather than
spending money, and the deterministic stub is what the suite is written against
anyway. This is a safety property, not a convenience: the cost of getting it wrong
is a bill and a set of flaky tests.

**No telemetry exporter.** A developer's ``.env`` points OpenTelemetry at a local
collector. During a test run there is no collector, so every span export retries
and then times out, filling the output with connection errors that look like
failures and are not.

Both are cleared here rather than in each package's conftest, because the leak is
a property of the process, not of any one suite.
"""

from __future__ import annotations

import os

import pytest

#: Cleared for every test. Anything that would make a test reach the network, or
#: make its result depend on the machine it runs on.
_ISOLATED = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
)


def _blank(name: str) -> None:
    """Set to empty rather than delete.

    Deleting is not enough: several settings classes read a ``.env`` file, and a
    deleted variable simply falls through to whatever that file says. An empty
    environment variable takes precedence over the file and reads as falsy, which
    is what every check downstream is looking for.
    """
    os.environ[name] = ""


@pytest.fixture(autouse=True, scope="session")
def _isolate_from_the_environment() -> None:
    for name in _ISOLATED:
        _blank(name)

    # Force the CI branch of every environment check, so a developer running the
    # suite locally gets the same behaviour the pipeline does.
    os.environ["BACKSTOP_ENV"] = "ci"
    os.environ["BACKSTOP_LOG_LEVEL"] = "WARNING"


def pytest_configure(config: pytest.Config) -> None:
    """Clear the environment before collection, not just before the first test.

    Module-level code runs at import time - during collection - and some of it
    reads the environment. Waiting for a fixture would be too late.
    """
    for name in _ISOLATED:
        _blank(name)
    os.environ["BACKSTOP_ENV"] = "ci"

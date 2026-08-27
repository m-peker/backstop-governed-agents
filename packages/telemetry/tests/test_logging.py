"""Logging bootstrap behaviour.

These tests exist because a mismatched logger factory and processor chain is a
configuration error that only surfaces on the first real log call - which, in this
application, happened to be inside the API lifespan handler. A unit test is a much
cheaper place to find it than a failed startup.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
import structlog

from backstop_telemetry import get_logger, setup_logging


@pytest.fixture(autouse=True)
def _reset_logging() -> Any:
    yield
    structlog.reset_defaults()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)


def test_native_event_renders_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(level="INFO", json_output=True)

    get_logger("backstop.test").info("ticket.received", ticket_id="TCK-1001")

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "ticket.received"
    assert record["ticket_id"] == "TCK-1001"
    assert record["level"] == "info"
    assert record["logger"] == "backstop.test"
    assert "timestamp" in record


def test_third_party_records_use_the_same_renderer(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(level="INFO", json_output=True)

    # A library that has never heard of structlog.
    logging.getLogger("uvicorn.error").warning("Application startup complete")

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "Application startup complete"
    assert record["level"] == "warning"
    assert record["logger"] == "uvicorn.error"


def test_level_filtering_is_honoured(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(level="WARNING", json_output=True)

    log = get_logger("backstop.test")
    log.info("this.is.dropped")
    log.warning("this.is.kept")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "this.is.kept"


def test_console_mode_is_not_json(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(level="INFO", json_output=False)

    get_logger("backstop.test").info("readable.for.humans")

    out = capsys.readouterr().out
    assert "readable.for.humans" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip())


def test_setup_is_repeatable_without_duplicating_handlers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    setup_logging(level="INFO", json_output=True)
    setup_logging(level="INFO", json_output=True)

    get_logger("backstop.test").info("emitted.once")

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1

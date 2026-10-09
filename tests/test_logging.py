"""Unit tests for the spectres.logging foundation (formatter, trace context, rotation, middleware)."""

import io
import json
import logging
import logging.handlers
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spectres.config import settings
from spectres.logging import (
    JsonFormatter,
    SecretRedactionFilter,
    TraceContextFilter,
    TraceIdMiddleware,
    bind_trace,
    configure_logging,
    current_trace_id,
    log_file_for_today,
    new_trace,
    reset_trace,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def restore_root_logger() -> Iterator[None]:
    """Snapshot and restore root logger handlers/level around configure_logging tests."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)


def _json_logger_stream(name: str = "spectres.extensions.etf_grid.test") -> tuple[logging.Logger, io.StringIO]:
    """Return a logger wired to a StringIO with JsonFormatter + TraceContextFilter."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(TraceContextFilter())
    logger = logging.getLogger(name)
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


class TestTraceContext:
    """The trace id lives in a contextvar and is bound/reset explicitly."""

    def test_default_is_none(self) -> None:
        """No active trace without a bind."""
        assert current_trace_id() is None

    def test_bind_and_reset(self) -> None:
        """bind_trace sets the id; reset_trace restores the previous value."""
        token = bind_trace("abc123")
        assert current_trace_id() == "abc123"
        reset_trace(token)
        assert current_trace_id() is None

    def test_new_trace_short_and_unique(self) -> None:
        """new_trace returns short unique ids suitable for grep keys."""
        ids = {new_trace() for _ in range(100)}
        assert len(ids) == 100
        assert all(8 <= len(trace_id) <= 16 for trace_id in ids)


class TestJsonFormatter:
    """One JSON object per line with fixed fields, extras, and exc_info summary."""

    def test_fixed_fields_and_extension_derivation(self) -> None:
        """ts/level/logger/extension/event/message/trace_id are always present."""
        logger, stream = _json_logger_stream()
        token = bind_trace("trace-1")
        try:
            logger.info("hello %s", "world", extra={"event": "test_event", "rows": 3})
        finally:
            reset_trace(token)
        record = json.loads(stream.getvalue())
        assert record["level"] == "INFO"
        assert record["logger"] == "spectres.extensions.etf_grid.test"
        assert record["extension"] == "etf_grid"
        assert record["event"] == "test_event"
        assert record["message"] == "hello world"
        assert record["trace_id"] == "trace-1"
        assert record["rows"] == 3  # arbitrary extras land as top-level fields
        assert "T" in record["ts"]  # ISO-8601 timestamp

    def test_core_logger_has_no_extension(self) -> None:
        """Loggers outside spectres.extensions.* get extension=None."""
        logger, stream = _json_logger_stream("spectres.main")
        logger.info("boot")
        assert json.loads(stream.getvalue())["extension"] is None

    def test_exc_info_is_a_summary_not_a_traceback(self) -> None:
        """exc_info carries type, message, and <=3 frames — never a raw traceback dump."""
        logger, stream = _json_logger_stream()
        try:
            raise ValueError("boom")
        except ValueError as exc:
            logger.error("failed", exc_info=exc)
        line = stream.getvalue()
        record = json.loads(line)
        assert record["exc_info"]["type"] == "ValueError"
        assert record["exc_info"]["message"] == "boom"
        assert 1 <= len(record["exc_info"]["frames"]) <= 3
        assert "test_logging.py" in record["exc_info"]["frames"][-1]
        assert "Traceback (most recent call last)" not in line


class TestSecretRedaction:
    """Known secret values are scrubbed from messages and extras before emission."""

    def test_message_and_args_redacted(self) -> None:
        """A secret appearing in the message or args is replaced with ***."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(SecretRedactionFilter(["sup3r-secret-key"]))
        logger, _ = _json_logger_stream("spectres.test.redaction")
        logger.handlers = [handler]
        logger.error("connecting with key %s failed", "sup3r-secret-key", extra={"detail": "key=sup3r-secret-key"})
        output = stream.getvalue()
        assert "sup3r-secret-key" not in output
        assert "***" in output

    def test_short_values_ignored(self) -> None:
        """Very short 'secrets' are not scrubbed (they would over-match common substrings)."""
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(SecretRedactionFilter(["ai"]))
        logger, _ = _json_logger_stream("spectres.test.redaction.short")
        logger.handlers = [handler]
        logger.info("main remains intact")
        assert "main remains intact" in stream.getvalue()

    def test_configured_secrets_stay_out_of_logs(self, tmp_path: Path, restore_root_logger: None) -> None:
        """End-to-end: settings secrets (DB url, keys) never reach the JSONL file."""
        test_settings = settings.model_copy(update={"log_dir": str(tmp_path)})
        configure_logging(test_settings)
        logging.getLogger("spectres.test.redaction.e2e").warning("db=%s key=%s", test_settings.database_url, test_settings.team_leader_llm_api_key)
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_file_for_today(tmp_path).read_text()
        for secret in (test_settings.db_pass, test_settings.database_url, test_settings.team_leader_llm_api_key, test_settings.tavily_api_key):
            if secret and len(secret) >= 8:
                assert secret not in content


class TestConfigureLogging:
    """configure_logging wires stdout + daily-rotated JSONL and routes uvicorn."""

    def test_rotation_wiring(self, tmp_path: Path, restore_root_logger: None) -> None:
        """The file handler is a daily TimedRotatingFileHandler under log_dir with retention."""
        test_settings = settings.model_copy(update={"log_dir": str(tmp_path)})
        handler = configure_logging(test_settings)
        assert isinstance(handler, logging.handlers.TimedRotatingFileHandler)
        assert Path(handler.baseFilename) == tmp_path / f"runtime-{date.today():%Y-%m-%d}.jsonl"
        assert handler.when.upper() == "MIDNIGHT"
        assert handler.backupCount == test_settings.log_retention_days
        assert handler.namer is not None
        rotated = handler.namer(str(tmp_path / "runtime-2026-09-30.jsonl.2026-09-29"))
        assert rotated == str(tmp_path / "runtime-2026-09-29.jsonl")
        assert handler.formatter.__class__ is JsonFormatter

    def test_root_handlers_replaced_and_uvicorn_routed(self, tmp_path: Path, restore_root_logger: None) -> None:
        """Root gets exactly stdout+file handlers; uvicorn loggers propagate into them."""
        configure_logging(settings.model_copy(update={"log_dir": str(tmp_path)}))
        root = logging.getLogger()
        assert len(root.handlers) == 2
        assert root.level == logging.getLevelName(settings.log_level.upper())
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
            uvicorn_logger = logging.getLogger(name)
            assert uvicorn_logger.handlers == []
            assert uvicorn_logger.propagate is True

    def test_records_written_as_jsonl(self, tmp_path: Path, restore_root_logger: None) -> None:
        """A record emitted after configure_logging lands as parseable JSON in today's file."""
        configure_logging(settings.model_copy(update={"log_dir": str(tmp_path)}))
        logging.getLogger("spectres.test.jsonl").info("file check", extra={"event": "check"})
        for handler in logging.getLogger().handlers:
            handler.flush()
        lines = log_file_for_today(tmp_path).read_text().strip().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["message"] == "file check"


class TestTraceIdMiddleware:
    """The ASGI middleware binds a fresh trace id per HTTP request."""

    def test_trace_id_bound_per_request(self) -> None:
        """Each request sees a distinct non-null trace id; none leaks afterwards."""
        app = FastAPI()

        @app.get("/trace")
        async def trace() -> dict[str, str | None]:
            """Echo the trace id visible inside the request context."""
            return {"trace_id": current_trace_id()}

        app.add_middleware(TraceIdMiddleware)
        client = TestClient(app)
        ids = [client.get("/trace").json()["trace_id"] for _ in range(2)]
        assert all(ids)
        assert ids[0] != ids[1]
        assert current_trace_id() is None


def test_log_file_for_today_matches_documented_pattern(tmp_path: Path) -> None:
    """The active file is logs/runtime-YYYY-MM-DD.jsonl (the pattern agents grep)."""
    path = log_file_for_today(tmp_path)
    assert path.parent == tmp_path
    assert path.name == f"runtime-{date.today():%Y-%m-%d}.jsonl"

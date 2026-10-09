"""Structured logging foundation for Spectres Runtime (v0.4.2).

Design (docs/plan/v0.4.2-runtime-logging.md): stdlib ``logging`` only, one
shared JSON Lines file for the whole Runtime (``logs/runtime-YYYY-MM-DD.jsonl``,
daily rotation + retention) plus stdout, and a ``contextvars``-backed
``trace_id`` that every record picks up automatically. Agents investigate
failures by grepping the JSONL file for the ``trace_id`` carried in the
structured tool-error contract, so a single shared file and stable field
names are deliberate.
"""

import contextvars
import json
import logging
import logging.handlers
import traceback
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from spectres.config import Settings

_EXTENSION_LOGGER_PREFIX = "spectres.extensions."

#: Only secrets of at least this length are scrubbed — shorter needles (e.g. a
#: two-character test password) would redact common substrings everywhere.
_MIN_SECRET_LENGTH = 8

#: ExcInfo triple as passed to formatters after a truthiness/None check.
_ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]

#: LogRecord attributes set by the logging machinery itself (plus the fields
#: this module injects); everything else on ``record.__dict__`` is an extra.
_RESERVED_RECORD_ATTRS = frozenset(set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "trace_id", "extension", "event", "taskName"})

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("spectres_trace_id", default=None)


def new_trace() -> str:
    """Return a fresh short trace id (correlation key for one logical operation)."""
    return uuid.uuid4().hex[:12]


def current_trace_id() -> str | None:
    """Return the trace id bound to the current context, or None."""
    return _trace_id.get()


def bind_trace(trace_id: str | None) -> contextvars.Token[str | None]:
    """Bind a trace id to the current context; reset with the returned token."""
    return _trace_id.set(trace_id)


def reset_trace(token: contextvars.Token[str | None]) -> None:
    """Restore the trace id to the value captured when ``token`` was created."""
    _trace_id.reset(token)


def log_file_for_today(log_dir: str | Path) -> Path:
    """Return the JSONL log file actively written today (local date)."""
    return Path(log_dir) / f"runtime-{date.today():%Y-%m-%d}.jsonl"


def _extension_from_logger(name: str) -> str | None:
    """Derive the extension id from a logger name (``spectres.extensions.<name>...``)."""
    if name.startswith(_EXTENSION_LOGGER_PREFIX):
        return name[len(_EXTENSION_LOGGER_PREFIX) :].split(".")[0]
    return None


class TraceContextFilter(logging.Filter):
    """Inject the active trace id and the extension id into every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Attach ``trace_id`` (from the contextvar) and ``extension`` (from the logger name)."""
        record.trace_id = current_trace_id()
        record.extension = _extension_from_logger(record.name)
        return True


class SecretRedactionFilter(logging.Filter):
    """Replace known secret values with ``***`` anywhere they appear in a record.

    Defense in depth: secrets must never be logged in the first place, but a
    stray f-string should not leak the DB password or an API key into a file
    the agent is encouraged to grep.
    """

    def __init__(self, secrets: list[str]) -> None:
        """Create the filter; empty or very short values are ignored (they would over-match)."""
        super().__init__()
        self._secrets = [secret for secret in secrets if len(secret) >= _MIN_SECRET_LENGTH]

    def filter(self, record: logging.LogRecord) -> bool:
        """Scrub secret occurrences from the message template, args, and extra fields."""
        if not self._secrets:
            return True
        if isinstance(record.msg, str):
            for secret in self._secrets:
                record.msg = record.msg.replace(secret, "***")
        if record.args:
            record.args = tuple(self._redact(arg) for arg in record.args) if isinstance(record.args, tuple) else {k: self._redact(v) for k, v in record.args.items()}
        for key, value in list(record.__dict__.items()):
            if key not in _RESERVED_RECORD_ATTRS and isinstance(value, str):
                setattr(record, key, self._redact(value))
        return True

    def _redact(self, value: Any) -> Any:
        """Return ``value`` with every known secret replaced by ``***``."""
        if isinstance(value, str):
            for secret in self._secrets:
                value = value.replace(secret, "***")
        return value


class JsonFormatter(logging.Formatter):
    """Format one JSON object per line with fixed fields plus extras.

    Fixed fields: ``ts`` (UTC ISO-8601), ``level``, ``logger``, ``extension``,
    ``event``, ``message``, ``trace_id``. Any extra keyword passed via
    ``logger.info(..., extra={...})`` lands as a top-level field. Exceptions
    are summarized (type, message, deepest frames) rather than dumped as a
    full traceback — the JSONL file is for triage, not debugging.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Serialize the record as a single JSON line."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "extension": getattr(record, "extension", None),
            "event": getattr(record, "event", None),
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info and not isinstance(record.exc_info, (bool, BaseException)) and record.exc_info[0] is not None:
            payload["exc_info"] = _summarize_exc_info(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _summarize_exc_info(exc_info: _ExcInfo) -> dict[str, Any]:
    """Summarize an exception as type, message, and the deepest stack frames."""
    exc_type, exc, tb = exc_info
    frames = traceback.extract_tb(tb) if tb is not None else []
    return {
        "type": exc_type.__name__,
        "message": str(exc),
        "frames": [f"{frame.filename}:{frame.lineno} in {frame.name}" for frame in frames[-3:]],
    }


class TextFormatter(logging.Formatter):
    """Human-friendly stdout format for local dev; carries the same trace id."""

    def format(self, record: logging.LogRecord) -> str:
        """Render ``ts LEVEL [logger] [trace] message`` plus a one-line exception summary."""
        trace_id = getattr(record, "trace_id", None) or "-"
        base = f"{self.formatTime(record)} {record.levelname} [{record.name}] [trace={trace_id}] {record.getMessage()}"
        if record.exc_info and not isinstance(record.exc_info, (bool, BaseException)) and record.exc_info[0] is not None:
            summary = _summarize_exc_info(record.exc_info)
            base += f" | {summary['type']}: {summary['message']} @ {'; '.join(summary['frames'])}"
        return base


def _rotated_name(default_name: str) -> str:
    """Map TimedRotatingFileHandler's default rotated name back to ``runtime-<date>.jsonl``.

    The handler rotates ``.../runtime-2026-09-30.jsonl`` to
    ``.../runtime-2026-09-30.jsonl.<suffix>``; rewrite that to
    ``.../runtime-<suffix>.jsonl`` so every file — active or rotated — matches
    the documented ``runtime-YYYY-MM-DD.jsonl`` pattern agents grep for.
    """
    base, _, suffix = default_name.rpartition(".")
    return str(Path(base).parent / f"runtime-{suffix}.jsonl")


def configure_logging(settings: "Settings") -> logging.handlers.TimedRotatingFileHandler:
    """Configure root logging: stdout plus the daily rotated JSONL file.

    Idempotent: existing root handlers are replaced. Uvicorn's loggers are
    re-pointed at the root handlers so access logs share the configuration.
    The JSONL file is always JSON regardless of ``log_format`` (which only
    selects the stdout rendering); it is the file agents grep.

    Args:
        settings: Runtime settings carrying ``log_level``, ``log_format``,
            ``log_dir``, and ``log_retention_days``.

    Returns:
        The JSONL file handler (exposed for tests and introspection).
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    trace_filter = TraceContextFilter()
    redaction = SecretRedactionFilter([settings.db_pass, settings.database_url, settings.team_leader_llm_api_key or "", settings.tavily_api_key or ""])

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(JsonFormatter() if settings.log_format == "json" else TextFormatter())
    stdout_handler.addFilter(trace_filter)
    stdout_handler.addFilter(redaction)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file_for_today(log_dir),
        when="midnight",
        backupCount=settings.log_retention_days,
        encoding="utf-8",
    )
    file_handler.namer = _rotated_name
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(TraceContextFilter())
    file_handler.addFilter(redaction)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(stdout_handler)
    root.addHandler(file_handler)

    # Uvicorn installs its own handlers; re-route its loggers into ours.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    return file_handler


class TraceIdMiddleware:
    """Pure ASGI middleware binding a fresh ``trace_id`` per HTTP request.

    Pure ASGI (not BaseHTTPMiddleware) so the contextvar is bound in the same
    task context that runs the endpoint — including streaming responses.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Bind a new trace id around HTTP/websocket handling, then reset it."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = bind_trace(new_trace())
        try:
            await self.app(scope, receive, send)
        finally:
            reset_trace(token)

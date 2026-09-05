"""
Structured application logging for the Self-Learning AI Agent.

Source of truth: BLUEPRINT.md S17 (security / telemetry privacy).

Design decisions:
- JSON-formatted output for machine readability in Docker Compose.
- Sensitive values (API keys, salts, connection strings with passwords)
  are NEVER logged.  BLUEPRINT.md S17 states: "plaintext keys are never
  stored, logged, or committed".
- Chain-of-thought and judge_reasoning are excluded from telemetry
  (BLUEPRINT.md S17: "allowlisted event types; chain-of-thought and
  judge_reasoning stripped").
- Active redaction masks sensitive keys, arguments, tokens, and structured
  extra fields before output.
- Uses stdlib logging so every dependency (FastAPI, Celery, SQLAlchemy,
  LangGraph) integrates without additional libraries.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Final

# -- Constants ---------------------------------------------------
LOG_FORMAT: Final[str] = (
    '{"time":"%(asctime)s","level":"%(levelname)s",'
    '"logger":"%(name)s","message":"%(message)s"}'
)
LOG_DATE_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%S%z"

# Fields that must never appear in plain text in any log output.
_REDACTED_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "TAVILY_API_KEY",
        "API_KEY_SALT",
        "POSTGRES_URL",
        "api_key",
        "api_key_hash",
        "judge_reasoning",
        "chain_of_thought",
    }
)

_REDACTED_FIELDS_LOWER: Final[frozenset[str]] = frozenset(
    f.lower() for f in _REDACTED_FIELDS
)

_STANDARD_LOGRECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

# Regex matching key-value pairs in text: key=val, key: val, "key": "val", 'key': 'val'
SENSITIVE_KV_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""(?i)(["']?)\b("""
    r"""ANTHROPIC_API_KEY|TAVILY_API_KEY|API_KEY_SALT|POSTGRES_URL|"""
    r"""api_key|api_key_hash|judge_reasoning|chain_of_thought"""
    r""")\b\1\s*([:=])\s*(?:"([^"]*)"|'([^']*)'|(\[REDACTED\]|[^\s,;'"}\]\[][^\r\n,;'"}\]]*))"""
)

# Regex matching known sensitive token formats and connection strings with credentials
SECRET_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"""(?i)\b("""
    r"""sk-ant-[a-zA-Z0-9_\-]+|"""
    r"""tvly-[a-zA-Z0-9_\-]+|"""
    r"""sk-[a-zA-Z0-9_\-]{20,}|"""
    r"""postgresql(\+[a-zA-Z0-9_]+)?://[^\s'"]+"""
    r""")\b"""
)


def _get_known_secrets() -> list[str]:
    """Retrieve known configured secret values from settings to redact."""
    secrets: list[str] = []
    try:
        from backend.core.config import settings

        for secret_obj in (
            settings.ANTHROPIC_API_KEY,
            settings.TAVILY_API_KEY,
            settings.API_KEY_SALT,
            settings.POSTGRES_URL,
        ):
            val = secret_obj.get_secret_value()
            if val and len(val) >= 4:
                secrets.append(val)
    except Exception:
        pass
    return secrets


def redact_text(text: str) -> str:
    """Redact sensitive key-value pairs, token patterns, and known secrets in text."""
    if not isinstance(text, str):
        return text

    for secret in _get_known_secrets():
        if secret in text:
            text = text.replace(secret, "[REDACTED]")

    def repl_kv(m: re.Match[str]) -> str:
        q1 = m.group(1)
        key = m.group(2)
        sep = m.group(3)
        v_dq = m.group(4)
        v_sq = m.group(5)
        v_uq = m.group(6)
        if v_uq == "[REDACTED]":
            return m.group(0)
        if v_dq == "[REDACTED]":
            return f'{q1}{key}{q1}{sep} "[REDACTED]"'
        if v_sq == "[REDACTED]":
            return f"{q1}{key}{q1}{sep} '[REDACTED]'"
        if v_dq is not None:
            return f'{q1}{key}{q1}{sep} "[REDACTED]"'
        elif v_sq is not None:
            return f"{q1}{key}{q1}{sep} '[REDACTED]'"
        else:
            return f"{q1}{key}{q1}{sep} [REDACTED]"

    text = SENSITIVE_KV_PATTERN.sub(repl_kv, text)
    text = SECRET_TOKEN_PATTERN.sub("[REDACTED]", text)
    return text


def redact_value(val: Any) -> Any:
    """Recursively redact sensitive data from strings, dicts, lists, and tuples."""
    if isinstance(val, str):
        return redact_text(val)
    elif isinstance(val, dict):
        return {
            k: (
                "[REDACTED]"
                if str(k).lower() in _REDACTED_FIELDS_LOWER
                else redact_value(v)
            )
            for k, v in val.items()
        }
    elif isinstance(val, list):
        return [redact_value(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(redact_value(item) for item in val)
    return val


class RedactingJsonFormatter(logging.Formatter):
    """
    JSON log formatter with active sensitive data redaction.

    Produces JSON output with 'time', 'level', 'logger', and 'message'
    plus any sanitized structured extra fields.
    """

    def __init__(self, datefmt: str = LOG_DATE_FORMAT) -> None:
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        # Sanitize record arguments if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_value(record.args)
            elif isinstance(record.args, (tuple, list)):
                record.args = tuple(redact_value(a) for a in record.args)

        # Get message after argument formatting
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)

        sanitized_message = redact_text(message)
        record.message = sanitized_message

        record_time = self.formatTime(record, self.datefmt)

        log_entry: dict[str, Any] = {
            "time": record_time,
            "level": record.levelname,
            "logger": record.name,
            "message": sanitized_message,
        }

        # Extra fields attached to LogRecord
        for key, val in list(record.__dict__.items()):
            if key not in _STANDARD_LOGRECORD_ATTRS:
                if str(key).lower() in _REDACTED_FIELDS_LOWER:
                    record.__dict__[key] = "[REDACTED]"
                    log_entry[key] = "[REDACTED]"
                else:
                    redacted_val = redact_value(val)
                    record.__dict__[key] = redacted_val
                    log_entry[key] = redacted_val

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            log_entry["exception"] = redact_text(record.exc_text)

        return json.dumps(log_entry, default=str)


def setup_logging(*, level: int = logging.INFO) -> None:
    """
    Configure the root logger for the application.

    Call once at process startup -- in backend/api/main.py for the
    API process and backend/worker/celery_app.py for the Celery
    worker process.

    Args:
        level: Logging level (default INFO).
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(RedactingJsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers on repeated calls (e.g. tests).
    if not root.handlers:
        root.addHandler(handler)
    else:
        root.handlers = [handler]

    # Quieten chatty third-party loggers to WARNING.
    for noisy in ("uvicorn.access", "celery.worker.strategy", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger.

    Usage::

        from backend.core.logging import get_logger
        logger = get_logger(__name__)
        logger.info("Task %s started", task_id)

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A stdlib Logger instance scoped to name.
    """
    return logging.getLogger(name)

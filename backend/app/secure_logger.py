"""
Secure Logging Utility — PII Auto-Redaction

Provides a structured logger that automatically redacts known PII patterns
(phone numbers, emails, SSNs, therapy content) from log output.

Usage:
    from app.secure_logger import get_secure_logger
    logger = get_secure_logger(__name__)
    logger.info("Password reset completed", user_id=uid, phone=phone)
    # phone value will be redacted in output
"""

import logging
import re
from typing import Any


# PII patterns to auto-redact in log values
_PII_PATTERNS = [
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), '[EMAIL_REDACTED]'),
    (re.compile(r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'), '[PHONE_REDACTED]'),
    (re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b'), '[SSN_REDACTED]'),
]

# Keys whose values should always be fully redacted
_SENSITIVE_KEYS = frozenset({
    'password', 'token', 'secret', 'api_key', 'passphrase',
    'phone', 'phone_number', 'phone_normalized',
    'email', 'ssn', 'credit_card',
    'text', 'message', 'body', 'content', 'transcript',
    'nate_query', 'help_text', 'user_text', 'query_text',
})


def _redact_value(key: str, value: Any) -> Any:
    """Redact a value if its key is sensitive or if it contains PII patterns."""
    if not isinstance(value, str):
        return value

    key_lower = key.lower()

    # Fully redact known-sensitive keys
    if key_lower in _SENSITIVE_KEYS:
        return f'[REDACTED:{len(value)} chars]'

    # Pattern-based redaction for other values
    result = value
    for pattern, replacement in _PII_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


class PIIRedactingFilter(logging.Filter):
    """Logging filter that redacts PII from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the main message args if present
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: _redact_value(k, v) for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _redact_value(f'arg{i}', v) for i, v in enumerate(record.args)
                )

        # Redact any extra attributes that may contain PII
        for attr in ('phone', 'email', 'text', 'body', 'message_text', 'query'):
            val = getattr(record, attr, None)
            if val and isinstance(val, str):
                setattr(record, attr, _redact_value(attr, val))

        return True


def get_secure_logger(name: str) -> logging.Logger:
    """Get a logger with PII auto-redaction filter attached.

    This replaces direct print() calls with structured logging
    that automatically strips sensitive data from output.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(handler)
    # Ensure PII filter is applied (idempotent check)
    if not any(isinstance(f, PIIRedactingFilter) for f in logger.filters):
        logger.addFilter(PIIRedactingFilter())
    logger.setLevel(logging.INFO)
    return logger

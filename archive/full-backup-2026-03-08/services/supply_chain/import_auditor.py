"""
HIVE DEFENSE v4.1 — Import Auditor
Runtime import monitoring to detect unexpected module loads.

Hooks into Python's import system to log and validate module imports
at runtime. Detects dynamic imports that bypass static analysis.
"""

import importlib
import logging
import sys
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

_logger = logging.getLogger("import_auditor")

# Modules that are expected to be imported at runtime
EXPECTED_MODULES: Set[str] = {
    "fastapi", "uvicorn", "asyncpg", "redis", "stripe", "pydantic",
    "starlette", "httpx", "websockets", "cryptography", "jose",
    "multipart", "aiohttp", "numpy", "scipy", "structlog",
    "dotenv", "psutil", "PIL", "jinja2", "yaml",
    "json", "os", "sys", "pathlib", "datetime", "typing",
    "asyncio", "logging", "hashlib", "re", "time", "math",
    "uuid", "enum", "dataclasses", "functools", "collections",
    "io", "base64", "secrets", "hmac", "copy", "traceback",
    "importlib", "inspect", "abc", "contextlib", "signal",
    "threading", "multiprocessing", "subprocess", "tempfile",
    "urllib", "email", "html", "http", "ssl", "socket",
}

# Blocked module patterns (known malicious or risky)
BLOCKED_PATTERNS: Set[str] = {
    "ctypes.wintypes",
    "pty",
    "webbrowser",
}


class ImportAuditor:
    """Runtime import monitoring and validation."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._import_log: List[Dict[str, Any]] = []
        self._suspicious_imports: List[Dict[str, Any]] = []
        self._original_import = None
        self._active = False
        self._max_log_size = 10000

    def activate(self) -> None:
        """Activate the import auditor by hooking Python's import system."""
        if self._active:
            return
        self._original_import = builtins.__import__
        builtins.__import__ = self._audited_import
        self._active = True
        _logger.info("ImportAuditor activated")

    def deactivate(self) -> None:
        """Deactivate the import auditor and restore original import."""
        if not self._active or not self._original_import:
            return
        builtins.__import__ = self._original_import
        self._active = False
        _logger.info("ImportAuditor deactivated")

    def _audited_import(self, name, *args, **kwargs):
        """Wrapper around __import__ that logs and validates imports."""
        # Check against blocked patterns
        for blocked in BLOCKED_PATTERNS:
            if name.startswith(blocked):
                _logger.critical("BLOCKED IMPORT: %s", name)
                self._suspicious_imports.append({
                    "module": name,
                    "reason": "blocked_pattern",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                raise ImportError(f"Module {name} is blocked by security policy")

        # Log the import
        root_module = name.split(".")[0]
        if root_module not in EXPECTED_MODULES and not name.startswith("_"):
            if len(self._suspicious_imports) < self._max_log_size:
                self._suspicious_imports.append({
                    "module": name,
                    "reason": "unexpected_module",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        # Proceed with the original import
        return self._original_import(name, *args, **kwargs)

    def get_suspicious_imports(self) -> List[Dict[str, Any]]:
        """Get list of suspicious/unexpected imports detected."""
        return list(self._suspicious_imports)

    def get_stats(self) -> Dict[str, Any]:
        """Get import auditor statistics."""
        return {
            "active": self._active,
            "suspicious_count": len(self._suspicious_imports),
            "total_logged": len(self._import_log),
        }


# Need to import builtins for the hook
import builtins

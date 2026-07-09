"""
Fail-closed guard for feature-flag defaults.

A `getattr(settings, "ENABLE_...", True)` call means: if the settings
attribute is ever renamed, removed, or fails to load, the dormant system
silently activates in production. Every such call must fail CLOSED
(default False) instead.

This test scans the two files known to gate background systems this way
(main.py, bridge_server.py) and fails if the dangerous pattern reappears.
"""
import re
from pathlib import Path

_BACKEND_APP = Path(__file__).resolve().parent.parent / "app"

_DANGEROUS_PATTERN = re.compile(
    r"""getattr\(\s*[\w.]*settings\s*,\s*["']ENABLE_[A-Z_]+["']\s*,\s*True\s*\)"""
)

_SCANNED_FILES = [
    _BACKEND_APP / "main.py",
    _BACKEND_APP / "websocket" / "bridge_server.py",
    _BACKEND_APP / "services" / "drip_scheduler.py",
]


def test_no_fail_open_enable_flag_defaults_in_scanned_files():
    """No ENABLE_* getattr call in the scanned files may default to True."""
    violations = []
    for path in _SCANNED_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _DANGEROUS_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path}:{line_no}: {match.group(0)}")

    assert not violations, (
        "Found fail-open ENABLE_* flag default(s) — a renamed/missing "
        "settings attribute would silently activate a dormant system:\n"
        + "\n".join(violations)
    )


def test_no_fail_open_enable_flag_defaults_anywhere_in_backend():
    """Codebase-wide sweep: no getattr(settings, "ENABLE_...", True) anywhere
    under backend/app. Broader net than the targeted file list above."""
    violations = []
    for path in _BACKEND_APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _DANGEROUS_PATTERN.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path}:{line_no}: {match.group(0)}")

    assert not violations, (
        "Found fail-open ENABLE_* flag default(s) under backend/app:\n"
        + "\n".join(violations)
    )

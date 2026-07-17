"""
Self-enforcing Sovereign Standard — docstring + risk gate for therapeutic modules.

CI / offline check: therapeutic paths must declare SOVEREIGN-STANDARD or
QUANTUM-CRYSTAL-ARCH / clinical governance markers. classify_risk stays RED.

# QUANTUM-CRYSTAL-ARCH — Sovereign Standard decorator CI
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from pathlib import Path
from typing import Any, Callable, List, Optional

logger = logging.getLogger("sovereign_standard_gate")

THERAPEUTIC_MARKERS = (
    "nevedal_engine",
    "sensitive_clinical",
    "sensitive_bridge",
    "therapeutic_controller",
    "littlenate_inference",
    "nate_memory_crystallizer",
    "twilio_grok",
)

REQUIRED_DOC_TOKENS = (
    "SOVEREIGN-STANDARD",
    "QUANTUM-CRYSTAL-ARCH",
    "clinical",
    "CEO",
    "RED",
)


def therapeutic_module(fn: Callable) -> Callable:
    """Decorator: mark callable as RED therapeutic — Dual-COO never auto-ships."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    wrapper.__sovereign_standard__ = True  # type: ignore[attr-defined]
    wrapper.__risk_class__ = "RED"  # type: ignore[attr-defined]
    return wrapper


def scan_therapeutic_sources(
    root: Optional[Path] = None,
) -> List[dict]:
    """Offline CI: flag therapeutic files missing governance docstring tokens."""
    base = root or Path(__file__).resolve().parents[2]  # backend/
    app = base / "app"
    findings: List[dict] = []
    if not app.is_dir():
        return findings
    for path in app.rglob("*.py"):
        rel = str(path.relative_to(base.parent)).replace("\\", "/")
        low = rel.lower()
        if not any(m in low for m in THERAPEUTIC_MARKERS):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception as e:
            findings.append({"path": rel, "ok": False, "detail": str(e)[:200]})
            continue
        head = text[:2500]
        ok = any(tok in head for tok in REQUIRED_DOC_TOKENS)
        if not ok:
            findings.append({
                "path": rel,
                "ok": False,
                "detail": "missing Sovereign Standard / QUANTUM-CRYSTAL-ARCH / clinical gate token in module head",
            })
        else:
            findings.append({"path": rel, "ok": True, "detail": "gated"})
    return findings


def ci_gate_pass(root: Optional[Path] = None) -> bool:
    """Return True if all therapeutic sources pass docstring gate."""
    if os.getenv("SOVEREIGN_STANDARD_GATE_ENABLED", "true").strip().lower() in (
        "0", "false", "no", "off",
    ):
        return True
    findings = scan_therapeutic_sources(root)
    fails = [f for f in findings if not f.get("ok")]
    if fails:
        for f in fails[:20]:
            logger.warning("Sovereign Standard gate FAIL: %s — %s", f.get("path"), f.get("detail"))
        return False
    return True


def assert_callable_gated(fn: Any) -> bool:
    return bool(getattr(fn, "__sovereign_standard__", False))


def module_doc_has_gate(obj: Any) -> bool:
    doc = inspect.getdoc(obj) or ""
    return any(tok in doc for tok in REQUIRED_DOC_TOKENS)
